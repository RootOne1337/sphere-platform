#!/usr/bin/env python3
"""Seed the configured enrollment key in the administrator's organization.

Run migrations and scripts/create_admin.py first. Both bootstrap commands use
SPHERE_BOOTSTRAP_ORG_SLUG (default: default). Existing keys are verified, never
reactivated, transferred or silently granted permissions by a repeated seed.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> None:
    from backend.services.enrollment_bootstrap import ensure_configured_enrollment_key

    key_id, org_id = await ensure_configured_enrollment_key()
    print(f"Enrollment key ready: id={key_id}, org_id={org_id}")


if __name__ == "__main__":
    asyncio.run(main())
