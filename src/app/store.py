# Saves each answered question as one JSON file, so reopening, reviewing
# or sharing a brief never calls the LLM again.

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

ID_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


class BriefStore:

    def __init__(self, directory="data/ui_briefs"):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def new_id(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{secrets.token_hex(3)}"

    def _path(self, brief_id):
        # Only accept ids this store made, so a URL can't point outside the folder
        if not ID_PATTERN.match(str(brief_id)):
            raise KeyError(brief_id)
        return self.directory / f"{brief_id}.json"

    def save(self, record):
        path = self._path(record["id"])
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)
        return record

    def load(self, brief_id):
        path = self._path(brief_id)
        if not path.exists():
            raise KeyError(brief_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self, limit=20):
        records = []

        for path in sorted(self.directory.glob("*.json"), reverse=True)[:limit]:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            entry = record.get("briefs", {}).get(record.get("audience")) or {}

            records.append({
                "id": record["id"],
                "query": record["query"],
                "audience": record.get("audience"),
                "status": record.get("status", "draft"),
                "created_at": record.get("created_at"),
                "papers": len(record.get("sources", [])),
                "evidence": entry.get("checks", {}).get("evidence", {}).get("level"),
            })

        return records
