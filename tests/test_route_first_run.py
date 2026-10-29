"""The real-video HTTP acceptance tool cannot overwrite or repeat an intent."""
import pytest
from scripts.pilot import check_route_first_run as first_run


def setup_scope(tmp_path,monkeypatch):
    monkeypatch.setattr(first_run,'ROOT',tmp_path)
    monkeypatch.setattr(first_run,'collect',lambda _:pytest.fail('preflight must precede resource work'))
    worker=tmp_path/'worker.exe';worker.touch()
    pilot=tmp_path/'.local-pilot';pilot.mkdir()
    return worker,pilot


def test_existing_first_run_result_is_never_reused_or_overwritten(tmp_path,monkeypatch):
    worker,pilot=setup_scope(tmp_path,monkeypatch)
    output=pilot/'saved';output.mkdir();(output/'intent.json').write_bytes(b'preserved')
    with pytest.raises(ValueError,match='first_run_exclusive_local_scope'):
        first_run.run(tmp_path/'source',output,worker)
    assert (output/'intent.json').read_bytes()==b'preserved'


def test_output_outside_local_pilot_is_refused_before_directory_creation(tmp_path,monkeypatch):
    worker,_=setup_scope(tmp_path,monkeypatch);output=tmp_path/'outside'
    with pytest.raises(ValueError,match='first_run_exclusive_local_scope'):
        first_run.run(tmp_path/'source',output,worker)
    assert not output.exists()


def test_partial_capture_does_not_start_a_server_or_create_an_intent(tmp_path,monkeypatch):
    worker,pilot=setup_scope(tmp_path,monkeypatch)
    source=tmp_path/'source';source.mkdir();(source/'video.h264').write_bytes(b'partial')
    output=pilot/'attempt'
    with pytest.raises(ValueError,match='first_run_source_files'):
        first_run.run(source,output,worker)
    assert not output.exists() and (source/'video.h264').read_bytes()==b'partial'


def test_quality_rejection_is_preserved_instead_of_becoming_cancelled(tmp_path):
    from types import SimpleNamespace
    job=tmp_path/'job';job.mkdir();(job/'state.json').write_text('{"phase":"sparse_complete"}')
    navigation=job/'navigation';navigation.mkdir()
    state=b'{"phase":"rejected","error":"route_map_has_unobserved_sections"}'
    (navigation/'state.json').write_bytes(state)
    jobs=SimpleNamespace(navigation=SimpleNamespace(current=lambda _:navigation,preparing=lambda _:False))
    first_run.stop_unfinished(jobs,job)
    assert not (job/'CANCEL').exists() and not (navigation/'CANCEL').exists()
    assert (navigation/'state.json').read_bytes()==state


def test_only_owned_unfinished_tasks_receive_cooperative_cancellation(tmp_path):
    from types import SimpleNamespace
    job=tmp_path/'job';job.mkdir();(job/'state.json').write_text('{"phase":"features"}')
    jobs=SimpleNamespace(navigation=SimpleNamespace(current=lambda _:None))
    first_run.stop_unfinished(jobs,job)
    assert (job/'CANCEL').is_file()
