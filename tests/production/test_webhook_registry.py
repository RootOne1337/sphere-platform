"""Persisted webhook list and enable controls under tenant row-level security."""

from sqlalchemy import select

from backend.database.engine import get_db
from backend.database.tenant import bind_tenant_context
from backend.main import app
from backend.models.webhook import Webhook
from backend.services.n8n_webhook_service import n8n_webhook_service


async def test_disabled_webhook_remains_listed_but_is_not_a_delivery_candidate(world, runtime_db):
    async def override_db():
        async with runtime_db.sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    own = world.auth(world.users["org_admin"])
    foreign = world.auth(world.users["foreign"])
    path = "/api/v1/n8n/webhooks"
    created = await world.client.post(path, headers=own, json={
        "name": "Audit webhook", "url": "https://receiver.example.test/hook", "events": ["task.completed"],
    })
    assert created.status_code == 201, created.text
    webhook_id = created.json()["id"]
    assert created.json()["secret"]
    item_path = f"{path}/{webhook_id}"

    disabled = await world.client.patch(item_path, headers=own, json={"is_active": False})
    assert disabled.status_code == 200, disabled.text
    own_list = await world.client.get(path, headers=own)
    assert own_list.status_code == 200
    assert own_list.json()["total"] == 1
    item, = own_list.json()["items"]
    assert item["id"] == webhook_id
    assert item["is_active"] is False
    assert item["secret"] is None

    foreign_list = await world.client.get(path, headers=foreign)
    assert foreign_list.status_code == 200
    assert foreign_list.json()["items"] == [] and foreign_list.json()["total"] == 0
    async with world.sessions() as db:
        foreign_user = await db.get(type(world.users["foreign"]), world.users["foreign"].id)
        foreign_user.role = "org_admin"
        await db.commit()
    foreign_patch = await world.client.patch(item_path, headers=foreign, json={"is_active": True})
    assert foreign_patch.status_code == 404

    async with world.sessions() as db:
        stored = await db.scalar(select(Webhook).where(Webhook.org_id == world.org_a.id))
        assert stored is not None and stored.is_active is False
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_a.id))
        assert await n8n_webhook_service.get_org_webhooks(db, world.org_a.id, active_only=True) == []

    enabled = await world.client.patch(item_path, headers=own, json={"is_active": True})
    assert enabled.status_code == 200, enabled.text
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(world.org_a.id))
        item, = await n8n_webhook_service.get_org_webhooks(db, world.org_a.id, active_only=True)
        assert str(item.id) == webhook_id
