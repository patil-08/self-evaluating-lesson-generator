> **Run status:** This is a human-edited fallback checked with the deterministic
> mock evaluator. It is not a live-provider generation or a real-model judge
> result.

# Introduction to RAG

## What is RAG?

RAG, short for Retrieval-Augmented Generation, is a way for AI to find useful
text before writing an answer. A language model is a computer program that
reads text and writes an answer.

## Why does RAG matter?

A model may not know a new school notice or a private guide unless someone
supplies it. RAG searches the supplied text first. This can help an answer use
details from that text. The system can also show the text it found, so a person
can check the answer. RAG does not train the model again for each question.

## How does RAG work?

Before a question arrives, long documents can be split into small pieces called
chunks. A chunk is a small piece of a document. An embedding is a list of
numbers that carries some meaning from text. A vector database stores these
number lists so a system can search them.

1. **Retrieve:** The system finds text related to the question.
2. **Augment:** It adds the useful text beside the question.
3. **Generate:** The language model writes an answer using both.

## Example

Imagine your family keeps a local train timetable at home. You ask, “What time
does the train leave?” This is only an analogy. A real RAG system uses software
to search text.

1. The system searches the timetable for a line about your station.
2. It puts that line beside your question.
3. The language model writes an answer using both.

You can check the answer against the timetable. The timetable is like saved
information. Finding a useful line is retrieval. Adding it beside your question
is augmentation. Writing an answer is generation.

## Limitations

Search can find poor or unrelated information. RAG does not guarantee a correct
answer. The model may use the found text badly. A person should check important
answers.

## Mini glossary

- **RAG:** A way to find useful text before an AI writes an answer.
- **Retrieval:** Finding useful text for a question.
- **Embedding:** A list of numbers that carries some meaning from text.
- **Vector database:** A tool that stores number lists for search.
- **Language model:** A computer program that reads text and writes an answer.

## Recap

RAG finds useful text, adds it to a question, and asks a language model to write
an answer. It can help with supplied documents, but it can still be wrong.

---

**Grounding note:** The factual explanation is based on reviewed facts F01,
F03–F14, and F18 in `sources/rag_facts.json`. The train timetable is an
illustration, not a claim about a particular service or schedule.
