# Introduction to RAG (Retrieval-Augmented Generation)

**By the end of this lesson, you will be able to:**

- Explain what Retrieval-Augmented Generation (RAG) means in simple words.
- List the main reasons why RAG is useful for Large Language Model (LLM) answers.
- Describe the five main steps of RAG: prepare, index, retrieve, augment, generate.
- Explain common limits and mistakes about RAG, such as thinking it retrains the model.

## Hook: A Direct First Picture

When you ask an AI system a question, it may need facts from documents. It should not answer only from memory.

**Artificial Intelligence** [कृत्रिम बुद्धि] means computer programs that do tasks needing human thinking. **Retrieval-Augmented Generation** [जानकारी खोजकर, उसे जोड़कर जवाब बनाने का तरीका] is a method for AI answers.

In this method, the system first finds useful information from documents. Then it adds that information to the question. After that, the AI writes the answer.

The document is the place that stores facts. The question is what you ask. The found text is the extra help. The final written text is the answer. The page or document name is the **source**.

## What RAG Is

A **Large Language Model** [बड़ा भाषा मॉडल], or LLM, is an AI model that can understand and write language. A **prompt** [मॉडल को दिया गया सवाल और निर्देश] is the text given to the model. It can include instructions and your question.

**Retrieval** [खोजकर लाना] means finding useful information and bringing it back. **Augmentation** [कुछ जोड़कर बढ़ाना] means adding useful information to make the prompt better. **Generation** [बनाना, रचना] means creating new text, like an answer.

So, RAG has a simple meaning. Before the LLM answers, the system finds useful outside information. It adds that information to the prompt with your question. Then the LLM writes the answer using that information.

A **knowledge base** [जानकारी का भंडार] is the document collection that RAG searches. It can contain web pages, college notices, policies, manuals, or articles. It is separate from the LLM. You can update it without changing the model.

Use a school exam comparison to remember the parts. In this comparison, a textbook represents the knowledge base. Finding the correct page represents retrieval. Adding useful lines to the question represents augmentation. Writing the final answer represents generation.

## Why RAG Matters

First, RAG helps with new information. **Training data** [प्रशिक्षण डेटा] is the text an AI model learned from. A **knowledge cutoff** [जानकारी की आखिरी तारीख] is the last date of that learned information. By itself, an LLM may not know a notice published after that date. The result can be a wrong answer about a new rule.

RAG can search the knowledge base when you ask. If the knowledge base is updated, the answer can use current text. For example, a college can add a new exam notice. Then students can ask about it.

Second, RAG helps reduce **hallucination** [मनगढ़ंत जवाब]. Hallucination means an AI gives a false answer that sounds correct. This can mislead a student about a deadline. RAG gives the LLM real text to use. This reduces the chance of a made-up answer. It does not remove the risk fully.

Third, RAG helps with private or specific documents. A general LLM may not have your school timetable or shop return policy. With RAG, those documents can be searched at answer time. The LLM does not permanently learn them.

Fourth, RAG can build trust. A **source** [स्रोत] is the place where information came from. A RAG answer can show the source. Then you can check the notice yourself.

Fifth, updates can be easier. **Fine-tuning** [मॉडल को दोबारा सिखाना] means training a model again so the model itself changes. Adding documents to a knowledge base is usually cheaper and faster than fine-tuning or retraining.

## How RAG Works Step by Step

RAG has five main steps.

Step 1 is prepare the knowledge. The system collects useful documents. It may collect web pages, files, notices, manuals, policies, or articles. Long documents are split into chunks. A **chunk** [टुकड़ा] is a small piece of a long document. It is often a few sentences or paragraphs. Small chunks help send only useful parts to the LLM.

Some systems split text by **tokens**. A **token** [शब्द का छोटा टुकड़ा] is a small piece of text an LLM reads. Some systems split by characters. Better systems often split at headings, paragraphs, or sentences.

Step 2 is index the chunks. An **index** [खोजने के लिए बनी सूची] is an organised store that makes search fast. In a common method, each chunk becomes an **embedding**. An **embedding** [अर्थ बताने वाली संख्याओं की सूची] is a list of numbers that shows meaning. A **vector** [संख्याओं की सूची] is a list of numbers. A **vector database** [संख्याओं की सूचियों का डेटाबेस] stores embeddings with their text. Some systems also use **keyword search**. **Keyword search** [शब्दों से खोज] finds text with the same words as the question.

Step 3 is retrieve. A **retriever** [खोजकर लाने वाला हिस्सा] is the part that searches and returns chunks. A **query** [सवाल या खोज] is your question for search. With embeddings, the query also becomes an embedding. **Similarity search** [मिलती-जुलती चीज़ खोजना] finds chunks closest in meaning to the query. **Top-k** [सबसे मिलते-जुलते कुछ नतीजे] means the best matching chunks returned. Often, this is between 3 and 10 chunks.

Step 4 is augment. The system adds the retrieved chunks to the prompt. It also adds your question and instructions. One instruction can say, “Use only the given information.” Another can say, “Say you do not know if it is not there.”

Step 5 is generate. The LLM reads the full augmented prompt. It writes the answer using the retrieved chunks. It can also mention the source.

The model itself does not change in these steps. **Model weights** [मॉडल के अंदर सीखी हुई संख्याएँ] are numbers inside the model that store what it learned. RAG does not retrain the LLM. It only changes the prompt for one question.

There is one more limit here. A **context window** [एक बार में पढ़ने की सीमा] is how much text an LLM can read at one time. Too much retrieved text may not fit. Extra unrelated text can also distract the model.

## Worked Example: College Scholarship Notice

Let us use a sample college knowledge base. The college notices are the documents that the system searches.

User question: “What is the last date to submit the scholarship form, and where should I submit it?”

Step 1, prepare. The system has college notices split into chunks.

Chunk 1 is from Source: College Notice A.

“Scholarship form submission: Students must submit the scholarship form by 15 August. Submit the form at the college office.”

Chunk 2 is from Source: College Notice B.

“Sports day practice will start on 20 August.”

Step 2, index. The system stores these chunks for fast search. It may store embeddings for their meanings.

Step 3, retrieve. The retriever searches for the user question. Chunk 1 matches the scholarship question. Chunk 2 is less useful, but it may also be returned.

Step 4, augment. The system builds this prompt for the LLM:

“Answer the question using only the information below.
If the answer is not in the information, say you don’t know.
Mention the source used.
Information:
[Source: College Notice A]
Scholarship form submission: Students must submit the scholarship form by 15 August.
Submit the form at the college office.
[Source: College Notice B]
Sports day practice will start on 20 August.
Question: What is the last date to submit the scholarship form, and where should I submit it?”

Step 5, generate. The LLM writes the final answer:

“The last date to submit the scholarship form is 15 August. You should submit it at the college office. Source: College Notice A.”

Notice how the answer uses College Notice A. It ignores the sports day line. You can check the source if needed.

## Common Misconceptions and Limits

Misconception 1: RAG retrains the model. This is false. RAG uses found information only for that one answer. Model weights do not change.

Misconception 2: RAG is the same as fine-tuning. This is false. Fine-tuning changes the model itself. RAG only adds information to the prompt.

Misconception 3: RAG always gives correct answers. This is false. Wrong chunks can be retrieved. Documents can also be old or wrong. Then the answer can still be wrong.

Misconception 4: More text is always better. This is false. The context window is limited. Unrelated text can confuse the model.

RAG has limits. Answer quality depends on retrieval quality. The knowledge base must be maintained. New documents must be added. Old or wrong documents should be updated or removed. The extra search step can add time and cost. The model can still hallucinate or ignore the retrieved text.

## Summary

RAG means retrieve, augment, and generate. The system finds the right information first. It adds the information with the question. Then the answer is written.

RAG helps with new, private, and specific information. It can reduce hallucination. It can show sources for checking. Its five steps are prepare, index, retrieve, augment, and generate.

RAG does not retrain the LLM. It does not permanently change model weights. It improves answers, but it does not guarantee correctness. The knowledge base and retrieval quality matter a lot.

## Key words (Glossary)

| Word | Simple meaning | Hindi |
|---|---|---|
| **Artificial Intelligence** | Computer programs that can do tasks that normally need human thinking. | कृत्रिम बुद्धि |
| **Retrieval-Augmented Generation** | A method where the system first finds useful information, adds it to the prompt, and then the AI writes an answer. | जानकारी खोजकर, उसे जोड़कर जवाब बनाने का तरीका |
| **Large Language Model** | An AI model that can understand and write language. | बड़ा भाषा मॉडल |
| **Retrieval** | Finding useful information and bringing it back. | खोजकर लाना |
| **Augmentation** | Making something better by adding useful information to it. | कुछ जोड़कर बढ़ाना |
| **Generation** | Creating new text, such as an answer. | बनाना, रचना |
| **Prompt** | The text given to an AI model, with instructions and a question. | मॉडल को दिया गया सवाल और निर्देश |
| **Knowledge base** | A collection of documents that a system can search. | जानकारी का भंडार |
| **Training data** | The text an AI model learned from. | प्रशिक्षण डेटा |
| **Knowledge cutoff** | The last date of the information an LLM learned from. | जानकारी की आखिरी तारीख |
| **Hallucination** | A false AI answer that sounds correct. | मनगढ़ंत जवाब |
| **Source** | The place where a piece of information comes from. | स्रोत |
| **Fine-tuning** | Training a model again on new examples so the model itself changes. | मॉडल को दोबारा सिखाना |
| **Chunk** | A small piece of a long document. | टुकड़ा |
| **Token** | A small piece of text that an LLM reads and writes. | शब्द का छोटा टुकड़ा |
| **Index** | An organised store that makes searching fast. | खोजने के लिए बनी सूची |
| **Embedding** | A list of numbers that shows the meaning of text. | अर्थ बताने वाली संख्याओं की सूची |
| **Vector** | A list of numbers. | संख्याओं की सूची |
| **Vector database** | A store that keeps embeddings and quickly finds similar ones. | संख्याओं की सूचियों का डेटाबेस |
| **Keyword search** | Search that finds text with the same words as the question. | शब्दों से खोज |
| **Retriever** | The part of a RAG system that searches and returns useful chunks. | खोजकर लाने वाला हिस्सा |
| **Query** | A question or search request given to a system. | सवाल या खोज |
| **Similarity search** | Search that finds text closest in meaning to the question. | मिलती-जुलती चीज़ खोजना |
| **Top-k** | The best matching chunks returned by the retriever. | सबसे मिलते-जुलते कुछ नतीजे |
| **Model weights** | The numbers inside a model that store what it learned. | मॉडल के अंदर सीखी हुई संख्याएँ |
| **Context window** | The amount of text an LLM can read at one time. | एक बार में पढ़ने की सीमा |

## Check your understanding

**1. What does RAG do before the LLM writes an answer?**

- A) It deletes the question.
- B) It finds useful outside information and adds it to the prompt.
- C) It permanently changes the model weights.
- D) It stops the LLM from writing.

**2. What is the correct order of the five main RAG steps?**

- A) Generate, retrieve, index, prepare, augment
- B) Prepare, index, retrieve, augment, generate
- C) Index, generate, prepare, retrieve, augment
- D) Retrieve, generate, prepare, augment, index

**3. Why can RAG help with a new college notice?**

- A) It searches an updated knowledge base when you ask.
- B) It guesses the notice from memory.
- C) It removes the context window.
- D) It always retrains the LLM.

**4. Which statement about RAG and fine-tuning is correct?**

- A) Both always change model weights.
- B) RAG changes the prompt, while fine-tuning changes the model itself.
- C) RAG is another name for fine-tuning.
- D) Fine-tuning only searches documents.

**5. Which is a real limit of RAG?**

- A) It cannot show sources.
- B) It has no need for documents.
- C) Wrong or old documents can lead to wrong answers.
- D) It always removes hallucination fully.

### Answers

1. **B** - RAG first retrieves useful information, augments the prompt with it, and then generates an answer.
2. **B** - The lesson teaches this order: prepare knowledge, index chunks, retrieve chunks, augment the prompt, and generate.
3. **A** - RAG can use current text if the knowledge base has been updated with the new notice.
4. **B** - RAG adds found information to the prompt for one question. Fine-tuning changes the model itself.
5. **C** - RAG depends on the knowledge base and retrieval quality. Wrong or old documents can still cause wrong answers.
