# Research Insight Agent: AI Research for Business Decisions

**Break Through Tech AI Studio · KPMG Challenge Project · Team 1J · Fall 2026**

Consultants get asked about AI all the time, but the answers are buried in hundreds of new research papers every week, written for scientists. The Research Insight Agent reads that research for them. A consultant asks a business question, and the agent finds the most relevant recent papers, summarizes what they found, and writes a short business brief with citations, an evidence rating and caveats, so every claim can be checked.

---

## 👥 Team Members

| Name | GitHub Handle | Contribution |
|---|---|---|
| Jenna Hunte | @jehunte | Break Through Tech Coach |
| Grace Zhou | @grcezh8 | LanceDB vector store, corpus workflow, token compression, market research feature |
| Chythra Malapati | @ | Automated paper download, end-to-end pipeline, web app, client projects |
| Thania Manik | @ | Combined retriever, retrieval evaluation and relevance labels, industry applications |
| Lakshmee Harivanam | @ | Summarization prompt, summary evaluation, POC Starter |
| Alena | @ | Chunking, embedding model comparison, EDA |
| Olivia | @oliiviiak | Hybrid search, deduplication and reranking, citations, comments |
| Liva | @ | RAG pipeline, workflow testing |
| Abdullah Al Muthasim | @ | Query rewriter and retrieval benchmark, gold-standard briefs, failure analysis, storage for adaptations, pilot plans and comments |

*Team: please check your row and fill in your GitHub handle.*

---

## 🎯 Project Highlights

- Built a **retrieval-augmented generation (RAG) agent** that answers business questions from recent arXiv AI research, with every claim cited to a paper.
- Indexed **6,500+ recent AI papers**, refreshed automatically three times a week.
- Chose the **LanceDB combined retriever** after comparing three search methods: it ranked every expected paper first, was about **9× faster** than our first version and used an **8× smaller** index (`evaluation/results/retriever_comparison.md`).
- Split the answer into **two steps**, a research summary and then a business brief, so the facts and the business interpretation can be checked separately.
- Built a **consultant web app**: briefs for different audiences, a Library, client projects, a review queue, industry applications, a pilot plan builder, and a market scan from SEC filings.
- Tested the system with **benchmark questions, human-written gold-standard briefs, a failure-case catalog and automatic citation checks**.

---

## 🧭 How It Works

```
Business question
  -> Search 6,500+ arXiv papers (keyword + meaning search, top 5 papers)
  -> Step 1: research summary (Objective, Methodology, Key Findings, Limitations), cited by paper ID
  -> Citation check: every cited paper must have been retrieved
  -> Step 2: business brief (Bottom Line, Why It Matters, What To Do, Evidence Strength, Caveat, Sources)
  -> Saved to the Library, reviewed in the Review Queue
```

**What the web app can do**

- **Ask a question** and choose the audience: Executive, Risk & compliance, or Technical lead.
- **Library:** every saved brief, with filters for audience, status, evidence level, date and project. Opening a saved brief costs no AI calls.
- **Projects:** organize briefs by client; briefs asked inside a project are tailored to that client.
- **Review Queue:** every brief starts as "Awaiting review" until a reviewer approves it or requests changes.
- **Follow-up questions** and **rewrite for another audience**, using the saved summary.
- **Industry applications:** how the research could apply in a chosen industry.
- **POC Starter:** pick a use case, answer a few questions, and get an editable pilot checklist that is saved.
- **Market scan:** what public companies say in their SEC filings about the technology, and where that points to growth.

---

## 👩🏽‍💻 Setup and Installation

You need **Python 3.12 or newer** and a free **NVIDIA API key** from [build.nvidia.com](https://build.nvidia.com).

**1. Get the code and install packages**

```bash
git clone https://github.com/Break-Through-Tech/KPMG-1J-ai-research-intelligence-agent-for-business-insight-translation.git
cd KPMG-1J-ai-research-intelligence-agent-for-business-insight-translation
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Download the papers and the search index**

```bash
mkdir -p data
curl -L -o data/papers_clean.parquet \
  https://github.com/Break-Through-Tech/KPMG-1J-ai-research-intelligence-agent-for-business-insight-translation/releases/latest/download/papers_clean.parquet
```

If the same release lists `index.tar.gz`, download it and unpack it with `tar -xzf index.tar.gz -C data`. Otherwise build the index yourself (one time, about 20 minutes); see `src/pipeline/README.md`, Setup. You should end up with `data/papers_clean.parquet` and `data/index/`.

**3. Set your API key**

```bash
export NVIDIA_API_KEY="your-key-here"
```

On a Mac, copy the key and run `export NVIDIA_API_KEY="$(pbpaste)"` so it never appears on screen. You can also put `NVIDIA_API_KEY=...` in a `.env` file in the repo root (it is git-ignored). For the Market tab, also set `SEC_USER_AGENT` (see `src/app/README.md`).

**4. Run the web app**

```bash
python -m src.app --provider nvidia
```

Wait for `Uvicorn running on http://127.0.0.1:8000`, then open **http://127.0.0.1:8000**. Press **Control + C** to stop. In a new terminal window, run `source .venv/bin/activate` and set the key again.

**Run the tests** (no API key needed):

```bash
python -m pytest -q
```

**Ask one question from the command line instead:**

```bash
python -m src.pipeline.cli "Can an AI model's step-by-step reasoning be trusted?" --provider nvidia
```

---

## 🏗️ Project Overview

This project was completed for the **Break Through Tech AI Studio** with **KPMG** as our Challenge Advisor company.

**The problem:** AI research moves faster than anyone can read. Consultants need answers grounded in the latest evidence, but papers are long and technical, and clients need plain business language.

**Our goal:** an agent that turns the newest AI research into short, trustworthy business briefs, with sources that can be checked, a clear evidence rating, and a human review step before anything reaches a client.

---

## 📊 Data Exploration

**Data:** recent AI research papers from [arXiv](https://arxiv.org), category `cs.AI` (papers often cross-list in Language, Machine learning, Vision, Security, Robotics and more). For each paper we keep the title, abstract, date, category and full text.

**Preparation**

1. **Ingestion** (`src/ingestion`): a GitHub workflow downloads new papers every Monday, Wednesday and Friday, extracts the PDF text and publishes the dataset as a GitHub release.
2. **Preprocessing** (`src/preprocessing`): removes boilerplate, normalizes text and labels sections (results, limitations, conclusion...).
3. **Chunking** (`src/chunking`): splits each paper into small passages by section.
4. **Embedding and indexing** (`src/vectorizing`, `src/indexing`): turns each chunk into a vector with `BAAI/bge-small-en-v1.5` and stores it in LanceDB.

EDA notebooks are in `notebooks/` (see `notebooks/README_eda_comparison.md`).

---

## 🧠 Model Development

**Search.** We compared three retrievers on the same benchmark (`evaluation/compare_retrievers.py`). The final choice, `lance-combined`, combines a title/abstract search with a hybrid (keyword + vector) chunk search and merges them with reciprocal rank fusion. It removes duplicate papers and adds each paper's most relevant results and limitations passages.

**Query rewriting.** We built a rewriter that turns business-style questions into research-style search queries (`src/rag/query_rewriter.py`) and compared search results with and without it on the benchmark (`src/evaluation/run_retrieval_benchmark.py`). The web app currently searches with the question as typed.

**Language model.** NVIDIA Nemotron Ultra (`nvidia/nemotron-3-ultra-550b-a55b`) writes the summary and the brief. The app also supports Groq and Gemini with `--provider`.

**Prompts.** Two-step prompting: a few-shot research summary that may only use the retrieved papers (`src/summarization`), then a business brief that may only use that summary (`src/translation`).

**Token usage.** An optional compressor (`src/pipeline/compress.py`, `--compress`) shortens the paper text. It cut the input by about 4–7% without accuracy problems, but answers got longer and slower, so it is off by default (see `src/pipeline/README.md`).

---

## 📈 Results & Key Findings

| Retriever | Expected paper in top 5 | Mean reciprocal rank | Precision (labelled results) | Seconds per query |
|---|---|---|---|---|
| chroma-combined (first version) | 8/12 | 0.542 | 0.846 | 0.295 |
| lance | 8/12 | 0.431 | 0.806 | 0.036 |
| **lance-combined (final)** | **8/12** | **0.667** | **0.897** | **0.034** |

- The ranking method mattered more than the database: adding the title/abstract ranking improved results the most.
- The two missed questions look like gaps in our answer key: the papers ranked above the expected ones were on-topic.
- The failure-case catalog (`evaluation/results/task8_failure_cases.md`) documents irrelevant retrievals, sensitivity to question wording and noisy chunks, with causes and fixes.
- Compressing the input saved few tokens and made answers longer (`evaluation/results/context_compression_llm.csv`).

See `evaluation/README.md` for every result file.

---

## 📁 Repository Guide

| Folder | What it does |
|---|---|
| `src/ingestion` | Downloads new arXiv papers and extracts their text |
| `src/preprocessing` | Cleans text and labels paper sections |
| `src/chunking` | Splits papers into passages |
| `src/vectorizing`, `src/indexing` | Embeds passages and builds the LanceDB index |
| `src/rag` | Search: retrievers and the query rewriter |
| `src/summarization` | Research summary prompt |
| `src/translation` | Business brief, follow-up, industry, POC and market prompts |
| `src/pipeline` | Runs search → summary → brief, plus the compressor and LLM client |
| `src/market` | SEC EDGAR client and market scan logic |
| `src/app` | The consultant web app and saved data |
| `src/evaluation` | Gold-standard briefs and the retrieval benchmark script |
| `evaluation` | Benchmark questions, comparison scripts and results |
| `notebooks` | EDA notebooks |
| `tests` | Automated tests (`python -m pytest -q`) |

Each folder under `src/` has its own README with details.

---

## 🚀 Next Steps

- Save AI-generated industry use cases, constraints and considerations automatically.
- Add a button that turns briefs into notes or slides for leadership.
- Show the reasoning and citations behind each pilot checklist step.
- Label the remaining search results to make the evaluation numbers more reliable.
- Keep testing ways to lower cost per question, now focusing on answer length.

---

## 📝 License

This project is licensed under the MIT License. *(Team: confirm this license with our Challenge Advisor before the final submission.)*

---

## 🙏 Acknowledgements

Thank you to **KPMG** for the challenge and guidance, to our AI Studio coach **Jenna Hunte**, and to **Break Through Tech**. Research papers come from [arXiv](https://arxiv.org); company filings from [SEC EDGAR](https://www.sec.gov/edgar).
