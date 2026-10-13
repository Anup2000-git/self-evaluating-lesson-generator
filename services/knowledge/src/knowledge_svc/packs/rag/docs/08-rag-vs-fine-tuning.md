---
title: RAG compared with fine-tuning
source: Microsoft Learn, "Augment large language models with RAG or fine-tuning"; OpenAI platform documentation (fine-tuning); curated summary.
---

## What fine-tuning is

Fine-tuning means training an already-trained model further on a smaller set of new examples. This changes the model's weights, so the change is permanent: the fine-tuned model behaves differently for every future question. Fine-tuning needs prepared training examples, computing power and time.

## How RAG is different

RAG does not change the model at all. It gives the model extra information inside the prompt for one particular question. When the next question comes, the system retrieves again. Information added through RAG is used only for that answer and is not stored inside the model.

## When each is used

RAG is a good fit when the knowledge changes often (prices, rules, notices, news), when answers must come from specific documents, and when answers should show their sources. Fine-tuning is a better fit for teaching a model a style, a format or a specialised behaviour that should apply to all answers. Updating facts with RAG is usually much cheaper and faster than fine-tuning, because only the documents need to change.

## Using both

RAG and fine-tuning are not opposites. Some systems fine-tune a model to follow a company's style or format and also use RAG to give it up-to-date facts.
