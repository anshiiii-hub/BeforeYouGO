from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound
from app.models import Claim, Event, StudentProfile, User


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return fwd or (request.client.host if request.client else None)


def get_event(db: Session, event_id: uuid.UUID, *, include_unpublished_for: User | None = None) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise NotFound("Event not found.", code="event_not_found")
    if not event.is_published:
        from app.core.deps import can_manage_event

        user = include_unpublished_for
        if user is None or not (can_manage_event(db, user, event) or user.role in ("admin", "reviewer")):
            raise NotFound("Event not found.", code="event_not_found")
    return event


def get_claim(db: Session, claim_id: uuid.UUID) -> Claim:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise NotFound("Claim not found.", code="claim_not_found")
    return claim


def profile_of(db: Session, user: User | None) -> StudentProfile | None:
    if user is None:
        return None
    return db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))


def require_owner(db: Session, user: User, event: Event) -> None:
    from app.core.deps import can_manage_event

    if not can_manage_event(db, user, event):
        raise Forbidden("You can only manage events owned by your organization.", code="not_event_owner")


def page(total: int, page_no: int, size: int, items: list[Any], **extra: Any) -> dict[str, Any]:
    return {"items": items, "total": total, "page": page_no, "page_size": size, **extra}
