# Combined Retriever

`combined_retriever.py` makes combined title/abstract and chunk search available for any query. It uses the existing embedding model and Chroma database.

## How it works

1. Load indexed papers and embed their titles and abstracts at startup.
2. Search titles and abstracts for up to 30 candidate papers.
3. Search 100 chunks and keep up to 30 distinct candidate papers.
4. Combine both paper rankings using reciprocal rank fusion.
5. Retrieve one relevant supporting chunk from each selected paper.

The supporting-chunk search happens after paper selection and does not change the paper ranking.

## How to use it

Run from the repository root with the existing local database, cleaned corpus, and project dependencies available.

```python
from src.rag.combined_retriever import CombinedRetriever

# Initialize once and reuse for later queries.
retriever = CombinedRetriever()

papers = retriever.search(
    "How can businesses reduce AI hallucinations?",
    top_k=5,
)

for paper in papers:
    print(paper["paper_id"], paper["title"])
    print(paper["best_chunk_text"])
```

`top_k` accepts integers from 1 to 30. Fewer results may be returned if there are fewer candidates.

## Returned information

| **Fields** | **Purpose** |
| --- | --- |
| `paper_id`, `title`, `abstract` | Identify and describe the paper. |
| `score` | Combined ranking score; not confidence or probability. |
| `chunk_id`, `chunk_paper_id` | Identify the supporting chunk and its indexed paper version. |
| `best_chunk_section`, `best_chunk_text` | Provide evidence for downstream summarization. |
| `chunk_distance` | Query-to-chunk distance; lower means a closer match. |

Pass `best_chunk_text` to the summarizer and retain the source identifiers for attribution. Generated claims and citations still need review.

The original `retriever.py` returns raw Chroma chunk results. This retriever returns a **list of paper dictionaries**, so calling code must use the new format.
