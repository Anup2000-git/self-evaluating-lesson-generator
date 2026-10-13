---
title: Chunking - splitting documents into pieces
source: Microsoft Learn, "Chunk large documents for vector search solutions in Azure AI Search"; curated summary.
---

## Why documents are split into chunks

Documents are split into smaller pieces called chunks for three reasons. First, an LLM's context window is limited, so a whole book or a long manual cannot be put into one prompt. Second, a smaller piece is more focused, so search can match the part of the document that actually answers the question. Third, sending only the relevant pieces keeps the prompt short, which saves time and cost.

## Chunk size

There is no single correct chunk size. Chunks are often a few sentences to a few paragraphs long, for example a few hundred tokens. Chunks that are too small can lose the surrounding meaning (a sentence may not make sense alone). Chunks that are too large can mix many topics, which makes search less precise and uses more of the context window.

## Splitting methods

Simple systems split text after a fixed number of tokens or characters. Better systems split at natural boundaries such as headings, paragraphs or sentences, so that each chunk is a complete idea. Some systems repeat a small part of the previous chunk at the start of the next one (overlap) so that an idea cut at the boundary is not lost.

## Keeping track of the source

Each chunk is stored together with information about where it came from, such as the document name, page or section. This makes it possible for a RAG answer to show its source.
