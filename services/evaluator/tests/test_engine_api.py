"""The full evaluation graph and the HTTP API, with every model scripted."""

from typing import Any

from fastapi.testclient import TestClient

from evaluator_svc.checks.fact_checker import ClaimList
from evaluator_svc.engine import EvaluationEngine
from evaluator_svc.main import create_app
from lessongen_common.context import bind_context
from lessongen_common.events import EventBus, configure_event_bus
from lessongen_common.llm import LLMProvider, LLMRole, LLMSettings
from lessongen_common.schemas import EvaluateRequest, Verdict
from lessongen_common.testing import ScriptedChatModel, sample_lesson, tool_call_message


class RecordingBus(EventBus):
    def __init__(self) -> None:
        super().__init__(None, "evaluator")
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(
        self, run_id: str, type: str, data: dict | None = None, **kwargs: Any
    ) -> None:  # type: ignore[override]
        self.events.append((type, data or {}))


def _engine(
    settings, fake_knowledge, fake_rubrics, responder, *, fail=(), crash=(), contradicted=False
) -> EvaluationEngine:
    respond = responder(set(fail), set(crash))
    verdict = "CONTRADICTED" if contradicted else "SUPPORTED"
    models = {
        LLMRole.JUDGE: ScriptedChatModel(model_name="mini", script=[respond] * 60),
        LLMRole.JUDGE_CONFIRM: ScriptedChatModel(model_name="mini-careful", script=[respond] * 30),
        LLMRole.JUDGE_TIEBREAK: ScriptedChatModel(model_name="gpt-5.5", script=[respond] * 30),
        LLMRole.FACT_CHECKER: ScriptedChatModel(
            script=[
                ClaimList(
                    claims=[
                        {
                            "id": "1",
                            "quote": "RAG does not change the LLM at all.",
                            "claim": "RAG does not change the model.",
                            "kind": "concept",
                        }
                    ]
                ),
                tool_call_message(
                    "submit_verdicts",
                    {
                        "verdicts": [
                            {
                                "claim_id": "C1",
                                "verdict": verdict,
                                "kb_chunk_ids": ["k"],
                                "explanation": "KB agrees."
                                if not contradicted
                                else "KB disagrees.",
                            }
                        ]
                    },
                ),
            ]
        ),
        LLMRole.LEARNER: ScriptedChatModel(
            script=[
                {
                    "answers": [
                        {
                            "question_id": f"Q{i}",
                            "answer": "an answer",
                            "support_quote": "RAG works in two parts.",
                        }
                        for i in range(1, 7)
                    ]
                }
            ]
        ),
    }
    provider = LLMProvider(LLMSettings(_env_file=None), overrides=models)  # type: ignore[call-arg]
    return EvaluationEngine(provider, fake_knowledge, fake_rubrics, settings)


async def test_engine_runs_all_23_checks_and_passes_a_good_lesson(
    settings, fake_knowledge, fake_rubrics, responder
) -> None:
    bus = RecordingBus()
    configure_event_bus(bus)
    try:
        with bind_context(run_id="run-1", attempt=1):
            report = await _engine(settings, fake_knowledge, fake_rubrics, responder).evaluate(
                EvaluateRequest(lesson=sample_lesson(), topic_id="rag")
            )
    finally:
        configure_event_bus(None)
    assert len(report.results) == 23
    assert report.passed, report.summary
    assert [r.check_id for r in report.results][:3] == ["ACC-1", "ACC-2", "ACC-3"]  # rubric order
    types = [t for t, _ in bus.events]
    assert types.count("check.completed") == 23
    assert types[-1] == "evaluation.completed"


async def test_engine_reports_failures_and_crashes_fail_safe(
    settings, fake_knowledge, fake_rubrics, responder
) -> None:
    engine = _engine(
        settings,
        fake_knowledge,
        fake_rubrics,
        responder,
        fail={"EX-2"},
        crash={"FLOW-2"},
        contradicted=True,
    )
    report = await engine.evaluate(EvaluateRequest(lesson=sample_lesson(), topic_id="rag"))
    assert not report.passed
    assert set(report.failed_check_ids) == {"ACC-1", "EX-2", "FLOW-2"}
    assert report.error_check_ids == ["FLOW-2"]
    flow2 = next(r for r in report.results if r.check_id == "FLOW-2")
    assert flow2.verdict == Verdict.FAIL and "could not be evaluated" in flow2.reasoning
    ex2 = next(r for r in report.results if r.check_id == "EX-2")
    assert len(ex2.votes) == 2  # FAIL confirmed by a second vote


def test_api_faults_and_evaluation(settings, fake_knowledge, fake_rubrics, responder) -> None:
    engine = _engine(settings, fake_knowledge, fake_rubrics, responder)
    app = create_app(settings, engine=engine)
    with TestClient(app) as client:
        faults = client.get("/v1/faults").json()
        assert {f["id"] for f in faults} >= {"factual_error", "wrong_hindi_hint"}
        injected = client.post(
            "/v1/faults/apply",
            json={"lesson": sample_lesson().model_dump(mode="json"), "fault_id": "factual_error"},
        ).json()
        assert injected["fault"]["expected_checks"] == ["ACC-1"]
        report = client.post(
            "/v1/evaluations",
            json={"lesson": sample_lesson().model_dump(mode="json"), "topic_id": "rag"},
        )
        assert report.status_code == 200 and report.json()["passed"] is True
        bad = client.post(
            "/v1/faults/apply",
            json={"lesson": sample_lesson().model_dump(mode="json"), "fault_id": "nope"},
        )
        assert bad.status_code == 404
