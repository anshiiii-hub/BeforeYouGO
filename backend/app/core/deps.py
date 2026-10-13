"""Authentication and authorisation dependencies. All role checks happen server side."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_access_token
from app.domain.enums import Role
from app.models import OrganizationMember, User

bearer = HTTPBearer(auto_error=False)
DbSession = Annotated[Session, Depends(get_db)]


def _load_user(db: Session, creds: HTTPAuthorizationCredentials | None) -> User | None:
    if creds is None:
        return None
    payload = decode_access_token(creds.credentials)
    try:
        uid = uuid.UUID(payload["sub"])
    except (ValueError, KeyError) as exc:
        raise Unauthorized("Invalid authentication token.", code="invalid_token") from exc
    user = db.get(User, uid)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise Unauthorized("Account not found or disabled.", code="account_disabled")
    if payload.get("tv") != user.token_version:
        raise Unauthorized("Session has been revoked. Please sign in again.", code="token_revoked")
    return user


def optional_user(
    request: Request, db: DbSession, creds: HTTPAuthorizationCredentials | None = Depends(bearer)
) -> User | None:
    user = _load_user(db, creds)
    if user:
        request.state.user_id = str(user.id)
        request.state.user_role = user.role
    return user


def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise Unauthorized("Sign in to continue.", code="not_authenticated")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]


def require_roles(*roles: Role) -> Callable[[User], User]:
    allowed = {r.value for r in roles}

    def dependency(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise Forbidden(
                f"This action requires one of the roles: {', '.join(sorted(allowed))}.", code="role_forbidden"
            )
        return user

    return dependency


RequireAdmin = Annotated[User, Depends(require_roles(Role.ADMIN))]
RequireReviewer = Annotated[User, Depends(require_roles(Role.REVIEWER, Role.ADMIN))]
RequireOrganizer = Annotated[User, Depends(require_roles(Role.ORGANIZER, Role.ADMIN, Role.REVIEWER))]
RequireOrganizerOnly = Annotated[User, Depends(require_roles(Role.ORGANIZER, Role.ADMIN))]


def user_org_ids(db: Session, user: User) -> set[uuid.UUID]:
    rows = db.execute(select(OrganizationMember.organization_id).where(OrganizationMember.user_id == user.id))
    return {r[0] for r in rows}


def can_manage_event(db: Session, user: User, event) -> bool:  # type: ignore[no-untyped-def]
    """Organizers manage only events owned by one of their organisations. Admins manage all."""
    if user.role == Role.ADMIN.value:
        return True
    if user.role != Role.ORGANIZER.value:
        return False
    if event.owner_org_id is None:
        return False
    return event.owner_org_id in user_org_ids(db, user)


def has_conflict_of_interest(db: Session, user: User, event) -> bool:  # type: ignore[no-untyped-def]
    """A reviewer who belongs to the event's owning organisation must not review its evidence."""
    if event.owner_org_id is None:
        return False
    return event.owner_org_id in user_org_ids(db, user)
