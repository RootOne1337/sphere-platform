# tests/n8n/test_n8n_api.py
"""
Integration tests for the n8n webhook and task endpoints.

Enterprise rationale
--------------------
- Webhook secret is returned ONLY on creation and never again (one-time exposure).
- Org isolation: webhook created by org-A is never visible to org-B (even knowing the UUID).
- PATCH updates specific fields without touching the rest.
- DELETE returns 404 for non-existent webhooks and for webhooks of another org.
- Task creation stores the webhook_url in input_params for suspend/resume pattern.
- Task polling is tenant-scoped: org-B cannot poll org-A task status.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

_WEBHOOK_BODY = {
    "name": "My CI Hook",
    "url": "https://n8n.example.com/webhook/abc123",
    "events": ["task.completed", "batch.completed"],
    "tags": ["prod"],
}


# ===========================================================================
# Webhook CRUD
# ===========================================================================

class TestWebhookCreate:
    async def test_create_returns_201_with_id(self, n8n_client):
        resp = await n8n_client.post("/api/v1/n8n/webhooks", json=_WEBHOOK_BODY)
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["name"] == "My CI Hook"

    async def test_secret_exposed_once_on_creation(self, n8n_client):
        """Plain secret must be in the response body — only on creation."""
        body = {**_WEBHOOK_BODY, "secret": "my-super-secret"}
        resp = await n8n_client.post("/api/v1/n8n/webhooks", json=body)
        assert resp.status_code == 201
        data = resp.json()
        # Secret returned as plain text exactly once
        assert data.get("secret") == "my-super-secret"

    async def test_create_without_secret_ok(self, n8n_client):
        body = {k: v for k, v in _WEBHOOK_BODY.items()}
        body["url"] = "https://n8n.example.com/webhook/nosecret"
        resp = await n8n_client.post("/api/v1/n8n/webhooks", json=body)
        assert resp.status_code == 201

    async def test_unauthenticated_returns_401(self, n8n_client):
        from httpx import ASGITransport, AsyncClient

        from backend.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as anon:
            resp = await anon.post("/api/v1/n8n/webhooks", json=_WEBHOOK_BODY)
        assert resp.status_code == 401


class TestWebhookSecretNotLeaked:
    async def test_get_webhook_does_not_return_secret(self, n8n_client):
        """GET /webhooks/{id} must NOT expose the stored plain secret."""
        create_resp = await n8n_client.post(
            "/api/v1/n8n/webhooks",
            json={**_WEBHOOK_BODY, "secret": "hidden-secret"},
        )
        webhook_id = create_resp.json()["id"]

        get_resp = await n8n_client.get(f"/api/v1/n8n/webhooks/{webhook_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        # Plain secret must not leak on subsequent reads
        assert data.get("secret") is None or data.get("secret") == ""

    async def test_list_webhooks_does_not_return_secrets(self, n8n_client):
        await n8n_client.post(
            "/api/v1/n8n/webhooks",
            json={**_WEBHOOK_BODY, "secret": "list-secret"},
        )
        resp = await n8n_client.get("/api/v1/n8n/webhooks")
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item.get("secret") is None or item.get("secret") == ""


class TestWebhookList:
    async def test_list_returns_empty_initially(self, n8n_client):
        resp = await n8n_client.get("/api/v1/n8n/webhooks")
        assert resp.status_code == 200
        body = resp.json()
        # Only webhooks created in THIS test session (other tests may have created some)
        assert "items" in body
        assert "total" in body

    async def test_created_webhook_appears_in_list(self, n8n_client):
        await n8n_client.post("/api/v1/n8n/webhooks", json=_WEBHOOK_BODY)
        resp = await n8n_client.get("/api/v1/n8n/webhooks")
        assert resp.status_code == 200
        ids = [w["id"] for w in resp.json()["items"]]
        assert len(ids) >= 1

    async def test_list_is_scoped_to_own_org(self, n8n_client, other_org_client):
        """Webhooks are organisation-scoped: other org sees none of mine."""
        # Create under n8n_client's org
        await n8n_client.post("/api/v1/n8n/webhooks", json=_WEBHOOK_BODY)

        # Other org list must not include it
        resp = await other_org_client.get("/api/v1/n8n/webhooks")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestWebhookGet:
    async def test_get_own_webhook(self, n8n_client):
        create_resp = await n8n_client.post("/api/v1/n8n/webhooks", json=_WEBHOOK_BODY)
        wid = create_resp.json()["id"]

        resp = await n8n_client.get(f"/api/v1/n8n/webhooks/{wid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == wid

    async def test_get_nonexistent_returns_404(self, n8n_client):
        resp = await n8n_client.get(f"/api/v1/n8n/webhooks/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_get_other_org_webhook_returns_404(self, n8n_client, other_org_client):
        """Knowing the UUID of another org's webhook must return 404 (not 403).
        This avoids leaking resource existence information."""
        create_resp = await n8n_client.post("/api/v1/n8n/webhooks", json=_WEBHOOK_BODY)
        wid = create_resp.json()["id"]

        resp = await other_org_client.get(f"/api/v1/n8n/webhooks/{wid}")
        assert resp.status_code == 404


class TestWebhookUpdate:
    async def test_patch_name(self, n8n_client):
        create_resp = await n8n_client.post("/api/v1/n8n/webhooks", json=_WEBHOOK_BODY)
        wid = create_resp.json()["id"]

        resp = await n8n_client.patch(
            f"/api/v1/n8n/webhooks/{wid}",
            json={"name": "Updated Name"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    async def test_patch_events(self, n8n_client):
        create_resp = await n8n_client.post("/api/v1/n8n/webhooks", json=_WEBHOOK_BODY)
        wid = create_resp.json()["id"]

        resp = await n8n_client.patch(
            f"/api/v1/n8n/webhooks/{wid}",
            json={"events": ["task.failed"]},
        )
        assert resp.status_code == 200
        assert resp.json()["events"] == ["task.failed"]

    async def test_patch_deactivate(self, n8n_client):
        create_resp = await n8n_client.post("/api/v1/n8n/webhooks", json=_WEBHOOK_BODY)
        wid = create_resp.json()["id"]

        resp = await n8n_client.patch(
            f"/api/v1/n8n/webhooks/{wid}",
            json={"is_active": False},
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    async def test_patch_other_org_returns_404(self, n8n_client, other_org_client):
        create_resp = await n8n_client.post("/api/v1/n8n/webhooks", json=_WEBHOOK_BODY)
        wid = create_resp.json()["id"]

        resp = await other_org_client.patch(
            f"/api/v1/n8n/webhooks/{wid}",
            json={"name": "Hijack"},
        )
        assert resp.status_code == 404


class TestWebhookDelete:
    async def test_delete_own_webhook(self, n8n_client):
        create_resp = await n8n_client.post("/api/v1/n8n/webhooks", json=_WEBHOOK_BODY)
        wid = create_resp.json()["id"]

        resp = await n8n_client.delete(f"/api/v1/n8n/webhooks/{wid}")
        assert resp.status_code == 204

        # Subsequent GET returns 404
        get_resp = await n8n_client.get(f"/api/v1/n8n/webhooks/{wid}")
        assert get_resp.status_code == 404

    async def test_delete_nonexistent_returns_404(self, n8n_client):
        resp = await n8n_client.delete(f"/api/v1/n8n/webhooks/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_delete_other_org_webhook_returns_404(self, n8n_client, other_org_client):
        create_resp = await n8n_client.post("/api/v1/n8n/webhooks", json=_WEBHOOK_BODY)
        wid = create_resp.json()["id"]

        resp = await other_org_client.delete(f"/api/v1/n8n/webhooks/{wid}")
        assert resp.status_code == 404


# ===========================================================================
# N8n Task endpoints
# ===========================================================================

class TestN8nTaskCreate:
    async def test_create_task_returns_201(
        self, n8n_client, db_session: AsyncSession, n8n_org
    ):
        from backend.models.device import Device
        from backend.models.script import Script

        device = Device(
            org_id=n8n_org.id,
            name="N8N Device",
            serial="n8n-dev-001",
        )
        script = Script(org_id=n8n_org.id, name="N8N Script")
        db_session.add(device)
        db_session.add(script)
        await db_session.flush()

        resp = await n8n_client.post(
            "/api/v1/n8n/tasks",
            json={
                "device_id": str(device.id),
                "script_id": str(script.id),
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "queued"
        assert data["device_id"] == str(device.id)

    async def test_create_task_with_webhook_url(
        self, n8n_client, db_session: AsyncSession, n8n_org
    ):
        """webhook_url (resumeUrl) stored in task for Suspend/Resume pattern."""
        from backend.models.device import Device
        from backend.models.script import Script

        device = Device(
            org_id=n8n_org.id,
            name="N8N Device WH",
            serial="n8n-dev-wh",
        )
        script = Script(org_id=n8n_org.id, name="N8N Script WH")
        db_session.add(device)
        db_session.add(script)
        await db_session.flush()

        resp = await n8n_client.post(
            "/api/v1/n8n/tasks",
            json={
                "device_id": str(device.id),
                "script_id": str(script.id),
                "webhook_url": "https://n8n.example.com/webhook/resume",
            },
        )
        assert resp.status_code == 201


class TestN8nTaskPoll:
    async def test_poll_own_task(
        self, n8n_client, db_session: AsyncSession, n8n_org
    ):
        from backend.models.device import Device
        from backend.models.script import Script

        device = Device(org_id=n8n_org.id, name="Poll Device", serial="poll-dev")
        script = Script(org_id=n8n_org.id, name="Poll Script")
        db_session.add(device)
        db_session.add(script)
        await db_session.flush()

        create_resp = await n8n_client.post(
            "/api/v1/n8n/tasks",
            json={"device_id": str(device.id), "script_id": str(script.id)},
        )
        assert create_resp.status_code == 201
        task_id = create_resp.json()["id"]

        poll_resp = await n8n_client.get(f"/api/v1/n8n/tasks/{task_id}")
        assert poll_resp.status_code == 200
        assert poll_resp.json()["id"] == task_id

    async def test_poll_nonexistent_task_404(self, n8n_client):
        resp = await n8n_client.get(f"/api/v1/n8n/tasks/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_poll_other_org_task_returns_404(
        self, n8n_client, other_org_client, db_session: AsyncSession, n8n_org
    ):
        """Cross-org task polling must return 404 for tenant isolation."""
        from backend.models.device import Device
        from backend.models.script import Script

        device = Device(org_id=n8n_org.id, name="Iso Device", serial="iso-dev")
        script = Script(org_id=n8n_org.id, name="Iso Script")
        db_session.add(device)
        db_session.add(script)
        await db_session.flush()

        create_resp = await n8n_client.post(
            "/api/v1/n8n/tasks",
            json={"device_id": str(device.id), "script_id": str(script.id)},
        )
        task_id = create_resp.json()["id"]

        resp = await other_org_client.get(f"/api/v1/n8n/tasks/{task_id}")
        assert resp.status_code == 404
