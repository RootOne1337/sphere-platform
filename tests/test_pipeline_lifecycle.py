"""Pipeline startup must register a shutdown hook for the process it owns."""

import asyncio
import importlib


async def test_pipeline_startup_registers_shutdown_and_awaits_its_owned_loop(monkeypatch):
    router = importlib.import_module("backend.api.v1.pipelines.router")
    registry = importlib.import_module("backend.core.lifespan_registry")
    module = importlib.import_module("backend.services.orchestrator.pipeline_executor")
    started, finished = asyncio.Event(), asyncio.Event()
    calls = []

    class FakeExecutor:
        async def start(self):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        async def stop(self):
            calls.append("stop")

    monkeypatch.setattr(module, "PipelineExecutor", FakeExecutor)
    monkeypatch.setattr(registry, "_shutdown_hooks", [])
    before = asyncio.all_tasks()
    try:
        await router._startup_pipeline_executor()
        await asyncio.wait_for(started.wait(), 2)
        assert any(name == "pipeline_executor" for name, _ in registry._shutdown_hooks)
        await registry.run_all_shutdown()
        assert calls == ["stop"] and finished.is_set()
    finally:
        tasks = asyncio.all_tasks() - before
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
