"""COV-5: does the lesson actually teach? A simulated beginner answers held-out questions.

The learner model must quote the lesson sentence that supports each answer; an answer
only counts if that quote is really in the lesson. This stops the model from answering
from its own knowledge of AI and turns the simulation into a test of the lesson itself.
The questions come from the topic pack and are never shown to the writer.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from evaluator_svc.checks.evidence import quote_found
from evaluator_svc.context import EvalContext
from evaluator_svc.settings import EvaluatorSettings
from lessongen_common.audience import AUDIENCE_SHORT
from lessongen_common.llm import LLMProvider, LLMRole, invoke_structured
from lessongen_common.prompts import PromptLibrary
from lessongen_common.schemas import CheckResult, CheckSpec, Verdict

PROMPTS = PromptLibrary(Path(__file__).resolve().parent.parent / "prompts")


class LearnerAnswer(BaseModel):
    question_id: str
    answer: str
    support_quote: str


class LearnerAnswers(BaseModel):
    answers: list[LearnerAnswer]


class Grade(BaseModel):
    question_id: str
    correct: bool
    reason: str


class Grades(BaseModel):
    grades: list[Grade]


class LearnerSimulator:
    def __init__(self, llm: LLMProvider, settings: EvaluatorSettings) -> None:
        self.llm = llm
        self.settings = settings

    async def run(self, ctx: EvalContext, spec: CheckSpec) -> CheckResult:
        questions = ctx.topic.learner_questions
        min_correct = int(spec.params.get("min_correct", max(1, len(questions) - 1)))
        answers = await invoke_structured(
            self.llm,
            self.llm.get(LLMRole.LEARNER),
            LearnerAnswers,
            [
                HumanMessage(
                    content=PROMPTS.render(
                        "learner.md.j2",
                        audience=AUDIENCE_SHORT,
                        lesson_markdown=ctx.lesson_markdown,
                        questions=questions,
                    )
                )
            ],
            name="learner.answer",
        )
        by_q = {a.question_id: a for a in answers.answers}
        items = [
            {
                "id": q.id,
                "question": q.question,
                "reference": q.reference_answer,
                "answer": by_q[q.id].answer if q.id in by_q else "NOT IN LESSON",
            }
            for q in questions
        ]
        grades = await invoke_structured(
            self.llm,
            self.llm.get(LLMRole.JUDGE),
            Grades,
            [HumanMessage(content=PROMPTS.render("grader.md.j2", items=items))],
            name="learner.grade",
        )
        graded = {g.question_id: g for g in grades.grades}

        rows = []
        for q in questions:
            answer = by_q.get(q.id)
            grade = graded.get(q.id)
            supported = bool(
                answer
                and answer.support_quote.strip()
                and quote_found(
                    answer.support_quote,
                    ctx.normalized_lesson,
                    self.settings.evidence_match_threshold,
                )
            )
            correct = bool(grade and grade.correct and supported)
            rows.append(
                {
                    "question_id": q.id,
                    "question": q.question,
                    "answer": answer.answer if answer else "NOT IN LESSON",
                    "support_quote": answer.support_quote if answer else "",
                    "supported_by_lesson": supported,
                    "correct": correct,
                    "grader_reason": grade.reason if grade else "not graded",
                }
            )
        score = sum(1 for r in rows if r["correct"])
        missed = [r for r in rows if not r["correct"]]
        passed = score >= min_correct
        return CheckResult(
            check_id=spec.id,
            dimension=spec.dimension,
            title=spec.title,
            method=spec.method,
            severity=spec.severity,
            verdict=Verdict.PASS if passed else Verdict.FAIL,
            reasoning=f"The simulated learner answered {score} of {len(rows)} held-out questions "
            f"correctly from the lesson alone (need {min_correct})."
            + (
                ""
                if passed
                else " Missed: "
                + "; ".join(f"{r['question_id']} ({r['grader_reason'][:120]})" for r in missed)
            ),
            evidence=[f"{r['question']} -> learner: {r['answer'][:160]}" for r in missed][:3],
            fix_instruction=""
            if passed
            else "A beginner reading only the lesson could not answer: "
            + " | ".join(f'"{r["question"]}"' for r in missed)
            + ". Teach these ideas explicitly, in simple words, in the body of the lesson.",
            evidence_verified=True,
            details={"score": score, "needed": min_correct, "answers": rows},
        )
