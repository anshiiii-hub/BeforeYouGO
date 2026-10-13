"""TEST DATA ONLY: in-test fixture adapters injected through ``set_adapter_overrides``.

Nothing here talks to the network and none of the records describe real events.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select

from app.models import Event, Source
from app.services.event_fields import NormalizedEvent
from app.services.ingest import ingest_record
from app.services.sources.base import FetchResult, RawRecord, SourceAdapter, SourceDescriptor
from app.services.sources.registry import seed_sources, set_adapter_overrides

DOC = "fixture-doc"


class FixtureAdapter(SourceAdapter):
    """Serves ``records`` (dicts) and normalises them to the shared schema. Mutable between syncs."""

    def __init__(self, key: str, records: list[dict[str, Any]] | None = None, priority: int = 50, crash: bool = False,
                 errors: list[dict[str, Any]] | None = None, complete: bool = True):
        self.descriptor = SourceDescriptor(key=key, name=f"TEST DATA adapter {key}", kind="fixture", homepage=None,
                                           access_method="in-test fixture", limitations="test data", rate_limit_note="none",
                                           auth_requirement="none", attribution="TEST DATA", priority=priority)
        self.records = records or []
        self.crash = crash
        self.errors = errors or []
        self.complete = complete

    def fetch(self, *, state: dict[str, Any], today: date) -> FetchResult:
        if self.crash:
            raise RuntimeError("fixture adapter crashed on purpose")
        res = FetchResult(errors=list(self.errors), complete=self.complete)
        for r in self.records:
            res.records.append(RawRecord(source_event_id=r["id"], payload={**r, "_file": DOC}, source_url=f"https://{self.key}.test.example/feed",
                                         event_url=r.get("url")))
        if not self.errors:
            res.succeeded_documents.append(DOC)
        return res

    def normalize(self, raw: RawRecord) -> NormalizedEvent:
        p = raw.payload
        n = NormalizedEvent(source_event_id=raw.source_event_id, title=p["title"], source_url=raw.source_url)
        n.set("title", p["title"])
        n.set("canonical_url", p.get("url"))
        n.set("start_date", date.fromisoformat(p["start"]) if p.get("start") else None)
        n.set("end_date", date.fromisoformat(p["end"]) if p.get("end") else None)
        n.set("city", p.get("city"))
        n.set("country", p.get("country"))
        n.set("format", p.get("format"))
        n.set("description", p.get("description"))
        n.set("category", p.get("category"))
        n.set("registration_deadline", datetime.fromisoformat(p["deadline"]) if p.get("deadline") else None)
        fee = p.get("fee")  # "free" | number | None (unknown)
        if fee == "free":
            n.set("fee_status", "free")
        elif fee is not None:
            n.set("fee_status", "paid")
            n.set("fee_amount", fee)
            n.set("fee_currency", "INR")
        n.set("lifecycle_status", p.get("lifecycle"))
        if p.get("accessibility"):
            n.accessibility["wheelchair_access"] = {"state": "documented", "excerpt": p["accessibility"]}
        return n


def install(*adapters: FixtureAdapter) -> None:
    set_adapter_overrides({a.key: a for a in adapters})


def source_row(db, adapter: FixtureAdapter) -> Source:
    seed_sources(db)
    db.commit()
    return db.scalar(select(Source).where(Source.key == adapter.key))


def ingest(db, adapter: FixtureAdapter, *, now=None) -> list[Event]:
    """Fetch from the fixture adapter and ingest every record (no sync-run bookkeeping)."""
    install(adapter)
    src = source_row(db, adapter)
    res = adapter.fetch(state={}, today=date.today())
    out = []
    for raw in res.records:
        o = ingest_record(db, src, adapter, raw, now=now)
        out.append(db.get(Event, o.event_id))
    db.commit()
    return out
