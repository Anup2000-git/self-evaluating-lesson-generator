---
title: How RAG works - step by step
source: Lewis et al. (2020), arXiv:2005.11401; Microsoft Learn, "Retrieval Augmented Generation (RAG) in Azure AI Search"; OpenAI platform documentation (embeddings); curated summary.
---

## Two phases

A RAG system works in two phases. The first phase, often called indexing or ingestion, prepares the knowledge base and is done before any question is asked (and repeated whenever documents change). The second phase, often called query time, happens every time a user asks a question.

## Phase 1, step 1 - collect and split the documents

First, the useful documents are collected, for example web pages, PDF files, notices or manuals. Long documents are then split into smaller pieces called chunks. A chunk is usually a few sentences to a few paragraphs long. Small chunks make it possible to find and send only the most relevant parts of a long document.

## Phase 1, step 2 - index the chunks

Next, the chunks are indexed so they can be searched quickly. In the most common approach each chunk is converted into an embedding, a list of numbers that represents its meaning, and the embeddings are stored in a vector database. Some systems instead, or additionally, build a keyword index that finds chunks containing the same words as the question.

## Phase 2, step 3 - retrieve

When a user asks a question, the retriever searches the index for the chunks most relevant to the question. With embeddings, the question is also converted into an embedding and the system finds the chunks whose embeddings are most similar to it (similarity search). The retriever returns a small number of the best-matching chunks, often between 3 and 10; this number is called top-k.

## Phase 2, step 4 - augment

The retrieved chunks are added to the prompt together with the user's question. The prompt usually also contains instructions, for example: answer only using the information provided, say "I don't know" if the answer is not there, and mention which source you used. This is the "augmented" part of RAG.

## Phase 2, step 5 - generate

The LLM reads the augmented prompt and generates the answer. Because the relevant information is right there in the prompt, the model can base its answer on it instead of relying only on what it learned during training. Many RAG systems also return the sources of the chunks so that users can check the answer.

## The model itself does not change

In all of these steps the LLM's weights stay the same. RAG changes what is in the prompt for one question; it does not retrain the model. The next question gets its own retrieval and its own augmented prompt.
