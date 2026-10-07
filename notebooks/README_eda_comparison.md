# EDA comparison

Three of us ran EDA on the ingestion output, each with a different focus. This page compares them so we can see what's covered, where they overlap, and what's still missing.

| | Chythra | Alena | Abdullah |
|---|---|---|---|
| branch | `chythras-eda` | `alena-eda` | `abdullah-eda` |
| notebook | `notebooks/eda_corpus.ipynb` | `notebooks/eda_data_quality.ipynb` | `notebooks/KPMG1J_EDA_Abdullah .ipynb` |
| main question | Is the text ready to chunk, and how big will the index be? | Is the data correct and consistent? | Did PDF extraction produce faithful text? |
| sample | 160 papers, Sept 22–25 | 50 papers, Sept 25 (~5 hours) | 20 papers, Sept 29 (~1 hour) |
| led to | `src/preprocessing` (Task #4) | 406 fix in `fetch_metadata.py` | `prepare_for_chunking.py` |

All three branches are unmerged as of October 6, 2026.

## what each one covers

**Chythra: corpus and text structure.** Looks at what was ingested and whether it can be chunked: date range, category mix, text length, silent extraction failures, markdown headings, how much of each paper is references, and index size. Her findings drove the preprocessing design: chunk on headings (every paper had them), drop references and appendices (about half of each paper), and flag bodies under 5,000 characters.

**Alena: data quality.** Checks the dataset itself: schema and types, missing values (including blank strings and empty lists), whether status columns match the actual text and PDFs, five kinds of duplicates, and malformed values like bad IDs or affiliations inside author names. It writes a per-paper flag file and can also check the preprocessed output.

**Abdullah: extraction quality.** Measures signs of extraction damage in the raw text: HTML tags, picture placeholders, replacement characters, repeated header lines, and math and table density. It then re-measures them after preprocessing, and sets up a manual review that compares extracted text against the original PDFs. It also records the commit and a hash of the dataset, so a run can be reproduced exactly.

## where they agree

- **The pipeline works.** All three found no missing values, no duplicates, and no status contradictions in their samples. Chythra's 160 papers had a 100% end-to-end success rate.
- **The raw text needs cleaning before chunking.** Abdullah found HTML tags and picture placeholders in all 20 of his papers, and replacement characters in 10. Chythra found running headers and page numbers (about 22 lines per paper). Her preprocessing handles all of these.

## where they overlap

Abdullah's and Alena's notebooks both check structure and types, missing values, duplicates, and status vs. file contradictions, using the same approach (counting blanks and empty lists as missing, generating findings from the numbers). We should keep these checks in one place rather than maintain two versions.

`prepare_for_chunking.py` on Abdullah's branch and `select_sections` in Alena's chunker (`src/chunking`) both pick which sections go into chunking. They mostly agree, with three differences to settle:

| | `prepare_for_chunking.py` | `src/chunking` |
|---|---|---|
| paper id | versioned (`2609.38178v1`) | base id (`2609.38178`), so a new version replaces the old |
| abstract | uses the abstract section from the PDF if there is one, otherwise `abstract_clean` | always uses `abstract_clean`, which is cleaner |
| short sections | kept as their own rows | merged into the next section if under 30 tokens |

## what's still missing

- **A shared dataset.** Each EDA ran on a different pull (160, 50, and 20 papers from different days), so the numbers can't be compared directly. Once Chythra's branch is merged, we should all rerun on the same published release.
- **The manual PDF review.** Abdullah's notebook selects 6 papers to compare against their PDFs, but none have been reviewed yet. This is the only check that confirms the extracted text matches what's actually in the paper.
- **Preprocessing results for Abdullah's signals.** His "after preprocessing" section hasn't run yet. It would confirm that Chythra's cleaning removes the damage he measured.
- **A longer time window.** All three samples cover a few days at most. Version duplicates only appear after papers get revised, so that check hasn't really been tested.

## suggested next steps

1. Merge `chythras-eda` so everyone works from the same preprocessing and published dataset.
2. Rerun all three notebooks on that dataset and update the numbers.
3. Finish Abdullah's manual review of the 6 selected papers.
4. Pick one set of data quality checks and one section-selection step, and remove the duplicate.
