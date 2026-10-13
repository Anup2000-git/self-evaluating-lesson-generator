"""Fact-checker (ReAct) and simulated-learner checks with scripted models."""

from evaluator_svc.checks.fact_checker import ClaimList, FactChecker
from evaluator_svc.checks.learner import LearnerSimulator
from evaluator_svc.faults import FACTUAL_ERROR, apply_fault
from lessongen_common.llm import LLMProvider, LLMRole, LLMSettings
from lessongen_common.rubric import load_seed_rubric
from lessongen_common.schemas import Verdict
from lessongen_common.testing import (
    ScriptedChatModel,
    multi_tool_call_message,
    sample_lesson,
    tool_call_message,
)

RUBRIC = load_seed_rubric()
ACC = [RUBRIC.by_id("ACC-1"), RUBRIC.by_id("ACC-2")]


def _provider(**models: ScriptedChatModel) -> LLMProvider:
    return LLMProvider(
        LLMSettings(_env_file=None),  # type: ignore[call-arg]
        overrides={LLMRole(k): v for k, v in models.items()},
    )


CLAIMS = ClaimList(
    claims=[
        {
            "id": "x",
            "quote": FACTUAL_ERROR,
            "claim": "RAG retrains the model on your documents for every question.",
            "kind": "concept",
        },
        {
            "id": "y",
            "quote": "An embedding is a list of numbers that captures the meaning of the text.",
            "claim": "An embedding is a list of numbers that captures meaning.",
            "kind": "concept",
        },
    ]
)


async def test_fact_checker_catches_the_injected_false_claim(
    settings, make_ctx, fake_knowledge
) -> None:
    model = ScriptedChatModel(
        model_name="mini",
        script=[
            CLAIMS,
            multi_tool_call_message(
                [
                    (
                        "search_knowledge_base",
                        {"reason": "Check C1", "query": "does RAG retrain the model"},
                    ),
                    (
                        "search_knowledge_base",
                        {"reason": "Check C2", "query": "what is an embedding"},
                    ),
                ]
            ),
            tool_call_message(
                "submit_verdicts",
                {
                    "verdicts": [
                        {
                            "claim_id": "C1",
                            "verdict": "CONTRADICTED",
                            "kb_chunk_ids": ["k1"],
                            "explanation": "RAG does not retrain the model.",
                        }
                    ]
                },
            ),
            tool_call_message(
                "submit_verdicts",
                {
                    "verdicts": [
                        {
                            "claim_id": "C1",
                            "verdict": "CONTRADICTED",
                            "kb_chunk_ids": ["k1"],
                            "explanation": "RAG does not retrain the model or change its weights.",
                        },
                        {
                            "claim_id": "C2",
                            "verdict": "SUPPORTED",
                            "kb_chunk_ids": ["k2"],
                            "explanation": "Embeddings are lists of numbers representing meaning.",
                        },
                    ]
                },
            ),
        ],
    )
    checker = FactChecker(_provider(fact_checker=model), fake_knowledge, settings)
    lesson = apply_fault(sample_lesson(), "factual_error").lesson
    acc1, acc2 = await checker.run(make_ctx(lesson), ACC)

    assert acc1.verdict == Verdict.FAIL
    assert acc1.evidence == [FACTUAL_ERROR]
    assert "does not retrain" in acc1.fix_instruction
    assert acc2.verdict == Verdict.PASS  # no specific facts (numbers, names) were claimed
    assert [c["id"] for c in acc1.details["claims"]] == ["C1", "C2"]
    assert fake_knowledge.queries == ["does RAG retrain the model", "what is an embedding"]
    # The first submission skipped C2 and was rejected with an explanation.
    rejection = str(model.calls[3][-1].content)
    assert "missing verdicts for claims: C2" in rejection


async def test_invented_specific_fact_fails_acc2(settings, make_ctx, fake_knowledge) -> None:
    claims = ClaimList(
        claims=[
            {
                "id": "1",
                "quote": "RAG was invented by Google in 2015",
                "claim": "Google invented RAG in 2015.",
                "kind": "specific_fact",
            }
        ]
    )
    model = ScriptedChatModel(
        script=[
            claims,
            tool_call_message(
                "submit_verdicts",
                {
                    "verdicts": [
                        {
                            "claim_id": "C1",
                            "verdict": "NOT_FOUND",
                            "kb_chunk_ids": [],
                            "explanation": "KB says 2020, Facebook AI Research.",
                        }
                    ]
                },
            ),
        ]
    )
    lesson = apply_fault(sample_lesson(), "invented_statistic").lesson
    acc1, acc2 = await FactChecker(_provider(fact_checker=model), fake_knowledge, settings).run(
        make_ctx(lesson), ACC
    )
    assert acc1.verdict == Verdict.PASS  # not contradicted, just unsupported
    assert acc2.verdict == Verdict.FAIL


async def test_learner_needs_lesson_backed_answers(settings, make_ctx) -> None:
    learner_model = ScriptedChatModel(
        script=[
            {
                "answers": [
                    {
                        "question_id": "Q1",
                        "answer": "Retrieval-Augmented Generation",
                        "support_quote": "It is called RAG, which stands for Retrieval-Augmented Generation.",
                    },
                    {
                        "question_id": "Q2",
                        "answer": "Its knowledge stops at the cutoff date",
                        "support_quote": "This date is called its knowledge cutoff",
                    },
                    {
                        "question_id": "Q3",
                        "answer": "It finds useful information first",
                        "support_quote": "RAG is a method where the system first finds useful information",
                    },
                    {
                        "question_id": "Q4",
                        "answer": "Retrieve, augment, generate",
                        "support_quote": "First, it retrieves useful chunks from a knowledge base.",
                    },
                    {
                        "question_id": "Q5",
                        "answer": "No",
                        "support_quote": "This sentence is not in the lesson at all, I made it up.",
                    },
                    {"question_id": "Q6", "answer": "NOT IN LESSON", "support_quote": ""},
                ]
            }
        ]
    )
    grader = ScriptedChatModel(
        script=[
            {
                "grades": [
                    {
                        "question_id": f"Q{i}",
                        "correct": i != 6,
                        "reason": "ok" if i != 6 else "no answer",
                    }
                    for i in range(1, 7)
                ]
            }
        ]
    )
    simulator = LearnerSimulator(_provider(learner=learner_model, judge=grader), settings)
    result = await simulator.run(make_ctx(), RUBRIC.by_id("COV-5"))

    rows = {r["question_id"]: r for r in result.details["answers"]}
    assert rows["Q5"]["supported_by_lesson"] is False and rows["Q5"]["correct"] is False
    assert result.details["score"] == 4
    assert result.verdict == Verdict.FAIL  # needs 5 of 6
    assert "Does RAG permanently change" in result.fix_instruction
    learner_prompt = str(learner_model.calls[0][0].content)
    assert "<lesson>" in learner_prompt and "Q6:" in learner_prompt
