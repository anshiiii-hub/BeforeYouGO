"""Adapter registry and source catalogue seeding.

Only connectors that exist as code are registered as adapters. Platforms that were
investigated but cannot be integrated appear in the catalogue with their honest status.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import SourceStatus
from app.models import Source
from app.services.sources.base import SourceAdapter
from app.services.sources.catalog import PLATFORMS
from app.services.sources.event_pages import EventPageAdapter
from app.services.sources.github_conferences import DevelopersEventsAdapter, TechConferencesAdapter
from app.services.sources.ics_feed import IcsFeedAdapter

logger = logging.getLogger("byg.sources.registry")

_adapter_overrides: dict[str, SourceAdapter] | None = None


def set_adapter_overrides(adapters: dict[str, SourceAdapter] | None) -> None:
    """Tests inject adapters backed by fixtures; production never calls this."""
    global _adapter_overrides
    _adapter_overrides = adapters


def build_adapters() -> dict[str, SourceAdapter]:
    if _adapter_overrides is not None:
        return dict(_adapter_overrides)
    adapters: list[SourceAdapter] = [
        TechConferencesAdapter(),
        DevelopersEventsAdapter(),
        IcsFeedAdapter(),
        EventPageAdapter(),
    ]
    return {a.key: a for a in adapters}


def seed_sources(db: Session) -> None:
    """Idempotently create/refresh catalogue rows. Never overwrites runtime state (status, config, timestamps)."""
    settings = get_settings()
    existing = {s.key: s for s in db.scalars(select(Source))}
    for adapter in build_adapters().values():
        d = adapter.descriptor
        configured, reason = adapter.check_configured(settings)
        row = existing.get(d.key)
        if row is None:
            row = Source(key=d.key, name=d.name, kind=d.kind, access_method=d.access_method)
            row.status = SourceStatus.PENDING.value if configured else SourceStatus.NOT_CONFIGURED.value
            row.status_detail = None if configured else reason
            row.config = {}
            db.add(row)
        row.name = d.name
        row.kind = d.kind
        row.homepage = d.homepage
        row.access_method = d.access_method
        row.limitations = d.limitations
        row.rate_limit_note = d.rate_limit_note
        row.auth_requirement = d.auth_requirement
        row.attribution = d.attribution
        row.terms_url = d.terms_url
        row.license_note = d.license_note
        row.priority = d.priority
        if not configured and row.status in (SourceStatus.PENDING.value, SourceStatus.NOT_CONFIGURED.value):
            row.status = SourceStatus.NOT_CONFIGURED.value
            row.status_detail = reason
        elif configured and row.status == SourceStatus.NOT_CONFIGURED.value:
            row.status = SourceStatus.PENDING.value
            row.status_detail = None
    for p in PLATFORMS:
        row = existing.get(p.key)
        if row is None:
            row = Source(key=p.key, name=p.name, kind="platform", access_method=p.access_method)
            row.config = {}
            db.add(row)
        row.name = p.name
        row.kind = "platform"
        row.homepage = p.homepage
        row.access_method = p.access_method
        row.limitations = p.limitations
        row.rate_limit_note = p.rate_limit_note
        row.auth_requirement = p.auth_requirement
        row.terms_url = p.terms_url
        row.priority = 40
        # Probe results (BLOCKED) are kept; otherwise show the researched status.
        if row.status not in (SourceStatus.BLOCKED.value,):
            row.status = p.status.value
        row.status_detail = p.why_not_integrated
        row.enabled = False
    db.flush()


def adapter_state(source: Source) -> dict[str, Any]:
    return dict(source.config or {})
