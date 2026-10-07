import re

#prototype of a text cleaning module

# pymupdf4llm sometimes returns half of a unicode pair (a "lone surrogate", e.g. \ud835 from math fonts)
# these can't be saved to parquet and crash the whole batch, so they get removed
SURROGATE_RE = re.compile(r"[\ud800-\udfff]")

def strip_surrogates(text):
    if isinstance(text, str):
        return SURROGATE_RE.sub("", text)
    return text

#this function just gets rid of the messy image descriptions that pymupdf4llm creates
def clean_text(raw_text: str) -> str:
    text = re.sub(r"<!-- Start of picture text -->.*?<!-- End of picture text -->", "[Picture Omitted]", raw_text, flags=re.DOTALL)
    return strip_surrogates(text)

def clean_all(papers):

    for paper in papers:
        if paper["extracted_text"] == None:
            continue
        paper["extracted_text"] = clean_text(paper["extracted_text"])
    return papers
