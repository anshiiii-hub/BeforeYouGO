"""Synchronisation runs: fetch from a connector, ingest, record honest per-source health."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import NotFound, Unprocessable
from app.domain.enums import OriginType, SourceStatus, SyncStatus
from app.models import Source, SyncRun, User
from app.models.base import utcnow
from app.services.audit import audit
from app.services.ingest import ingest_record, mark_missing_records, utc_today
from app.services.safe_fetch import EgressDenied, FetchError
from app.services.sources.base import FetchResult
from app.services.sources.event_pages import EventPageAdapter
from app.services.sources.registry import build_adapters, seed_sources
from app.services.urls import canonicalize_url

logger = logging.getLogger("byg.sync")
MAX_ERRORS_STORED = 50


def run_source_sync(source_key: str, *, trigger: str = "scheduled", user_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Run one synchronisation. Network I/O happens outside any open transaction."""
    adapters = build_adapters()
    adapter = adapters.get(source_key)
    if adapter is None:
        raise NotFound(f"'{source_key}' has no connector in this deployment.", code="no_connector")

    with session_scope() as db:
        source = db.scalar(select(Source).where(Source.key == source_key))
        if source is None:
            raise NotFound("Unknown source.")
        if not source.enabled:
            raise Unprocessable("This source is disabled.", code="source_disabled")
        configured, reason = adapter.check_configured(get_settings())
        if not configured:
            source.status = SourceStatus.NOT_CONFIGURED.value
            source.status_detail = reason
            return {"source": source_key, "status": "not_configured", "detail": reason}
        run = SyncRun(source_id=source.id, trigger=trigger, triggered_by=user_id, status=SyncStatus.RUNNING.value)
        db.add(run)
        source.last_attempt_at = utcnow()
        db.flush()
        run_id, source_id = run.id, source.id
        state = dict(source.config or {})

    try:
        result: FetchResult = adapter.fetch(state=state, today=utc_today())
    except Exception as exc:  # an adapter bug must not take the scheduler down
        logger.exception("connector crashed")
        result = FetchResult(errors=[{"document": None, "code": "connector_error", "message": str(exc)[:300]}])

    with session_scope() as db:
        source = db.get(Source, source_id)
        run = db.get(SyncRun, run_id)
        assert source is not None and run is not None
        created = updated = unchanged = skipped = 0
        errors: list[dict[str, Any]] = list(result.errors)
        seen: set[str] = set()
        for raw in result.records:
            try:
                with db.begin_nested():
                    outcome = ingest_record(db, source, adapter, raw)
            except Exception as exc:
                skipped += 1
                errors.append({"document": raw.payload.get("_file"), "code": "record_failed", "message": f"{raw.source_event_id}: {str(exc)[:200]}"})
                continue
            seen.add(raw.source_event_id)
            if outcome.kind == "created":
                created += 1
            elif outcome.kind == "updated":
                updated += 1
            else:
                unchanged += 1

        missing = 0
        if result.succeeded_documents:
            docs = set(result.succeeded_documents) - set(result.unchanged_documents)
            if docs:
                missing = mark_missing_records(db, source, seen, docs)

        run.records_fetched = len(result.records)
        run.created_count, run.updated_count, run.unchanged_count = created, updated, unchanged
        run.skipped_count, run.missing_count = skipped, missing
        run.errors = errors[:MAX_ERRORS_STORED]
        run.finished_at = utcnow()
        denied = any(e.get("code") == "egress_denied" for e in errors)
        got_data = bool(result.records) or bool(result.unchanged_documents)

        if errors and not got_data:
            run.status = SyncStatus.FAILED.value
        elif errors:
            run.status = SyncStatus.PARTIAL.value
        else:
            run.status = SyncStatus.SUCCESS.value

        cfg = dict(source.config or {})
        cfg.update(result.state_updates)
        source.config = cfg
        if run.status == SyncStatus.FAILED.value:
            source.consecutive_failures += 1
            source.status = SourceStatus.BLOCKED.value if denied else SourceStatus.DEGRADED.value
            source.last_error = (errors[0].get("message") if errors else None)
            source.status_detail = "Last synchronisation failed: " + (source.last_error or "unknown error")
        elif not got_data and not result.succeeded_documents:
            source.status_detail = " ".join(result.notes) or "Nothing to synchronise yet."
        else:
            source.last_success_at = utcnow()
            source.consecutive_failures = 0
            if run.status == SyncStatus.PARTIAL.value:
                source.status = SourceStatus.DEGRADED.value
                source.last_error = errors[0].get("message") if errors else None
                source.status_detail = f"Last synchronisation succeeded with {len(errors)} document error(s)."
            else:
                source.status = SourceStatus.ACTIVE.value
                source.last_error = None
                source.status_detail = " ".join(result.notes) or None
        if user_id:
            audit(db, actor=db.get(User, user_id), action="source.sync_triggered", target_type="source", target_id=source.id,
                  details={"trigger": trigger, "status": run.status})
        summary = {
            "source": source_key,
            "status": run.status,
            "fetched": run.records_fetched,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "skipped": skipped,
            "missing": missing,
            "errors": errors[:5],
        }
    logger.info("sync finished", extra={"extra_fields": summary})
    return summary


def sync_all_sources(trigger: str = "scheduled") -> list[dict[str, Any]]:
    with session_scope() as db:
        seed_sources(db)
        keys = [s.key for s in db.scalars(select(Source).where(Source.enabled.is_(True)))]
    adapters = build_adapters()
    out = []
    for key in keys:
        if key not in adapters:
            continue
        try:
            out.append(run_source_sync(key, trigger=trigger))
        except Exception as exc:
            logger.exception("sync failed for %s", key)
            out.append({"source": key, "status": "error", "detail": str(exc)[:200]})
    return out


def submit_event_url(db: Session, url: str, *, user: User, origin: OriginType = OriginType.USER_SUBMITTED) -> dict[str, Any]:
    """Fetch a public event page now (SSRF-safe, robots-respecting) and ingest what it publishes."""
    canon = canonicalize_url(url)
    if canon is None:
        raise Unprocessable("That does not look like a valid http(s) URL.", code="invalid_url")
    adapter = EventPageAdapter()
    try:
        records = adapter.fetch_page(url)
    except EgressDenied as exc:
        raise Unprocessable(
            f"This deployment cannot reach that site ({exc.message}). Paste the event text into the analyzer instead.",
            code="egress_denied",
        ) from exc
    except FetchError as exc:
        raise Unprocessable(f"The page could not be retrieved: {exc.message}", code=exc.code) from exc
    if not records:
        raise Unprocessable("The page was reachable but no event information could be read from it.", code="no_event_data")

    source = db.scalar(select(Source).where(Source.key == adapter.key))
    if source is None:
        seed_sources(db)
        source = db.scalar(select(Source).where(Source.key == adapter.key))
    assert source is not None
    urls = list((source.config or {}).get("urls", []))
    if url not in urls:
        source.config = {**(source.config or {}), "urls": [*urls, url]}
    ids = []
    for raw in records:
        outcome = ingest_record(db, source, adapter, raw, origin_type=origin.value)
        ids.append(str(outcome.event_id))
    source.last_success_at = utcnow()
    source.status = SourceStatus.ACTIVE.value
    audit(db, actor=user, action="event.url_submitted", target_type="source", target_id=source.id, details={"url": url, "events": ids})
    return {"event_ids": ids, "retrieved_at": datetime.now(UTC).isoformat()}
