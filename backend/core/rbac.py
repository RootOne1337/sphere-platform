# backend/core/rbac.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-3. Матрица ролей и разрешений.
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    SUPER_ADMIN = "super_admin"
    ORG_OWNER = "org_owner"
    ORG_ADMIN = "org_admin"
    DEVICE_MANAGER = "device_manager"
    SCRIPT_RUNNER = "script_runner"
    VIEWER = "viewer"
    API_USER = "api_user"


# Матрица разрешений: permission → список ролей, которым разрешено.
# Более высокие роли включают права более низких НЕ через hierarchy, а явно в каждом списке —
# это проще в отладке и аудите (нет скрытых inherit-цепочек).
PERMISSIONS: dict[str, list[Role]] = {
    # ── Устройства ──────────────────────────────────────────────────────────
    "device:read": [
        Role.VIEWER, Role.SCRIPT_RUNNER, Role.DEVICE_MANAGER,
        Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN,
    ],
    "device:write": [
        Role.DEVICE_MANAGER, Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN,
    ],
    "device:delete": [Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    "device:bulk_action": [
        Role.DEVICE_MANAGER, Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN,
    ],

    # ── Скрипты ─────────────────────────────────────────────────────────────
    "script:read": [
        Role.VIEWER, Role.SCRIPT_RUNNER, Role.DEVICE_MANAGER,
        Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN,
    ],
    "script:write": [
        Role.DEVICE_MANAGER, Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN,
    ],
    "script:execute": [
        Role.SCRIPT_RUNNER, Role.DEVICE_MANAGER,
        Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN,
    ],

    # ── VPN ─────────────────────────────────────────────────────────────────
    "vpn:read": [
        Role.VIEWER, Role.DEVICE_MANAGER,
        Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN,
    ],
    "vpn:write": [Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    "vpn:mass_operation": [Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],

    # ── Пользователи ────────────────────────────────────────────────────────
    "user:read": [Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    "user:write": [Role.ORG_OWNER, Role.SUPER_ADMIN],

    # ── Мониторинг ──────────────────────────────────────────────────────────
    "monitoring:read": [
        Role.VIEWER, Role.SCRIPT_RUNNER, Role.DEVICE_MANAGER,
        Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN,
    ],

    # ── API Keys ─────────────────────────────────────────────────────────────
    "api_key:read": [Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    "api_key:write": [Role.ORG_OWNER, Role.SUPER_ADMIN],

    # ── Аудит ───────────────────────────────────────────────────────────────
    "audit:read": [Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
}


def has_permission(user_role: str, permission: str) -> bool:
    """Проверить, есть ли у роли указанное разрешение."""
    allowed_roles = PERMISSIONS.get(permission, [])
    try:
        return Role(user_role) in allowed_roles
    except ValueError:
        return False
