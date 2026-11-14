# Source review notes

- **F14-F15 (RAG and weight updates):** F14 is limited to the usual inference
  flow: looking up passages does not itself change model weights. F15 records
  the important qualification that the original 2020 research system fine-tuned
  its retriever and generator. RAG implementations may also use training or
  fine-tuning; please verify this distinction before presenting it as "RAG
  never trains a model."
- **F10 (vector databases):** Products differ in whether they keep the original
  text, metadata, or only vectors and references. The fact deliberately says
  they *can* keep searchable information and avoids claiming every product
  stores the same fields.
- **F12 (sources shown with answers):** Source display is a system feature, not
  an automatic guarantee of every RAG implementation. Verify whether the
  implementation being discussed returns citations or retrieved passages.

The original paper's arXiv landing page could not be fetched directly in this
environment. Its title, year, and abstract were checked through the OpenAlex
record for the same arXiv identifier:
https://api.openalex.org/works/https%3A%2F%2Fdoi.org%2F10.48550%2FarXiv.2005.11401
