# final pipeline using all of the helper files
from datetime import date
from .dataset import load_existing, get_ingested_ids, merge_and_save
from .fetch_metadata import fetch_metadata
from .download_pdfs import download_all
from .extract_text import extract_all
from .clean_text import clean_all

def run_pipeline(category = "cat:cs.AI", max_results=50, raw_pdf_dir = "data/raw_pdfs", dataset_path = "data/papers.parquet", since: date | None = None):

    existing_df = load_existing(dataset_path) #loads existing papers
    ingested_ids = get_ingested_ids(existing_df)

    papers = fetch_metadata(category, max_results, since)
    papers = [p for p in papers if p["arxiv_id"] not in ingested_ids]
    if not papers:
        print("Nothing new to ingest")
        return existing_df

    papers = download_all(papers, raw_pdf_dir)
    papers = extract_all(papers)
    papers = clean_all(papers)

    return merge_and_save(existing_df, papers, dataset_path)



