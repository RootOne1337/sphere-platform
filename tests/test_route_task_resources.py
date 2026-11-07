"""Route tasks cannot borrow volume proofs or memory across worker lifetimes."""
from pathlib import Path

import pytest

from scripts.pilot import reconstruct_route as pipeline
from scripts.pilot import route_resource_monitor


@pytest.mark.parametrize('fail', [False, True])
def test_route_proof_is_task_owned_and_closed_on_every_exit(tmp_path, monkeypatch, fail):
    instances, samples, evaluated = [], [], []

    class Monitor:
        def __init__(self, _root):
            self.closed = False
            instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = True

        def sample(self):
            assert not self.closed
            value = {'task': len(instances), 'memory': len(samples)}
            samples.append(value)
            return value

    monkeypatch.setattr(route_resource_monitor, 'TaskResourceMonitor', Monitor)
    monkeypatch.setattr(pipeline, 'collect', lambda _: pytest.fail('route task must use its own monitor'))
    monkeypatch.setattr(pipeline, '_checkpoint_snapshot', lambda _j, s, **_k: evaluated.append(s))

    def inner(job, _mask, _steps, *, route_only):
        assert route_only
        pipeline.checkpoint(job)
        with pytest.raises(RuntimeError, match='route_resource_task_mismatch'):
            pipeline.checkpoint(job.parent/'another-job')
        with pytest.raises(RuntimeError, match='route_resource_task_already_active'):
            pipeline.reconstruct(job.parent/'another-job','game',30000,route_only=False)
        callback = pipeline.make_observation_checkpoint(job)
        callback()
        if fail:
            raise RuntimeError('owned_worker_failure')
        return callback

    monkeypatch.setattr(pipeline, '_reconstruct_with_telemetry', inner)
    for i in range(2):
        job = tmp_path / str(i)
        job.mkdir()
        if fail:
            with pytest.raises(RuntimeError, match='owned_worker_failure'):
                pipeline.reconstruct(job, 'game', 30000, route_only=True)
        else:
            callback = pipeline.reconstruct(job, 'game', 30000, route_only=True)
            # A retained callback does not silently attach to a later task.
            with pytest.raises(AssertionError):
                callback()
        assert pipeline._TASK_RESOURCES is None
        assert pipeline._TASK_RESOURCE_JOB is None
        assert instances[-1].closed
    assert samples == evaluated
    assert [s['task'] for s in samples] == [1, 1, 2, 2]


def test_cancellation_precedes_monitor_and_dense_path_keeps_existing_collector(tmp_path, monkeypatch):
    job = tmp_path / 'job'
    job.mkdir()
    (job / 'CANCEL').touch()
    with pytest.raises(RuntimeError, match='cancelled'):
        pipeline.checkpoint(job)
    (job / 'CANCEL').unlink()
    monkeypatch.setattr(route_resource_monitor, 'TaskResourceMonitor', lambda _: pytest.fail('dense budget changed'))
    monkeypatch.setattr(pipeline, 'collect', lambda _: {'fresh': True})
    seen = []
    monkeypatch.setattr(pipeline, '_checkpoint_snapshot', lambda _j, s, **_k: seen.append(s))

    def dense(directory: Path, *_args, **_kwargs):
        pipeline.checkpoint(directory, learned=True)

    monkeypatch.setattr(pipeline, '_reconstruct_with_telemetry', dense)
    pipeline.reconstruct(job, 'game', 30000, route_only=False)
    assert seen == [{'fresh': True}]
