import pytest

from backend.websocket.viewer_link import ViewerLinkProbe


def test_bounded_server_echo_is_rate_limited_independently_per_viewer():
    probe = ViewerLinkProbe()
    value = {"type": "stream_link_probe", "sequence": 1}
    assert probe.reply(value, 0) == {"type": "stream_link_result", "sequence": 1}
    assert probe.reply(value, .5) is None
    assert probe.reply(value, 1) == {"type": "stream_link_result", "sequence": 1}
    assert ViewerLinkProbe().reply(value, .5) is not None


@pytest.mark.parametrize("sequence", [0, -1, 2147483648, True, 1.0, "1", None, [], {}])
def test_invalid_probe_sequence_has_no_echo(sequence):
    assert ViewerLinkProbe().reply({"type": "stream_link_probe", "sequence": sequence}, 0) is None


def test_unknown_fields_and_nonfinite_clock_are_not_echoed():
    value = {"type": "stream_link_probe", "sequence": 1}
    assert ViewerLinkProbe().reply(value | {"text": "private"}, 0) is None
    assert ViewerLinkProbe().reply(value, float("nan")) is None
    assert ViewerLinkProbe().reply(value, float("inf")) is None
