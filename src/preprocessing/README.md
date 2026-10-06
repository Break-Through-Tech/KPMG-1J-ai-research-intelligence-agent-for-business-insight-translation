# preprocessing

## what I added (Task #4: data preprocessing)

Grace's ingestion pipeline already gets us from arXiv to metadata, PDFs, and the raw markdown text for each paper. When I looked through the text, it was still a bit messy, so I handled it with the EDA changes here!

**new files**
- `src/preprocessing/metadata.py`: removes duplicate versions of the same paper, adds date fields, and cleans up abstracts
- `src/preprocessing/normalize.py`: fixes odd characters and strips leftover formatting
- `src/preprocessing/boilerplate.py`: removes page headers, footers, and page numbers
- `src/preprocessing/sections.py`: splits each paper into labeled sections and builds a main-text version without the references and appendix
- `src/preprocessing/quality.py`: flags papers that came out broken or nearly empty
- `src/preprocessing/pipeline.py` and `cli.py`: run everything with one command
- `tests/test_preprocessing.py`: unit tests for each step
- `scripts/pull_recent_papers.sh`: pulls new papers since our newest one and reruns preprocessing
- `.github/workflows/update-corpus.yml`: runs that script Mon/Wed/Fri at midnight and publishes the data as a GitHub release, so anyone can load it without setting anything up
- `src/ingestion/check_coverage.py`: compares our dataset with arXiv's own list of papers so we know nothing was missed

**edited files**
- `notebooks/eda_corpus.ipynb`: added a before/after preprocessing section and filled in the findings table
- `requirements.txt`: added matplotlib and pytest
- `.gitignore`: ignores the new output files

**how it follows through on the EDA**

The EDA notebook ended with a few open decisions, and this is where they got made:
- *Drop references before indexing?* Yes. References and appendices were close to half of each paper, so the main text leaves them out. They're still saved separately in case we need them later.
- *Add a minimum-length check?* Yes. Any paper whose main text comes out under about 5,000 characters gets flagged, which catches PDFs that "extracted" but came back nearly empty.
- *Heading-based or fixed-size chunking?* Every paper had usable headings, so the cleaned text keeps them and each section is labeled with its type. That makes it easy for the next step to chunk by section and cite which part of a paper an answer came from.

---

This folder turns the raw ingestion output (`data/papers.parquet`) into a clean, section-structured dataset (`data/papers_clean.parquet`) that the chunking / embedding / retrieval steps build on. It is the data preparation step between ingestion and the RAG pipeline.

It never modifies the raw `extracted_text`. Cleaning rules can be changed and rerun in seconds without downloading or re-extracting any PDFs.

```
arXiv API ──► src/ingestion ──► data/papers.parquet ──► src/preprocessing ──► data/papers_clean.parquet ──► chunking / embeddings
                                 (raw markdown text)                           (body_text + sections + quality flags)
```

## how to run

from the project root:

```bash
.venv/bin/python -m src.preprocessing.cli
.venv/bin/python -m pytest tests/        # unit tests
```

| argument | default | description |
|---|---|---|
| `--input` | `data/papers.parquet` | parquet written by the ingestion pipeline |
| `--output` | `data/papers_clean.parquet` | cleaned dataset |
| `--report` | `data/preprocess_report.json` | corpus level summary (counts, quality issues, unusable papers) |

`notebooks/eda_corpus.ipynb` §10 loads both outputs and plots what preprocessing changed.

## getting the data

You don't need to run anything or make any accounts. The latest cleaned dataset is published as a GitHub release, and you can load it straight into pandas:

```python
import pandas as pd

URL = "https://github.com/Break-Through-Tech/KPMG-1J-ai-research-intelligence-agent-for-business-insight-translation/releases/latest/download/papers_clean.parquet"
df = pd.read_parquet(URL)
df = df[df["is_usable"]]   # only papers that passed the quality checks
```

Every update is its own release (named like `data-2026-10-05-0400`) on the repo's **Releases** page. For evaluation, pin one specific release instead of `latest` so scores stay comparable between weeks, by swapping `latest/download` for `download/<release name>` in the URL.

## keeping the corpus up to date

This happens automatically. The GitHub workflow in `.github/workflows/update-corpus.yml` runs every **Monday, Wednesday and Friday at 12:00 AM Eastern**, and anyone with write access can also start it from the repo's **Actions** tab → **Update arXiv corpus** → **Run workflow** (set "max papers" to something like 20 for a quick test).

Each run picks up **every** cs.AI paper (cross-lists included) published since the newest one we have:

| run | what it picks up | roughly |
|---|---|---|
| Monday | everything since Friday's run (includes the weekend) | 550–800 papers, ~1–1.5 hrs |
| Wednesday | everything since Monday's run | ~550 papers, ~1 hr |
| Friday | everything since Wednesday's run | ~550 papers, ~1 hr |

**How it makes sure no papers get lost**
- New papers are processed **oldest first** and **saved every 100 papers**, so if a run crashes or runs long, everything done so far is kept and published.
- Each run handles up to 1,500 papers (about 3.3 hours). If there are more, the rest is a **backlog** that the next run starts on, exactly where this one stopped, so there are no gaps.
- Papers whose PDF failed to download or extract are retried on the next runs (for up to 14 days).
- PDFs aren't stored anywhere, since the text is already saved and every paper links back to arXiv.

**How we know it's working**
- Every run gets a ✅ or ❌ on the **Actions** tab, and GitHub emails the person who set up the workflow when a scheduled run fails. The unit tests run first, so broken code fails before it can touch the data.
- Every run that adds papers publishes a release whose notes say how many were added, the new total, the date range, and any backlog. The end date should keep moving forward.
- The last step asks arXiv for its own list of every cs.AI paper in the window the run covered and compares it with our dataset. If anything is missing, it lists the IDs and turns the run ❌.

GitHub schedules use UTC, so when daylight saving time ends (Nov 1) the cron line in the workflow needs to change from `"0 4 * * 1,3,5"` to `"0 5 * * 1,3,5"` to stay at midnight Eastern.

**Running it locally** (for testing or development):

```bash
./scripts/pull_recent_papers.sh                       # updates your local data/ folder
MAX_PAPERS=20 ./scripts/pull_recent_papers.sh         # small test run
./scripts/pull_recent_papers.sh --delete-pdfs         # also deletes PDFs once their text is saved
./scripts/pull_recent_papers.sh --snapshot            # also saves a dated copy to data/snapshots/
python -m src.ingestion.check_coverage --since 2026-10-05   # run the "did we miss anything?" check on its own
```

Local runs don't publish anything; only the workflow does, so there's always one shared copy.

Note for the embedding step: after an update, only embed papers whose `base_id` isn't already in the index, instead of rebuilding everything.

## why preprocessing is needed

EDA on the `pymupdf4llm` markdown found these problems. Each step below fixes one of them.

| problem found in the raw text | example | step that fixes it |
|---|---|---|
| running headers/footers repeated on every page | `Preprint` ×25 in one paper, `Manuscript submitted to ACM` ×20, `4 O. Nepal et al.` | boilerplate |
| bare page number lines | up to 43 per paper | boilerplate |
| picture blocks / placeholders | `[Picture Omitted]`, `<!-- Start of picture text -->` | normalize |
| markdown/HTML formatting noise | `**bold**` headings, `<br>` (up to 324 per paper), `<sup>1</sup>` footnote marks | normalize |
| italic spans splitting numbers | `2 _._ 23 _×_` instead of `2.23×` | normalize |
| unicode noise | `𝑝` (math italic), `ﬁ` ligatures, `�` replacement chars, zero width spaces | normalize |
| references are ~14% of the cleaned text and match almost any query lexically | `## References` followed by hundreds of citations | sections |
| appendices (~32% of the text: prompt templates, hyperparameter tables) and author/affiliation blocks | author emails, `B.1 Hyperparameter Settings` | sections |
| same paper can be stored twice (v1 and v2), ingestion dedupes on the versioned id | `2609.26780v1`, `2609.26780v2` | metadata |
| ingestion marks a paper `complete` even when extraction returned almost nothing | scanned or image only PDF | quality |

## pipeline steps

1. **metadata** (`metadata.py`)
   - splits `arxiv_id` into `base_id` and `version`, keeps one row per `base_id`, preferring a completely ingested row and then the newest version
   - adds `published_date` and `year_month` (for time filtering and trend questions), and `author_count`
   - converts `authors` and `categories` to plain lists and tidies the title's whitespace
   - `abstract_clean`: NFKC unicode, simple LaTeX commands unwrapped (`\textit{x}` → `x`), whitespace collapsed. `$…$` math is kept
2. **normalize** (`normalize.py`), character level
   - NFKC unicode normalization, then removes control characters, zero width characters, soft hyphens and `�`
   - removes picture blocks and `[Picture Omitted]` placeholders. Figure captions (`Figure 1: …`) are kept because they often state results
   - `<br>` → space, footnote `<sup>` markers dropped, exponents kept as `x^2`, `<sub>` → `_`
   - strips `**bold**` / `_italic_` markers and rejoins numbers that italics split (`2 _._ 23` → `2.23`)
   - collapses repeated spaces and 3+ blank lines
3. **boilerplate** (`boilerplate.py`), line level
   - drops bare page number lines (`12`, `Page 3 of 10`)
   - drops running heads: any short line (<80 chars) that repeats ≥3 times across ≥30% of the document, ignoring a leading/trailing page number. Nothing is hard coded, so it adapts to each paper's template
   - never touches table rows, list items, code blocks or headings, except headings whose text is already a detected running head
4. **sections** (`sections.py`)
   - splits on markdown headings (plus bold `**References**` lines that were not rendered as headings)
   - strips numbering from each heading (`3.2`, `B.1`, `IV`) and classifies it with keywords as `abstract`, `introduction`, `related_work`, `method`, `experiments`, `results`, `discussion`, `limitations`, `conclusion`, `acknowledgments`, `references`, `appendix`, `back_matter` or `other`
   - uses position to correct the guess: everything before the abstract/introduction is `front_matter`, everything after References is `appendix`, lettered sections after the conclusion are `appendix`, and sub-sections inherit their parent's type (`4.1` under `4 Results` → `results`)
   - builds `body_text` from every section except `front_matter`, `acknowledgments`, `back_matter` (CRediT/funding/data availability/AI-use statements), `references` and `appendix`. Headings stay inline as `## 3.1 Heading`, so the chunker can split on section boundaries and cite a section
5. **quality** (`quality.py`)
   - computes the per-paper numbers and flags in the table below
   - `is_usable` is False if any blocking issue is present

## quality flags

| issue | blocking | rule |
|---|---|---|
| `ingestion_not_complete` | yes | ingestion status is `partial` or `failed` |
| `no_text` | yes | nothing was extracted |
| `short_body` | yes | `body_text` < 5,000 chars. Real papers are 20k+, so this is a broken or near empty extraction |
| `high_replacement_chars` | yes | > 1% of raw characters are `�` (broken font encoding) |
| `no_headings` | no | no markdown headings, so the paper can't be split into sections and needs fixed size chunking |
| `no_references_found` | no | no References heading, so the bibliography may still be inside `body_text` |
| `missing_abstract` | no | arXiv returned no abstract |

Downstream steps should index only `is_usable == True` rows.

## output schema (`data/papers_clean.parquet`)

one row per paper (unique `base_id`)

| column | description |
|---|---|
| `arxiv_id`, `base_id`, `version` | `2609.26780v1`, `2609.26780`, `1` |
| `title`, `abstract`, `abstract_clean` | original abstract kept for display, clean one for embedding |
| `authors`, `author_count`, `primary_category`, `categories` | lists are plain Python lists |
| `published`, `published_date`, `year_month`, `updated` | UTC timestamps plus derived date fields |
| `pdf_url`, `abs_url` | for citations |
| `ingestion_status` | carried over from ingestion |
| `body_text` | retrieval ready main text with markdown headings |
| `sections` | list of `{idx, level, number, heading, section_type, text, char_count}` covering the whole paper, including front matter, references and appendix, so later steps can opt back in (e.g. index appendices) |
| `n_artifact_lines_removed` | running heads + page numbers removed |
| `raw_char_count`, `body_char_count`, `body_word_count`, `est_tokens` | `est_tokens` ≈ body chars / 4 |
| `n_sections`, `has_references`, `has_appendix`, `replacement_char_ratio` | structure/quality numbers |
| `quality_issues`, `is_usable` | see above |

`extracted_text` and `pdf_path` are not copied over. Join back to `data/papers.parquet` on `arxiv_id` if you need them.

## results on the current corpus

160 newest cs.AI submissions (published 2026-09-22 → 2026-09-25), run on 2026-09-28. Numbers come from `data/preprocess_report.json` and `notebooks/eda_corpus.ipynb`.

| metric | value |
|---|---|
| papers in / out | 160 / 160 (0 duplicate versions) |
| usable for indexing (`is_usable`) | 160 (100%) |
| running head / page number lines removed | 3,526 (~22 per paper) |
| References heading detected | 99.4% (1 miss: `2609.31070v1`, flagged `no_references_found`) |
| papers with an appendix | 66.9% |
| papers with no usable headings | 0 |
| raw chars → `body_text` chars | 11.46M → 5.79M (51% kept) |
| median paper: raw → body | 63.5k → 32.9k chars (~8.2k tokens) |
| shortest `body_text` | 9.3k chars (`2609.31078v1`, a short system demo paper, checked by hand) |
| total body tokens | ~1.45M → ~2.1k chunks at 800 tokens / 15% overlap |

share of cleaned text by section type: appendix 31.9%, references 13.6%, experiments 9.7%, other 9.3%, method 8.4%, introduction 7.5%, results 7.1%, related work 4.5%, discussion 2.0%, conclusion 1.8%, abstract 1.6%, front matter 1.0%, limitations 0.9%, back matter 0.4%, acknowledgments 0.3%.

**what this means for the RAG step**
- index `body_text` of `is_usable` rows. Dropping references and appendices roughly halves the index size and removes the sections most likely to produce false lexical matches.
- headings are present in every paper, so heading aware chunking (split on `##`/`###`, then fixed size inside long sections) is viable, and each chunk can carry `section_type` + heading for citations.
- `abstract_clean` is a good "tier 1" document per paper for a fast baseline retriever or for re-ranking.

## known limitations

- **math and tables are approximations.** `pymupdf4llm` has no LaTeX source, so equations come out as flattened unicode (`p < 0.05`, `x^2`) and complex tables can lose alignment. Good enough for retrieval and summarisation, not for reproducing formulas.
- **markdown bold is stripped everywhere**, including inside code blocks (`**kwargs` → `kwargs`). Harmless for retrieval.
- **section typing is keyword based.** Unusual headings ("The Proximity Trap") are typed `other` and stay in `body_text`. Journal layouts that put Methods after References (e.g. Nature style) lose those sections to `appendix`. They are still in `sections` if needed.
- **running head detection needs ≥3 repeats**, so very short papers (1–2 pages) keep their headers.
- **no OCR.** Scanned or image only PDFs are flagged `short_body` and excluded, not recovered.
- **English only / no language detection**, fine for arXiv cs.AI but not verified.
- **the corpus is a recency slice** (the newest N cs.AI submissions), not a representative sample of the field.
