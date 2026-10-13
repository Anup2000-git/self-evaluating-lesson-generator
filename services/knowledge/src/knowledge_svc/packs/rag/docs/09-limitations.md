---
title: Limitations of RAG
source: Microsoft Learn, "Retrieval Augmented Generation (RAG) in Azure AI Search"; Lewis et al. (2020), arXiv:2005.11401; curated summary.
---

## Retrieval quality decides answer quality

A RAG answer can only be as good as the chunks it receives. If the retriever brings back the wrong chunk, an incomplete chunk or nothing useful, the model may give a wrong or incomplete answer. This is often summarised as "wrong information in, wrong answer out".

## The knowledge base must be maintained

RAG uses whatever is in the knowledge base. If documents are outdated, wrong or missing, answers will be too. New documents must be added and old ones updated or removed, otherwise the system keeps answering from old information.

## Hallucination is reduced, not removed

Even with good chunks, the model can still misunderstand them, mix information from different chunks wrongly, or ignore them and answer from its training. RAG reduces hallucination but does not guarantee correct answers. Important answers still need checking.

## Limited context window

Only a limited amount of retrieved text fits into the model's context window. If too much text is added, the most useful parts may not fit, and irrelevant text can distract the model. This is why systems send only the top few chunks.

## Extra time and cost

Every question needs an extra search step before the model answers. This adds some delay and cost compared with asking the model directly. Building and maintaining the index also needs effort.

## Access control

If the knowledge base contains private documents, the system must make sure users only retrieve documents they are allowed to see.
