"""Per-application registration and farming configuration."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKeyConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.engine import Base


class ApplicationAutomationPolicy(Base):
    __tablename__ = "application_automation_policies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "application_profile_id"], ["application_profiles.org_id", "application_profiles.id"],
            name="fk_automation_policy_profile",
        ),
        ForeignKeyConstraint(
            ["org_id", "registration_script_id"], ["scripts.org_id", "scripts.id"],
            name="fk_automation_policy_registration_script",
        ),
        ForeignKeyConstraint(
            ["org_id", "farming_script_id"], ["scripts.org_id", "scripts.id"],
            name="fk_automation_policy_farming_script",
        ),
        CheckConstraint("revision >= 1", name="ck_automation_policy_revision"),
        CheckConstraint(
            "(NOT registration_enabled OR registration_script_id IS NOT NULL) "
            "AND (NOT farming_enabled OR farming_script_id IS NOT NULL)",
            name="ck_automation_policy_enabled_script",
        ),
        CheckConstraint(
            "max_concurrent_registrations BETWEEN 1 AND 100 "
            "AND registration_timeout_seconds BETWEEN 60 AND 7200 "
            "AND max_concurrent_farming BETWEEN 1 AND 500 "
            "AND farming_session_duration_seconds BETWEEN 300 AND 86400 "
            "AND default_target_level BETWEEN 1 AND 100 "
            "AND cooldown_between_sessions_minutes BETWEEN 0 AND 1440",
            name="ck_automation_policy_limits",
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    application_profile_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    registration_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    registration_script_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    max_concurrent_registrations: Mapped[int] = mapped_column(Integer, nullable=False)
    registration_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    farming_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    farming_script_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    max_concurrent_farming: Mapped[int] = mapped_column(Integer, nullable=False)
    farming_session_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    default_target_level: Mapped[int] = mapped_column(Integer, nullable=False)
    cooldown_between_sessions_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
