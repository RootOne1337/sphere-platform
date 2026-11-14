"""Bounded audit fixture for the documented raw catalog payload budget.

This local ASGI/PostgreSQL check is not the three-series deployed API latency,
server RSS/CPU, WAN, browser heap/cache, or cold-cache release benchmark.
"""

import json
import re
import time
import uuid
from datetime import datetime, timezone

import pytest_asyncio
from sqlalchemy import delete, event, select, update

from backend.models.script import Script, ScriptVersion
from backend.services.script_service import ScriptService

SOURCE_TARGET_BYTES = 480 * 1024
CATALOG_MAX_BYTES = 256 * 1024
ROW_COUNT = 100
NODE_COUNT = 500


@pytest_asyncio.fixture
async def budget_script_ids(world):
    ids = []
    try:
        yield ids
    finally:
        # Release the roughly 48 MiB fixture even after an assertion fails. Only
        # IDs registered by this test in its new disposable tenant are eligible.
        if ids:
            async with world.sessions() as db:
                await db.execute(update(Script).where(Script.id.in_(ids), Script.org_id == world.org_a.id)
                    .values(current_version_id=None))
                await db.execute(delete(ScriptVersion).where(ScriptVersion.script_id.in_(ids),
                    ScriptVersion.org_id == world.org_a.id))
                await db.execute(delete(Script).where(Script.id.in_(ids), Script.org_id == world.org_a.id))
                await db.commit()


def source_fixture(*, heavy):
    nodes = []
    for index in range(NODE_COUNT):
        node = {
            "id": f"n{index}",
            "action": {"type": "start" if index == 0 else "end" if index == NODE_COUNT - 1 else "sleep"},
        }
        if index + 1 < NODE_COUNT:
            node["on_success"] = f"n{index + 1}"
        nodes.append(node)
    source = {"version": "1.0", "entry_node": "n0", "nodes": nodes}
    if heavy:
        # One synthetic string avoids retaining thousands of separate padding
        # buffers during fixture creation; all 500 nodes remain reachable.
        nodes[0]["action"]["synthetic_source_padding"] = ""
        overhead = len(json.dumps(source, sort_keys=True, ensure_ascii=False).encode())
        nodes[0]["action"]["synthetic_source_padding"] = "x" * (SOURCE_TARGET_BYTES - overhead)
    source_size = len(json.dumps(source, sort_keys=True, ensure_ascii=False).encode())
    if heavy:
        assert source_size == SOURCE_TARGET_BYTES
    return source, source_size


async def publish_fixture(world, ids, source, version_number, stamp):
    expected = {}
    async with world.sessions() as db:
        for script_id in ids:
            version = ScriptVersion(
                script_id=script_id, org_id=world.org_a.id, version=version_number,
                dag=source, created_at=stamp, updated_at=stamp,
            )
            db.add(version)
            await ScriptService(db).populate_version_metadata(version)
            assert version.node_count == NODE_COUNT
            expected[str(script_id)] = (str(version.id), version.dag_hash, NODE_COUNT)
            # Explicitly preserve fixed metadata timestamps across the two
            # fixtures. New versions keep the earlier source immutable.
            await db.execute(update(Script).where(Script.id == script_id).values(
                current_version_id=version.id, updated_at=stamp,
            ))
            # Flush each source before the next iteration so the session retains
            # no collection of 100 source dicts or pending JSONB buffers.
            await db.flush()
        await db.commit()
    return expected


async def read_catalog(world, prefix, expected, per_page, monkeypatch):
    catalog_sql = []

    def forbidden(*args, **kwargs):
        raise AssertionError("Catalog attempted source access/hash/legacy serialization")

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "scripts" not in statement and "script_versions" not in statement:
            return  # Ordinary HTTP identity/audit SQL is outside the catalog.
        assert "catalog_scripts AS" in statement, "Unexpected separate script/version query"
        assert not re.search(r"\bdag\b|\bjsonb_\w+|\bjson_\w+", statement, re.IGNORECASE)
        catalog_sql.append(statement)

    with monkeypatch.context() as patch:
        patch.setattr("backend.services.script_service._compute_dag_hash", forbidden)
        patch.setattr("backend.api.v1.scripts.router._to_script_response", forbidden)
        event.listen(world.engine.sync_engine, "before_cursor_execute", capture)
        try:
            started = time.perf_counter()
            response = await world.client.get("/api/v1/scripts/catalog",
                headers=world.auth(world.users["viewer"]),
                params={"query": prefix, "state": "all", "per_page": per_page})
            elapsed_ms = (time.perf_counter() - started) * 1000
        finally:
            event.remove(world.engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text[:512]
    assert response.headers["cache-control"] == "no-store"
    assert len(catalog_sql) == 1
    body = response.json()
    assert body["catalog_schema"] == 1 and body["total"] == ROW_COUNT
    assert len(body["items"]) == min(ROW_COUNT, per_page)
    for item in body["items"]:
        version_id, digest, count = expected[item["id"]]
        assert len(item["name"]) == 64 and len(item["description"]) == 256
        assert item["current_version_id"] == item["current_version"]["id"] == version_id
        assert item["current_version"]["dag_hash"] == digest and item["node_count"] == count
        assert "dag" not in item["current_version"]
    assert b"synthetic_source_padding" not in response.content
    assert len(response.content) <= CATALOG_MAX_BYTES
    return len(response.content), elapsed_ms


async def read_legacy(world, prefix, expected):
    started = time.perf_counter()
    response = await world.client.get("/api/v1/scripts", headers=world.auth(world.users["viewer"]),
        params={"query": prefix, "state": "all", "per_page": ROW_COUNT})
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert response.status_code == 200, response.text[:512]
    body = response.json()
    assert body["total"] == len(body["items"]) == ROW_COUNT
    for item in body["items"]:
        version_id, digest, count = expected[item["id"]]
        version = item["current_version"]
        assert item["current_version_id"] == version["id"] == version_id
        assert version["dag_hash"] == digest and len(version["dag"]["nodes"]) == count
    # Return only scalar measurements. Never retain either full legacy source
    # response or its decoded tree across another request.
    return len(response.content), elapsed_ms


async def test_100_by_500_catalog_raw_budget_and_source_size_independence(world, budget_script_ids, monkeypatch, record_property):
    prefix = "catalog-budget-" + uuid.uuid4().hex[:12]
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ids = budget_script_ids
    async with world.sessions() as db:
        for index in range(ROW_COUNT):
            script = Script(org_id=world.org_a.id, name=f"{prefix}-{index:03}".ljust(64, "n"),
                description="d" * 256, created_at=stamp, updated_at=stamp)
            db.add(script)
            await db.flush()
            ids.append(script.id)
        await db.commit()

    minimal_source, minimal_bytes = source_fixture(heavy=False)
    minimal = await publish_fixture(world, ids, minimal_source, 1, stamp)
    minimal_catalog_bytes, minimal_catalog_ms = await read_catalog(world, prefix, minimal, ROW_COUNT, monkeypatch)
    minimal_legacy_bytes, minimal_legacy_ms = await read_legacy(world, prefix, minimal)

    heavy_source, heavy_bytes = source_fixture(heavy=True)
    heavy = await publish_fixture(world, ids, heavy_source, 2, stamp)
    # The fresh scalar read establishes the 100 current pointer/pair bindings.
    async with world.sessions() as db:
        rows = (await db.execute(select(Script.id, Script.current_version_id, ScriptVersion.id,
            ScriptVersion.dag_hash, ScriptVersion.node_count).join(ScriptVersion,
            Script.current_version_id == ScriptVersion.id).where(Script.id.in_(ids)))).all()
        assert len(rows) == ROW_COUNT
        for script_id, pointer, version_id, digest, count in rows:
            assert pointer == version_id
            assert heavy[str(script_id)] == (str(version_id), digest, count)
    heavy_catalog_bytes, heavy_catalog_ms = await read_catalog(world, prefix, heavy, ROW_COUNT, monkeypatch)
    heavy_legacy_bytes, heavy_legacy_ms = await read_legacy(world, prefix, heavy)
    assert heavy_legacy_bytes > minimal_legacy_bytes
    assert heavy_catalog_bytes == minimal_catalog_bytes
    drop = 1 - heavy_catalog_bytes / heavy_legacy_bytes
    assert drop >= 0.95

    for per_page in [25, 50, 200]:
        await read_catalog(world, prefix, heavy, per_page, monkeypatch)
    for label, value in {
        "fixture_rows": ROW_COUNT, "nodes_per_version": NODE_COUNT,
        "name_characters": 64, "description_characters": 256,
        "minimal_source_utf8_bytes_per_version": minimal_bytes,
        "heavy_source_utf8_bytes_per_version": heavy_bytes,
        "minimal_legacy_raw_utf8_bytes": minimal_legacy_bytes,
        "heavy_legacy_raw_utf8_bytes": heavy_legacy_bytes,
        "minimal_catalog_raw_utf8_bytes": minimal_catalog_bytes,
        "heavy_catalog_raw_utf8_bytes": heavy_catalog_bytes,
        "heavy_raw_reduction_percent": round(drop * 100, 4),
        "local_asgi_minimal_catalog_ms_single_request": round(minimal_catalog_ms, 3),
        "local_asgi_heavy_catalog_ms_single_request": round(heavy_catalog_ms, 3),
        "local_asgi_minimal_legacy_ms_single_request": round(minimal_legacy_ms, 3),
        "local_asgi_heavy_legacy_ms_single_request": round(heavy_legacy_ms, 3),
        "deployed_latency_rss_browser_release_gates_measured": False,
    }.items():
        record_property(label, value)
