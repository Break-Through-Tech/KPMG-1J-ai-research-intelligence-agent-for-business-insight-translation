#!/usr/bin/env bash
# downloads the newest published dataset and search index (the "latest" GitHub release
# made by .github/workflows/update-corpus.yml) so the web UI searches the newest papers
#
# usage (from anywhere):
#   ./scripts/get_latest_data.sh      # then restart: python -m src.app
#
# it writes the files the app reads by default:
#   data/papers_clean.parquet   (--papers)
#   data/index/                 (--index-dir)
# about 1.5 GB to download. Your current files are kept until the new ones are complete,
# and the previous index is kept once as data/index.previous in case you need to go back.
# saved briefs, projects and presentations (data/ui_*) are never touched.

set -euo pipefail
cd "$(dirname "$0")/.."

REPO="${REPO:-Break-Through-Tech/KPMG-1J-ai-research-intelligence-agent-for-business-insight-translation}"
DATA_DIR="${DATA_DIR:-data}"
URL="https://github.com/$REPO/releases/latest/download"
TMP="$DATA_DIR/.download"

mkdir -p "$TMP"

echo "Latest release:"
if command -v gh >/dev/null 2>&1; then
    gh release view --repo "$REPO" --json tagName,body -q '.tagName + "\n" + .body' | head -8 || true
else
    echo "  (install the gh CLI to see the release notes)"
fi
echo

fetch() {
    echo "Downloading $1..."
    curl --fail --location --retry 3 --progress-bar -o "$TMP/$1" "$URL/$1"
}

fetch papers_clean.parquet
fetch index.tar.gz

echo "Unpacking the search index..."
mkdir -p "$TMP/unpacked"
tar -xzf "$TMP/index.tar.gz" -C "$TMP/unpacked"
if [ ! -f "$TMP/unpacked/index/index_manifest.json" ]; then
    echo "The downloaded index has no index_manifest.json, so nothing was replaced." >&2
    exit 1
fi

# everything downloaded fine, so swap the new files in
mv "$TMP/papers_clean.parquet" "$DATA_DIR/papers_clean.parquet"
if [ -d "$DATA_DIR/index" ]; then
    if [ -d "$DATA_DIR/index.previous" ]; then
        rm -r "$DATA_DIR/index.previous"
    fi
    mv "$DATA_DIR/index" "$DATA_DIR/index.previous"
fi
mv "$TMP/unpacked/index" "$DATA_DIR/index"
rm -r "$TMP"

PYTHON="${PYTHON:-.venv/bin/python}"
"$PYTHON" - "$DATA_DIR" <<'EOF'
import json, sys
import pandas as pd
data = sys.argv[1]
m = json.load(open(f"{data}/index/index_manifest.json"))
papers = pd.read_parquet(f"{data}/papers_clean.parquet", columns=["published_date"])["published_date"]
print(f"Searchable: {m['n_papers']:,} papers, {m['date_range'][0]} to {m['date_range'][1]} "
      f"(index built {m.get('updated_at', '?')[:10]})")
print(f"Downloaded: {len(papers):,} papers, {papers.min()} to {papers.max()}")
if len(papers) > m["n_papers"]:
    print(f"{len(papers) - m['n_papers']:,} papers aren't in the search index yet; the next successful update run adds them.")
EOF
echo
echo "Done. Restart the app to use it: python -m src.app"
