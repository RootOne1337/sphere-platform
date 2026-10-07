"""Browser and native identities have deliberately different trust boundaries."""
from dataclasses import FrozenInstanceError

import pytest

from backend.websocket.continuous_protocol import (
    CaptureBinding,
    CloseInput,
    InputReceipt,
    InvalidContinuousInput,
    TouchEvent,
    viewer_continuous,
)

EPOCH = "00112233-4455-6677-8899-aabbccddeeff"
OPEN = {"type": "touch_open", "capture_epoch": EPOCH, "frame_width": 960, "frame_height": 540}
EVENT = {"type": "touch_event", "sequence": 1, "gesture": 1, "action": 0, "x": 100, "y": 200}
RECEIPT = {"type": "continuous_input_status", "session_id": "viewer_session_01",
           "owner": "owner_nonce_01", "capture_epoch": EPOCH, "sequence": 0,
           "status": 0, "stage": "startup", "origin": "injector", "device_uptime_ms": 1234}


def test_browser_cannot_mutate_validated_binding():
    capture = viewer_continuous(OPEN)
    assert capture == CaptureBinding(EPOCH, 960, 540)
    assert viewer_continuous(EVENT) == TouchEvent(1, 1, 0, 100, 200)
    assert viewer_continuous({"type": "touch_close"}) == CloseInput()
    with pytest.raises(FrozenInstanceError):
        capture.width = 1


@pytest.mark.parametrize("extra", ["owner", "session_id", "org_id", "agent_session", "capture_epoch"])
def test_browser_event_rejects_identity_and_capture_overrides(extra):
    with pytest.raises(InvalidContinuousInput, match="^continuous_input_invalid$"):
        viewer_continuous({**EVENT, extra: "private_payload"})


@pytest.mark.parametrize("value", [True, 1.0, "1", None, -1, 2_147_483_648])
def test_sequence_is_a_bounded_json_integer(value):
    with pytest.raises(InvalidContinuousInput):
        viewer_continuous({**EVENT, "sequence": value})


@pytest.mark.parametrize("patch", [
    {"gesture": 0}, {"gesture": 9_007_199_254_740_991}, {"action": True},
    {"action": 5}, {"x": -1}, {"x": 16_384}, {"y": 1.5}, {"sequence": 0},
])
def test_invalid_event_never_becomes_an_android_command(patch):
    with pytest.raises(InvalidContinuousInput):
        viewer_continuous({**EVENT, **patch})


def test_idle_heartbeat_and_last_pixel_have_explicit_bounds():
    heartbeat = viewer_continuous({**EVENT, "gesture": 0, "action": 4, "x": 959, "y": 539})
    assert heartbeat.inside(CaptureBinding(EPOCH, 960, 540))
    assert not heartbeat.inside(CaptureBinding(EPOCH, 959, 540))


@pytest.mark.parametrize("patch", [
    {"capture_epoch": "00000000-0000-0000-0000-000000000000"},
    {"capture_epoch": EPOCH.upper()}, {"capture_epoch": EPOCH.replace("-", "")},
    {"frame_width": 0}, {"frame_width": True}, {"frame_height": 16_385},
    {"owner": "owner_injected"},
])
def test_open_requires_an_exact_non_nil_frame_binding(patch):
    with pytest.raises(InvalidContinuousInput):
        viewer_continuous({**OPEN, **patch})


@pytest.mark.parametrize("message", [None, [], {}, {"type": "continuous_input_open"},
                                         {"type": "touch_close", "owner": "owner_injected"}])
def test_unknown_or_native_browser_messages_are_rejected(message):
    with pytest.raises(InvalidContinuousInput):
        viewer_continuous(message)


def test_receipts_separate_ready_execution_unknown_and_known_release():
    assert InputReceipt.parse(RECEIPT).ready
    executed = InputReceipt.parse({**RECEIPT, "stage": "input", "sequence": 2, "status": 1})
    assert not executed.ready and not executed.released and not executed.failed
    released = InputReceipt.parse({**RECEIPT, "stage": "release", "status": 3})
    assert released.released and not released.ready
    unknown = InputReceipt.parse({**RECEIPT, "stage": "release", "status": 6})
    assert unknown.failed and not unknown.released


@pytest.mark.parametrize("patch", [
    {"origin": "admission"}, {"stage": "input"}, {"sequence": 1},
    {"status": True}, {"status": 1}, {"device_uptime_ms": -1},
    {"owner": "пример123456"}, {"session_id": "../private/session"},
    {"stage": "release", "status": 1}, {"org_id": "private_tenant"},
])
def test_forged_or_incompatible_receipts_cannot_grant_ready_or_release(patch):
    with pytest.raises(InvalidContinuousInput):
        InputReceipt.parse({**RECEIPT, **patch})
