from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPk, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUIDPk]
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default="student", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(default=0)  # bump to revoke all tokens
    created_at: Mapped[CreatedAt]
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped[StudentProfile | None] = relationship(back_populates="user", uselist=False)


class StudentProfile(Base):
    """Optional, user-editable preference data. Every field is optional by design."""

    __tablename__ = "student_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    education_level: Mapped[str | None] = mapped_column(String(40))  # diploma/undergraduate/postgraduate/...
    year_of_study: Mapped[int | None]
    institution: Mapped[str | None] = mapped_column(String(200))
    interests: Mapped[list[Any]] = mapped_column(default=list)
    skill_level: Mapped[str | None] = mapped_column(String(20))  # beginner/intermediate/advanced
    learning_goals: Mapped[str | None] = mapped_column(Text)
    career_goals: Mapped[str | None] = mapped_column(Text)
    available_from: Mapped[date | None] = mapped_column(Date)
    available_to: Mapped[date | None] = mapped_column(Date)
    max_budget_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    preferred_formats: Mapped[list[Any]] = mapped_column(default=list)
    require_format: Mapped[bool] = mapped_column(Boolean, default=False)  # hard constraint when true
    home_city: Mapped[str | None] = mapped_column(String(120))
    max_travel_km: Mapped[int | None]
    accessibility_needs: Mapped[list[Any]] = mapped_column(default=list)
    preferred_duration_days_max: Mapped[int | None]
    team_preference: Mapped[str | None] = mapped_column(String(20))  # individual/team/either
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="profile")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[UUIDPk]
    name: Mapped[str] = mapped_column(String(200), unique=True)
    website: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[CreatedAt]


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)

    id: Mapped[UUIDPk]
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[CreatedAt]


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow
    )
