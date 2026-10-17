"""Disposable HTTP fixture using the PACKAGED instrumentation, never pilot DB."""
import os

from fastapi import FastAPI
from starlette_exporter import handle_metrics

from backend.metrics import db_pool_checked_out, db_pool_size
from backend.middleware.metrics import PrometheusMiddleware

app = FastAPI()
app.add_middleware(PrometheusMiddleware)
app.add_route("/metrics", handle_metrics)
db_pool_size.set(10)
db_pool_checked_out.set(1)


@app.get("/identity")
async def identity():
    return {"pid": os.getpid(), "directory": os.environ["PROMETHEUS_MULTIPROC_DIR"]}


@app.get("/canary/{name}")
async def canary(name: str):
    return {"pid": os.getpid()}
