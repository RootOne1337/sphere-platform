"""The HTTP replay harness cannot reuse an intent or accept unbounded cases."""
import pytest
from scripts.pilot import check_route_control_replay as replay


@pytest.mark.parametrize('kind',['outside','existing','unknown_case','too_long'])
def test_invalid_scope_stops_before_resource_work_or_recording_reads(tmp_path,monkeypatch,kind):
    monkeypatch.setattr(replay,'ROOT',tmp_path)
    monkeypatch.setattr(replay,'collect',lambda _:pytest.fail('scope must be checked first'))
    output=tmp_path/'.local-pilot'/'run';output.parent.mkdir()
    options={}
    if kind=='outside':output=tmp_path/'outside'
    if kind=='existing':output.mkdir();(output/'intent.json').write_text('preserved')
    if kind=='unknown_case':options['cases']=('arbitrary_input',)
    if kind=='too_long':options['seconds']=600
    with pytest.raises(ValueError,match='scope_or_quota'):
        replay.run(tmp_path/'source',tmp_path/'query',output,**options)
    if kind=='existing':assert (output/'intent.json').read_text()=='preserved'
    else:assert not output.exists()
