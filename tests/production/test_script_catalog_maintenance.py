"""Preserved-source publication and bounded metadata backfill on isolated PostgreSQL."""

import copy
import re
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select

from backend.database.tenant import bind_tenant_context
from backend.models.script import Script, ScriptVersion
from backend.services.script_service import _compute_dag_hash, _compute_dag_metadata
from backend.services.script_version_admin import publish_preserved_source
from scripts import backfill_script_metadata as maintenance
from scripts.publish_script_source import patch_source


def historical_source(count=2, padding=""):
    # Intentionally outside the current DAG schema. Maintenance must preserve it
    # rather than normalize old actions, unknown fields, or a historical loop.
    return {
        "old_schema": "preserve-me", "unknown": {"unicode": "Снег 雪", "zero": 0, "off": False, "null": None},
        "nodes": [{"id": f"old-{index}", "action": {"type": "retired_action", "private": padding,
                   "nested": {"number": 1e20, "negative_zero": -0.0}}, "on_success": "old-0"}
                  for index in range(count)],
    }


async def snapshot(world):
    async with world.sessions() as db:
        script = await db.get(Script, world.script.id)
        versions = list(await db.scalars(select(ScriptVersion).where(
            ScriptVersion.script_id == world.script.id).order_by(ScriptVersion.id)))
        return {
            "script": {key: copy.deepcopy(getattr(script, key)) for key in
                       ["id", "org_id", "name", "current_version_id", "created_at", "updated_at", "is_archived"]},
            "versions": {version.id: {key: copy.deepcopy(getattr(version, key)) for key in
                         ["id", "org_id", "script_id", "version", "dag", "notes", "created_at", "updated_at",
                          "dag_hash", "node_count"]} for version in versions},
        }


def unchanged_source_fields(before, after):
    assert after["script"] == before["script"]
    assert after["versions"].keys() == before["versions"].keys()
    for version_id, old in before["versions"].items():
        assert {key: value for key, value in after["versions"][version_id].items()
                if key not in {"dag_hash", "node_count"}} == {
                    key: value for key, value in old.items() if key not in {"dag_hash", "node_count"}}


async def add_history(world, sources):
    stamp = datetime(2020, 4, 5, 6, 7, 8, tzinfo=timezone.utc)
    async with world.sessions() as db:
        versions = [ScriptVersion(script_id=world.script.id, org_id=world.org_a.id, version=index + 2,
                    dag=source, notes="historical source", created_at=stamp, updated_at=stamp)
                    for index, source in enumerate(sources)]
        db.add_all(versions)
        await db.commit()
        return [version.id for version in versions]


async def test_maintenance_publication_preserves_history_and_hashes_the_saved_source(world):
    before = await snapshot(world)
    candidate = historical_source()
    original_candidate = copy.deepcopy(candidate)
    async with world.sessions() as db:
        version = await publish_preserved_source(db, org_id=world.org_a.id, script_id=world.script.id,
            expected_current_version_id=world.version.id, dag=candidate, notes="preserved legacy source")
        assert version.id != world.version.id and version.version == 2
        new_id = version.id
        await db.commit()
    assert candidate == original_candidate
    after = await snapshot(world)
    assert after["versions"][world.version.id] == before["versions"][world.version.id]
    assert after["script"]["current_version_id"] == new_id
    stored = after["versions"][new_id]
    assert stored["dag"] == candidate and stored["notes"] == "preserved legacy source"
    assert stored["dag_hash"] == _compute_dag_hash(stored["dag"])
    assert stored["node_count"] == len(candidate["nodes"]) == 2
    assert stored["dag"]["old_schema"] == "preserve-me"
    assert stored["dag"]["nodes"][0]["action"]["type"] == "retired_action"


@pytest.mark.parametrize("condition", ["none", "stale", "foreign_org", "archived"])
async def test_maintenance_publication_rejects_wrong_precondition_or_scope_without_writing(world, condition):
    if condition == "archived":
        async with world.sessions() as db:
            script = await db.get(Script, world.script.id)
            script.is_archived = True
            await db.commit()
    before = await snapshot(world)
    expected = None if condition == "none" else uuid.uuid4() if condition == "stale" else world.version.id
    async with world.sessions() as db:
        with pytest.raises(HTTPException) as refused:
            await publish_preserved_source(db,
                org_id=world.org_b.id if condition == "foreign_org" else world.org_a.id,
                script_id=world.script.id, expected_current_version_id=expected,
                dag=historical_source(), notes="must not persist")
        assert refused.value.status_code == (404 if condition == "foreign_org" else 409)
        await db.rollback()
    assert await snapshot(world) == before


async def test_maintenance_exact_none_precondition_publishes_only_an_unpublished_parent(world):
    async with world.sessions() as db:
        script = Script(org_id=world.org_a.id, name="unpublished maintenance fixture")
        db.add(script)
        await db.flush()
        script_id = script.id
        version = await publish_preserved_source(db, org_id=world.org_a.id, script_id=script_id,
            expected_current_version_id=None, dag=historical_source(0), notes="first source")
        version_id = version.id
        await db.commit()
    async with world.sessions() as db:
        script = await db.get(Script, script_id)
        version = await db.get(ScriptVersion, version_id)
        assert script.current_version_id == version_id and version.version == 1 and version.node_count == 0
        assert version.dag_hash == _compute_dag_hash(version.dag)
        with pytest.raises(HTTPException) as stale_none:
            await publish_preserved_source(db, org_id=world.org_a.id, script_id=script_id,
                expected_current_version_id=None, dag=historical_source(), notes="must not persist")
        assert stale_none.value.status_code == 409
        await db.rollback()


async def test_maintenance_publication_and_pointer_are_rolled_back_together(world):
    before = await snapshot(world)
    async with world.sessions() as db:
        await publish_preserved_source(db, org_id=world.org_a.id, script_id=world.script.id,
            expected_current_version_id=world.version.id, dag=historical_source(), notes="rolled back")
        await db.rollback()
    assert await snapshot(world) == before


async def test_maintenance_publication_works_under_an_explicit_nonowner_tenant(runtime_db):
    r, w = runtime_db, runtime_db.world
    async with r.sessions() as db:
        await bind_tenant_context(db, str(w.org_a.id))
        version = await publish_preserved_source(db, org_id=w.org_a.id, script_id=w.script.id,
            expected_current_version_id=w.version.id, dag=historical_source(), notes="runtime tenant maintenance")
        new_id = version.id
        await db.commit()
    async with w.sessions() as db:
        saved = await db.get(ScriptVersion, new_id)
        assert saved.org_id == w.org_a.id and saved.script_id == w.script.id
        assert saved.dag_hash == _compute_dag_hash(saved.dag) and saved.node_count == 2


async def test_backfill_dry_apply_and_idempotent_repeat_preserve_all_source_identity_fields(world):
    await add_history(world, [historical_source(1), historical_source(5)])
    async with world.sessions() as db:
        foreign = Script(org_id=world.org_b.id, name="foreign maintenance fixture")
        db.add(foreign)
        await db.flush()
        foreign_version = ScriptVersion(org_id=world.org_b.id, script_id=foreign.id, dag=historical_source())
        db.add(foreign_version)
        await db.commit()
        foreign_id = foreign_version.id
    before = await snapshot(world)
    dry = await maintenance.backfill(world.sessions, org_id=world.org_a.id, max_versions=100)
    assert dry["scanned"] == dry["would_update"] == 3 and dry["updated"] == dry["failed"] == 0
    assert dry["stopped"] == "complete" and await snapshot(world) == before
    applied = await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True, max_versions=100)
    assert applied["updated"] == applied["would_update"] == 3 and applied["failed"] == 0
    assert applied["source_changed"] is False and applied["tasks_created"] == 0
    after = await snapshot(world)
    unchanged_source_fields(before, after)
    for saved in after["versions"].values():
        assert (saved["dag_hash"], saved["node_count"]) == _compute_dag_metadata(saved["dag"])
    repeated = await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True, max_versions=100)
    assert repeated["scanned"] == repeated["updated"] == repeated["would_update"] == repeated["failed"] == 0
    assert repeated["stopped"] == "complete" and await snapshot(world) == after
    async with world.sessions() as db:
        untouched = await db.get(ScriptVersion, foreign_id)
        assert untouched.dag_hash is untouched.node_count is None


async def test_backfill_version_budget_reports_cursor_and_resumes_without_skipping(world):
    await add_history(world, [historical_source(count) for count in range(1, 5)])
    before = await snapshot(world)
    ids = sorted(before["versions"])
    first = await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True, max_versions=2)
    assert first["scanned"] == first["updated"] == 2 and first["stopped"] == "version_budget"
    assert first["after"] == str(ids[1])
    resumed = await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True,
        after=uuid.UUID(first["after"]), max_versions=100)
    assert resumed["scanned"] == resumed["updated"] == 3 and resumed["stopped"] == "complete"
    assert resumed["after"] == str(ids[-1])
    after = await snapshot(world)
    unchanged_source_fields(before, after)
    assert all(row["dag_hash"] == _compute_dag_hash(row["dag"]) for row in after["versions"].values())


async def test_backfill_time_budget_keeps_cursor_before_the_unread_source(world, monkeypatch):
    before = await snapshot(world)
    ticks = iter([0.0, 0.0, 0.0, 2.0])
    # Replace this module's clock reference, never the shared asyncio clock.
    monkeypatch.setattr(maintenance, "time", SimpleNamespace(monotonic=lambda: next(ticks, 2.0)))
    result = await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True, max_seconds=1)
    assert result["stopped"] == "time_budget" and result["after"] is None
    assert result["scanned"] == result["updated"] == result["failed"] == 0
    assert await snapshot(world) == before


async def test_backfill_contested_version_stops_before_cursor_and_can_be_retried(world):
    before = await snapshot(world)
    async with world.sessions() as holder:
        await holder.execute(select(ScriptVersion.id).where(ScriptVersion.id == world.version.id).with_for_update())
        contested = await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True)
        assert contested["stopped"] == "contested_version" and contested["after"] is None
        assert contested["scanned"] == contested["updated"] == contested["failed"] == 0
        assert await snapshot(world) == before
        await holder.rollback()
    retried = await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True)
    assert retried["stopped"] == "complete" and retried["updated"] == 1 and retried["failed"] == 0
    unchanged_source_fields(before, await snapshot(world))


async def test_backfill_rejects_invalid_or_oversized_source_and_retry_is_explicit(world):
    invalid_id, large_id = await add_history(world, [{"nodes": "not-an-array"}, historical_source(1, "x" * 2048)])
    before = await snapshot(world)
    result = await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True, max_source_bytes=1024)
    assert result["failed"] == 2 and result["updated"] == 1
    assert {row["version_id"] for row in result["failures"]} == {str(invalid_id), str(large_id)}
    assert all(row["code"] == "source_invalid_or_over_budget" for row in result["failures"])
    after = await snapshot(world)
    unchanged_source_fields(before, after)
    assert after["versions"][invalid_id]["node_count"] is after["versions"][large_id]["node_count"] is None
    # Restart from the beginning with a larger budget: the previous cursor crossed
    # failed rows deliberately, so a NULL-pair retry must not reuse that cursor.
    retried = await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True, max_source_bytes=4096)
    assert retried["failed"] == 1 and retried["updated"] == 1
    final = await snapshot(world)
    assert final["versions"][invalid_id]["dag_hash"] is final["versions"][invalid_id]["node_count"] is None
    assert final["versions"][large_id]["dag_hash"] == _compute_dag_hash(final["versions"][large_id]["dag"])
    unchanged_source_fields(before, final)


async def test_readiness_reports_missing_current_metadata_without_reading_source(world):
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        assert not re.search(r"\bdag\b|\bjsonb_\w+|\bjson_\w+", statement, re.IGNORECASE)

    event.listen(world.engine.sync_engine, "before_cursor_execute", capture)
    try:
        before = await maintenance.metadata_readiness(world.sessions, org_id=world.org_a.id)
    finally:
        event.remove(world.engine.sync_engine, "before_cursor_execute", capture)
    assert statements and before["scripts"] == 1
    assert before["invalid_current_pointers"] == 0
    assert before["current_metadata_missing"] == before["version_metadata_missing"] == 1
    assert before["catalog_ready"] is False and before["source_hashes_reconciled"] is False
    await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True)
    after = await maintenance.metadata_readiness(world.sessions, org_id=world.org_a.id)
    assert after["catalog_ready"] is True and after["current_metadata_missing"] == after["version_metadata_missing"] == 0
    # Completeness is not a certificate that all populated hashes were reconciled.
    assert after["source_hashes_reconciled"] is False


@pytest.mark.parametrize("pointer", ["other_script", "foreign_org", "foreign_version_org"])
async def test_readiness_refuses_a_cross_script_or_cross_org_current_pointer(world, pointer):
    await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True)
    async with world.sessions() as db:
        if pointer == "foreign_version_org":
            owner_id, owner_org = world.script.id, world.org_b.id
        else:
            owner_org = world.org_a.id if pointer == "other_script" else world.org_b.id
            owner = Script(org_id=owner_org, name="readiness wrong pointer")
            db.add(owner)
            await db.flush()
            owner_id = owner.id
        source = historical_source()
        digest, count = _compute_dag_metadata(source)
        version = ScriptVersion(script_id=owner_id, org_id=owner_org, dag=source,
                                dag_hash=digest, node_count=count)
        db.add(version)
        await db.flush()
        target = await db.get(Script, world.script.id)
        target.current_version_id = version.id
        await db.commit()
    result = await maintenance.metadata_readiness(world.sessions, org_id=world.org_a.id)
    assert result["invalid_current_pointers"] == 1 and result["current_metadata_missing"] == 0
    assert result["catalog_ready"] is False


async def test_initial_page_sql_timeout_returns_a_cursor_receipt_without_modifying_source(world):
    before = await snapshot(world)

    def delay_lookup(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT script_versions.id "):
            statement = statement.replace("FROM script_versions", "FROM script_versions CROSS JOIN pg_sleep(0.2)", 1)
        return statement, parameters

    event.listen(world.engine.sync_engine, "before_cursor_execute", delay_lookup, retval=True)
    try:
        result = await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True, max_seconds=0.05)
    finally:
        event.remove(world.engine.sync_engine, "before_cursor_execute", delay_lookup)
    assert result["stopped"] == "query_budget" and result["after"] is None
    assert result["scanned"] == result["updated"] == result["failed"] == 0
    assert await snapshot(world) == before


@pytest.mark.parametrize("patch", ["fix_sleep_wait", "fix_dag_v2", "fix_dag_add_validate"])
def test_retired_sql_patch_replacement_changes_only_the_intended_preserved_source(patch):
    source = {"unknown": {"retained": [0, False, None, "雪"]}, "nodes": [
        {"id": "sleep_wait", "action": {"type": "sleep", "ms": 5000}, "on_failure": "old"},
        {"id": "scan_all", "action": {"type": "historical", "fail_if_not_found": False}},
        {"id": "route_play", "action": {"type": "condition", "on_true": "old"}},
        {"id": "check_watchdog", "action": {"type": "condition", "code": "old"}},
    ]}
    before = copy.deepcopy(source)
    changed = patch_source(source, patch)
    assert source == before and changed["unknown"] == before["unknown"]
    by_id = {node["id"]: node for node in changed["nodes"]}
    if patch == "fix_sleep_wait":
        assert by_id["sleep_wait"]["on_failure"] == "check_game_alive"
        assert changed["nodes"][1:] == before["nodes"][1:]
    elif patch == "fix_dag_v2":
        assert by_id["scan_all"]["action"]["fail_if_not_found"] is True
        assert by_id["route_play"]["action"]["on_true"] == "sleep_wait"
        assert by_id["check_watchdog"]["action"]["code"] == "return true"
        assert changed["nodes"][0] == before["nodes"][0]
    else:
        assert changed["nodes"][:-1] == before["nodes"]
        assert by_id["validate_game_pid"]["on_success"] == "reset_dead_alive"
        assert by_id["validate_game_pid"]["on_failure"] == "increment_dead_count"
        with pytest.raises(ValueError, match="already exists"):
            patch_source(changed, patch)


async def test_reconciliation_repairs_only_a_stale_derived_pair_without_changing_source(world):
    [version_id] = await add_history(world, [historical_source(3)])
    async with world.sessions() as db:
        version = await db.get(ScriptVersion, version_id)
        version.dag_hash, version.node_count = "0" * 64, 0
        await db.commit()
    before = await snapshot(world)
    regular = await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True)
    assert regular["updated"] == 1  # The legacy base version has the only NULL pair.
    interim = await snapshot(world)
    assert interim["versions"][version_id]["dag_hash"] == "0" * 64
    reconciled = await maintenance.backfill(world.sessions, org_id=world.org_a.id, apply=True, reconcile=True)
    assert reconciled["updated"] == 1 and reconciled["failed"] == 0
    after = await snapshot(world)
    assert after["versions"][version_id]["dag_hash"] == _compute_dag_hash(after["versions"][version_id]["dag"])
    assert after["versions"][version_id]["node_count"] == 3
    unchanged_source_fields(before, after)
