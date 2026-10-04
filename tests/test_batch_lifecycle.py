"""The durable batch loop starts once and is awaited during shutdown."""

import asyncio
import importlib

import pytest


async def test_batch_admission_startup_and_shutdown_own_one_task(monkeypatch):
    router = importlib.import_module("backend.api.v1.batches.router")
    registry = importlib.import_module("backend.core.lifespan_registry")
    module = importlib.import_module("backend.services.batch_admission")
    entered, finished = asyncio.Event(), asyncio.Event()

    class Worker:
        def __init__(self, sessions):
            pass

        async def run(self):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

    monkeypatch.setattr(module, "BatchAdmissionWorker", Worker)
    monkeypatch.setattr(router, "_admission_task", None)
    assert ("batch_admission", router._startup_batch_admission) in registry._startup_hooks
    assert ("batch_admission", router._shutdown_batch_admission) in registry._shutdown_hooks
    try:
        await router._startup_batch_admission()
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(RuntimeError, match="already running"):
            await router._startup_batch_admission()
    finally:
        await router._shutdown_batch_admission()
    assert finished.is_set() and router._admission_task is None
