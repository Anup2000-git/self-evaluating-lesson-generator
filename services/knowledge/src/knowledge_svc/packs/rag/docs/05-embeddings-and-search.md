---
title: Embeddings, vectors and searching for relevant chunks
source: OpenAI platform documentation (embeddings guide); Microsoft Learn, "Vector search in Azure AI Search"; Robertson & Zaragoza (2009) on BM25; curated summary.
---

## Embeddings

An embedding is a list of numbers that represents the meaning of a piece of text. An embedding model converts text into such a list. Texts with similar meaning get similar lists of numbers, even when they use different words. For example, "exam fee last date" and "deadline to pay the exam fee" get embeddings that are close to each other.

## Vectors

A list of numbers like an embedding is also called a vector. Embeddings usually contain hundreds or thousands of numbers. Each number on its own does not have a simple human meaning; the meaning is captured by the whole list together.

## Vector databases

A vector database (or vector store) is a system that stores many embeddings together with the text they came from and can quickly find the stored embeddings that are most similar to a new one. Examples include dedicated vector databases and vector features built into search engines and regular databases.

## Similarity search

To find relevant chunks, the question is converted into an embedding and compared with the stored chunk embeddings. The chunks whose embeddings are closest to the question's embedding are returned. This is called similarity search, semantic search or vector search. Closeness is measured with a similarity score; a common one is cosine similarity.

## Keyword search and hybrid search

Search can also be done with keywords: a keyword search finds chunks that contain the same words as the question. A well-known keyword ranking method is BM25 (Best Matching 25). Keyword search is good at exact terms like names, codes and numbers; similarity search is good at matching meaning. Many systems combine both, which is called hybrid search.

## Top-k

The retriever returns only the k best-matching chunks, often between 3 and 10. Returning too few chunks can miss the answer; returning too many can add irrelevant text and fill up the context window.
