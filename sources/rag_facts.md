# Reviewed RAG facts

These are short paraphrases for lesson grounding, not quotations.

- **F01**: Retrieval-Augmented Generation (RAG) joins document search with a language model that writes an answer using selected information. Source: https://arxiv.org/abs/2005.11401
- **F02**: A language model may not have a user's private documents or the newest information unless that information is supplied. Source: https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview
- **F03**: A RAG system searches its document collection for information related to the user's question before it writes a response. Source: https://cloud.google.com/use-cases/retrieval-augmented-generation
- **F04**: The selected passages and the question are added to the model's input; the model then writes an answer using that context. Source: https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview
- **F05**: Long documents are often split into smaller pieces called chunks so search can return useful parts instead of whole files. Source: https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview
- **F06**: An embedding is a list of numbers created from text that represents some of its meaning and context. Source: https://learn.microsoft.com/en-us/azure/search/vector-search-overview
- **F07**: Texts with related meaning often have embeddings that are close in the chosen numerical space, even if they use different words. Source: https://learn.microsoft.com/en-us/azure/search/vector-search-overview
- **F08**: A vector search index stores numerical text representations and can find representations close to the user's question. Source: https://learn.microsoft.com/en-us/azure/search/vector-search-overview
- **F09**: A vector database or index can support RAG search; products differ in whether they also store the original text and other fields. Source: https://learn.microsoft.com/en-us/azure/search/vector-search-overview
- **F10**: Supplying relevant documents can make a model's answer more useful for questions about those documents. Source: https://cloud.google.com/use-cases/retrieval-augmented-generation
- **F11**: Showing retrieved passages or their sources can help a person check where answer details came from. Source: https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview
- **F12**: RAG cannot promise a correct answer; search can return poor passages and the model can use them badly. Source: https://cloud.google.com/use-cases/retrieval-augmented-generation
- **F13**: In a typical RAG request, retrieved text is added to the model input; this step does not update the model's learned weights. Source: https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview
- **F14**: The 2020 research system by Lewis and colleagues fine-tuned its retriever and generator, so it is wrong to claim that no RAG system is ever trained. Source: https://arxiv.org/abs/2005.11401
- **F15**: Retrieval and ranking choices affect which passages are passed to the language model. Source: https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview
- **F16**: Systems that search private files need access checks so each user sees only documents they are allowed to use. Source: https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview
- **F17**: A simple analogy is checking class notes before answering a question: find the notes first, then use them to write the answer. Source: https://cloud.google.com/use-cases/retrieval-augmented-generation

## Facts to verify

- **F14** is about the specific 2020 research model, not every current RAG
  application. Verify the paper's training details before making a broader
  statement about training in RAG systems.
- **F09** deliberately says products differ. Check the documentation for a
  chosen vector database before describing its storage features.
