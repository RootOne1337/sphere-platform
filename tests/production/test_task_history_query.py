"""Task history must query all tenant rows, not a UI's newest hundred."""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import Depends

from backend.api.v1.tasks.router import get_task_service
from backend.database.engine import get_db
from backend.main import app
from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.models.script import Script
from backend.models.task import Task, TaskStatus
from backend.services.task_service import TaskService


@pytest_asyncio.fixture
async def history(world):
    async def service(db=Depends(get_db)):
        return TaskService(db)

    app.dependency_overrides[get_task_service] = service
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with world.sessions() as db:
        special = Script(org_id=world.org_a.id, name="Old 100%_failure")
        foreign_script = Script(org_id=world.org_b.id, name="Old 100%_failure")
        decoy = Script(org_id=world.org_a.id, name="Old 100XXfailure")
        db.add_all([special, foreign_script, decoy])
        await db.flush()
        tasks = [Task(org_id=world.org_a.id, device_id=world.dev_a.id,
                      script_id=world.script.id, status=TaskStatus.COMPLETED,
                      priority=5, created_at=stamp+timedelta(minutes=i+1))
                 for i in range(125)]
        tasks[0].script_id = decoy.id
        old = Task(org_id=world.org_a.id, device_id=world.dev_a2.id,
                   script_id=special.id, status=TaskStatus.FAILED, priority=1,
                   created_at=stamp)
        active = [Task(org_id=world.org_a.id, device_id=world.dev_a.id,
                       script_id=world.script.id, status=status, priority=9,
                       created_at=stamp) for status in
                  [TaskStatus.QUEUED, TaskStatus.ASSIGNED, TaskStatus.RUNNING]]
        foreign = Task(org_id=world.org_b.id, device_id=world.dev_b.id,
                       script_id=foreign_script.id, status=TaskStatus.FAILED,
                       created_at=stamp)
        db.add_all([*tasks, old, *active, foreign])
        await db.commit()
    yield world, old, active, special
    app.dependency_overrides.pop(get_task_service, None)


async def get(history, **params):
    world, *_ = history
    response = await world.client.get('/api/v1/tasks', params=params,
                                     headers=world.auth(world.users['viewer']))
    assert response.status_code == 200, response.text
    return response.json()


async def test_counts_cover_whole_filtered_tenant_history_even_on_empty_page(history):
    first = await get(history, per_page=25, include_counts=True)
    empty = await get(history, page=99, per_page=25, include_counts=True)
    assert first['total'] == empty['total'] == 129
    assert len(first['items']) == 25 and empty['items'] == []
    assert first['status_counts'] == empty['status_counts'] == {
        'queued': 1, 'assigned': 1, 'running': 1, 'completed': 125,
        'failed': 1, 'timeout': 0, 'cancelled': 0,
    }
    filtered = await get(history, status='failed', include_counts=True)
    assert filtered['total'] == 1 and filtered['status_counts']['completed'] == 0


@pytest.mark.parametrize('query', ['100%_', 'OLD 100%', 'task_id'])
async def test_search_reaches_old_failure_and_escapes_literal_wildcards(history, query):
    _, old, _, _ = history
    value = str(old.id)[8:20] if query == 'task_id' else query
    found = await get(history, search=value, include_counts=True)
    assert [t['id'] for t in found['items']] == [str(old.id)]
    assert found['total'] == 1 and found['status_counts']['failed'] == 1
    assert (await get(history, search='does-not-exist', include_counts=True))['total'] == 0


async def test_active_filter_reaches_older_work_and_combines_existing_filters(history):
    world, _, active, _ = history
    found = await get(history, active_only=True, include_counts=True)
    assert {t['id'] for t in found['items']} == {str(t.id) for t in active}
    assert found['total'] == 3 and found['status_counts']['completed'] == 0
    assert (await get(history, active_only=True, device_id=str(world.dev_a2.id)))['total'] == 0


async def test_filtered_history_works_under_restricted_postgres_role(history, runtime_db):
    world, old, _, _ = history

    async def scoped_db():
        async with runtime_db.sessions() as session:
            yield session

    app.dependency_overrides[get_db] = scoped_db
    found = await get(history, search='100%_', include_counts=True)
    assert found['total'] == 1
    assert [t['id'] for t in found['items']] == [str(old.id)]
    foreign = await world.client.get('/api/v1/tasks', params={'include_counts': True},
                                    headers=world.auth(world.users['foreign']))
    assert foreign.status_code == 200, foreign.text
    assert foreign.json()['total'] == 1
    assert foreign.json()['status_counts']['completed'] == 0


async def test_server_sort_has_stable_ties_and_all_pages(history):
    all_ids = []
    for page in range(1, 7):
        result = await get(history, page=page, per_page=25, sort_by='priority', sort_dir='asc')
        all_ids.extend(t['id'] for t in result['items'])
    _, old, _, _ = history
    assert all_ids[0] == str(old.id)
    assert len(all_ids) == len(set(all_ids)) == 129
    repeated = await get(history, per_page=25, sort_by='priority', sort_dir='asc')
    assert [t['id'] for t in repeated['items']] == all_ids[:25]
    reverse = await get(history, per_page=200, sort_by='priority', sort_dir='desc')
    assert [t['id'] for t in reverse['items']] == list(reversed(all_ids))


@pytest.mark.parametrize('params', [{'sort_by':'untrusted'}, {'sort_dir':'other'}, {'search':'x'*201}])
async def test_query_contract_rejects_unbounded_or_unknown_options(history, params):
    world, *_ = history
    response = await world.client.get('/api/v1/tasks', params=params,
                                     headers=world.auth(world.users['viewer']))
    assert response.status_code == 422


async def test_active_pipeline_query_does_not_hide_old_waiting_runs(world):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with world.sessions() as db:
        pipeline = Pipeline(org_id=world.org_a.id, name='history fixture')
        db.add(pipeline)
        await db.flush()
        active = [PipelineRun(org_id=world.org_a.id, pipeline_id=pipeline.id,
                              device_id=world.dev_a.id, steps_snapshot=[], status=s,
                              created_at=stamp) for s in [PipelineRunStatus.QUEUED,
                              PipelineRunStatus.RUNNING, PipelineRunStatus.WAITING,
                              PipelineRunStatus.PAUSED]]
        terminal = [PipelineRun(org_id=world.org_a.id, pipeline_id=pipeline.id,
                                device_id=world.dev_a.id, steps_snapshot=[],
                                status=PipelineRunStatus.COMPLETED,
                                created_at=stamp+timedelta(days=1)) for _ in range(12)]
        db.add_all([*active, *terminal])
        await db.commit()
    response = await world.client.get('/api/v1/pipelines/runs',
        params={'active_only':True,'per_page':10}, headers=world.auth(world.users['org_admin']))
    assert response.status_code == 200, response.text
    assert response.json()['total'] == 4
    assert {t['id'] for t in response.json()['items']} == {str(t.id) for t in active}
