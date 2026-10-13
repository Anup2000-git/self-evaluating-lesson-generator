---
title: Large language models (LLMs) - the basics
source: Curated summary of widely documented LLM concepts (OpenAI platform documentation; Microsoft Learn, Azure OpenAI concepts).
---

## What a large language model is

A large language model (LLM) is a computer program trained on a very large amount of text, such as books, articles and web pages. During training it learns patterns of language: which words and ideas usually go together. Using these patterns, it can understand a question and write a new answer one small piece at a time. Chatbots such as ChatGPT use an LLM to write their replies. An LLM is a type of artificial intelligence (AI), which means computer programs that do tasks that normally need human thinking.

## Training data and model weights

The text an LLM learns from is called its training data. What the model learns is stored as numbers inside the model, called model weights or parameters. After training, the weights stay fixed. Using the model to answer questions does not change its weights. Changing what a model knows permanently needs further training, for example fine-tuning.

## Tokens

LLMs do not read text letter by letter or word by word. They split text into tokens, which are small pieces of words. A short common word is often one token; a long word may be split into several tokens. Limits and prices of LLMs are usually counted in tokens.

## Prompts

The input we give to an LLM is called a prompt. A prompt contains the user's question and can also contain instructions (for example "answer in simple English") and extra information for the model to use. The model writes its answer based on everything in the prompt plus what it learned during training.

## Knowledge cutoff

An LLM's training data was collected up to a certain date. This date is called its knowledge cutoff. On its own, the model does not know about events, prices, rules or documents that appeared after that date. If asked about them, it may say it does not know, or it may give outdated information.

## Hallucination

Sometimes an LLM produces an answer that sounds fluent and confident but is false or made up. This is called hallucination. It happens because the model generates text that is likely to sound right, not text that it has checked against a source. Hallucination is more likely when the question is about something the model never saw in its training data.

## Context window

An LLM can only read a limited amount of text at one time, including the prompt and its own answer. This limit is called the context window and is measured in tokens. Anything that does not fit in the context window cannot be used by the model for that answer.
