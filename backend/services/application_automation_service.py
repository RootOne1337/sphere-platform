"""Persist explicit tenant application configuration without rewriting legacy state."""

import uuid

from fastapi import HTTPException
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.account_session import AccountSession
from backend.models.application_automation_policy import ApplicationAutomationPolicy
from backend.models.application_profile import ApplicationProfile
from backend.models.device import Device
from backend.models.game_account import AccountStatus, GameAccount
from backend.models.pipeline import PipelineRun, PipelineRunStatus
from backend.models.script import Script, ScriptVersion
from backend.models.task import Task, TaskStatus
from backend.schemas.application_automation import (
    ApplicationAutomationPolicyResponse,
    ApplicationAutomationPolicyUpdate,
    DeviceApplicationBindingResponse,
    DeviceApplicationBindingUpdate,
)
from backend.services.application_profile_service import BUILTIN_ID


async def lock_admission_devices(
    db: AsyncSession, org_id: uuid.UUID, device_ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    """Fence bulk automation admission against binding writes without a lock wait."""
    candidates = select(Device.id).where(
        Device.org_id == org_id, Device.id.in_(device_ids), Device.is_active.is_(True),
    )
    # NO KEY UPDATE still serializes binding/retirement and other admissions.
    # An event or task INSERT only holds a compatible FK KEY SHARE on Device.
    locked = list(await db.scalars(candidates.order_by(Device.id).with_for_update(skip_locked=True, key_share=True)))
    if len(locked) < len(set(device_ids)):
        existing = set(await db.scalars(candidates))
        if existing.difference(locked):
            raise HTTPException(409, "Device configuration is changing; retry the automation launch")
    return locked


class ApplicationAutomationService:
    def __init__(self, db: AsyncSession, org_id: uuid.UUID):
        self.db = db
        self.org_id = org_id

    async def _profile(
        self, profile_id: uuid.UUID, *, for_update: bool = False,
    ) -> ApplicationProfile:
        if profile_id == BUILTIN_ID:
            raise HTTPException(409, "Built-in application uses the legacy configuration")
        query = select(ApplicationProfile).where(
            ApplicationProfile.id == profile_id, ApplicationProfile.org_id == self.org_id,
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        profile = await self.db.scalar(query)
        if profile is None:
            raise HTTPException(404, "Application profile not found")
        return profile

    async def _device(self, device_id: uuid.UUID, *, for_update: bool = False) -> Device:
        query = select(Device).where(Device.id == device_id, Device.org_id == self.org_id, Device.is_active.is_(True))
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        device = await self.db.scalar(query)
        if device is None:
            raise HTTPException(404, "Device not found")
        return device

    @staticmethod
    def _binding(device: Device) -> DeviceApplicationBindingResponse:
        return DeviceApplicationBindingResponse(
            device_id=device.id,
            application_profile_id=device.application_profile_id,
            application_server_key=device.application_server_key,
            revision=device.application_binding_revision,
        )

    async def get_binding(self, device_id: uuid.UUID) -> DeviceApplicationBindingResponse:
        return self._binding(await self._device(device_id))

    async def update_binding(
        self, device_id: uuid.UUID, request: DeviceApplicationBindingUpdate,
    ) -> DeviceApplicationBindingResponse:
        # Shared order with task admission and assignment: device, then account.
        device = await self._device(device_id, for_update=True)
        if device.application_binding_revision != request.expected_revision:
            raise HTTPException(409, "Application binding changed; reload before saving")
        if (device.application_profile_id, device.application_server_key) == (
            request.application_profile_id, request.application_server_key,
        ):
            return self._binding(device)

        if request.application_profile_id is not None:
            profile = await self._profile(request.application_profile_id)
            if not any(server["key"] == request.application_server_key for server in profile.servers):
                raise HTTPException(422, "Server key is not in the application profile")

        await self._require_idle_device(device.id)
        device.application_profile_id = request.application_profile_id
        device.application_server_key = request.application_server_key
        device.application_binding_revision += 1
        await self.db.flush()
        return self._binding(device)

    async def _require_idle_device(self, device_id: uuid.UUID) -> None:
        active_task = select(Task.id).where(
            Task.org_id == self.org_id, Task.device_id == device_id,
            Task.status.in_((TaskStatus.QUEUED, TaskStatus.ASSIGNED, TaskStatus.RUNNING)),
        ).exists()
        active_run = select(PipelineRun.id).where(
            PipelineRun.org_id == self.org_id, PipelineRun.device_id == device_id,
            PipelineRun.status.in_((PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING,
                                   PipelineRunStatus.PAUSED, PipelineRunStatus.WAITING)),
        ).exists()
        account = select(GameAccount.id).where(
            GameAccount.org_id == self.org_id, GameAccount.device_id == device_id,
            GameAccount.status.in_((AccountStatus.in_use, AccountStatus.pending_registration)),
        ).exists()
        session = select(AccountSession.id).where(
            AccountSession.org_id == self.org_id, AccountSession.device_id == device_id, AccountSession.ended_at.is_(None),
        ).exists()
        if await self.db.scalar(select(active_task | active_run | account | session)):
            raise HTTPException(409, "Device has active automation or an account session")

    def _policy(self, profile_id: uuid.UUID) -> Select[tuple[ApplicationAutomationPolicy]]:
        return select(ApplicationAutomationPolicy).where(
            ApplicationAutomationPolicy.org_id == self.org_id,
            ApplicationAutomationPolicy.application_profile_id == profile_id,
        )

    async def get_policy(self, profile_id: uuid.UUID) -> ApplicationAutomationPolicyResponse:
        await self._profile(profile_id)
        row = await self.db.scalar(self._policy(profile_id))
        if row is None:
            return ApplicationAutomationPolicyResponse(application_profile_id=profile_id)
        return ApplicationAutomationPolicyResponse.model_validate(row)

    async def update_policy(
        self, profile_id: uuid.UUID, request: ApplicationAutomationPolicyUpdate,
    ) -> ApplicationAutomationPolicyResponse:
        # The parent lock serializes the first write before a policy row exists.
        profile = await self._profile(profile_id, for_update=True)
        row = await self.db.scalar(self._policy(profile_id).execution_options(populate_existing=True))
        current = (ApplicationAutomationPolicyResponse.model_validate(row) if row
                   else ApplicationAutomationPolicyResponse(application_profile_id=profile_id))
        if current.revision != request.expected_revision:
            raise HTTPException(409, "Application policy changed; reload before saving")
        changes = request.model_dump(exclude_unset=True, exclude={"expected_revision"})
        effective = current.model_dump() | changes
        await self._validate_scripts(profile, effective, changes)
        if all(getattr(current, key) == value for key, value in changes.items()):
            return current

        effective["revision"] = current.revision + 1
        if row is None:
            row = ApplicationAutomationPolicy(org_id=self.org_id, **effective)
            self.db.add(row)
        else:
            for key, value in changes.items():
                setattr(row, key, value)
            row.revision = effective["revision"]
        await self.db.flush()
        return ApplicationAutomationPolicyResponse.model_validate(row)

    async def _validate_scripts(self, profile: ApplicationProfile, effective: dict, changes: dict) -> None:
        enabled = (effective["registration_enabled"], effective["farming_enabled"])
        script_ids = (effective["registration_script_id"], effective["farming_script_id"])
        if any(enabled) and not profile.android_package:
            raise HTTPException(422, "Android package is required to enable automation")
        selected = set()
        for active, field, script_id in zip(enabled, ("registration_script_id", "farming_script_id"), script_ids, strict=True):
            if active and script_id is None:
                raise HTTPException(422, "An enabled operation requires a published script")
            if script_id is not None and (active or field in changes):
                selected.add(script_id)
        if not selected:
            return
        available = set(await self.db.scalars(
            select(Script.id).join(
                ScriptVersion,
                (ScriptVersion.id == Script.current_version_id) & (ScriptVersion.script_id == Script.id)
                & (ScriptVersion.org_id == Script.org_id),
            ).where(Script.org_id == self.org_id, Script.id.in_(selected), Script.is_archived.is_(False)),
        ))
        if available != selected:
            raise HTTPException(422, "Select an active published script in this organization")
