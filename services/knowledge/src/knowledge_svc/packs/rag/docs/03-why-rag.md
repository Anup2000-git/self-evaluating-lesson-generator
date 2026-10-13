---
title: Why RAG is useful - the problems it addresses
source: Lewis et al. (2020), arXiv:2005.11401; Microsoft Learn, "Retrieval Augmented Generation (RAG) in Azure AI Search"; curated summary.
---

## Problem 1 - outdated knowledge (knowledge cutoff)

An LLM only knows what was in its training data, which was collected up to its knowledge cutoff date. It does not automatically learn new facts after that date. For example, it cannot know today's cricket score, a new government rule or a notice published last week. RAG addresses this by searching a knowledge base at the moment the question is asked. If the knowledge base is kept up to date, the model can answer using current information.

## Problem 2 - hallucination

LLMs sometimes produce answers that sound correct but are false (hallucination). When the model is given relevant, reliable text inside the prompt and is instructed to answer from it, it has real facts to base its answer on. This reduces hallucination. It does not remove it completely: the model can still misread the text, combine it wrongly or ignore it.

## Problem 3 - private and specific information

A general LLM was never trained on an organisation's own documents, such as a company's leave policy, a hospital's records, a school's timetable or a college's notices. These documents were not part of its training data. RAG lets the model use such documents at answer time without retraining the model and without the model permanently learning them.

## Benefit - answers with sources

Because the answer is based on specific retrieved documents, a RAG system can show where the information came from (its source or citation). Users can then open the source and check the answer themselves, which builds trust.

## Benefit - cheaper and faster updates

Retraining or fine-tuning an LLM to add new knowledge takes a lot of computing power, time and money. With RAG, adding new knowledge usually means adding or updating documents in the knowledge base, which is much cheaper and faster.
