# Saves each answered question as one JSON file, so reopening, reviewing
# or sharing a brief never calls the LLM again. Projects (client
# engagements) are saved the same way and list the briefs they hold.

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

ID_PATTERN = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


class JsonStore:
    """One JSON file per record, named by an id this store made."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def new_id(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{secrets.token_hex(3)}"

    def _path(self, record_id):
        # Only accept ids this store made, so a URL can't point outside the folder
        if not ID_PATTERN.match(str(record_id)):
            raise KeyError(record_id)
        return self.directory / f"{record_id}.json"

    def save(self, record):
        path = self._path(record["id"])
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)
        return record

    def load(self, record_id):
        path = self._path(record_id)
        if not path.exists():
            raise KeyError(record_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _all(self):
        """Every readable record, newest file name first."""
        for path in sorted(self.directory.glob("*.json"), reverse=True):
            try:
                yield json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue


class BriefStore(JsonStore):

    def __init__(self, directory="data/ui_briefs"):
        super().__init__(directory)

    @staticmethod
    def _summary(record):
        entry = record.get("briefs", {}).get(record.get("audience")) or {}
        return {
            "id": record["id"],
            "query": record["query"],
            "audience": record.get("audience"),
            "status": record.get("status", "draft"),
            "created_at": record.get("created_at"),
            "papers": len(record.get("sources", [])),
            "evidence": entry.get("checks", {}).get("evidence", {}).get("level"),
        }

    def list(self, limit=20):
        records = []
        for record in self._all():
            if len(records) >= limit:
                break
            records.append(self._summary(record))
        return records

    def summaries(self, ids):
        """List rows for these brief ids, in the given order; missing ones are skipped."""
        rows = []
        for brief_id in ids:
            try:
                rows.append(self._summary(self.load(brief_id)))
            except (KeyError, OSError, json.JSONDecodeError):
                continue
        return rows


class ProjectStore(JsonStore):

    def __init__(self, directory="data/ui_projects"):
        super().__init__(directory)

    def list(self, include_archived=True):
        # brief_ids are kept, so the Library can show and filter by project
        projects = [
            {**p, "brief_count": len(p.get("brief_ids", []))}
            for p in self._all()
            if include_archived or p.get("status", "active") != "archived"
        ]
        projects.sort(key=lambda p: p.get("updated_at") or "", reverse=True)
        return projects

    def projects_for(self, brief_id):
        """Short {id, name, client} entries for every project holding this brief."""
        return [
            {"id": p["id"], "name": p.get("name", ""), "client": p.get("client", "")}
            for p in self._all()
            if brief_id in p.get("brief_ids", [])
        ]
