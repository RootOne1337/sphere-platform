"""A short diagnostics request must not transfer a full journal over a weak WAN link."""

import uuid
from unittest.mock import AsyncMock

import pytest

from backend.api.v1.devices import router as device_router


@pytest.mark.asyncio
@pytest.mark.parametrize("lines,budget", [(1, 4096), (20, 5120), (500, 65536)])
async def test_persisted_log_request_scales_wire_budget(monkeypatch, lines, budget):
    request = AsyncMock(return_value={"status": "completed", "result": {"logs": "recent\n"}})
    monkeypatch.setattr(device_router, "_request_interactive_command", request)

    result = await device_router.request_logcat(
        uuid.uuid4(), device_router.RequestLogcatRequest(lines=lines),
        current_user=object(), db=object(), svc=object(),
    )

    assert result == {"logcat": "recent"}
    assert request.await_args.args[4] == {"max_bytes": budget}
