"""LLM doctor: verifies the Azure OpenAI configuration with tiny real calls.

For every distinct deployment used by a role it checks a plain completion, structured
output (json_schema) and forced tool calling - the three capabilities the agents rely on.
Run it once after filling in .env:

    docker compose run --rm orchestrator-worker python -m lessongen_common.llm.doctor
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any

from pydantic import BaseModel

from lessongen_common.llm.config import LLMRole
from lessongen_common.llm.provider import LLMProvider


class _Ping(BaseModel):
    ok: bool
    word: str


class _PingTool(BaseModel):
    """Call this tool with the word 'pong'."""

    word: str


async def _timed(coro: Any) -> tuple[bool, str, int]:
    started = time.perf_counter()
    try:
        detail = await coro
        return True, str(detail)[:120], int((time.perf_counter() - started) * 1000)
    except Exception as exc:  # report, never raise: this is a diagnostic
        return (
            False,
            f"{type(exc).__name__}: {str(exc)[:300]}",
            int((time.perf_counter() - started) * 1000),
        )


async def _plain(model: Any) -> str:
    reply = await model.ainvoke("Reply with exactly one word: OK")
    return str(reply.content)


async def _structured(model: Any) -> str:
    out = await model.with_structured_output(_Ping, method="json_schema").ainvoke(
        "Return ok=true and word='pong'."
    )
    return out.model_dump_json()


async def _tools(model: Any) -> str:
    bound = model.bind_tools([_PingTool], tool_choice="required")
    reply = await bound.ainvoke("Call the tool.")
    return f"{len(reply.tool_calls)} tool call(s)"


async def run_doctor(provider: LLMProvider | None = None) -> list[dict[str, Any]]:
    provider = provider or LLMProvider()
    by_deployment: dict[str, list[LLMRole]] = {}
    for role in LLMRole:
        by_deployment.setdefault(provider.resolve(role).deployment, []).append(role)

    results: list[dict[str, Any]] = []
    for deployment, roles in by_deployment.items():
        model = provider.get(roles[0])
        row: dict[str, Any] = {
            "deployment": deployment,
            "roles": [r.value for r in roles],
            "reasoning_effort": provider.resolve(roles[0]).reasoning_effort,
        }
        for name, check in (
            ("chat", _plain),
            ("structured_output", _structured),
            ("tool_calling", _tools),
        ):
            ok, detail, ms = await _timed(check(model))
            row[name] = {"ok": ok, "detail": detail, "latency_ms": ms}
        # Every reasoning effort configured for this deployment must be accepted by the
        # API version in use (e.g. "none" needs a recent one).
        by_effort: dict[str, LLMRole] = {}
        for role in roles:
            by_effort.setdefault(str(provider.resolve(role).reasoning_effort or "default"), role)
        row["efforts"] = {}
        for effort, role in by_effort.items():
            ok, detail, ms = await _timed(_plain(provider.get(role)))
            row["efforts"][effort] = {"ok": ok, "detail": detail, "latency_ms": ms}
        row["ok"] = all(
            row[k]["ok"] for k in ("chat", "structured_output", "tool_calling")
        ) and all(e["ok"] for e in row["efforts"].values())
        results.append(row)
    return results


def main() -> int:
    provider = LLMProvider()
    if not provider.settings.configured:
        print("Azure OpenAI is not configured: set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY.")
        return 2
    rows = asyncio.run(run_doctor(provider))
    for row in rows:
        status = "OK  " if row["ok"] else "FAIL"
        print(f"[{status}] {row['deployment']}  roles={','.join(row['roles'])}")
        checks = [(c, row[c]) for c in ("chat", "structured_output", "tool_calling")]
        checks += [(f"effort={e}", r) for e, r in row["efforts"].items()]
        for name, r in checks:
            print(
                f"    {name:18s} {'ok ' if r['ok'] else 'ERR'} {r['latency_ms']:>6} ms  {r['detail']}"
            )
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
