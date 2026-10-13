#!/usr/bin/env python3
"""Command-line client for a running Lesson Studio stack (standard library only).

Talks to the nginx gateway (default http://localhost:8080, override with LESSONGEN_URL):

    python scripts/lessongen.py generate --topic "Introduction to RAG"
    python scripts/lessongen.py lab --fault factual_error [--repair]
    python scripts/lessongen.py watch <run_id>
    python scripts/lessongen.py export <run_id> --out docs/final-lesson
    python scripts/lessongen.py status
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE = os.environ.get("LESSONGEN_URL", "http://localhost:8080").rstrip("/")
TERMINAL = {"run.completed", "run.failed", "run.cancelled"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def call(method: str, path: str, body: Any = None, *, raw: bool = False) -> Any:
    request = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")
        with contextlib.suppress(ValueError, AttributeError):
            detail = json.loads(detail).get("detail", detail)
        sys.exit(f"error {err.code} from {path}: {detail}")
    except urllib.error.URLError as err:
        sys.exit(f"cannot reach {BASE} ({err.reason}). Is `docker compose up` running?")
    return payload if raw else json.loads(payload)


def describe(event: dict[str, Any]) -> str | None:
    t, d = event["type"], event.get("data") or {}
    attempt = f"[attempt {event['attempt']}] " if event.get("attempt") else ""
    match t:
        case "run.queued":
            return f"queued: {d.get('topic')} (max retries {d.get('max_retries')})"
        case "run.started":
            return "worker picked up the run"
        case "node.started":
            return f"{attempt}> {d.get('node')}"
        case "node.completed":
            secs = (d.get("duration_ms") or 0) / 1000
            return f"{attempt}  done {d.get('node')} in {secs:.1f}s ${d.get('cost_usd', 0):.3f} - {d.get('summary', '')}"
        case "memory.recalled":
            return f"  memory: {len(d.get('guidelines', []))} learned guideline(s) injected"
        case "agent.tool_call":
            return f"{attempt}  {d.get('agent')} THOUGHT: {d.get('reason', '')}\n{' ' * len(attempt)}    ACTION: {d.get('tool')}({json.dumps(d.get('args', {}), ensure_ascii=False)[:120]})"
        case "agent.tool_result":
            return f"{attempt}    OBSERVATION: {str(d.get('preview', ''))[:140]}"
        case "agent.submitted":
            return f"{attempt}  {d.get('agent')} submitted via {d.get('tool')}"
        case "check.completed":
            mark = "PASS" if d.get("verdict") == "PASS" else "FAIL"
            return f"{attempt}    {mark} {d.get('check_id'):7s} {d.get('title')}"
        case "evaluation.completed":
            return f"{attempt}  evaluation: {d.get('summary')}"
        case "attempt.rejected":
            return f"{attempt}  rejected -> {d.get('next')} ({d.get('reason')})"
        case "revision.completed":
            notes = "; ".join(f"{n['check_id']}: {n['change']}" for n in d.get("notes", []))
            return f"  revised (attempt {d.get('attempt')}, {d.get('strategy')}): {notes}"
        case "memory.consolidated":
            return f"  memory updated: {d.get('summary')}"
        case "run.completed":
            return f"FINISHED: {d.get('status')} - {d.get('status_reason') or ''} (cost ${d.get('cost_usd', 0):.2f})"
        case "run.failed":
            return f"FAILED: {d.get('error')}"
        case "run.cancelled":
            return "CANCELLED"
        case _:
            return None


def watch(run_id: str) -> None:
    request = urllib.request.Request(
        f"{BASE}/api/orchestrator/v1/runs/{run_id}/events", headers={"Accept": "text/event-stream"}
    )
    with urllib.request.urlopen(request, timeout=3600) as response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:])
            text = describe(event)
            if text:
                print(text, flush=True)
            if event["type"] in TERMINAL:
                return


def start(body: dict[str, Any]) -> str:
    run = call("POST", "/api/orchestrator/v1/runs", body)
    print(f"run {run['id']} queued - open {BASE}/runs/{run['id']} to watch it in the UI\n")
    watch(run["id"])
    return run["id"]


def cmd_generate(args: argparse.Namespace) -> None:
    run_id = start(
        {"topic": args.topic, "max_retries": args.retries, "helper_language": args.language}
    )
    print(f"\nexport: python scripts/lessongen.py export {run_id} --out docs/final-lesson")


def cmd_lab(args: argparse.Namespace) -> None:
    if args.from_run:
        run = call("GET", f"/api/orchestrator/v1/runs/{args.from_run}")
        final = next(
            (a for a in run["attempts"] if a["attempt_no"] == run["final_attempt_no"]),
            run["attempts"][-1],
        )
        lesson = final["lesson"]
    else:
        lesson = call("GET", "/api/evaluator/v1/faults/reference-lesson")
    applied = call(
        "POST", "/api/evaluator/v1/faults/apply", {"lesson": lesson, "fault_id": args.fault}
    )
    fault = applied["fault"]
    print(
        f"injected [{fault['title']}]: {fault['injected_text']}\nexpected to be caught by: {', '.join(fault['expected_checks'])}\n"
    )
    run_id = start(
        {
            "topic": args.topic,
            "mode": "repair" if args.repair else "evaluate_only",
            "initial_lesson": applied["lesson"],
            "fault_id": fault["id"],
            "max_retries": 2 if args.repair else 0,
        }
    )
    run = call("GET", f"/api/orchestrator/v1/runs/{run_id}")
    first = next(a for a in run["attempts"] if a["attempt_no"] == 1)
    failed = set(first["evaluation"]["failed_check_ids"])
    caught = [c for c in fault["expected_checks"] if c in failed]
    print(
        f"\ncaught by: {', '.join(caught) or 'NOTHING'} | also flagged: {', '.join(sorted(failed - set(caught))) or '-'}"
    )


def cmd_export(args: argparse.Namespace) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    lesson = call("GET", f"/api/orchestrator/v1/runs/{args.run_id}/export/lesson.md", raw=True)
    log = call("GET", f"/api/orchestrator/v1/runs/{args.run_id}/export/rejection-log.md", raw=True)
    (out / "introduction-to-rag.md").write_text(lesson, encoding="utf-8")
    (out / "rejection-log.md").write_text(log, encoding="utf-8")
    run = call("GET", f"/api/orchestrator/v1/runs/{args.run_id}")
    (out / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out / 'introduction-to-rag.md'}, {out / 'rejection-log.md'}, {out / 'run.json'}")


def cmd_status(_: argparse.Namespace) -> None:
    s = call("GET", "/api/orchestrator/v1/system/status")
    for svc in s["services"]:
        print(f"{'ok  ' if svc.get('ok') else 'DOWN'} {svc['name']}")
    print(f"queue: {s['queue']}")
    print(f"azure configured: {s['llm']['configured']} (api {s['llm']['api_version']})")
    for role in s["llm"]["roles"]:
        print(f"  {role['role']:15s} {role['deployment']:16s} effort={role['reasoning_effort']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate", help="generate a lesson and stream the run")
    g.add_argument("--topic", default="Introduction to RAG")
    g.add_argument("--retries", type=int, default=2, choices=[1, 2])
    g.add_argument("--language", default="Hindi")
    g.set_defaults(func=cmd_generate)
    lab = sub.add_parser("lab", help="inject a deliberate error and watch the evaluator catch it")
    lab.add_argument("--fault", default="factual_error")
    lab.add_argument("--repair", action="store_true", help="let the loop fix the lesson")
    lab.add_argument(
        "--from-run", help="start from a run's final lesson instead of the reference lesson"
    )
    lab.add_argument("--topic", default="Introduction to RAG")
    lab.set_defaults(func=cmd_lab)
    w = sub.add_parser("watch", help="stream the events of a run")
    w.add_argument("run_id")
    w.set_defaults(func=lambda a: watch(a.run_id))
    e = sub.add_parser("export", help="save a run's lesson, rejection log and full record")
    e.add_argument("run_id")
    e.add_argument("--out", default="docs/final-lesson")
    e.set_defaults(func=cmd_export)
    st = sub.add_parser("status", help="service health and model configuration")
    st.set_defaults(func=cmd_status)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
