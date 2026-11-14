import pytest
from fastapi import HTTPException, WebSocketDisconnect
from structlog.testing import capture_logs

from backend.api.ws.direct.router import record_signaling_failure, signaling_failure_code
from backend.websocket.direct_probe_protocol import InvalidDirectProbe


@pytest.mark.parametrize("error, expected", [
    (InvalidDirectProbe("invalid_video_renewal"), "invalid_video_renewal"),
    (InvalidDirectProbe("video_renewal_rejected"), "video_renewal_rejected"),
    (InvalidDirectProbe("probe_expired"), "probe_expired"),
    (InvalidDirectProbe("private_sdp_or_token"), "protocol_rejected"),
    (HTTPException(401, detail="private_cookie"), "access_rejected"),
    (HTTPException(403, detail="private_cookie"), "access_rejected"),
    (HTTPException(500, detail="private_cookie"), "http_rejected"),
    (TimeoutError("private_path"), "operation_deadline"),
    (WebSocketDisconnect(1006, reason="private_peer"), "signaling_disconnected"),
    (ValueError("private_payload"), "malformed_message"),
    (TypeError("private_payload"), "malformed_message"),
    (RuntimeError("private_failure"), "signaling_unavailable"),
])
def test_signaling_failures_publish_only_fixed_codes(error, expected):
    assert signaling_failure_code(error) == expected


def test_signaling_stage_is_diagnostic_without_peer_credentials():
    with capture_logs() as logs:
        record_signaling_failure("reviewed-device", "renewal", InvalidDirectProbe("video_renewal_rejected"))
    assert logs == [{"event": "direct_video_signaling_stopped", "log_level": "warning",
                     "device_id": "reviewed-device", "phase": "renewal", "reason_code": "video_renewal_rejected"}]
