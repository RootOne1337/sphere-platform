"""Stored JSONB metadata, one-snapshot catalog reads, and real tenant boundaries."""

import importlib.util
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from backend.database.tenant import bind_tenant_context
from backend.models.script import Script, ScriptVersion
from backend.models.user import User
from backend.schemas.script import UpdateScriptRequest
from backend.services.script_service import ScriptService, _compute_dag_hash, _compute_dag_metadata


def dag_fixture(label="source", number=1, count=2, padding=""):
    nodes = []
    for index in range(count):
        node = {"id": f"n{index}", "action": {
            "type": "start" if index == 0 else "end" if index == count - 1 else "sleep",
            "unknown": {"unicode": "Привет 雪", "numbers": [number, 0, False, None, {"fraction": number}]},
            "private_marker": padding,
        }}
        if index + 1 < count:
            node["on_success"] = f"n{index + 1}"
        if node["action"]["type"] == "sleep":
            node["action"]["ms"] = 1
        nodes.append(node)
    return {"version": "1.0", "name": label, "entry_node": "n0", "nodes": nodes}


@pytest.mark.parametrize("count", [2, 5, 500])
def test_catalog_fixture_actions_follow_publication_contract(count):
    from backend.services.script_service import validate_publication_dag

    # Numeric round-trip payloads remain unknown preserved fields. Executable
    # sleep actions must independently provide their required duration.
    source = dag_fixture(number=1e20, count=count)
    validated = validate_publication_dag(source)
    assert len(validated["nodes"]) == count
    assert validated["nodes"][0]["action"]["unknown"]["numbers"][0] == 1e20


async def test_historical_missing_action_parameters_remain_readable_and_rollback_preserves_source(catalog_ready):
    w = catalog_ready
    source = dag_fixture(count=5)
    for node in source["nodes"]:
        node["action"].pop("ms", None)
    async with w.sessions() as db:
        script = await add_catalog_script(db, w.org_a.id, name="historical incomplete actions", source=source)
        await db.commit()
        script_id, original_id = str(script.id), str(script.current_version_id)
    headers = w.auth(w.users["org_admin"])
    read = await w.client.get(f"/api/v1/scripts/{script_id}/versions/{original_id}", headers=headers)
    assert read.status_code == 200 and read.json()["dag"] == source
    rejected = await w.client.put(f"/api/v1/scripts/{script_id}", headers=headers,
        json={"name": "must not be assigned", "dag": source, "expected_current_version_id": original_id})
    assert rejected.status_code == 422
    assert all(row["type"] == "action_parameter.required" for row in rejected.json()["detail"])
    current = await w.client.get(f"/api/v1/scripts/{script_id}", headers=headers)
    assert current.status_code == 200
    assert current.json()["name"] == "historical incomplete actions"
    assert current.json()["current_version_id"] == original_id
    rolled = await w.client.post(f"/api/v1/scripts/{script_id}/versions/{original_id}/rollback", headers=headers,
        json={"expected_current_version_id": original_id})
    assert rolled.status_code == 200, rolled.text
    rolled_id = rolled.json()["current_version_id"]
    assert rolled_id != original_id
    restored = await w.client.get(f"/api/v1/scripts/{script_id}/versions/{rolled_id}", headers=headers)
    assert restored.status_code == 200 and restored.json()["dag"] == source
    assert await assert_persisted_pair(w, script_id, rolled_id, 5) == _compute_dag_hash(source)


@pytest_asyncio.fixture
async def catalog_ready(world):
    # The shared legacy fixture intentionally has a NULL pair; prepare only the
    # random tenant belonging to this test, without changing shared fixtures.
    async with world.sessions() as db:
        version = await db.get(ScriptVersion, world.version.id)
        version.dag_hash, version.node_count = _compute_dag_metadata(version.dag)
        await db.commit()
    return world


async def add_catalog_script(db, org_id, *, name, description=None, archived=False, source=None, stamp=None):
    script = Script(org_id=org_id, name=name, description=description, is_archived=archived)
    if stamp:
        script.created_at = script.updated_at = stamp
    db.add(script)
    await db.flush()
    if source is not None:
        version = ScriptVersion(script_id=script.id, org_id=org_id, version=1, dag=source)
        db.add(version)
        await ScriptService(db).populate_version_metadata(version)
        script.current_version_id = version.id
        if stamp:
            # A pointer update invokes the model's timestamp onupdate; explicitly
            # restore the tie after that flush rather than assigning an equal
            # identity-map value, which SQLAlchemy may consider unchanged.
            await db.flush()
            await db.execute(update(Script).where(Script.id == script.id).values(updated_at=stamp))
    return script


async def assert_persisted_pair(world, script_id, version_id, count):
    # A fresh session is essential: neither the input dict nor an identity-map
    # object establishes the Python representation seen after JSONB storage.
    async with world.sessions() as db:
        version = await db.get(ScriptVersion, uuid.UUID(version_id))
        assert version.dag_hash == _compute_dag_hash(version.dag)
        assert version.node_count == len(version.dag["nodes"]) == count
        stored_hash = version.dag_hash
    headers = world.auth(world.users["viewer"])
    source = await world.client.get(f"/api/v1/scripts/{script_id}/versions/{version_id}", headers=headers)
    assert source.status_code == 200, source.text
    assert source.json()["dag_hash"] == stored_hash
    catalog = await world.client.get("/api/v1/scripts/catalog", headers=headers, params={"state": "all"})
    assert catalog.status_code == 200, catalog.text
    item = next(row for row in catalog.json()["items"] if row["id"] == script_id)
    assert item["current_version_id"] == item["current_version"]["id"] == version_id
    assert item["current_version"]["dag_hash"] == stored_hash and item["node_count"] == count
    assert "dag" not in item["current_version"]
    return stored_hash


@pytest.mark.parametrize("number", [1e20, -0.0, 0.12345678901234568, 1.2345678901234568e-20])
async def test_postgres_roundtrip_create_update_rollback_and_legacy_dedup(catalog_ready, number):
    w = catalog_ready
    headers = w.auth(w.users["org_admin"])
    candidate = dag_fixture(number=number)
    created = await w.client.post("/api/v1/scripts", headers=headers, json={"name": "numeric metadata", "dag": candidate})
    assert created.status_code == 201, created.text
    body = created.json()
    script_id, original = body["id"], body["current_version_id"]
    original_hash = await assert_persisted_pair(w, script_id, original, 2)
    assert body["current_version"]["dag_hash"] == original_hash

    # Retain the existing candidate-vs-stored hash dedup rule even where JSONB
    # changes 1e20 or -0.0. Persisted metadata must not silently replace that rule.
    async with w.sessions() as db:
        candidate_hash = ScriptService(db)._validate_dag(candidate)[1]
    same = await w.client.put(f"/api/v1/scripts/{script_id}", headers=headers, json={"dag": candidate})
    assert same.status_code == 200, same.text
    same_id = same.json()["current_version_id"]
    assert (same_id == original) is (candidate_hash == original_hash)
    await assert_persisted_pair(w, script_id, same_id, 2)

    changed = await w.client.put(f"/api/v1/scripts/{script_id}", headers=headers,
        json={"dag": dag_fixture(label="five", number=number, count=5), "expected_current_version_id": same_id})
    assert changed.status_code == 200, changed.text
    changed_id = changed.json()["current_version_id"]
    changed_hash = await assert_persisted_pair(w, script_id, changed_id, 5)
    rename = await w.client.put(f"/api/v1/scripts/{script_id}", headers=headers, json={"name": "renamed metadata"})
    assert rename.status_code == 200 and rename.json()["current_version_id"] == changed_id
    assert await assert_persisted_pair(w, script_id, changed_id, 5) == changed_hash

    rollback = await w.client.post(f"/api/v1/scripts/{script_id}/versions/{original}/rollback", headers=headers,
        json={"expected_current_version_id": changed_id})
    assert rollback.status_code == 200, rollback.text
    rolled_id = rollback.json()["current_version_id"]
    assert rolled_id not in {original, same_id, changed_id}
    assert await assert_persisted_pair(w, script_id, rolled_id, 2) == original_hash
    async with w.sessions() as db:
        old = await db.get(ScriptVersion, uuid.UUID(original))
        assert old.dag_hash == original_hash and old.node_count == 2


async def test_catalog_matches_legacy_search_state_order_and_empty_pages(catalog_ready):
    w = catalog_ready
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with w.sessions() as db:
        owned = []
        for name, description, archived, source in [
            ("Catalog-Fixture alpha", None, False, {"nodes": []}),
            ("catalog-fixture beta", "DeScRiPtIoN OnLy", False, {"nodes": [1, 2]}),
            ("catalog-fixture gamma", None, True, {"nodes": [1] * 5}),
            ("catalog-fixture unpublished", None, False, None),
        ]:
            owned.append(await add_catalog_script(db, w.org_a.id, name=name, description=description,
                archived=archived, source=source, stamp=stamp))
        await add_catalog_script(db, w.org_b.id, name="Catalog-Fixture alpha", source={"nodes": []}, stamp=stamp)
        await db.commit()
    headers = w.auth(w.users["viewer"])
    for state in ["active", "archived", "all"]:
        for query in ["CATALOG-FIXTURE", "description only", "catalog-fixture _", "catalog-fixture %", "absent marker"]:
            for page, per_page in [(1, 1), (2, 1), (20, 1), (1, 25), (1, 50), (1, 100), (1, 200)]:
                params = {"state": state, "query": query, "page": page, "per_page": per_page}
                legacy = await w.client.get("/api/v1/scripts", headers=headers, params=params)
                catalog = await w.client.get("/api/v1/scripts/catalog", headers=headers, params=params)
                assert legacy.status_code == catalog.status_code == 200, catalog.text
                old, new = legacy.json(), catalog.json()
                assert {key: new[key] for key in ("total", "page", "per_page", "pages")} == {
                    key: old[key] for key in ("total", "page", "per_page", "pages")}
                assert [row["id"] for row in new["items"]] == [row["id"] for row in old["items"]]
                assert catalog.headers["cache-control"] == "no-store"
    result = (await w.client.get("/api/v1/scripts/catalog", headers=headers,
        params={"state": "all", "query": "catalog-fixture"})).json()
    assert [row["id"] for row in result["items"]] == sorted(str(script.id) for script in owned)
    unpublished = next(row for row in result["items"] if "unpublished" in row["name"])
    assert unpublished["current_version_id"] is unpublished["current_version"] is unpublished["node_count"] is None
    zero = next(row for row in result["items"] if row["name"].endswith("alpha"))
    assert zero["node_count"] == 0 and zero["current_version"] is not None


@pytest.mark.parametrize("bad_pointer", ["null_metadata", "other_script", "other_org", "foreign_version_org"])
async def test_catalog_bad_metadata_or_unowned_pointer_is_503_without_source_fallback(world, bad_pointer):
    w = world
    if bad_pointer != "null_metadata":
        async with w.sessions() as db:
            if bad_pointer == "foreign_version_org":
                version = ScriptVersion(script_id=w.script.id, org_id=w.org_b.id, dag={"nodes": []},
                    dag_hash=_compute_dag_hash({"nodes": []}), node_count=0)
                db.add(version)
                await db.flush()
            else:
                owner = await add_catalog_script(db, w.org_a.id if bad_pointer == "other_script" else w.org_b.id,
                    name="foreign pointer", source={"nodes": []})
                version = await db.get(ScriptVersion, owner.current_version_id)
            script = await db.get(Script, w.script.id)
            script.current_version_id = version.id
            await db.commit()
    response = await w.client.get("/api/v1/scripts/catalog", headers=w.auth(w.users["viewer"]),
        params={"query": "audit-script"})
    assert response.status_code == 503 and response.json() == {"detail": {"code": "script_catalog_metadata_unavailable"}}
    assert response.headers["cache-control"] == "no-store"
    assert "nodes" not in response.text and "dag" not in response.text
    # Rollout retains the old list even while historical metadata is missing.
    legacy = await w.client.get("/api/v1/scripts", headers=w.auth(w.users["viewer"]))
    assert legacy.status_code == 200


async def test_catalog_permission_and_nonowner_rls_apply_to_items_and_total(catalog_ready, runtime_db):
    w, r = catalog_ready, runtime_db
    async with w.sessions() as db:
        await add_catalog_script(db, w.org_b.id, name="audit-script", source={"nodes": []})
        denied = User(org_id=w.org_a.id, email=f"catalog-denied-{w.suffix}@example.org",
            role="api_user", password_hash="unused-local-fixture")
        db.add(denied)
        await db.commit()
    assert (await w.client.get("/api/v1/scripts/catalog", headers=w.auth(denied))).status_code == 403
    for org in [w.org_a, w.org_b]:
        async with r.sessions() as db:
            await bind_tenant_context(db, str(org.id))
            items, total = await ScriptService(db).list_script_catalog(org.id)
            assert total == len(items) == 1 and items[0].org_id == org.id
            # Explicit foreign org filtering cannot override the connection's RLS.
            other_org = w.org_b if org.id == w.org_a.id else w.org_a
            foreign, foreign_total = await ScriptService(db).list_script_catalog(other_org.id)
            assert foreign == [] and foreign_total == 0


async def test_catalog_100_rows_never_reads_source_and_payload_is_independent(catalog_ready, monkeypatch):
    w = catalog_ready
    async with w.sessions() as db:
        for index in range(100):
            await add_catalog_script(db, w.org_a.id, name=f"source-free-fixture {index:03}",
                description="constant metadata", source=dag_fixture(padding="private-small"))
        await db.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("Catalog recomputed a source hash")

    monkeypatch.setattr("backend.services.script_service._compute_dag_hash", forbidden)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        assert not re.search(r"\bdag\b|\bjsonb_\w+|\bjson_\w+", statement, re.IGNORECASE)

    async def read():
        statements.clear()
        event.listen(w.engine.sync_engine, "before_cursor_execute", capture)
        try:
            async with w.sessions() as db:
                items, total = await ScriptService(db).list_script_catalog(w.org_a.id, "source-free-fixture", per_page=100)
                assert total == len(items) == 100
        finally:
            event.remove(w.engine.sync_engine, "before_cursor_execute", capture)
        assert len(statements) == 1
        body = json.dumps([item.model_dump(mode="json") for item in items], ensure_ascii=False).encode()
        assert b"private-small" not in body and b"private-large" not in body
        return len(body)

    small_size = await read()
    # Change only arbitrary action payloads in these isolated historical fixture
    # versions. The derived pair stays valid; the metadata shape/length is fixed.
    monkeypatch.undo()
    async with w.sessions() as db:
        versions = list(await db.scalars(select(ScriptVersion).join(Script, Script.id == ScriptVersion.script_id)
            .where(Script.org_id == w.org_a.id, Script.name.like("source-free-fixture%"))))
        for version in versions:
            version.dag = dag_fixture(padding="private-large" + "x" * 4096)
            await ScriptService(db).populate_version_metadata(version)
        await db.commit()
    monkeypatch.setattr("backend.services.script_service._compute_dag_hash", forbidden)
    assert await read() == small_size
    statements.clear()
    event.listen(w.engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with w.sessions() as db:
            items, total = await ScriptService(db).list_script_catalog(w.org_a.id, "source-free-fixture", page=9, per_page=25)
            assert items == [] and total == 100
    finally:
        event.remove(w.engine.sync_engine, "before_cursor_execute", capture)
    assert len(statements) == 1


async def test_catalog_publication_and_archive_are_coherent_before_and_after_commit(catalog_ready):
    w = catalog_ready
    async with w.sessions() as writer, w.sessions() as reader:
        script = await ScriptService(writer).update_script(w.script.id, w.org_a.id, w.users["org_admin"].id,
            UpdateScriptRequest(dag=dag_fixture(count=5)))
        new_id = script.current_version_id
        await writer.flush()
        before, total = await ScriptService(reader).list_script_catalog(w.org_a.id)
        assert total == 1 and before[0].current_version_id == w.version.id and before[0].node_count == 0
        await writer.commit()
        after, total = await ScriptService(reader).list_script_catalog(w.org_a.id)
        assert total == 1 and after[0].current_version_id == after[0].current_version.id == new_id
        assert after[0].node_count == 5
        assert after[0].current_version.dag_hash == _compute_dag_hash((await reader.get(ScriptVersion, new_id)).dag)
        await ScriptService(writer).archive_script(w.script.id, w.org_a.id, new_id)
        await writer.flush()
        active_before, total = await ScriptService(reader).list_script_catalog(w.org_a.id)
        assert total == 1 and active_before[0].is_archived is False
        await writer.commit()
        active_after, total = await ScriptService(reader).list_script_catalog(w.org_a.id)
        archived, archived_total = await ScriptService(reader).list_script_catalog(w.org_a.id, state="archived")
        assert active_after == [] and total == 0
        assert archived_total == 1 and archived[0].is_archived is True and archived[0].current_version_id == new_id


async def test_catalog_additive_migration_accepts_old_writers_and_enforces_pair(world):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261006_script_catalog_metadata.py"
    spec = importlib.util.spec_from_file_location("script_catalog_metadata_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def exercise(connection):
        schema = "catalog_metadata_" + uuid.uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(text("CREATE TABLE script_versions(id uuid PRIMARY KEY, dag jsonb NOT NULL)"))
        original_id = uuid.uuid4()
        connection.execute(text("INSERT INTO script_versions VALUES (:id, '{\"nodes\": []}'::jsonb)"), {"id": original_id})
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert all(column["nullable"] for column in inspect(connection).get_columns("script_versions")
            if column["name"] in {"dag_hash", "node_count"})
        row = connection.execute(text("SELECT * FROM script_versions WHERE id=:id"), {"id": original_id}).mappings().one()
        assert row["dag"] == {"nodes": []} and row["dag_hash"] is row["node_count"] is None
        connection.execute(text("INSERT INTO script_versions(id,dag) VALUES (:id,'{}'::jsonb)"), {"id": uuid.uuid4()})
        for digest, count in [("a" * 64, None), (None, 0), ("A" * 64, 0), ("g" * 64, 0), ("a" * 63, 0), ("a" * 64, -1)]:
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text("INSERT INTO script_versions(id,dag,dag_hash,node_count) VALUES (:id,'{}'::jsonb,:hash,:count)"),
                    {"id": uuid.uuid4(), "hash": digest, "count": count})
        connection.execute(text("UPDATE script_versions SET dag_hash=:hash,node_count=0 WHERE id=:id"),
            {"id": original_id, "hash": _compute_dag_hash({"nodes": []})})
        migration.downgrade()
        assert {column["name"] for column in inspect(connection).get_columns("script_versions")} == {"id", "dag"}
        assert connection.scalar(text("SELECT count(*) FROM script_versions")) == 2
        migration.upgrade()
    async with world.engine.connect() as db:
        transaction = await db.begin()
        try:
            await db.run_sync(exercise)
        finally:
            await transaction.rollback()
