# ingestion

This folder contains the ingestion pipeline. It fetches recent papers from arXiv, downloads the PDFs, extracts and cleans the text, and saves everything to a parquet dataset, which would be the input for later chunking, embedding, and vector database steps.

## pipeline steps

1. load the existing dataset and find papers already ingested (`dataset.py`)
2. fetch paper metadata from arXiv and drop papers already ingested (`fetch_metadata.py`) papers marked `complete` are skipped on later runs, so rerunning only processes new papers
3. download the PDFs (`download_pdfs.py`)
4. extract text from the PDFs as markdown (`extract_text.py`)
5. clean the extracted text (`clean_text.py`)
6. merge the new papers into the dataset and save it as parquet (`dataset.py`)

## files

| file | what it does |
|---|---|
| `fetch_metadata.py` | searches arxiv by category and returns metadata for each paper: id, title, abstract, authors, categories, published/updated dates, PDF and abstract URLs and optionally stops at a `since` date |
| `download_pdfs.py` | downloads each paper's PDF into the raw PDF directory. Skips files that already exist and records a `download_status` (`downloaded`, `skipped_exists`, `failed`) and waits 3 seconds between downloads by arxiv rules |
| `extract_text.py` | converts each PDF to markdown text with `pymupdf4llm` and records an `extraction_status` (`extracted`, `failed`, `not_attempted`) |
| `clean_text.py` | replaces the annoying picture-text blocks that `pymupdf4llm` produces with `[Picture Omitted]` and skips papers with no extracted text |
| `dataset.py` | loads the existing parquet, finds already-ingested ids, looks at each paper's `ingestion_status` (`complete`, `partial`, `failed`), then merges, deduplicates by `arxiv_id`, and saves |
| `pipeline.py` | ties the steps together in `run_pipeline(...)` |
| `cli.py` | command-line entrypoint that passes arguments to `run_pipeline` |

## how to use the CLI

run it from the project root as a module, so the relative imports work so for example:

```bash
python -m src.ingestion.cli --max-results 10
```

| argument | default | description |
|---|---|---|
| `--category` | `cat:cs.AI` | arXiv category query |
| `--max-results` | `50` | mmnaximum number of papers to fetch |
| `--since` | none | only include papers published on or after this date (`YYYY-MM-DD`) |
| `--raw-pdf-dir` | `data/raw_pdfs` | where PDFs are saved |
| `--dataset-path` | `data/papers.parquet` | where the parquet dataset is saved |

## what the output is

The parquet file has one row per paper, with the metadata fields above plus `pdf_path`, `download_status`, `extracted_text`, `extraction_status`, and `ingestion_status`
