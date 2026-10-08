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
    print("--- Testing ChromaRetriever ---")
    query = "What are the key financial risks in AI adoption?"
    top_k = 3

    print(f"Executing search for query: '{query}' (top_k={top_k})\n")

    try:
        retriever = ChromaRetriever()
        res = retriever.search(query, top_k=top_k)

        documents = res.get("documents", [[]])[0]
        metadatas = res.get("metadatas", [[]])[0]
        distances = res.get("distances", [[]])[0]

        print(f"Retrieved {len(documents)} context chunks:\n")
        for idx, (doc, meta, dist) in enumerate(zip(documents, metadatas, distances), start=1):
            print(f"[{idx}] Distance (Score): {dist:.4f}")
            print(f"    Metadata: {meta}")
            print(f"    Content snippet: {doc[:150]}...")
            print("-" * 50)

    except Exception as e:
        print(f"Error executing ChromaRetriever: {e}")
        print("Tip: Ensure 'data/chroma_db' exists and contains 'kpmg_research_collection'.")
