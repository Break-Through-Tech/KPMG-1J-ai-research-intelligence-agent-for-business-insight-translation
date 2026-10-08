import chromadb
from src.vectorizing.embedder import TextEmbedder

class ChromaRetriever:
    def __init__(self, db_dir: str = "data/chroma_db", collection_name: str = "kpmg_research_collection"):
        self.client = chromadb.PersistentClient(path=db_dir)
        self.collection = self.client.get_collection(name=collection_name)
        self.embedder = TextEmbedder()

    def search(self, user_query: str, top_k: int = 5):
        query_vector = self.embedder.embed_query(user_query)

        results = self.collection.query(
            query_embeddings=[query_vector.tolist()],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )
        return results

if __name__ == "__main__":
    retriever = ChromaRetriever()
    res = retriever.search("What are the key financial risks in AI adoption?", top_k=3)
