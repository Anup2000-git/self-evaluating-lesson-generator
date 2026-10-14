# Loom walkthrough script (15-20 minutes)

The video must show three things: **the agentic workflow running end to end**, **the evaluator
catching a deliberate error**, and **a face-visible walkthrough of how the workflow works**.
Keep your camera bubble on for the whole recording.

## Before you record (10 minutes)

1. `docker compose up -d` and open http://localhost:8080. **System** page: every service shows
   *ready*; click **Run LLM check** - all three checks green for both deployments.
2. Do **one warm-up run** from the Studio so Memory already has learned guidelines and the
   learning chart has a first point. (A fresh run during the video then shows "Recalled N
   guidelines" - the self-evolving part becomes visible.)
3. Open these tabs in order so switching is instant: Studio, Evaluator Lab, Memory & Learning,
   Rubric, Langfuse (http://localhost:3000, already logged in - credentials are in `.env`), the
   README on GitHub (architecture diagram), `docs/ARCHITECTURE.md`.
4. Have a terminal ready in the repo folder (for `docker compose ps` and the CLI).
5. Close notifications. Zoom the browser to 110% so text is readable in the recording.

A full generate run takes several minutes with reasoning models - start it at the beginning of
part 3 and explain the architecture while it runs; the live page catches up instantly.

---

## 1. Introduction - 0:00-1:30 (face on)

- Who you are, and the task in one sentence: *"I built an agentic system that writes a beginner
  lesson, judges it against 23 hard pass/fail checks, and regenerates it until it is good enough
  to ship - before a human ever sees it."*
- The learner: *"a 12th-grade graduate from a non-English-medium school who wants to get into AI
  - so simple English, Indian examples, and a Hindi hint for every key word."*
- What you will show: a live run, the evaluator catching a deliberate mistake, how the system
  learns, and why it is built this way.

## 2. Architecture in 3 minutes - 1:30-4:30

Show the README diagram, then `docker compose ps` in the terminal (the app's containers plus
the self-hosted Langfuse stack).

- *"The loop itself is a LangGraph state machine - deterministic control flow. The agents live
  inside its nodes. That is how I can guarantee the loop always stops: at most 2 retries, a cost
  budget, and a recursion limit."*
- *"The author is not the judge."* Generator and evaluator are separate services, with separate
  prompts and different models: GPT-5.5 writes, GPT-5.4-mini judges - so the writer's model is
  not grading its own work.
- *"Grounded or refused."* A curated knowledge pack is the ground truth; the writer researches it
  and the fact-checker verifies against it. Topics without a pack are refused.
- Memory service = long-term memory and the learning step; Redis Streams = job queue and live
  events; Postgres = memory plus LangGraph checkpoints, so a crashed run resumes.

## 3. A live end-to-end run - 4:30-9:30

**Studio** -> topic *Introduction to RAG*, Hindi, 2 retries -> **Generate lesson**.

Narrate as the run page fills in:

- **Agentic loop** diagram: the active node is highlighted. *"Recall memory injected N guidelines
  that previous runs learned."* Expand that list.
- **Live activity**: point at a writer step - *"This is ReAct: Thought, then Action - it searches
  the knowledge base - then Observation."* Show `lookup_glossary` returning the approved Hindi and
  `check_readability`: *"the writer self-checks with the evaluator's own metrics."*
- When evaluation starts, the **Evaluation** tab fills in check by check. Explain the three kinds:
  9 code checks, 11 single-question LLM judges, a ReAct fact-checker and a simulated learner.
- Open the **Rubric** page briefly while it runs: *"Every check is binary; the lesson ships only if
  all 23 pass. No partial credit."*
- If an attempt is rejected: click a failed check -> reasoning, **quoted evidence (verified in code)**,
  **the fix sent to the writer**, and the **judge votes** (a FAIL needs a second vote). Then
  **What changed**: the writer's note per failed check and the sections it touched.
- When it ships: **Lesson** tab - simple English, Hindi hints, the analogy table, the worked
  example, the interactive quiz. **Rejection log** tab: what failed, why, what changed.
- Click **Copy for Google Docs** (this is how the submission document was made) and show the cost
  in the header.
- Click **Trace in Langfuse**: the same run as one trace - expand `write` -> `generator.write` ->
  the writer's LangGraph run -> a `search_knowledge_base` tool call and an LLM generation with its
  prompt, tokens and latency. *"Every container writes into the run's trace; the span context
  travels between services in a `traceparent` header."*

## 4. The evaluator catching a deliberate error - 9:30-13:00

**Evaluator Lab** -> *Reference lesson* -> **Factual error** (it adds *"RAG retrains the model on
your documents every time you ask a question"*) -> **Evaluate only**.

- The **Deliberate error** card shows *expected: ACC-1*. When the fact-checker finishes: **Caught by
  ACC-1**. Open ACC-1: the injected sentence is quoted as evidence, and the **claims table** shows
  the knowledge base saying RAG does not change the model's weights.
- *"The evaluator does not just say it's wrong - it proves it with a quote and a source."*
- Back to the Lab -> **Unexplained jargon** -> Evaluate only: JAR-1 (cosine similarity has no
  glossary entry) and JAR-3 (HNSW never expanded) fail instantly - *"these are code checks, no LLM,
  fully reproducible."*
- Optional: **Factual error** -> **Evaluate + repair**: the loop feeds the failure back, the
  writer fixes it, the next attempt passes.
- Mention the measurement: *"I also measure the evaluator itself - `evals/run_evaluator_eval.py`
  injects every preset and reports detection rate and false-fail rate."*

## 5. Memory and self-evolution - 13:00-15:30

**Memory & Learning** page:

- The **learning curve** - checks failed on the first attempt, per run.
- **Learned guidelines**: each one linked to the checks it prevents, with *applied / helped /
  missed*. *"After every run, consolidation turns what failed - and what fixed it - into short
  guidelines for the next run. If a guideline doesn't help, it is retired automatically. If the
  same check keeps failing anyway, it's escalated to a human."*
- **Human feedback**: on a run, mark a check as wrong ("the evaluator was wrong on EX-2"), click
  **Learn from feedback now** -> a **rubric proposal** appears here -> **Approve** -> the Rubric page
  shows v2. *"The writer learns on its own, but the quality bar only changes with a human sign-off -
  the system can't make its own exam easier."*

## 6. Production qualities - 15:30-17:30

- **System** page: health of every service, queue depth, the role -> model table.
- Resilience (optional, impressive): start a run, then in the terminal
  `docker compose restart orchestrator-worker` - after ~30-45 seconds the run continues from its
  last LangGraph checkpoint ("Resumed from the last checkpoint" in the activity feed).
- Mention: 140 backend tests with scripted fake LLMs (no Azure needed), strict TypeScript, CI,
  structured logs with run ids across services, Langfuse traces across services, per-call cost
  tracking, secrets never leave the backend, only localhost ports, non-root containers.

## 7. Trade-offs and close - 17:30-18:30 (face on)

- One or two trade-offs you would defend: a graph instead of a manager agent (guaranteed
  termination); one judge call per check (no halo effect) paid for with a cheaper model and
  prompt caching; BM25 instead of a vector database for a small curated corpus.
- Next steps: new topics via an "ungrounded" mode that always ends in human review; scheduled
  evaluator meta-evaluation; A/B testing of guidelines; auth at the gateway.
- Thank them.

---

## If something goes wrong while recording

| Symptom | Fix |
|---|---|
| A service is not ready on the System page | `docker compose ps`; `docker compose logs <service> --tail 50`; `docker compose up -d`. |
| Run fails with "LLM not configured" (424) | `.env` is missing values; fix it, then `docker compose up -d` to restart. |
| Azure 429 (rate limit) | Wait a minute or lower `LLM_MAX_CONCURRENCY` in `.env`. |
| The run takes long | Keep narrating the architecture; the page is live and catches up. |
| Want a clean slate | `docker compose down -v` deletes runs and memory, then `docker compose up -d`. |
