import re

#prototype of a text cleaning module

#this function just gets rid of the messy image descriptions that pymupdf4llm creates
def clean_text(raw_text: str) -> str:
    return re.sub(r"<!-- Start of picture text -->.*?<!-- End of picture text -->", "[Picture Omitted]", raw_text, flags=re.DOTALL)

def clean_all(papers):
    for paper in papers:
        paper["extracted_text"] = clean_text(paper["extracted_text"])
    return papers