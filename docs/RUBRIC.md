# The rubric

**23 hard pass/fail checkpoints. A lesson ships only if every one passes - there is no partial
credit and no weighting.** Severity (critical/major) is used only to order fixes and to pick the
best attempt when retries run out.

The rubric is **data** (`libs/common/src/lessongen_common/rubric/rubric.v1.yaml`), validated by
Pydantic, versioned in the memory service and stamped on every evaluation report. Judge criteria
use placeholders that are filled from the topic pack's ground truth at evaluation time
(`{how_steps}`, `{why_points}`, `{misconceptions}` ...), so the same rubric works for any topic
that has a pack.

## The checks

### Accurate & grounded

| ID | PASS only if | Method | Why it matters |
|---|---|---|---|
| ACC-1 | No technical claim is contradicted by the knowledge base | ReAct fact-checker | Teaching a beginner something false is the worst possible failure. |
| ACC-2 | Every specific fact (number, date, name, statistic) is supported by the knowledge base | ReAct fact-checker | LLMs invent plausible specifics ("Google, 2015", "95% more accurate"). |
| ACC-3 | Every Hindi hint correctly conveys its English term | LLM judge | A wrong hint is worse than none for this learner. |

### Beginner-friendly language

| ID | PASS only if | Method | Why it matters |
|---|---|---|---|
| LANG-1 | Flesch-Kincaid grade <= 8.0 (English text only) | Code | A measurable reading level. Hindi hints are stripped before measuring. |
| LANG-2 | Average sentence <= 15 words and none > 28 words | Code | Long sentences are the main barrier for non-native readers. |
| LANG-3 | <= 10 distinct difficult words outside the glossary/jargon | Code | Difficulty = rarer than Zipf 3.8 in English or on an academic-words list ("leverage", "furthermore"...), with stemming and a list of words familiar to Indian students. |
| LANG-4 | No idioms, culture-bound references or assumed knowledge | LLM judge | "Piece of cake", "Super Bowl" and "as you know" all exclude this learner. |
| LANG-5 | 900-2,000 words (a 10-15 minute read) | Code | Long enough to teach from zero, short enough to finish. |

### Teaches by example

| ID | PASS only if | Method | Why it matters |
|---|---|---|---|
| EX-1 | A concrete end-to-end worked example shows the question, the retrieved information, the augmented prompt and the answer | LLM judge | Beginners understand processes by watching one run. |
| EX-2 | At least one everyday-India analogy whose parts are explicitly mapped to the topic's parts | LLM judge | An unmapped analogy entertains but does not teach. |

### Clear, no unexplained jargon

| ID | PASS only if | Method | Why it matters |
|---|---|---|---|
| JAR-1 | Every watch-list term used has a glossary entry | Code | Stem-based, longest-match first ("vector database" does not also count as "vector"). |
| JAR-2 | Every technical term is explained simply at or before its first use in the body | LLM judge | A glossary at the end is too late for a beginner reading top to bottom. |
| JAR-3 | Every acronym is written out in full at first use | Code | Known expansions are verified near the first occurrence; familiar acronyms (PDF, ATM...) and capitalised emphasis ("NOT") are skipped. |
| JAR-4 | Every glossary entry has a meaning in the helper-language script (Devanagari for Hindi) | Code | Guarantees the hint is in the learner's script. |

### Covers the key points

| ID | PASS only if | Method | Why it matters |
|---|---|---|---|
| COV-1 | A short, correct, simple definition early in the lesson | LLM judge | "What it is" from the brief. |
| COV-2 | At least two problems the topic solves, each with a concrete consequence | LLM judge | "Why it matters" from the brief. |
| COV-3 | Every step of how it works, correctly and in order | LLM judge | "How it works" from the brief; steps come from the pack. |
| COV-4 | At least one limitation and one corrected misconception | LLM judge | Prevents the most common wrong beliefs ("RAG retrains the model"). |
| COV-5 | A simulated beginner answers at least 5 of 6 held-out questions from the lesson alone, quoting it | Learner agent + grader | Tests whether the lesson actually teaches; the writer never sees these questions. |

### Coherent teaching flow

| ID | PASS only if | Method | Why it matters |
|---|---|---|---|
| FLOW-1 | Required sections in teaching order: what -> why -> how -> example -> summary | Code | A fixed pedagogical template makes lessons consistent and checkable. |
| FLOW-2 | No idea is used before it is introduced; each section builds on the last | LLM judge | Forward references lose beginners. |
| FLOW-3 | 3-5 MCQs, 3-4 distinct options each, exactly one correct, each explained | Code | A well-formed self-check. |
| FLOW-4 | Every quiz answer is taught in the body and every marked answer is correct | LLM judge | A quiz on untaught material, or a wrong answer key, damages trust. |

Critical checks: ACC-1, ACC-2, COV-1, COV-2, COV-3, FLOW-1.

## Why these methods

- **9 deterministic checks** cover everything that can be measured in code. They are free,
  reproducible, explainable, and the writer can run the very same metrics as a tool.
- **11 LLM judges** cover what needs judgment. Each answers one yes/no question with explicit
  PASS-only-if and FAIL-if criteria, must quote verifiable evidence, and a FAIL is confirmed by a
  second vote (a disagreement goes to a third, stronger model).
- **2 agent checks** handle accuracy against the knowledge base and real teaching effectiveness.

## Calibration

Thresholds marked in code (`params` in the YAML) were set from the reviewed reference lesson -
which passes every deterministic check with margin (FK grade 4.3, average sentence 8.5 words,
2 difficult words, 1,189 words) - and the fault presets, which must fail them. The evaluator's
agreement with expectations on real models is measured by `evals/run_evaluator_eval.py`.

## How the rubric evolves

Reviewers can mark any verdict as wrong from the run page. The memory service turns that into a
**rubric clarification proposal** (extra notes or criteria for that check). Nothing changes until
a human approves it on the Memory page; approval creates a new rubric version. Checks that keep
failing despite learned guidelines are also escalated as proposals. The system never loosens its
own bar.
