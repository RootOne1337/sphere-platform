"""Independent byte fixtures for the canary's v2 header and queue classification."""
from __future__ import annotations

import pytest

from backend.websocket.frames import FrameType, VideoFrame, detect_first_nal_type
from backend.websocket.video_queue import VideoStreamQueue

EPOCH = bytes.fromhex("00112233445566778899aabbccddeeff")


def packet(payload: bytes, epoch: bytes = EPOCH, flags: int = 1) -> bytes:
    return bytes((2, flags)) + (12345).to_bytes(8, "big") + len(payload).to_bytes(4, "big") + epoch + payload


def test_network_order_golden_picture_retains_original_packet():
    raw = bytes.fromhex("020100000000000030390000000600112233445566778899aabbccddeeff000000016542")
    frame = VideoFrame(raw, "device")
    assert frame.data is raw
    assert frame.nal_type == FrameType.IDR_SLICE
    assert frame.nal_types == {5}
    assert frame.is_keyframe and frame.is_picture
    assert detect_first_nal_type(raw) == FrameType.IDR_SLICE


@pytest.mark.parametrize("prefix", [b"\0\0\1", b"\0\0\0\1"])
@pytest.mark.parametrize("nal,kind", [(0x65, FrameType.IDR_SLICE), (0x41, FrameType.NON_IDR),
                                    (0x67, FrameType.SPS), (0x68, FrameType.PPS)])
def test_payload_classification_uses_v2_offset(prefix, nal, kind):
    raw = packet(prefix + bytes((nal, 42)), flags=int(kind == FrameType.IDR_SLICE))
    frame = VideoFrame(raw, "device")
    assert frame.nal_type == kind
    assert detect_first_nal_type(raw) == kind
    assert frame.is_configuration == (kind in {FrameType.SPS, FrameType.PPS})


def test_uuid_bytes_cannot_masquerade_as_a_picture():
    epoch_with_start_codes = bytes.fromhex("000000016500000168000000aabbccdd")
    frame = VideoFrame(packet(b"\0\0\0\1\x67\x42", epoch_with_start_codes), "device")
    assert frame.nal_types == {7}
    assert frame.is_configuration and not frame.is_picture


@pytest.mark.parametrize("damage", ["truncated_header", "wrong_size", "nil_epoch", "flags", "empty", "oversize"])
def test_invalid_envelopes_do_not_trust_uuid_or_payload_start_codes(damage):
    raw = packet(b"\0\0\0\1\x65\x42")
    if damage == "truncated_header":
        raw = raw[:29]
    elif damage == "wrong_size":
        raw = raw[:10] + (99).to_bytes(4, "big") + raw[14:]
    elif damage == "nil_epoch":
        raw = packet(b"\0\0\0\1\x65\x42", bytes(16))
    elif damage == "flags":
        raw = packet(b"\0\0\0\1\x65\x42", flags=3)
    elif damage == "empty":
        raw = packet(b"")
    else:
        raw = packet(b"\0\0\0\1\x65" + b"x" * 1024 * 1024)
    frame = VideoFrame(raw, "device")
    assert frame.nal_type == FrameType.UNKNOWN
    assert not frame.nal_types and not frame.keyframe_flag and not frame.is_keyframe


async def test_queue_recovery_classifies_v2_config_and_idr_without_rewriting_bytes():
    queue = VideoStreamQueue("device")
    configuration = VideoFrame(packet(b"\0\0\0\1\x67\x42", flags=0), "device")
    picture = VideoFrame(packet(b"\0\0\0\1\x65\x42"), "device")
    assert await queue.put(configuration)
    assert await queue.put(picture)
    assert await queue.get() is configuration
    assert await queue.get() is picture
