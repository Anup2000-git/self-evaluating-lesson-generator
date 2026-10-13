"""A hand-written, reviewed 'Introduction to RAG' lesson.

Used as: the clean baseline of the evaluator golden set, the input for fault-injection
tests, and the default lesson in the Evaluator Lab before any run has shipped.
"""

from __future__ import annotations

from lessongen_common.schemas.lesson import (
    GlossaryEntry,
    Lesson,
    LessonPlan,
    PlannedSection,
    QuizQuestion,
    Section,
    SectionKind,
)

_HOOK = """\
Riya studies at a college in Patna. One evening she asks an AI (Artificial Intelligence) chatbot a simple question: "What is the last date to pay our exam fee?"

The chatbot answers in one second. It sounds very sure. But the date is wrong!

Why did this happen? The chatbot never saw the notice board of Riya's college. So it guessed.

In this lesson, you will learn a method that fixes this problem. It is called RAG, which stands for Retrieval-Augmented Generation.
"""

_WHAT = """\
Let us understand the name RAG one word at a time.

- **Retrieval** (खोज कर लाना) means finding useful information and bringing it back.
- **Augmented** (बढ़ाया हुआ) means made better by adding something extra.
- **Generation** (बनाना) means creating something new, like writing an answer.

The AI that writes the answer is called a **Large Language Model**, or **LLM** (बड़ा भाषा मॉडल). An LLM is a computer program that has read a huge amount of text. From this text, it learned how words go together. So it can write answers like a person. Chatbots such as ChatGPT use an LLM.

The message we give to an LLM is called a **prompt** (निर्देश). A prompt has our question and sometimes some instructions.

So, **RAG is a method where the system first finds useful information, then adds that information to the prompt, and then the LLM writes the answer using it.** The place where RAG searches is called a **knowledge base** (जानकारी का भंडार). It is a collection of documents, like college notices, books or a company's help pages.

**An easy way to remember RAG: the open-book exam**

In a closed-book exam, you answer only from memory. If you forget something, you may guess. In an open-book exam, you first find the right page in your book. Then you write your answer using that page.

An LLM without RAG is like a student in a closed-book exam. An LLM with RAG is like a student in an open-book exam. Here is how the parts match:

| Open-book exam | RAG |
|---|---|
| The question in the exam paper | The user's question |
| Your textbook | The knowledge base |
| Finding the right page | Retrieval |
| Keeping that page open next to your question | Augmentation (adding the information to the prompt) |
| Writing your answer | Generation |
"""

_WHY = """\
LLMs are very useful. But they have three big problems. RAG helps with all three.

**Problem 1: Old information.** An LLM learns from text collected up to a certain date. This date is called its **knowledge cutoff** (जानकारी की आखिरी तारीख). After this date, the LLM learns nothing new. So if you ask about yesterday's cricket match, it cannot know the score. It may even give last year's score. RAG fixes this. It searches fresh documents at the moment you ask.

**Problem 2: Made-up answers.** Sometimes an LLM writes an answer that sounds correct but is false. This is called **hallucination** (मनगढ़ंत जवाब). Riya's chatbot did this when it gave a wrong date. With RAG, the LLM gets the real notice, so it has true facts to use. This reduces made-up answers. But it does not remove them completely.

**Problem 3: Private information.** An LLM never saw your college notices, your company's rules or a hospital's records. These were not part of its **training data** (वह जानकारी जिससे मॉडल ने सीखा). RAG lets the LLM use such private documents. The LLM does not need to learn them first.

There is one more benefit. RAG can show the **source** (स्रोत) of its answer, like the name of the notice. So you can check the answer yourself.
"""

_HOW = """\
RAG works in two parts. First, we prepare the documents. Then, we answer questions.

**Part A: Prepare the knowledge base (done once, before any question)**

1. **Collect documents.** Gather useful documents, such as college notices, PDF files or web pages.
2. **Split them into chunks.** Long documents are cut into small pieces called **chunks** (टुकड़े). A chunk may be one or two paragraphs. Small pieces are easier to search.
3. **Turn each chunk into numbers and store it.** Each chunk is changed into an **embedding** (अर्थ बताने वाली संख्याएँ). An embedding is a list of numbers that captures the meaning of the text. Texts with similar meaning get similar numbers. All embeddings are saved in a special store called a **vector database** (संख्याओं की सूचियों का डेटाबेस). "Vector" is just another name for a list of numbers.

**Part B: Answer a question (done every time someone asks)**

4. **Retrieve.** The user's question is also turned into an embedding. The system then finds the chunks whose meaning is closest to the question. This is called **similarity search** (मिलती-जुलती चीज़ खोजना). Usually it picks the top 3 to 5 chunks.
5. **Augment.** The system puts these chunks into the prompt, next to the question. It also adds an instruction like "Answer only from this information."
6. **Generate.** The LLM reads this prompt. Then it writes the answer using the chunks. It can also say which document it used.

Remember: the LLM itself does not change in RAG. RAG only gives the LLM the right information at the right time.
"""

_EXAMPLE = """\
Let us go back to Riya and follow her question through RAG.

**Riya's question:** "What is the last date to pay our exam fee?"

**Step 1 - Retrieve.** The system searches the college knowledge base. It finds this chunk from the notice board:

> "Notice 45: Students must pay the semester exam fee of Rs. 1,200 by 20 November. After 20 November, a late fee of Rs. 100 must be paid."

**Step 2 - Augment.** The system builds this prompt for the LLM:

> Answer only from the information below.
> Information: "Notice 45: Students must pay the semester exam fee of Rs. 1,200 by 20 November. After 20 November, a late fee of Rs. 100 must be paid."
> Question: What is the last date to pay our exam fee?

**Step 3 - Generate.** The LLM writes:

> "The last date to pay the exam fee is 20 November. After that, you must also pay a late fee of Rs. 100. (Source: Notice 45)"

This time, the answer is correct. It also shows the source, so Riya can check it on the notice board.
"""

_MISCONCEPTIONS = """\
Let us clear some common confusions about RAG.

- **Wrong idea: "RAG teaches the LLM new facts forever."** This is not true. RAG does not change the LLM at all. The information is given only for that one question. Changing the model itself is a different method called **fine-tuning** (मॉडल को दोबारा सिखाना).
- **Wrong idea: "With RAG, answers are always correct."** This is also not true. If the search brings the wrong chunk, the answer can still be wrong. RAG is only as good as its documents and its search.
- **Limit: documents must stay updated.** If the college puts up a new notice, someone must add it to the knowledge base. Otherwise RAG will use old information.
- **Limit: the prompt has a size limit.** An LLM can read only a limited amount of text at one time. This limit is called the **context window** (एक बार में पढ़ने की सीमा). So RAG sends only the most useful chunks, not every document.
"""

_SUMMARY = """\
- **RAG** means Retrieval-Augmented Generation.
- First, it **retrieves** useful chunks from a knowledge base.
- Then, it **augments** the prompt by adding those chunks next to the question.
- Finally, the LLM **generates** an answer using them.
- RAG helps with old information, made-up answers and private documents.
- RAG does not retrain the LLM, and it is not perfect. Good documents and good search matter.

Now you know how an AI can look things up before it answers, just like you do in an open-book exam!
"""


def sample_lesson() -> Lesson:
    return Lesson(
        title="Introduction to RAG: How AI Looks Things Up Before It Answers",
        learning_objectives=[
            "Explain in simple words what RAG (Retrieval-Augmented Generation) is.",
            "Give two reasons why RAG is useful.",
            "List the main steps of RAG in the correct order.",
            "Follow a real example of RAG from question to answer.",
        ],
        sections=[
            Section(
                kind=SectionKind.HOOK, heading="A Wrong Answer from a Chatbot", body_markdown=_HOOK
            ),
            Section(kind=SectionKind.WHAT, heading="What Is RAG?", body_markdown=_WHAT),
            Section(kind=SectionKind.WHY, heading="Why Do We Need RAG?", body_markdown=_WHY),
            Section(
                kind=SectionKind.HOW, heading="How Does RAG Work? Step by Step", body_markdown=_HOW
            ),
            Section(
                kind=SectionKind.EXAMPLE, heading="Let Us See RAG in Action", body_markdown=_EXAMPLE
            ),
            Section(
                kind=SectionKind.MISCONCEPTIONS,
                heading="Common Confusions and Limits",
                body_markdown=_MISCONCEPTIONS,
            ),
            Section(kind=SectionKind.SUMMARY, heading="Quick Summary", body_markdown=_SUMMARY),
        ],
        glossary=[
            GlossaryEntry(
                term="AI (Artificial Intelligence)",
                simple_meaning="Computer programs that can do tasks that normally need human thinking.",
                helper_meaning="कृत्रिम बुद्धि",
            ),
            GlossaryEntry(
                term="RAG (Retrieval-Augmented Generation)",
                simple_meaning="A method where the system first finds useful information and then the AI uses it to write an answer.",
                helper_meaning="जानकारी खोजकर, जोड़कर जवाब बनाना",
            ),
            GlossaryEntry(
                term="Retrieval",
                simple_meaning="Finding useful information and bringing it back.",
                helper_meaning="खोज कर लाना",
            ),
            GlossaryEntry(
                term="Augmented",
                simple_meaning="Made better by adding something extra.",
                helper_meaning="बढ़ाया हुआ",
            ),
            GlossaryEntry(
                term="Generation",
                simple_meaning="Creating something new, like writing an answer.",
                helper_meaning="बनाना",
            ),
            GlossaryEntry(
                term="Large Language Model (LLM)",
                simple_meaning="A computer program that has read a huge amount of text and can write like a person.",
                helper_meaning="बड़ा भाषा मॉडल",
            ),
            GlossaryEntry(
                term="Prompt",
                simple_meaning="The message, with a question and instructions, that we give to an AI.",
                helper_meaning="निर्देश",
            ),
            GlossaryEntry(
                term="Knowledge base",
                simple_meaning="A collection of documents that the system can search.",
                helper_meaning="जानकारी का भंडार",
            ),
            GlossaryEntry(
                term="Knowledge cutoff",
                simple_meaning="The last date of the information an LLM learned from.",
                helper_meaning="जानकारी की आखिरी तारीख",
            ),
            GlossaryEntry(
                term="Hallucination",
                simple_meaning="When an AI gives a false answer that sounds correct.",
                helper_meaning="मनगढ़ंत जवाब",
            ),
            GlossaryEntry(
                term="Training data",
                simple_meaning="The text an AI model learned from.",
                helper_meaning="वह जानकारी जिससे मॉडल ने सीखा",
            ),
            GlossaryEntry(
                term="Chunk",
                simple_meaning="A small piece of a long document.",
                helper_meaning="टुकड़ा",
            ),
            GlossaryEntry(
                term="Embedding",
                simple_meaning="A list of numbers that captures the meaning of a text.",
                helper_meaning="अर्थ बताने वाली संख्याएँ",
            ),
            GlossaryEntry(
                term="Vector database",
                simple_meaning="A store that keeps embeddings and quickly finds similar ones.",
                helper_meaning="संख्याओं की सूचियों का डेटाबेस",
            ),
            GlossaryEntry(
                term="Similarity search",
                simple_meaning="Finding the pieces of text whose meaning is closest to a question.",
                helper_meaning="मिलती-जुलती चीज़ खोजना",
            ),
            GlossaryEntry(
                term="Fine-tuning",
                simple_meaning="Training a model again so that the model itself changes.",
                helper_meaning="मॉडल को दोबारा सिखाना",
            ),
            GlossaryEntry(
                term="Context window",
                simple_meaning="The amount of text an LLM can read at one time.",
                helper_meaning="एक बार में पढ़ने की सीमा",
            ),
        ],
        quiz=[
            QuizQuestion(
                question='What does the "R" in RAG stand for?',
                options=["Robot", "Retrieval", "Reading", "Repeat"],
                correct_option_index=1,
                explanation="R stands for Retrieval, which means finding useful information and bringing it back.",
            ),
            QuizQuestion(
                question="Why can an LLM without RAG give an old score for yesterday's cricket match?",
                options=[
                    "It does not like cricket.",
                    "It learned nothing after its knowledge cutoff date.",
                    "It reads the news every second.",
                    "It is not allowed to talk about sports.",
                ],
                correct_option_index=1,
                explanation="An LLM only knows text from before its knowledge cutoff, so it cannot know new results.",
            ),
            QuizQuestion(
                question="What is the correct order of the main RAG steps when a question comes?",
                options=[
                    "Generate, then retrieve, then augment",
                    "Augment, then generate, then retrieve",
                    "Retrieve, then augment, then generate",
                ],
                correct_option_index=2,
                explanation="RAG first retrieves useful chunks, then adds them to the prompt, then the LLM generates the answer.",
            ),
            QuizQuestion(
                question="Does RAG permanently change the LLM?",
                options=[
                    "Yes, it retrains the LLM every time.",
                    "No, it only gives the LLM information for that question.",
                    "Yes, it deletes the LLM's old knowledge.",
                ],
                correct_option_index=1,
                explanation="RAG does not change the model. Changing the model is a different method called fine-tuning.",
            ),
            QuizQuestion(
                question='In the open-book exam example, what matches "retrieval"?',
                options=[
                    "Writing the answer",
                    "Finding the right page in your book",
                    "Reading the question paper",
                ],
                correct_option_index=1,
                explanation="Retrieval is finding the right information, just like finding the right page in your textbook.",
            ),
        ],
    )


def sample_plan() -> LessonPlan:
    lesson = sample_lesson()
    return LessonPlan(
        title=lesson.title,
        learning_objectives=lesson.learning_objectives,
        analogy="Open-book exam: question paper = user's question, textbook = knowledge base, "
        "finding the page = retrieval, keeping the page open = augmentation, writing = generation.",
        worked_example="Riya asks a college chatbot for the exam-fee deadline; RAG retrieves Notice 45, "
        "adds it to the prompt and the LLM answers '20 November' with the source.",
        sections=[
            PlannedSection(
                kind=s.kind, heading=s.heading, key_points=[s.heading], terms_to_define=[]
            )
            for s in lesson.sections
        ],
        glossary_terms=[g.term for g in lesson.glossary],
        quiz_focus=[
            "meaning of RAG",
            "knowledge cutoff",
            "order of steps",
            "no retraining",
            "analogy",
        ],
    )
