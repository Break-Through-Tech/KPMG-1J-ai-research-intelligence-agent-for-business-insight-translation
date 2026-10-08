# RAG Module (`src/rag/`)

This module manages document vector indexing and similarity retrieval using ChromaDB.

---

## 1. Indexer (`indexer.py`)

* **Purpose**: Processes text chunks and embeds them into the ChromaDB vector store.
* **Key Components**:
  * `build_chroma_index(...)`: Takes chunked text documents, embeds them using `TextEmbedder`, and stores/persists them into the designated ChromaDB collection.
* **Default Database Path**: `data/chroma_db`
* **Default Collection Name**: `kpmg_research_collection`

### Usage / Standalone Execution
To build or update the index directly:
```bash
python -m src.rag.indexer
