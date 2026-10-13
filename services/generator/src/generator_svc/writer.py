"""The writer: a ReAct agent that researches, drafts, self-checks and submits the lesson.

Tools
* search_knowledge_base - grounding: every technical fact comes from the curated pack.
* lookup_glossary       - approved simple meanings + helper-language hints (consistent, correct).
* check_readability     - the SAME metric code the evaluator uses, so the writer can self-check.
* submit_lesson / submit_revision - typed final answer; structural contract violations are
  returned to the agent so it fixes them before the expensive evaluation runs.

The same agent revises: it receives the failed checks (reason, evidence, fix) and the checks
that passed (must not regress), and must explain per failed check what it changed.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from generator_svc.common import PROMPTS, focus_lines, guidelines_for
from generator_svc.settings import GeneratorSettings
from lessongen_common import textmetrics as tm
from lessongen_common.audience import AUDIENCE_PROFILE, AUDIENCE_SHORT
from lessongen_common.clients import KnowledgeClient, RubricProvider
from lessongen_common.llm import (
    AgentTool,
    LLMProvider,
    LLMRole,
    ReactAgent,
    SubmitTool,
    usage_scope,
)
from lessongen_common.schemas import (
    GenerationContext,
    GuidelineTarget,
    Lesson,
    LessonResponse,
    LessonRevision,
    ReviseRequest,
    ReviseStrategy,
    Rubric,
    TopicPack,
    WriteRequest,
    validate_lesson_contract,
)


class SearchArgs(BaseModel):
    reason: str = Field(description="One short sentence: why you need this now.")
    query: str = Field(description="What to look up in the knowledge base.")


class GlossaryArgs(BaseModel):
    reason: str = Field(description="One short sentence: why you need these terms.")
    terms: list[str] = Field(description="Technical terms to look up (max 15).")


class ReadabilityArgs(BaseModel):
    reason: str = Field(description="One short sentence: what you are checking.")
    text: str = Field(description="Draft text (Markdown) to check.")


def _targets(rubric: Rubric) -> dict[str, float]:
    def param(check_id: str, name: str, default: float) -> float:
        try:
            return float(rubric.by_id(check_id).params.get(name, default))
        except KeyError:
            return default

    return {
        "max_grade": param("LANG-1", "max_grade", 8.0),
        "max_avg_words": param("LANG-2", "max_avg_words", 15),
        "max_words": param("LANG-2", "max_words", 28),
        "max_difficult": param("LANG-3", "max_distinct", 10),
        "zipf": param("LANG-3", "zipf_threshold", tm.DEFAULT_ZIPF_THRESHOLD),
        "min_words": param("LANG-5", "min_words", 900),
        "max_words_total": param("LANG-5", "max_words", 2000),
    }


def _body_word_count(lesson: Lesson) -> int:
    body = "\n\n".join(s.body_markdown for s in lesson.sections)
    return len(tm.words(tm.english_only(tm.strip_markdown(body))))


def lesson_problems(lesson: Lesson, helper_language: str, targets: dict[str, float]) -> list[str]:
    """Contract problems the writer must fix before submitting (cheap, deterministic)."""
    problems = [f"{v.field}: {v.problem}" for v in validate_lesson_contract(lesson)]
    for entry in lesson.glossary:
        if tm.has_script(entry.helper_meaning, helper_language) is False:
            problems.append(
                f"glossary '{entry.term}': helper_meaning must be written in {helper_language} script"
            )
    words = _body_word_count(lesson)
    if words < targets["min_words"]:
        problems.append(
            f"the lesson body has only {words} words; write at least {int(targets['min_words'])}"
        )
    if words > targets["max_words_total"]:
        problems.append(
            f"the lesson body has {words} words; keep it under {int(targets['max_words_total'])}"
        )
    return problems


class Writer:
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

    # ----------------------------------------------------------------- tools
    def _tools(
        self, topic: TopicPack, helper_language: str, targets: dict[str, float]
    ) -> list[AgentTool[Any]]:
        language_key = helper_language.strip().lower()
        allowed = [j.term for j in topic.jargon] + [a for j in topic.jargon for a in j.aliases]

        async def search(args: SearchArgs) -> str:
            response = await self.knowledge.search(topic.id, args.query, 4)
            if not response.hits:
                return "No matching knowledge-base chunks. Do not state facts you cannot ground."
            return "\n\n".join(
                f"[{h.chunk.id}] {h.chunk.doc_title} > {h.chunk.heading}\n{h.chunk.text}"
                for h in response.hits
            )

        async def lookup(args: GlossaryArgs) -> str:
            result = await self.knowledge.lookup(topic.id, args.terms[:15])
            lines = []
            for item in result.found:
                hint = item.translations.get(language_key, "")
                lines.append(
                    f"- {item.term}: {item.simple_meaning}"
                    + (
                        f" | {helper_language}: {hint}"
                        if hint
                        else f" | ({helper_language} hint: write your own)"
                    )
                )
            if result.missing:
                lines.append(
                    "Not in the approved glossary (write a simple meaning and a correct "
                    f"{helper_language} hint yourself): " + ", ".join(result.missing)
                )
            return "\n".join(lines) or "No terms found."

        async def readability(args: ReadabilityArgs) -> str:
            report = tm.analyze(
                args.text,
                allowed_words=allowed,
                long_sentence_words=int(targets["max_words"]),
                zipf_threshold=targets["zipf"],
            )
            mark = lambda ok: "OK" if ok else "TOO HIGH"  # noqa: E731
            lines = [
                f"Words: {report.word_count}, sentences: {report.sentence_count}",
                f"Flesch-Kincaid grade: {report.fk_grade} (target <= {targets['max_grade']}) {mark(report.fk_grade <= targets['max_grade'])}",
                f"Average sentence: {report.avg_sentence_words} words (target <= {targets['max_avg_words']}) {mark(report.avg_sentence_words <= targets['max_avg_words'])}",
            ]
            if report.long_sentences:
                lines.append(f"Sentences over {int(targets['max_words'])} words (split them):")
                lines += [f'  - "{s[:200]}"' for s in report.long_sentences[:6]]
            if report.difficult_words:
                lines.append(
                    f"Rare words (whole lesson may have at most {int(targets['max_difficult'])} outside the glossary): "
                    + ", ".join(report.difficult_words[:25])
                )
            return "\n".join(lines)

        return [
            AgentTool(
                "search_knowledge_base",
                "Search the curated knowledge base about the topic. Returns relevant chunks with ids.",
                SearchArgs,
                search,
                preview=lambda text: text[:240],
            ),
            AgentTool(
                "lookup_glossary",
                f"Get approved simple meanings and {helper_language} hints for technical terms.",
                GlossaryArgs,
                lookup,
            ),
            AgentTool(
                "check_readability",
                "Measure a draft with the reviewer's own reading-level metrics.",
                ReadabilityArgs,
                readability,
            ),
        ]

    # ---------------------------------------------------------------- shared
    async def _setup(self, context: GenerationContext) -> tuple[TopicPack, Rubric, list[str]]:
        topic = await self.knowledge.topic(context.topic_id)
        rubric = await self.rubrics.get()
        glossary_terms = [g.term for g in await self.knowledge.glossary(topic.id)]
        return topic, rubric, glossary_terms

    def _system(
        self, context: GenerationContext, topic: TopicPack, rubric: Rubric, submit_tool: str
    ) -> SystemMessage:
        titles = {c.id: c.title for c in rubric.checks}
        return SystemMessage(
            content=PROMPTS.render(
                "writer_system.md.j2",
                audience=AUDIENCE_SHORT,
                audience_profile=AUDIENCE_PROFILE,
                topic_title=topic.title,
                helper_language=context.helper_language,
                submit_tool=submit_tool,
                checklist=[
                    {
                        "id": c.id,
                        "title": c.title,
                        "pass_condition": c.pass_condition.replace(
                            "{helper_language}", context.helper_language
                        ),
                    }
                    for c in rubric.checks
                ],
                guidelines=guidelines_for(context.memory, GuidelineTarget.WRITER),
                focus=focus_lines(context.memory, titles),
                human_notes=context.memory.human_notes,
            )
        )

    @staticmethod
    def _summary(lesson: Lesson) -> dict[str, Any]:
        return {
            "title": lesson.title,
            "sections": len(lesson.sections),
            "glossary": len(lesson.glossary),
            "quiz": len(lesson.quiz),
            "words": _body_word_count(lesson),
        }

    # ---------------------------------------------------------------- create
    async def write(self, request: WriteRequest) -> LessonResponse:
        context = request.context
        with usage_scope() as usage:
            topic, rubric, glossary_terms = await self._setup(context)
            targets = _targets(rubric)
            agent: ReactAgent[Lesson] = ReactAgent(
                name="writer",
                model=self.llm.get(LLMRole.WRITER),
                provider=self.llm,
                tools=self._tools(topic, context.helper_language, targets),
                submit=SubmitTool(
                    "submit_lesson",
                    "Submit the complete lesson. Rejected submissions list problems to fix.",
                    Lesson,
                    validate=lambda lesson: lesson_problems(
                        lesson, context.helper_language, targets
                    ),
                    summarize=self._summary,
                ),
                max_steps=self.settings.writer_max_steps,
                max_rejections=self.settings.writer_max_rejections,
            )
            user = PROMPTS.render(
                "writer_create.md.j2",
                plan_json=request.plan.model_dump_json(indent=1),
                topic=topic,
                helper_language=context.helper_language,
                glossary_terms=glossary_terms,
            )
            result = await agent.run(
                [self._system(context, topic, rubric, "submit_lesson"), HumanMessage(content=user)]
            )
        return LessonResponse(
            lesson=result.output,
            usage=usage,
            agent_steps=result.steps,
            prompt_version=f"{PROMPTS.version('writer_system.md.j2')}+{PROMPTS.version('writer_create.md.j2')}",
        )

    # ---------------------------------------------------------------- revise
    async def revise(self, request: ReviseRequest) -> LessonResponse:
        context = request.context
        failed_ids = [r.check_id for r in request.failed]
        with usage_scope() as usage:
            topic, rubric, _glossary = await self._setup(context)
            targets = _targets(rubric)

            def validate(revision: LessonRevision) -> list[str]:
                problems = lesson_problems(revision.lesson, context.helper_language, targets)
                noted = {n.check_id for n in revision.revision_notes}
                missing = [cid for cid in failed_ids if cid not in noted]
                if missing:
                    problems.append(
                        "add a revision note for each failed check: " + ", ".join(missing)
                    )
                return problems

            agent: ReactAgent[LessonRevision] = ReactAgent(
                name="writer",
                model=self.llm.get(LLMRole.WRITER),
                provider=self.llm,
                tools=self._tools(topic, context.helper_language, targets),
                submit=SubmitTool(
                    "submit_revision",
                    "Submit the full revised lesson plus one revision note per failed check id.",
                    LessonRevision,
                    validate=validate,
                    summarize=lambda r: {**self._summary(r.lesson), "notes": len(r.revision_notes)},
                ),
                max_steps=self.settings.writer_max_steps,
                max_rejections=self.settings.writer_max_rejections,
            )
            user = PROMPTS.render(
                "writer_revise.md.j2",
                strategy=request.strategy.value,
                failed=[r.model_dump() for r in request.failed],
                passed=request.passed_check_ids,
                lesson_json=json.dumps(
                    request.previous_lesson.model_dump(mode="json"), ensure_ascii=False, indent=1
                ),
                plan_json=request.plan.model_dump_json(indent=1) if request.plan else "",
            )
            result = await agent.run(
                [
                    self._system(context, topic, rubric, "submit_revision"),
                    HumanMessage(content=user),
                ]
            )
        notes = [
            n for n in result.output.revision_notes if n.check_id in failed_ids
        ] or result.output.revision_notes
        return LessonResponse(
            lesson=result.output.lesson,
            revision_notes=notes,
            usage=usage,
            agent_steps=result.steps,
            prompt_version=f"{PROMPTS.version('writer_system.md.j2')}+{PROMPTS.version('writer_revise.md.j2')}"
            + ("" if request.strategy == ReviseStrategy.PATCH else ":rewrite"),
        )
