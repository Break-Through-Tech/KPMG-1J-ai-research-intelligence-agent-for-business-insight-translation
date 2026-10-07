#!/usr/bin/env bash
# brings the dataset up to date with new arXiv papers, then reruns preprocessing and checks nothing was missed
# the GitHub workflow runs this Mon/Wed/Fri, it can also be run locally
#
# usage (from anywhere):
#   ./scripts/pull_recent_papers.sh                   # pull everything new since the newest paper we have
#   ./scripts/pull_recent_papers.sh --delete-pdfs     # also delete PDFs that were fully ingested (saves disk space)
#   ./scripts/pull_recent_papers.sh --snapshot        # also save a dated copy of the clean dataset for evaluation
#
# settings can be overridden with env vars, e.g. MAX_PAPERS=20 ./scripts/pull_recent_papers.sh
#
# how it avoids losing papers:
#   - new papers are processed oldest first and saved every BATCH_SIZE papers, so a crash or timeout keeps the work done so far
#   - at most MAX_PAPERS are processed per run, the rest (the backlog) is picked up by the next run with no gaps
#   - papers whose PDF failed in the last RETRY_DAYS days are retried
#   - at the end, the coverage check compares our dataset against arXiv's own list of papers

set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
DATA_DIR="${DATA_DIR:-data}"
CATEGORY="${CATEGORY:-cat:cs.AI}"
MAX_PAPERS="${MAX_PAPERS:-1000}"      # new papers per run (~13.5s each, so 1000 is ~3.75h, under the workflow's 4.5h step limit)
BATCH_SIZE="${BATCH_SIZE:-100}"       # save progress every this many papers
MAX_RESULTS="${MAX_RESULTS:-20000}"   # safety cap on metadata records fetched from the arXiv API
OVERLAP_DAYS="${OVERLAP_DAYS:-2}"     # re-check a couple of days back for late announcements, duplicates are skipped
RETRY_DAYS="${RETRY_DAYS:-14}"        # retry failed PDFs from up to this many days ago
FIRST_RUN_DAYS="${FIRST_RUN_DAYS:-7}" # how far back to go when there is no dataset yet
CHECK_STRICT="${CHECK_STRICT:-false}" # true = fail (exit 1) if the coverage check finds missing papers
RUN_CHECK="${RUN_CHECK:-true}"        # the GitHub workflow runs the check itself, after publishing
INGEST_ATTEMPTS="${INGEST_ATTEMPTS:-3}" # retry ingestion this many times if it fails (e.g. the arXiv API is down)
RETRY_WAIT="${RETRY_WAIT:-300}"       # seconds to wait between attempts

DELETE_PDFS=false
SNAPSHOT=false
for arg in "$@"; do
    case "$arg" in
        --delete-pdfs) DELETE_PDFS=true ;;
        --snapshot) SNAPSHOT=true ;;
        *) echo "unknown option: $arg" >&2; exit 1 ;;
    esac
done

DATASET="$DATA_DIR/papers.parquet"
CLEAN="$DATA_DIR/papers_clean.parquet"
REPORT="$DATA_DIR/preprocess_report.json"
RAW_PDF_DIR="$DATA_DIR/raw_pdfs"
mkdir -p "$DATA_DIR"

count_papers() {
    "$PYTHON" -c "
import os, pandas as pd
print(len(pd.read_parquet('$DATASET')) if os.path.exists('$DATASET') else 0)"
}

# start from the newest paper we have (minus the overlap), or earlier if a recent PDF failed and needs a retry
SINCE=$("$PYTHON" -c "
import os, datetime as dt, pandas as pd
if not os.path.exists('$DATASET'):
    print(dt.date.today() - dt.timedelta(days=$FIRST_RUN_DAYS))
else:
    df = pd.read_parquet('$DATASET', columns=['published', 'ingestion_status'])
    published = pd.to_datetime(df['published'], utc=True).dt.date
    # never reach back before our oldest paper, the dataset only promises completeness from there on
    since = max(published.max() - dt.timedelta(days=$OVERLAP_DAYS), published.min())
    retry_from = dt.date.today() - dt.timedelta(days=$RETRY_DAYS)
    failed = published[(df['ingestion_status'] != 'complete') & (published >= retry_from)]
    if len(failed):
        since = min(since, failed.min())
    print(since)")

BEFORE=$(count_papers)
echo "dataset has $BEFORE papers, fetching $CATEGORY papers published since $SINCE"
# recorded right away so the workflow's coverage check still knows the window even if ingestion times out
if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "since=$SINCE" >> "$GITHUB_OUTPUT"; fi

# retrying is safe: finished batches are already saved and already-ingested papers are skipped
INGEST_LOG="$(mktemp)"
for attempt in $(seq 1 "$INGEST_ATTEMPTS"); do
    if "$PYTHON" -m src.ingestion.cli \
        --category "$CATEGORY" \
        --max-results "$MAX_RESULTS" \
        --since "$SINCE" \
        --raw-pdf-dir "$RAW_PDF_DIR" \
        --dataset-path "$DATASET" \
        --max-papers "$MAX_PAPERS" \
        --batch-size "$BATCH_SIZE" | tee "$INGEST_LOG"; then
        break
    fi
    if [ "$attempt" -eq "$INGEST_ATTEMPTS" ]; then
        echo "ingestion failed $INGEST_ATTEMPTS times, giving up (everything saved so far is kept)" >&2
        rm -f "$INGEST_LOG"
        exit 1
    fi
    echo "ingestion failed (attempt $attempt/$INGEST_ATTEMPTS), often the arXiv API having trouble. retrying in ${RETRY_WAIT}s"
    sleep "$RETRY_WAIT"
done
BACKLOG=$(sed -n 's/.*, \([0-9]*\) more left for the next run.*/\1/p' "$INGEST_LOG" | tail -1)
BACKLOG="${BACKLOG:-0}"
rm -f "$INGEST_LOG"

AFTER=$(count_papers)
echo "added $((AFTER - BEFORE)) new papers ($AFTER total)"
if [ "$BACKLOG" -gt 0 ]; then
    echo "backlog: $BACKLOG papers left for the next run"
fi

"$PYTHON" -m src.preprocessing.cli --input "$DATASET" --output "$CLEAN" --report "$REPORT"

if $DELETE_PDFS; then
    # the text is already saved in the parquet, so PDFs of completely ingested papers aren't needed anymore
    "$PYTHON" -c "
import os, pandas as pd
df = pd.read_parquet('$DATASET', columns=['pdf_path', 'ingestion_status'])
paths = df.loc[df['ingestion_status'] == 'complete', 'pdf_path'].dropna()
removed = [p for p in paths if os.path.exists(p)]
for p in removed:
    os.remove(p)
print(f'deleted {len(removed)} ingested PDFs')"
fi

if $SNAPSHOT; then
    mkdir -p "$DATA_DIR/snapshots"
    SNAPSHOT_PATH="$DATA_DIR/snapshots/papers_clean_$(date +%Y-%m-%d).parquet"
    cp "$CLEAN" "$SNAPSHOT_PATH"
    echo "saved evaluation snapshot to $SNAPSHOT_PATH"
fi

# lets the GitHub workflow decide whether to publish a release
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    {
        echo "added=$((AFTER - BEFORE))"
        echo "total=$AFTER"
        echo "backlog=$BACKLOG"
    } >> "$GITHUB_OUTPUT"
fi

# compare against arXiv's own list of papers, last so the data above is always saved first
if [ "$RUN_CHECK" = "true" ]; then
    STRICT_FLAG=""
    if [ "$CHECK_STRICT" = "true" ]; then STRICT_FLAG="--strict"; fi
    "$PYTHON" -m src.ingestion.check_coverage --dataset "$DATASET" --category "$CATEGORY" --since "$SINCE" $STRICT_FLAG
fi
