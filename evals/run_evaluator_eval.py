#!/usr/bin/env python3
"""Meta-evaluation: how good is the evaluator?

An evaluator that cannot be trusted makes the whole loop meaningless, so it is measured like
any other model:

* **Detection rate** - every deliberate-error preset declares which checks *should* fail. We
  inject each one into the reviewed reference lesson and count how many expected checks
  actually failed.
* **False-fail rate** - the clean reference lesson is evaluated as-is; every failed check is
  a false alarm (each one would trigger a needless, costly rewrite).

Runs against the live stack through the gateway (real Azure models, ~10 evaluations, roughly
$1-2) and writes a Markdown + JSON report to evals/reports/.

    python evals/run_evaluator_eval.py                    # all presets, 1 repeat
    python evals/run_evaluator_eval.py --faults factual_error,complex_language --repeat 2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE = os.environ.get("LESSONGEN_URL", "http://localhost:8080").rstrip("/")
REPORTS = Path(__file__).parent / "reports"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def call(method: str, path: str, body: Any = None, timeout: float = 900) -> Any:
    request = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def evaluate(lesson: dict[str, Any]) -> dict[str, Any]:
    return call("POST", "/api/evaluator/v1/evaluations", {"lesson": lesson, "topic_id": "rag"})


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--faults", help="comma-separated preset ids (default: all)")
    parser.add_argument(
        "--repeat", type=int, default=1, help="evaluations per case (judges are stochastic)"
    )
    args = parser.parse_args()

    reference = call("GET", "/api/evaluator/v1/faults/reference-lesson")
    presets = call("GET", "/api/evaluator/v1/faults")
    if args.faults:
        wanted = set(args.faults.split(","))
        presets = [p for p in presets if p["id"] in wanted]

    rows: list[dict[str, Any]] = []
    cost = 0.0
    started = time.time()

    for i in range(args.repeat):
        report = evaluate(reference)
        cost += report["usage"]["cost_usd"]
        rows.append(
            {
                "case": "clean reference lesson",
                "repeat": i + 1,
                "expected": [],
                "failed": report["failed_check_ids"],
            }
        )
        print(f"clean #{i + 1}: false alarms = {report['failed_check_ids'] or 'none'}")

    for preset in presets:
        faulted = call(
            "POST",
            "/api/evaluator/v1/faults/apply",
            {"lesson": reference, "fault_id": preset["id"]},
        )["lesson"]
        for i in range(args.repeat):
            report = evaluate(faulted)
            cost += report["usage"]["cost_usd"]
            failed = report["failed_check_ids"]
            caught = [c for c in preset["expected_checks"] if c in failed]
            rows.append(
                {
                    "case": preset["id"],
                    "repeat": i + 1,
                    "expected": preset["expected_checks"],
                    "failed": failed,
                    "caught": caught,
                }
            )
            print(
                f"{preset['id']} #{i + 1}: expected {preset['expected_checks']} -> caught {caught or 'NONE'} (failed: {failed})"
            )

    fault_rows = [r for r in rows if r["expected"]]
    expected_total = sum(len(r["expected"]) for r in fault_rows)
    caught_total = sum(len(r["caught"]) for r in fault_rows)
    detected_any = sum(1 for r in fault_rows if r["caught"])
    clean_rows = [r for r in rows if not r["expected"]]
    false_fails = sum(len(r["failed"]) for r in clean_rows)
    check_count = 23

    summary = {
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "presets": len(presets),
        "repeat": args.repeat,
        "fault_detected_rate": round(detected_any / len(fault_rows), 3) if fault_rows else None,
        "expected_check_recall": round(caught_total / expected_total, 3)
        if expected_total
        else None,
        "false_fail_rate": round(false_fails / (len(clean_rows) * check_count), 3)
        if clean_rows
        else None,
        "cost_usd": round(cost, 3),
        "minutes": round((time.time() - started) / 60, 1),
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    (REPORTS / f"evaluator-eval-{stamp}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8"
    )
    lines = [
        f"# Evaluator meta-evaluation - {summary['date']}",
        "",
        f"- Presets: {summary['presets']} x {summary['repeat']} repeat(s); cost ${summary['cost_usd']}, {summary['minutes']} min",
        f"- **Faults detected** (at least one expected check failed): {summary['fault_detected_rate']:.0%}"
        if fault_rows
        else "",
        f"- **Expected-check recall** (expected checks that failed): {summary['expected_check_recall']:.0%}"
        if expected_total
        else "",
        f"- **False-fail rate on the clean lesson** (failed checks / checks evaluated): {summary['false_fail_rate']:.1%}"
        if clean_rows
        else "",
        "",
        "| Case | Expected to fail | Actually failed | Caught |",
        "|---|---|---|---|",
    ]
    for r in rows:
        caught = ", ".join(r.get("caught", [])) or ("-" if not r["expected"] else "**missed**")
        lines.append(
            f"| {r['case']} | {', '.join(r['expected']) or '(none)'} | {', '.join(r['failed']) or '(none)'} | {caught} |"
        )
    path = REPORTS / f"evaluator-eval-{stamp}.md"
    path.write_text("\n".join(line for line in lines if line is not None) + "\n", encoding="utf-8")
    print(f"\n{json.dumps(summary, indent=2)}\nreport: {path}")


if __name__ == "__main__":
    main()
