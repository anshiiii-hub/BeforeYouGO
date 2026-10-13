"""Operator-adjustable policy values (freshness window, evidence thresholds, scoring weights).

Stored in ``system_settings`` so an administrator can change them without a redeploy; every change is
audited by the admin API. Environment values are the defaults.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import SystemSetting
from app.services.scoring import DEFAULT_WEIGHTS

KEY = "policy"


def defaults() -> dict[str, Any]:
    s = get_settings()
    return {
        "stale_after_days": s.stale_after_days,
        "participant_threshold": s.participant_threshold,
        "unverified_grace_days": s.unverified_grace_days,
        "min_outcome_responses": s.min_outcome_responses,
        "scoring_weights": dict(DEFAULT_WEIGHTS),
    }


def effective(db: Session) -> dict[str, Any]:
    out = defaults()
    row = db.get(SystemSetting, KEY)
    if row and isinstance(row.value, dict):
        for k, v in row.value.items():
            if k in out and v is not None:
                out[k] = {**out[k], **v} if isinstance(out[k], dict) else v
    return out


def normalised_weights(weights: dict[str, float]) -> dict[str, float]:
    """Weights must be non-negative and sum to 1; unknown keys are rejected by the caller."""
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()} if total > 0 else dict(DEFAULT_WEIGHTS)
