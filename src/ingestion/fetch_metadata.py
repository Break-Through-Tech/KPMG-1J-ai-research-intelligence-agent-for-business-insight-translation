import arxiv, re
from datetime import date

# file for fetching metadata from the PDFs in Arxiv

def fetch_metadata(category = "cat:cs.AI", max_results = 50, since: date | None = None) -> list[dict]:
    """runs the arxiv.Client search loop, returns metadata dicts with 
    arxiv_id, title, abstract, authors, primary_category, categories, published,
    updated, pdf_url, abs_url)"""

    client = arxiv.Client(num_retries = 3, delay_seconds = 3)
    search = arxiv.Search(query = category, max_results = max_results, sort_by = arxiv.SortCriterion.SubmittedDate)

    papers = []
    for result in client.results(search):

        if since is not None and result.published.date() < since:
            break # results are newest first so nothing after will match either but this can be removed

        short_id = result.get_short_id()

        papers.append({
            "arxiv_id": short_id,
            "title": re.sub(r"\s+", " ", result.title).strip(), # re.sub(r"\s+")... is a way to get rid of white space using regex patterns
            "abstract": re.sub(r"\s+", " ", result.summary).strip(),
            "authors": [a.name for a in result.authors],
            "primary_category": result.primary_category,
            "categories": result.categories,
            "published": result.published,
            "updated": result.updated,
            "pdf_url": result.pdf_url,
            "abs_url": result.abs_url,
        })

    return papers

