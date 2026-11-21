"""Live quality RPC never substitutes publication for an installed-APK receipt."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from backend.api.v1.streaming.router import _quality_rpc
from backend.schemas.stream_quality import StreamQualitySettings, StreamQualitySnapshot


def snapshot():
    return {"supported": True, "protocol": 1, "settings": {"profile": "detail", "max_fps": 60, "max_bitrate_bps": 12_000_000},
            "active": {"width": 960, "height": 540, "source_fps": 60, "codec_max_fps": 60, "target_fps": 60,
                       "max_bitrate_bps": 12_000_000, "target_bitrate_bps": 12_000_000, "adaptation": "webrtc"}}


@pytest.mark.parametrize("field,value", [("profile", "lossless"), ("max_fps", 0), ("max_fps", 61), ("max_fps", True),
    ("max_fps", "60"), ("max_bitrate_bps", 99_999), ("max_bitrate_bps", 32_000_001), ("max_bitrate_bps", True), ("other", 1)])
def test_invalid_settings_are_rejected(field, value):
    with pytest.raises(ValidationError):
        StreamQualitySettings.model_validate({field: value})


async def test_write_waits_for_completed_result_on_live_channel_without_replay():
    publisher = AsyncMock()
    publisher.send_command_wait_result.return_value = {"status": "completed", "result": snapshot()}
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher):
        actual = await _quality_rpc("device", StreamQualitySettings.model_validate(snapshot()["settings"]))
    assert actual.model_dump() == snapshot()
    args, kwargs = publisher.send_command_wait_result.call_args
    assert args[0] == "device" and args[1]["type"] == "stream_quality"
    assert args[1]["payload"] == {"action": "set", "settings": snapshot()["settings"]}
    assert args[1]["command_id"].startswith("interactive_")
    assert kwargs == {"timeout": 8.0, "live_only": True}
    publisher.send_command_wait_result.assert_awaited_once()


async def test_read_does_not_send_or_persist_any_settings():
    publisher = AsyncMock()
    publisher.send_command_wait_result.return_value = {"status": "completed", "result": snapshot()}
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher):
        await _quality_rpc("device", None)
    assert publisher.send_command_wait_result.call_args.args[1]["payload"] == {"action": "get"}


@pytest.mark.parametrize("result,status", [({"status": "running"}, 502), ({"status": "received"}, 502),
    ({"status": "completed", "result": {}}, 502),
    ({"status": "failed", "error": "stream_quality_unsupported"}, 409),
    ({"status": "failed", "error": "stream_quality_codec_refused"}, 409),
    ({"status": "failed", "error": "stream_quality_storage_unavailable"}, 409),
    ({"status": "failed", "error": "private remote exception"}, 502)])
async def test_only_valid_native_completion_is_success(result, status):
    publisher = AsyncMock()
    publisher.send_command_wait_result.return_value = result
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher), pytest.raises(HTTPException) as error:
        await _quality_rpc("device", StreamQualitySettings())
    assert error.value.status_code == status
    assert "private remote exception" not in error.value.detail
    publisher.send_command_wait_result.assert_awaited_once()


@pytest.mark.parametrize("failure,status", [(HTTPException(504, "timeout"), 504), (RedisConnectionError(), 503)])
async def test_unknown_completion_is_not_repeated(failure, status):
    publisher = AsyncMock()
    publisher.send_command_wait_result.side_effect = failure
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher), pytest.raises(HTTPException) as error:
        await _quality_rpc("device", StreamQualitySettings())
    assert error.value.status_code == status
    publisher.send_command_wait_result.assert_awaited_once()


@pytest.mark.parametrize("field,value", [("target_fps", 61), ("source_fps", 30), ("codec_max_fps", 30),
    ("target_bitrate_bps", 12_000_001), ("adaptation", "local_queue_is_network")])
def test_incoherent_android_snapshot_is_rejected(field, value):
    data = snapshot()
    data["active"][field] = value
    with pytest.raises(ValidationError):
        StreamQualitySnapshot.model_validate(data)
