---
title: Augmenting the prompt and generating the answer
source: Microsoft Learn, "Retrieval Augmented Generation (RAG) in Azure AI Search"; OpenAI platform documentation (prompting); curated summary.
---

## What augmentation looks like

After retrieval, the system builds a prompt that contains three parts: instructions for the model, the retrieved chunks, and the user's question. A simple augmented prompt looks like this:

"Answer the question using only the information below. If the answer is not in the information, say you don't know. Information: [retrieved chunk 1] [retrieved chunk 2]. Question: [user's question]."

## Instructions in the prompt

Instructions guide how the model uses the retrieved text. Common instructions are: answer only from the given information; say "I don't know" when the information does not contain the answer; keep the answer short; and name the source used. These instructions reduce made-up answers but cannot guarantee that the model follows them perfectly.

## Generating the answer

The LLM reads the whole augmented prompt and writes the answer. It uses the retrieved chunks as its main evidence and its general language skill to write a clear reply. If the retrieved chunks are relevant and correct, the answer is usually accurate. If they are wrong, outdated or missing, the answer can be wrong too.

## Showing sources

Because each chunk carries information about its source, the system can show the user which document, page or notice the answer came from. Showing sources lets people verify the answer and is one of the main reasons organisations use RAG.
