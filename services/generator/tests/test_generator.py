from fastapi.testclient import TestClient
from langchain_core.messages import ToolMessage

from generator_svc.main import create_app
from generator_svc.planner import Planner, plan_problems
from generator_svc.writer import Writer, _targets, lesson_problems
from lessongen_common.llm import LLMProvider, LLMRole, LLMSettings
from lessongen_common.rubric import load_seed_rubric
from lessongen_common.schemas import (
    PlanRequest,
    ReviseRequest,
    ReviseStrategy,
    SectionKind,
    WriteRequest,
)
from lessongen_common.testing import (
    ScriptedChatModel,
    multi_tool_call_message,
    sample_lesson,
    sample_plan,
    sample_report,
    tool_call_message,
)

TARGETS = _targets(load_seed_rubric())


def _provider(**models: ScriptedChatModel) -> LLMProvider:
    return LLMProvider(
        LLMSettings(_env_file=None), overrides={LLMRole(k): v for k, v in models.items()}
    )  # type: ignore[call-arg]


def test_lesson_problems_catch_contract_script_and_length() -> None:
    assert lesson_problems(sample_lesson(), "Hindi", TARGETS) == []
    broken = sample_lesson()
    broken.glossary[0].helper_meaning = "artificial intelligence"
    broken.sections = [s for s in broken.sections if s.kind != SectionKind.EXAMPLE]
    broken.sections[1].body_markdown = "Too short."
    problems = " | ".join(lesson_problems(broken, "Hindi", TARGETS))
    assert "missing a 'example' section" in problems
    assert "must be written in Hindi script" in problems
    assert "write at least 900" in problems


async def test_planner_grounds_the_plan_and_fixes_its_own_problems(
    settings, knowledge, rubrics, context
) -> None:
    bad = sample_plan().model_copy(update={"sections": sample_plan().sections[:2]})
    model = ScriptedChatModel(script=[bad, sample_plan()])
    planner = Planner(_provider(planner=model), knowledge, rubrics, settings)
    response = await planner.plan(PlanRequest(context=context))
    assert plan_problems(response.plan) == []
    assert len(model.calls) == 2
    assert "missing a 'why' section" in str(model.calls[1][-1].content)
    user_prompt = str(model.calls[0][1].content)
    assert "Plan the analogy first." in user_prompt  # planner guideline injected
    assert "Explain 'embedding'" not in user_prompt  # writer-only guideline is not
    assert knowledge.queries  # deterministic research happened
    assert response.prompt_version.startswith("planner_system@")


async def test_writer_researches_self_checks_and_resubmits(
    settings, knowledge, rubrics, context
) -> None:
    too_few_questions = sample_lesson().model_copy(update={"quiz": sample_lesson().quiz[:2]})
    model = ScriptedChatModel(
        script=[
            multi_tool_call_message(
                [
                    (
                        "search_knowledge_base",
                        {"reason": "Need the definition", "query": "what is RAG"},
                    ),
                    (
                        "lookup_glossary",
                        {"reason": "Need hints", "terms": ["Retrieval", "Embedding", "Quantum"]},
                    ),
                ]
            ),
            tool_call_message(
                "check_readability",
                {"reason": "Check the draft", "text": sample_lesson().body_markdown()},
            ),
            tool_call_message("submit_lesson", too_few_questions.model_dump(mode="json")),
            tool_call_message("submit_lesson", sample_lesson().model_dump(mode="json")),
        ]
    )
    writer = Writer(_provider(writer=model), knowledge, rubrics, settings)
    response = await writer.write(WriteRequest(context=context, plan=sample_plan()))

    assert response.lesson == sample_lesson()
    assert response.agent_steps == 4
    observations = [m.content for m in model.calls[2] if isinstance(m, ToolMessage)]
    assert any("खोजकर लाना" in str(o) for o in observations)  # approved Hindi hint returned
    assert any(
        "Not in the approved glossary" in str(o) and "Quantum" in str(o) for o in observations
    )
    readability = str([m for m in model.calls[2] if isinstance(m, ToolMessage)][-1].content)
    assert "Flesch-Kincaid grade" in readability and "target <= 8.0" in readability
    rejection = str(model.calls[3][-1].content)
    assert "REJECTED" in rejection and "need 3 to 5 questions" in rejection
    system = str(model.calls[0][0].content)
    assert "COV-5 Simulated learner passes" in system  # the rubric is the writer's spec
    assert "Explain 'embedding' as a list of numbers" in system  # learned guideline
    assert "Use more cricket examples." in system  # human note
    assert "Plan the analogy first." not in system


async def test_writer_revision_must_explain_every_fix(
    settings, knowledge, rubrics, context
) -> None:
    report = sample_report(["JAR-2", "EX-1"])
    failed = report.failed_results()
    fixed = sample_lesson()
    model = ScriptedChatModel(
        script=[
            tool_call_message(
                "submit_revision",
                {
                    "lesson": fixed.model_dump(mode="json"),
                    "revision_notes": [{"check_id": "JAR-2", "change": "Defined embedding first."}],
                },
            ),
            tool_call_message(
                "submit_revision",
                {
                    "lesson": fixed.model_dump(mode="json"),
                    "revision_notes": [
                        {
                            "check_id": "JAR-2",
                            "change": "Defined embedding before its first use in 'How it works'.",
                        },
                        {
                            "check_id": "EX-1",
                            "change": "Showed the exact retrieved notice text in the example.",
                        },
                        {"check_id": "LANG-9", "change": "Unrelated note."},
                    ],
                },
            ),
        ]
    )
    writer = Writer(_provider(writer=model), knowledge, rubrics, settings)
    response = await writer.revise(
        ReviseRequest(
            context=context,
            plan=sample_plan(),
            previous_lesson=sample_lesson(),
            failed=failed,
            passed_check_ids=[r.check_id for r in report.results if r.passed],
            strategy=ReviseStrategy.PATCH,
        )
    )
    assert [n.check_id for n in response.revision_notes] == ["JAR-2", "EX-1"]
    assert "add a revision note for each failed check: EX-1" in str(model.calls[1][-1].content)
    revise_prompt = str(model.calls[0][1].content)
    assert "Fix JAR-2." in revise_prompt and "change only what is needed" in revise_prompt


def test_api_routes(settings, knowledge, rubrics, context) -> None:
    model = ScriptedChatModel(script=[sample_plan()])
    app = create_app(settings, _provider(planner=model), knowledge=knowledge, rubrics=rubrics)
    with TestClient(app) as client:
        response = client.post(
            "/v1/plans", json=PlanRequest(context=context).model_dump(mode="json")
        )
        assert response.status_code == 200
        assert response.json()["plan"]["title"] == sample_plan().title
        assert client.get("/healthz").json()["service"] == "generator"
