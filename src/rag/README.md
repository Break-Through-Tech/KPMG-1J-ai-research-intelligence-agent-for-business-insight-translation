# RAG Module (`src/rag/`)

This module manages document vector indexing and similarity retrieval using ChromaDB.

---

## 1. Indexer (`indexer.py`)

- **Purpose**: Processes text chunks and embeds them into the ChromaDB vector store.
- **Key Components**:
  - `build_chroma_index(...)`: Takes chunked text documents, embeds them using `TextEmbedder`, and stores/persists them into the designated ChromaDB collection.
- **Default Database Path**: `data/chroma_db`
- **Default Collection Name**: `kpmg_research_collection`

### Usage / Standalone Execution
To build or update the index directly:
`python -m src.rag.indexer`

---

## 2. Retriever (`retriever.py`)

- **Purpose**: Searches stored vector embeddings in ChromaDB to retrieve relevant context chunks for user queries.
- **Key Components**:
  - `ChromaRetriever`: Class that initializes the ChromaDB persistent client, loads `TextEmbedder`, and executes vector queries.
  - `.search(user_query, top_k=5)`: Converts a plain text query to an embedding vector and returns top matching documents, metadata, and distance scores.

### Usage / Standalone Execution
To test query retrieval directly:
`python -m src.rag.retriever`
