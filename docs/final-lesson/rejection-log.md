# Rejection log — Introduction to RAG

- **Run:** `run_ed13a53166f4` (generate)
- **Outcome:** SHIPPED on attempt 2 — passed all 23 checks on attempt 2
- **Attempts:** 2 (max retries: 2)
- **Rubric version:** v1
- **Guidelines applied from memory:** 3
- **LLM cost:** $0.741 across 46 calls

## Attempt 1 — REJECTED (21/23 checks passed) · initial

**Failed checks:**

| Check | Dimension | Why it failed | Evidence |
|---|---|---|---|
| **LANG-4** No idioms or assumed knowledge | Beginner-friendly language | The lesson uses figurative comparison rather than fully literal wording, especially in the hook section. The open-book exam comparison and repeated “like” analogies are understandable, but this checkpoint requires no id… | “Like an Open-Book Exam”; “The student is like the AI model.” |
| **JAR-3** Acronyms expanded | Clear, no unexplained jargon | Acronyms used without being written out in full at first use: LLM. | “List the main reasons why RAG is useful for LLM answers.” |

**Fix instructions fed back to the writer:**

- `LANG-4`: Rewrite the hook section to use direct, literal explanation instead of the open-book exam comparison and other “like” analogies; keep the same meaning but state RAG steps and roles in plain factual sentences.
- `JAR-3`: At the first use of each of these acronyms, write the full form next to it, e.g. 'LLM (Large Language Model)': LLM

## Attempt 2 — PASSED (23/23 checks passed) · patch

_Strategy:_ patch: 2 of 23 checks failed (<= 6), so only the failing parts were edited and passing parts were kept

**What changed (writer's revision notes):**

- `LANG-4` → I rewrote the hook section with direct, literal RAG roles and steps. I also removed the open-book exam heading and removed extra 'like' wording in the example and summary.
- `JAR-3` → I expanded LLM in the learning objective as Large Language Model (LLM) before using the acronym.

**Sections touched:** Hook: A Direct First Picture (modified, 144→112 words), What RAG Is (modified, 176→187 words), Worked Example: College Scholarship Notice (modified, 275→276 words), Summary (modified, 88→84 words)

All checks passed — the lesson cleared the bar.
