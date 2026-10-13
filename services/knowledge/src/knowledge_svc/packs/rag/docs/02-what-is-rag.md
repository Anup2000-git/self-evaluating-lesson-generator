---
title: What RAG (Retrieval-Augmented Generation) is
source: Lewis et al. (2020), "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", NeurIPS 2020, arXiv:2005.11401; Microsoft Learn, "Retrieval Augmented Generation (RAG) in Azure AI Search".
---

## Definition

Retrieval-Augmented Generation (RAG) is a method for answering questions with a large language model (LLM). Before the model answers, the system first retrieves (searches for and brings back) relevant pieces of information from an outside knowledge source, such as a collection of documents. It then adds those pieces to the prompt together with the question. Finally, the LLM generates its answer using that information. In short: retrieve, then augment, then generate.

## Meaning of the name

Retrieval means finding and bringing back relevant information. Augmented means made bigger or better by adding something; here the prompt is augmented with the retrieved information. Generation means creating new text; here the LLM generates the answer. So Retrieval-Augmented Generation means generating an answer from a prompt that has been augmented with retrieved information.

## The knowledge base

The outside knowledge source that RAG searches is often called a knowledge base. It can be any collection of documents: web pages, PDF files, company policies, product manuals, college notices or a database of articles. The knowledge base is separate from the LLM. It can be changed or updated at any time without changing the model.

## Where the idea comes from

The term "retrieval-augmented generation" was introduced in a 2020 research paper by Patrick Lewis and colleagues from Facebook AI Research (now Meta AI), University College London and New York University. The paper combined a language model with a retriever that searched Wikipedia, and showed that this helped on knowledge-heavy question answering tasks. Since then, RAG has become one of the most common ways to build AI assistants that answer from specific documents.

## A simple way to picture RAG

A common teaching picture is the open-book exam. In a closed-book exam a student answers only from memory, like an LLM answering only from its training. In an open-book exam the student first finds the right page in the book and then writes the answer using it, like an LLM that is given retrieved information before answering.
