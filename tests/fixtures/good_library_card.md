# Introduction to RAG

## What is RAG?
RAG means Retrieval-Augmented Generation, a way for a computer to search
useful text before it writes an answer. It uses a language model, an AI program
that reads and writes words, to form the answer. The chosen notes can give the
model details it may not already have.

## How does RAG work?
First, a person asks a question. Next, the system searches its saved notes.
Long pages can be split into small pieces called chunks. An embedding is a list
of numbers that carries some meaning from a piece of text. A vector database is
a tool that stores these number patterns and can find close matches.
The system finds text that may help with the question. It gives that text and
the question to the language model. Then the model writes an answer using the
text it found.

## Everyday worked example
Imagine a student wants to know which book is on loan from a library. A library
card has the book name and its due date. RAG works in a similar way, but a
computer searches a set of supplied records.
First, the student asks, "When is this book due?"
Next, the helper finds the library card for that book.
Then, the helper uses the card's date to answer the question.
Finally, the student can check the card.
The card is like saved information. Finding the right line is retrieval.
Giving that line to the helper adds context. Writing the date is generation.
This example shows the main steps without using a computer term for each one.

## Why does RAG matter?
A model may not have access to a private guide or a recent change. RAG can
search information supplied for a task before the model answers. This can make
an answer more useful for questions about those notes. A system can show the
source text with its answer. Then a person can check where the detail came from.

## Mini glossary
- **RAG**: A way to search information before an AI writes an answer.
- **Retrieval**: Finding useful text for a question.
- **Embedding**: A list of numbers that carries some meaning from text.
- **Vector database**: A tool that stores number patterns for search.
- **Language model**: An AI program that reads and writes words.

## Limits
RAG does not guarantee a correct answer. The search may find the wrong text.
The model can still be wrong, so important answers need checking.
