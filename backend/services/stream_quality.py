"""Live native quality receipts shared by REST and capture-only admission."""
from __future__ import annotations

import time
import uuid

from fastapi import HTTPException
from pydantic import ValidationError
from redis.exceptions import RedisError

from backend.schemas.stream_quality import StreamQualitySettings, StreamQualitySnapshot


async def quality_rpc(device_id: str, settings: StreamQualitySettings | None) -> StreamQualitySnapshot:
    from backend.websocket.pubsub_router import get_pubsub_publisher

    publisher = get_pubsub_publisher()
    if publisher is None:
        raise HTTPException(503, "Stream quality command transport is unavailable")
    payload = {"action": "get"} if settings is None else {
        "action": "set", "settings": settings.model_dump(),
    }
    try:
        receipt = await publisher.send_command_wait_result(device_id, {
            "type": "stream_quality", "command_id": f"interactive_{uuid.uuid4()}",
            "payload": payload, "signed_at": int(time.time()), "ttl_seconds": 15,
        }, timeout=8.0, live_only=True)
    except RedisError as exc:
        # The source may have applied this setting. Never repeat an uncertain write.
        raise HTTPException(503, "Stream quality result unavailable; refresh the current setting") from exc
    if receipt.get("status") == "failed":
        error = receipt.get("error")
        if error == "stream_quality_unsupported":
            raise HTTPException(409, "Update the Android agent to configure stream quality")
        if error in {"stream_quality_codec_refused", "stream_quality_storage_unavailable"}:
            raise HTTPException(409, "Android could not apply this quality setting")
        raise HTTPException(502, "Android rejected the stream quality request")
    if receipt.get("status") != "completed":
        raise HTTPException(502, "Invalid stream quality completion receipt")
    try:
        return StreamQualitySnapshot.model_validate(receipt.get("result"))
    except ValidationError as exc:
        raise HTTPException(502, "Invalid stream quality snapshot") from exc
