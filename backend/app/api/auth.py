from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, select

from app.api.common import client_ip, profile_of
from app.core.deps import CurrentUser, DbSession, user_org_ids
from app.core.errors import Conflict, Unauthorized, Unprocessable
from app.core.ratelimit import auth_limit
from app.core.security import (
    create_access_token,
    hash_password,
    password_needs_rehash,
    validate_password_strength,
    verify_password,
)
from app.models import (
    ComparisonHistory,
    Organization,
    RecommendationFeedback,
    SavedEvent,
    StudentProfile,
    User,
)
from app.models.base import utcnow
from app.schemas.api import DeleteAccountIn, LoginIn, MeUpdateIn, ProfileIn, RegisterIn
from app.services.audit import audit

router = APIRouter(prefix="/api", tags=["auth"])
_DUMMY_HASH = hash_password("not-a-real-password-1A")


def user_dict(db, user: User) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    orgs = []
    ids = user_org_ids(db, user)
    if ids:
        orgs = [{"id": str(o.id), "name": o.name, "website": o.website} for o in db.scalars(select(Organization).where(Organization.id.in_(ids)))]
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name, "role": user.role,
            "created_at": user.created_at.isoformat() if user.created_at else None, "organizations": orgs,
            "has_profile": profile_of(db, user) is not None}


def token_response(db, user: User) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {"access_token": create_access_token(str(user.id), user.token_version), "token_type": "bearer", "user": user_dict(db, user)}


@router.post("/auth/register", status_code=201, dependencies=[Depends(auth_limit)])
def register(body: RegisterIn, db: DbSession, request: Request) -> dict[str, Any]:
    problems = validate_password_strength(body.password)
    if problems:
        raise Unprocessable("That password is too weak.", details=problems, code="weak_password")
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise Conflict("An account with this email already exists.", code="email_taken")
    user = User(email=email, password_hash=hash_password(body.password), display_name=body.display_name, role=body.role)
    db.add(user)
    db.flush()
    audit(db, actor=user, action="user.registered", target_type="user", target_id=user.id, details={"role": body.role}, ip=client_ip(request))
    return token_response(db, user)


@router.post("/auth/login", dependencies=[Depends(auth_limit)])
def login(body: LoginIn, db: DbSession, request: Request) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active or user.deleted_at is not None:
        raise Unauthorized("Email or password is incorrect.", code="invalid_credentials")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = utcnow()
    audit(db, actor=user, action="user.login", target_type="user", target_id=user.id, ip=client_ip(request))
    return token_response(db, user)


@router.post("/auth/logout")
def logout(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """Revokes every token issued to this account (token_version bump)."""
    user.token_version += 1
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    return user_dict(db, user)


@router.patch("/me")
def update_me(body: MeUpdateIn, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    if body.display_name:
        user.display_name = body.display_name
    if body.new_password:
        if not body.current_password or not verify_password(body.current_password, user.password_hash):
            raise Unauthorized("Current password is incorrect.", code="invalid_credentials")
        problems = validate_password_strength(body.new_password)
        if problems:
            raise Unprocessable("That password is too weak.", details=problems, code="weak_password")
        user.password_hash = hash_password(body.new_password)
        user.token_version += 1
        db.flush()
        return token_response(db, user)
    return user_dict(db, user)


@router.delete("/me")
def delete_me(body: DeleteAccountIn, user: CurrentUser, db: DbSession, request: Request) -> dict[str, Any]:
    """Data-minimising deletion: personal data is erased, content other people rely on is detached from the person.

    Feedback and evidence rows keep a pointer to an anonymised tombstone account so published aggregates
    stay consistent without retaining any personal information.
    """
    if not verify_password(body.password, user.password_hash):
        raise Unauthorized("Password is incorrect.", code="invalid_credentials")
    uid = user.id
    db.execute(delete(StudentProfile).where(StudentProfile.user_id == uid))
    db.execute(delete(SavedEvent).where(SavedEvent.user_id == uid))
    db.execute(delete(ComparisonHistory).where(ComparisonHistory.user_id == uid))
    db.execute(delete(RecommendationFeedback).where(RecommendationFeedback.user_id == uid))
    user.email = f"deleted-{uuid.uuid4().hex}@deleted.invalid"
    user.display_name = "Deleted user"
    user.password_hash = hash_password(uuid.uuid4().hex + "Aa1")
    user.is_active = False
    user.deleted_at = utcnow()
    user.token_version += 1
    audit(db, actor=None, action="user.deleted", target_type="user", target_id=uid, ip=client_ip(request))
    return {"ok": True}


# ------------------------------------------------------------------ profile


def profile_dict(p: StudentProfile | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {
        "education_level": p.education_level, "year_of_study": p.year_of_study, "institution": p.institution,
        "interests": p.interests or [], "skill_level": p.skill_level, "learning_goals": p.learning_goals,
        "career_goals": p.career_goals, "available_from": p.available_from.isoformat() if p.available_from else None,
        "available_to": p.available_to.isoformat() if p.available_to else None,
        "max_budget_inr": float(p.max_budget_inr) if p.max_budget_inr is not None else None,
        "preferred_formats": p.preferred_formats or [], "require_format": p.require_format, "home_city": p.home_city,
        "max_travel_km": p.max_travel_km, "accessibility_needs": p.accessibility_needs or [],
        "preferred_duration_days_max": p.preferred_duration_days_max, "team_preference": p.team_preference,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/me/profile")
def get_profile(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    return {"profile": profile_dict(profile_of(db, user)),
            "data_use": "Used only to rank and explain events for you. Every field is optional, can be edited or deleted at any time, "
                        "and is never used to train models or shown to organizers."}


@router.put("/me/profile")
def put_profile(body: ProfileIn, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    p = profile_of(db, user)
    if p is None:
        p = StudentProfile(user_id=user.id)
        db.add(p)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.flush()
    return {"profile": profile_dict(p)}


@router.delete("/me/profile")
def delete_profile(user: CurrentUser, db: DbSession) -> dict[str, Any]:
    db.execute(delete(StudentProfile).where(StudentProfile.user_id == user.id))
    return {"ok": True}
