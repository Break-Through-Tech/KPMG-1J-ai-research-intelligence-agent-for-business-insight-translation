#!/usr/bin/env bash
# brings the dataset up to date with new arXiv papers, then reruns preprocessing
# arXiv announces new papers every weekday, so running this about once a week is enough
#
# usage (from anywhere):
#   ./scripts/pull_recent_papers.sh                   # pull everything new since the last run
#   ./scripts/pull_recent_papers.sh --delete-pdfs     # also delete PDFs that were fully ingested (saves disk space)
#   ./scripts/pull_recent_papers.sh --snapshot        # also save a dated copy of the clean dataset for evaluation
#
# settings can be overridden with env vars, e.g. MAX_RESULTS=50 ./scripts/pull_recent_papers.sh

set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
DATA_DIR="${DATA_DIR:-data}"
CATEGORY="${CATEGORY:-cat:cs.AI}"
MAX_RESULTS="${MAX_RESULTS:-2000}"   # safety cap, the --since date is what actually limits the pull
OVERLAP_DAYS="${OVERLAP_DAYS:-2}"    # re-check a couple of days back for late announcements, duplicates are skipped
FIRST_RUN_DAYS="${FIRST_RUN_DAYS:-7}" # how far back to go when there is no dataset yet

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

# start from the newest paper we already have, minus the overlap
SINCE=$("$PYTHON" -c "
import os, datetime as dt, pandas as pd
if os.path.exists('$DATASET'):
    newest = pd.to_datetime(pd.read_parquet('$DATASET', columns=['published'])['published']).max().date()
    print(newest - dt.timedelta(days=$OVERLAP_DAYS))
else:
    print(dt.date.today() - dt.timedelta(days=$FIRST_RUN_DAYS))")

BEFORE=$(count_papers)
echo "dataset has $BEFORE papers, fetching $CATEGORY papers published since $SINCE"

"$PYTHON" -m src.ingestion.cli \
    --category "$CATEGORY" \
    --max-results "$MAX_RESULTS" \
    --since "$SINCE" \
    --raw-pdf-dir "$RAW_PDF_DIR" \
    --dataset-path "$DATASET"

AFTER=$(count_papers)
echo "added $((AFTER - BEFORE)) new papers ($AFTER total)"
# lets the GitHub workflow skip publishing a release when nothing changed
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "added=$((AFTER - BEFORE))" >> "$GITHUB_OUTPUT"
    echo "total=$AFTER" >> "$GITHUB_OUTPUT"
fi

# if the window holds as many papers as the cap, the fetch probably stopped before reaching $SINCE
"$PYTHON" -c "
import pandas as pd
df = pd.read_parquet('$DATASET', columns=['published'])
in_window = (pd.to_datetime(df['published']).dt.date >= pd.Timestamp('$SINCE').date()).sum()
if in_window >= $MAX_RESULTS:
    print('WARNING: hit MAX_RESULTS=$MAX_RESULTS, some papers since $SINCE may be missing. rerun with a higher MAX_RESULTS')"

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
