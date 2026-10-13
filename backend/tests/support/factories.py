"""Row factories for arranging test state directly in the test database. All values are synthetic TEST DATA."""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.security import create_access_token, hash_password
from app.models import (
    Claim,
    ClaimStatusHistory,
    Event,
    Evidence,
    FeedbackResponse,
    Organization,
    OrganizationMember,
    Participation,
    StudentProfile,
    User,
)

PASSWORD = "Str0ngPassw0rd!"
_HASH = hash_password(PASSWORD)
_counter = itertools.count(1)


def today() -> date:
    return datetime.now(UTC).date()


def days(n: int) -> date:
    return today() + timedelta(days=n)


def make_user(db, role: str = "student", email: str | None = None, name: str | None = None) -> User:
    n = next(_counter)
    u = User(email=email or f"{role}{n}@test.example", password_hash=_HASH, display_name=name or f"Test {role} {n}", role=role)
    db.add(u)
    db.commit()
    return u


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.token_version)}"}


def make_org(db, *members: User, name: str | None = None) -> Organization:
    org = Organization(name=name or f"Test Org {next(_counter)}")
    db.add(org)
    db.flush()
    for m in members:
        db.add(OrganizationMember(organization_id=org.id, user_id=m.id))
    db.commit()
    return org


def make_event(db, title: str | None = None, **kw: Any) -> Event:
    kw.setdefault("is_published", True)
    kw.setdefault("extras", {})
    kw.setdefault("origin_type", "organizer_submitted")
    e = Event(title=title or f"Test Event {next(_counter)}", **kw)
    db.add(e)
    db.commit()
    return e


def make_claim(db, event: Event, text: str | None = None, *, status: str = "advertised", category: str = "prize",
               claim_type: str = "specific", active: bool = True) -> Claim:
    import hashlib

    text = text or f"Winners receive a cash prize of Rs 50000 ({next(_counter)})"
    c = Claim(event_id=event.id, text_hash=hashlib.sha256(text.encode()).hexdigest(), original_text=text, normalized_text=text,
              category=category, claim_type=claim_type, extraction_method="manual", status=status, is_active=active)
    db.add(c)
    db.flush()
    db.add(ClaimStatusHistory(claim_id=c.id, actor_role="system", from_status=None, to_status="advertised", reason="seeded test claim"))
    db.commit()
    return c


def make_evidence(db, claim: Claim, *, kind: str = "public_source", review_status: str = "pending", submitted_by: User | None = None,
                  claim_specific: bool = True) -> Evidence:
    ev = Evidence(event_id=claim.event_id, claim_id=claim.id, kind=kind, url="https://evidence.test.example/page",
                  excerpt="test evidence excerpt", claim_specific=claim_specific, review_status=review_status,
                  submitted_by=submitted_by.id if submitted_by else None)
    db.add(ev)
    db.commit()
    return ev


def make_participation(db, user: User, event: Event, *, coi: bool = False) -> Participation:
    p = Participation(user_id=user.id, event_id=event.id, conflict_of_interest=coi)
    db.add(p)
    db.commit()
    return p


def make_feedback(db, user: User, claim: Claim, response: str = "delivered", status: str = "published") -> FeedbackResponse:
    f = FeedbackResponse(event_id=claim.event_id, claim_id=claim.id, user_id=user.id, participation_level="self_declared",
                         response=response, status=status)
    db.add(f)
    db.commit()
    return f


def make_profile(db, user: User, **kw: Any) -> StudentProfile:
    p = StudentProfile(user_id=user.id, **kw)
    db.add(p)
    db.commit()
    return p


def new_id() -> str:
    return str(uuid.uuid4())
