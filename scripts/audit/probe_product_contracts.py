"""Read-only audit: pure DAG roundtrip and mocked legacy webhook classification.

Run from the repository with installed backend dependencies and frontend TypeScript.
No app lifespan, DB session, live HTTP request or Android command is started.
The JSON reports current behavior; a confirmed defect is not reported as a passing
product test. This probe remains useful after a fix: compare its outcomes.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("JWT_SECRET_KEY", "audit-only-not-a-production-secret")

from backend.schemas.dag import VALID_ACTION_TYPES, DAGScript  # noqa: E402
from backend.services.webhook_service import WebhookService  # noqa: E402


async def probe() -> dict:
    exported = json.loads(subprocess.run(
        ["node", str(ROOT / "scripts/audit/probe_builder_contract.cjs")],
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=15,
        cwd=ROOT,
    ).stdout)
    try:
        DAGScript.model_validate(exported["payload"])
        backend_accepted, errors = True, []
    except ValidationError as exc:
        backend_accepted = False
        errors = [{"loc": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
    canonical = {
        "version": "1.0", "entry_node": "start", "nodes": [
            {"id": "start", "action": {"type": "start"}, "on_success": "tap"},
            {"id": "tap", "action": {"type": "tap", "x": 20, "y": 30}, "on_success": "end"},
            {"id": "end", "action": {"type": "end"}},
        ],
    }
    DAGScript.model_validate(canonical)
    fixture = DAGScript.model_validate(exported["canonicalFixture"]).model_dump()
    roundtrip = DAGScript.model_validate(exported["roundtrip"]).model_dump()
    if fixture != roundtrip or set(exported["actionTypes"]) != VALID_ACTION_TYPES:
        raise AssertionError("Builder roundtrip or action catalogue differs from backend contract")
    client = MagicMock()
    client.post = AsyncMock(return_value=MagicMock(status_code=403))
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=client)
    manager.__aexit__ = AsyncMock(return_value=None)
    with patch("backend.services.webhook_service.httpx.AsyncClient", return_value=manager), \
            patch("backend.services.webhook_service.logger") as logger:
        await WebhookService().deliver("https://example.invalid/audit-only", {"event_type": "audit.mock"})
        calls = [call.args[0] for call in logger.info.call_args_list if call.args]
    sources = ["frontend/lib/dag/export.ts", "backend/schemas/dag.py", "backend/services/webhook_service.py"]
    return {
        "schemaVersion": 1, "readOnly": True, "networkWasMocked": True,
        "canonicalControlAccepted": True, "builder": {
            **exported, "backendAccepted": backend_accepted, "backendErrors": errors,
            "canonicalRoundtripAccepted": True, "roundtripPreserved": fixture == roundtrip,
            "actionCatalogueMatchesBackend": True,
        },
        "legacyWebhook": {"receiverStatus": 403, "infoEvents": calls, "calls": client.post.call_count},
        "sourceSha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe()), ensure_ascii=False, indent=2))
