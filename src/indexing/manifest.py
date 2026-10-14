#records how the index was built so vectors made with different settings don't get mixed
#vectors from two different models or two chunk sizes can't be compared

import json
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_NAME = "index_manifest.json"

#settings that change what a stored vector means (so if any differ the index must be rebuilt)
BUILD_KEYS = ("model_name", "embedding_dim", "metric", "chunk_config")

#loads the manifest from the index directory
def load_manifest(index_dir) -> dict | None:
    path = Path(index_dir) / MANIFEST_NAME
    if not path.exists():
        return None
    return json.loads(path.read_text())

#saves the manifest 
def save_manifest(index_dir, manifest: dict) -> dict:
    manifest = {**manifest, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    Path(index_dir).mkdir(parents=True, exist_ok=True)
    (Path(index_dir)/MANIFEST_NAME).write_text(json.dumps(manifest, indent = 2))
    return manifest

def check_compatible(saved: dict, current: dict):
    mismatched = [k for k in BUILD_KEYS if saved.get(k) != current.get(k)]
    if mismatched: 
        details = "; ".join(f"{k}: index has {saved.get(k)!r}, now {current.get(k)!r}" for k in mismatched)
        raise ValueError(f"index was built with different settings ({details}). Rebuild it with --rebuild")