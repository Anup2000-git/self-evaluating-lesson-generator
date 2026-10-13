"""Planner: one structured call that outlines the lesson before anything is written.

Planning first separates *what to teach* from *how to write it*: coverage and teaching
order are decided once, and revisions can fix the writing without re-deciding the content.
Knowledge notes are retrieved deterministically (one query per key point), so the plan is
grounded without an agent loop.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from generator_svc.common import PROMPTS, focus_lines, guidelines_for
from generator_svc.settings import GeneratorSettings
from lessongen_common.audience import AUDIENCE_PROFILE, AUDIENCE_SHORT
from lessongen_common.clients import KnowledgeClient, RubricProvider
from lessongen_common.events import emit
from lessongen_common.llm import LLMProvider, LLMRole, invoke_structured, usage_scope
from lessongen_common.schemas import (
    REQUIRED_SECTIONS,
    TEACHING_ORDER,
    EventType,
    GuidelineTarget,
    LessonPlan,
    PlanRequest,
    PlanResponse,
    SearchHit,
)


def plan_problems(plan: LessonPlan) -> list[str]:
    kinds = [s.kind for s in plan.sections]
    problems = [f"missing a '{k.value}' section" for k in REQUIRED_SECTIONS if k not in kinds]
    present = [k for k in TEACHING_ORDER if k in kinds]
    first = sorted(present, key=kinds.index)
    if first != present:
        problems.append("sections must follow the order " + " -> ".join(k.value for k in present))
    if not 3 <= len(plan.learning_objectives) <= 4:
        problems.append("write 3 or 4 learning objectives")
    return problems


class Planner:
    def __init__(
        self,
        llm: LLMProvider,
        knowledge: KnowledgeClient,
        rubrics: RubricProvider,
        settings: GeneratorSettings,
    ) -> None:
        self.llm = llm
        self.knowledge = knowledge
        self.rubrics = rubrics
        self.settings = settings

    async def _research(self, topic_id: str, queries: list[str]) -> list[SearchHit]:
        seen: set[str] = set()
        notes: list[SearchHit] = []
        for query in queries:
            response = await self.knowledge.search(
                topic_id, query, self.settings.planner_notes_per_query
            )
            for hit in response.hits:
                if hit.chunk.id not in seen:
                    seen.add(hit.chunk.id)
                    notes.append(hit)
        return notes

    async def plan(self, request: PlanRequest) -> PlanResponse:
        context = request.context
        with usage_scope() as usage:
            topic = await self.knowledge.topic(context.topic_id)
            kp = topic.key_points
            notes = await self._research(
                topic.id,
                [kp.what, *kp.why, *kp.how_steps, *kp.misconceptions[:2], *kp.limitations[:2]],
            )
            glossary = await self.knowledge.glossary(topic.id)
            rubric = await self.rubrics.get()
            titles = {c.id: c.title for c in rubric.checks}
            messages = [
                SystemMessage(
                    content=PROMPTS.render(
                        "planner_system.md.j2",
                        audience=AUDIENCE_SHORT,
                        audience_profile=AUDIENCE_PROFILE,
                        topic_title=topic.title,
                        helper_language=context.helper_language,
                    )
                ),
                HumanMessage(
                    content=PROMPTS.render(
                        "planner_user.md.j2",
                        topic=topic,
                        notes=notes,
                        glossary_terms=[g.term for g in glossary],
                        guidelines=guidelines_for(context.memory, GuidelineTarget.PLANNER),
                        focus=focus_lines(context.memory, titles),
                    )
                ),
            ]
            plan = await invoke_structured(
                self.llm, self.llm.get(LLMRole.PLANNER), LessonPlan, messages, name="planner"
            )
            for _ in range(self.settings.planner_max_attempts - 1):
                problems = plan_problems(plan)
                if not problems:
                    break
                messages = [
                    *messages,
                    HumanMessage(
                        content="Your plan has problems: "
                        + "; ".join(problems)
                        + ". Return the corrected complete plan as JSON."
                    ),
                ]
                plan = await invoke_structured(
                    self.llm,
                    self.llm.get(LLMRole.PLANNER),
                    LessonPlan,
                    messages,
                    name="planner.fix",
                )
        await emit(
            EventType.PLAN_CREATED,
            {
                "title": plan.title,
                "objectives": plan.learning_objectives,
                "sections": [{"kind": s.kind.value, "heading": s.heading} for s in plan.sections],
                "analogy": plan.analogy,
                "worked_example": plan.worked_example,
                "notes_used": [h.chunk.id for h in notes],
            },
        )
        return PlanResponse(
            plan=plan,
            usage=usage,
            prompt_version=f"{PROMPTS.version('planner_system.md.j2')}+{PROMPTS.version('planner_user.md.j2')}",
        )
