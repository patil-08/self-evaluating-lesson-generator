# Grounding notes for "Introduction to RAG" (used by Planner, Generator and Evaluator)
- RAG stands for Retrieval-Augmented Generation. It was introduced in 2020 by Lewis et al. (Facebook AI Research) in the paper "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks".
- Problem it solves: a large language model (LLM) only knows what it saw during training. Its knowledge can be out of date, it knows nothing about private documents (like a company's own files), and it sometimes makes up answers that sound correct but are wrong (called hallucination).
- Idea: before the LLM answers, the system first RETRIEVES the most relevant pieces of text from a knowledge base, then AUGMENTS the prompt by adding those pieces, and then the LLM GENERATES the answer using them.
- Typical steps: (1) split documents into small chunks; (2) turn each chunk into an embedding (a list of numbers that captures meaning); (3) store embeddings in a vector database; (4) turn the user's question into an embedding; (5) find the chunks whose embeddings are closest to the question; (6) put the question + those chunks into the prompt; (7) the LLM writes the answer from them.
- RAG does NOT retrain or change the LLM's weights. To update knowledge, you just update the documents in the knowledge base.
- Benefits: fresher answers, works with private data, fewer made-up answers, answers can show their sources.
- Limitations: if retrieval finds the wrong chunks, the answer will be poor; chunking choices matter; it adds extra steps and cost; the LLM can still make mistakes.
- Everyday analogy: an open-book exam. The student (LLM) doesn't need to memorise everything; they look up the right pages (retrieval) and then write the answer.
