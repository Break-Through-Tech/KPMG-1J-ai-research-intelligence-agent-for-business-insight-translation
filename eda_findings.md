# EDA findings (Abdullah)

Dataset source: team ingestion pipeline (`data/papers.parquet`, sha256 842e8108e452...)
Repository commit: 5435927f9c3673bca32a0f464ef62bd7e7e3bd3e
Notebook run (UTC): 2026-09-30 05:06
Sample: 20 papers, published 2026-09-29 17:08 to 2026-09-29 17:59 UTC

## Automated checks
- Missing values (null, blank, empty list): none
- Duplicates: none
- Status/text/file contradictions: none
- Extracted length: median 10,340 words (min 3,192, max 23,531)
- Extraction-quality signals (raw text): papers with HTML tags (<sup> etc.): 20; papers with [Picture Omitted]: 20; papers with replacement characters: 10; papers with table-like rows: 20; papers with >10% repeated lines: 3
- After preprocessing (body_text, papers still affected): not checked (papers_clean.parquet not found)

## Manual review
Reviewed 0 of 6 selected papers (2609.38043v1, 2609.38108v1, 2609.38093v1, 2609.38107v1, 2609.38147v1, 2609.38109v1).
**NOT YET DONE. Do not report manual findings until the log in section 6 is filled in.**

## Recommended cleaning / pipeline fixes (from measured signals)
- Strip or convert HTML tags such as <sup> (20 raw papers).
- Decide whether [Picture Omitted] placeholders stay in chunks (20 raw papers, 149 blocks).
- Check running headers/footers/tables in 3 raw papers with many repeated lines.
- Replacement characters (encoding damage) in 10 raw papers.

## Limitations
- Small recent-paper sample; not representative of all AI research.
- Word/character counts are approximate and include Markdown, tables and references.
- Signals are heuristics; only the manual review checks correctness against the PDFs.
