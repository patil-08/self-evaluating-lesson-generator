> **Run status:** A live-provider run was not possible because this environment
> has no live LLM credentials configured. This lesson is a human-edited fallback
> checked with the deterministic mock evaluator; it is not represented as a
> real-key generation or a real-model judge result.

# Introduction to RAG

## What is RAG?

RAG means Retrieval-Augmented Generation, a way for an AI to find useful text
before it writes an answer. A language model is an AI program that receives text
and writes an answer. RAG gives that program selected information with the
question.

## How does RAG work?

Before a question arrives, long documents can be split into small pieces called
chunks. An embedding is a list of numbers that carries some meaning from text.
A vector database is a tool that stores these number lists for search.

1. **Retrieve:** Retrieval means finding useful text for a question. The system
   searches stored text for parts related to the question.
2. **Augment:** Augment means add the useful text beside the question. The
   system sends both to the language model.
3. **Generate:** Generate means write. The language model uses the question and
   the added text to write an answer.

## Everyday worked example

Imagine your family has a printed timetable for a local train in India. You
ask, “What time does the train leave from our station?” This example is only an
analogy. A real RAG system searches text with software.

1. The system finds timetable lines about that station.
2. It adds a useful line beside your question.
3. The language model writes a reply using the question and that line.

You can compare the reply with the timetable. The timetable is like saved
information. Finding a useful line is retrieval. Giving it with the question
is augmentation. Writing the reply is generation.

## Why does RAG matter?

A model may not have a private guide or a recent notice unless that text is
provided. RAG can search supplied information before the model answers. This
can make the answer more useful for questions about those documents. A system
can show the found text, so a person can check where a detail came from.
RAG supplies extra text for this answer. It does not train the AI again.

## Mini glossary

- **RAG:** A way to find useful text before an AI writes an answer.
- **Retrieval:** Finding useful text for a question.
- **Embedding:** A list of numbers that carries some meaning from text.
- **Vector database:** A tool that stores number lists for search.
- **Language model:** An AI program that receives text and writes an answer.

## Limits

Search can find poor or unrelated information. RAG does not guarantee a
correct answer. The model may use found information badly, so check important
answers.

## Recap

RAG finds useful text, adds it to a question, and uses an AI to write an answer.
It can help with supplied documents, but a person should still check important
answers.

---

**Grounding note:** The factual explanation is based on reviewed facts F01,
F03–F14, and F18 in `sources/rag_facts.json`. The train timetable is an
illustration, not a claim about a particular service or schedule.
