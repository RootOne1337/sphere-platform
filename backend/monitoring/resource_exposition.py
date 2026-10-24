"""Keep existing worker exposition and append one container snapshot per scrape."""
from prometheus_client import CollectorRegistry, generate_latest
from starlette.requests import Request
from starlette.responses import Response
from starlette_exporter import handle_metrics as worker_metrics

from backend.monitoring.container_resources import ContainerResources


def handle_metrics(request: Request) -> Response:
    response = worker_metrics(request)
    registry = CollectorRegistry()
    registry.register(ContainerResources())
    headers = {key: value for key, value in response.headers.items() if key.lower() != "content-length"}
    return Response(bytes(response.body) + generate_latest(registry), status_code=response.status_code, headers=headers)
