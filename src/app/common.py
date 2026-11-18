# Helpers shared by the route files (server.py, market.py, present.py)

from fastapi import HTTPException
from pydantic import BaseModel


class StatusRequest(BaseModel):
    """Approve or request changes on a brief or a market scan."""
    status: str
    note: str = ""


def load_or_404(store, record_id, label, status_code=404):
    """store.load(record_id), or an HTTP error saying "<label> not found"."""
    try:
        return store.load(record_id)
    except KeyError:
        raise HTTPException(status_code, f"{label} not found")
