# PDF -> raw text using PyMuPDF

import os
from pathlib import Path
import pymupdf4llm #package for parsing pdfs and organizing the info

def extract_text(pdf_path: Path) -> str | None:
    try:
        text = pymupdf4llm.to_markdown(pdf_path)
        return text
    except Exception as e:
        print(f"Failed to extract text from {pdf_path}: {e}")
        return None

def extract_all(papers):
    for paper in papers:
        if paper["download_status"] == "failed":
            paper["extracted_text"] = None
            paper["extraction_status"] = "not_attempted"
            continue
        text = extract_text(paper["pdf_path"])
        paper["extracted_text"] = text
        paper["extraction_status"] = "extracted" if text is not None else "failed"
        if text is None and os.path.exists(paper["pdf_path"]):
            os.remove(paper["pdf_path"]) # likely corrupt, so the retry downloads it again
    return papers