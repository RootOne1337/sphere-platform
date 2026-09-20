"""A healthy socket/initial IDR cannot certify continued video delivery."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.pilot import android_soak as soak


@pytest.mark.parametrize("failure", ["original_frozen", "extra_frozen", "frozen_after_close"])
async def test_overlap_cannot_pass_when_a_viewer_loses_frames(tmp_path, monkeypatch, failure):
    runner, viewers = setup_runner(tmp_path, monkeypatch, failure)
    with pytest.raises(soak.SoakFailure, match="fresh video"):
        await runner.cycle(4)
    assert runner.state["cycles_passed"] == 0
    assert all(not v.active for v in viewers)
    events = [json.loads(row) for row in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert not any(row["event"] == "cycle_passed" for row in events)


async def test_both_motion_phases_are_required_before_cycle_success(tmp_path, monkeypatch):
    runner, viewers = setup_runner(tmp_path, monkeypatch, None)
    await runner.cycle(4)
    assert runner.state["cycles_passed"] == 1
    assert all(not v.active for v in viewers)
    events = [json.loads(row) for row in (tmp_path / "events.jsonl").read_text().splitlines()]
    motion = [row for row in events if row["event"] == "viewer_motion_verified"]
    assert [row["stage"] for row in motion] == ["overlap", "after_overlap_close"]
    assert [len(row["viewers"]) for row in motion] == [2, 1]
    assert all(v["new_frames"] > 0 for row in motion for v in row["viewers"])


def setup_runner(tmp_path, monkeypatch, failure):
    device = "85f2f935-7739-400e-9389-0d71227e8f0a"
    config = {"devices": [{"id": device}], "package": "com.sphereplatform.agent.pilot.debug",
              "script_id": "script", "version_id": "version"}
    runner = soak.Runner(config, tmp_path, 120)
    runner.stopping = lambda: True  # Skip cadence waits; still execute one whole cycle.
    runner.check_script = AsyncMock()
    runner.sample = AsyncMock()
    viewers = []
    monkeypatch.setattr(soak, "time", SimpleNamespace(monotonic=lambda: 0))

    async def yield_only(seconds):
        await asyncio.sleep(0)

    monkeypatch.setattr(soak, "asyncio", SimpleNamespace(sleep=yield_only, timeout=asyncio.timeout))

    async def open_viewer(stack, requested_device):
        viewer = SimpleNamespace(device=requested_device, frames=3, active=True,
                                 check=lambda: None, summary=lambda: {"device": requested_device})
        viewers.append(viewer)
        stack.callback(lambda: setattr(viewer, "active", False))
        return viewer

    async def batch(number):
        for viewer in viewers:
            viewer.frames += 1

    async def shell(requested_device, command):
        assert requested_device == device
        assert command in {"cmd statusbar expand-notifications", "cmd statusbar collapse"}
        for index, viewer in enumerate(viewers):
            frozen = ((failure == "original_frozen" and index == 0) or
                      (failure == "extra_frozen" and index == 1) or
                      (failure == "frozen_after_close" and not viewers[-1].active))
            if viewer.active and not frozen:
                viewer.frames += 1
        return ""

    runner.open_viewer = open_viewer
    runner.batch = batch
    runner.shell = shell
    return runner, viewers
