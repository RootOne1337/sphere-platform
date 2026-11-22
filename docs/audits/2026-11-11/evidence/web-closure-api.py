"""Loopback fixture for Chromium checks of WEB-10 and WEB-14.

Only the capability handler and task stop handler are from the product API.
Authentication and GET data are synthetic. Any database dependency raises.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.api.v1.auth.router import capabilities
from backend.api.v1.tasks.router import force_stop_task
from backend.core.dependencies import get_current_user
from backend.database.engine import get_db

app = FastAPI()
viewer = SimpleNamespace(id=UUID(int=1), org_id=UUID(int=2), role="viewer", email="viewer@example.invalid")
task_id = UUID(int=3)
date = "2026-11-11T00:00:00Z"
observed = {"device_pages": [], "task_stop_requests": 0, "database_calls": 0}
devices = [
    {"id": str(UUID(int=100 + n)), "name": f"Audit Android {n}", "status": "online",
     "group_ids": [], "location_ids": []}
    for n in range(1, 6)
]


async def no_database():
    observed["database_calls"] += 1
    raise AssertionError("The loopback browser fixture has no database")


app.dependency_overrides[get_current_user] = lambda: viewer
app.dependency_overrides[get_db] = no_database
app.add_api_route("/api/v1/auth/capabilities", capabilities, methods=["GET"])
app.add_api_route("/api/v1/tasks/{task_id}/stop", force_stop_task, methods=["POST"])


@app.middleware("http")
async def observe_task_stop(request: Request, call_next):
    if request.method == "POST" and request.url.path == f"/api/v1/tasks/{task_id}/stop":
        observed["task_stop_requests"] += 1
    return await call_next(request)


@app.post("/api/v1/auth/refresh")
async def refresh_fixture():
    return {"access_token": "loopback-fixture-access", "user": vars(viewer)}


@app.get("/api/v1/devices")
async def list_devices(page: int = 1, per_page: int = 4):
    observed["device_pages"].append(page)
    if page == 2:
        await asyncio.sleep(0.75)
    start = (page - 1) * per_page
    return {"items": devices[start:start + per_page], "page": page, "per_page": per_page,
            "pages": (len(devices) + per_page - 1) // per_page, "total": len(devices),
            "scope_total": len(devices), "presence_available": True,
            "status_counts": {"online": 5, "busy": 0, "connecting": 0, "offline": 0, "issues": 0}}


@app.get(f"/api/v1/tasks/{task_id}")
async def get_task_fixture():
    return {"id": task_id, "org_id": viewer.org_id, "device_id": devices[0]["id"],
            "script_id": UUID(int=4), "script_version_id": UUID(int=5), "status": "running",
            "priority": 5, "created_at": date, "started_at": date, "updated_at": date,
            "finished_at": None, "result": None, "error_message": None, "input_params": {}}


@app.get("/__audit_observations")
async def observations():
    return observed


@app.get("/api/v1/{path:path}")
async def empty_fixture_reads(path: str):
    if path in {"groups", "locations", "pipeline-settings/servers"} or path.endswith(("/logs", "/live-logs")):
        return []
    if path.endswith("/progress"):
        return {"nodes_done": 0, "total_nodes": 3, "cycles": 0, "current_node": "fixture", "started_at": None}
    return JSONResponse({"detail": "Endpoint excluded from loopback fixture"}, status_code=404)
