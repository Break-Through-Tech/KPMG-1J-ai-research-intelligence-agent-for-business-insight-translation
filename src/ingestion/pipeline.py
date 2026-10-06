# final pipeline using all of the helper files
from datetime import date
from .dataset import load_existing, get_ingested_ids, merge_and_save
from .fetch_metadata import fetch_metadata
from .download_pdfs import download_all
from .extract_text import extract_all
from .clean_text import clean_all

def run_pipeline(category = "cat:cs.AI", max_results=50, raw_pdf_dir = "data/raw_pdfs", dataset_path = "data/papers.parquet", since: date | None = None,
                 max_papers: int | None = None, batch_size: int | None = None):
    """max_papers caps how many new papers one run processes, batch_size saves progress every N papers.
    when either is set, papers are processed oldest first, so a capped or interrupted run
    leaves no gaps: the next run picks up right where this one stopped"""

    existing_df = load_existing(dataset_path) #loads existing papers
    ingested_ids = get_ingested_ids(existing_df)

    papers = fetch_metadata(category, max_results, since)
    papers = [p for p in papers if p["arxiv_id"] not in ingested_ids]
    if not papers:
        print("Nothing new to ingest")
        return existing_df

    if max_papers is None and batch_size is None:
        papers = download_all(papers, raw_pdf_dir)
        papers = extract_all(papers)
        papers = clean_all(papers)
        return merge_and_save(existing_df, papers, dataset_path)

    # oldest first, so stopping early never skips anything older than what was saved
    papers.sort(key=lambda p: p["published"])
    backlog = 0
    if max_papers is not None and len(papers) > max_papers:
        backlog = len(papers) - max_papers
        papers = papers[:max_papers]

    size = batch_size or len(papers)
    n_batches = (len(papers) + size - 1) // size
    print(f"{len(papers)} new papers to ingest in {n_batches} batch(es)"
          + (f", {backlog} more left for the next run" if backlog else ""))

    for i in range(n_batches):
        batch = papers[i * size:(i + 1) * size]
        batch = download_all(batch, raw_pdf_dir)
        batch = extract_all(batch)
        batch = clean_all(batch)
        existing_df = merge_and_save(existing_df, batch, dataset_path) #saved after every batch
        print(f"batch {i + 1}/{n_batches} saved ({len(batch)} papers, {len(existing_df)} total)")

    return existing_df
