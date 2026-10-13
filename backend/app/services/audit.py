from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def audit(
    db: Session,
    *,
    actor: User | None,
    action: str,
    target_type: str | None = None,
    target_id: object | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Record a privileged action. The audit_logs table is append-only (DB trigger)."""
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_role=actor.role if actor else "system",
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=details or {},
        ip_address=ip,
    )
    db.add(entry)
    db.flush()
    return entry
