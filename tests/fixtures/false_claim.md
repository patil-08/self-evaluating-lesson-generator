# Introduction to RAG

## What is RAG?
RAG, short for Retrieval-Augmented Generation, is a way for AI to find useful text before writing an answer. A language model is an AI program that reads and writes words.

## Why does RAG matter?
A model may not know a new notice or a private guide unless someone supplies it. RAG can use supplied documents to make an answer more useful. It can also show the text used, so a person can check the answer.
For example, a learning app could search a lesson guide supplied by a learner. This can help answer questions about that guide, but the result still depends on the text the search finds.

## How does RAG work?
First, long documents can be split into small pieces called chunks. An embedding is a list of numbers that carries some meaning from text. A vector database stores these number patterns for search.
1. Retrieve: The system searches for text related to the question.
2. Augment: It adds the found text beside the question.
3. Generate: The language model writes an answer using both.

## Example
Imagine asking a family member about a school exam date. First, they find the date in a school notice. Next, they read that line with your question. Then, they tell you the date. RAG follows a similar idea, but computer software searches text and writes the answer.

## Limitations
Search can find poor information. RAG guarantees a correct answer. A person should check important answers.

## Recap
RAG searches supplied text, adds useful parts to a question, and helps an AI write an answer.

## Mini glossary
- RAG: A way to search text before an AI answers.
- Retrieval: Finding useful text for a question.
- Embedding: A list of numbers that carries some meaning from text.
- Vector database: A tool that stores number patterns for search.
- Language model: An AI program that reads and writes words.
