---
title: Common misconceptions about RAG
source: Curated from the documents in this pack (Lewis et al. 2020; Microsoft Learn RAG and fine-tuning guidance).
---

## "RAG teaches the model new facts permanently"

False. RAG does not retrain the model or change its weights. The retrieved information is placed in the prompt and used only for that one answer. Permanently changing a model requires training, such as fine-tuning.

## "With RAG, the answer is always correct"

False. If the retriever returns the wrong or outdated chunks, or the documents themselves are wrong, the answer can still be wrong. The model can also misread the information. RAG makes answers more grounded, not guaranteed.

## "RAG and fine-tuning are the same thing"

False. Fine-tuning changes the model itself by training it on new examples. RAG leaves the model unchanged and adds information to the prompt at question time.

## "The model searches the whole internet by itself"

False. In RAG, a separate retrieval step searches a chosen knowledge source, which may be a small set of documents. The LLM only sees the chunks that the retriever puts into the prompt.

## "More retrieved text always gives a better answer"

False. The context window is limited, and irrelevant chunks can distract the model. Good RAG systems send a small number of the most relevant chunks.
