"""Finite real-HTTP callback canary, confined to a temporary loopback receiver.

No Sphere task, DB, Android command, production webhook or external request.
Retry sleeps are recorded and omitted; HTTP serialization/transport are real.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, patch

from structlog.testing import capture_logs

from backend.services.webhook_service import WebhookService


async def probe() -> dict:
    cases = [
        ("acknowledged", [204], "delivered"),
        ("forbidden", [403], "rejected"),
        ("rate_limit_recovery", [429, 204], "delivered"),
        ("server_recovery", [503, 204], "delivered"),
        ("server_exhaustion", [503] * 4, "server_error"),
    ]
    state: dict = {"statuses": [], "requests": []}

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state["requests"].append({"body": body, "delivery_id": self.headers["X-Sphere-Delivery"],
                                      "signature": self.headers["X-Sphere-Signature"]})
            code = state["statuses"][len(state["requests"]) - 1]
            self.send_response(code)
            self.send_header("Content-Length", "0")
            if code == 429:
                self.send_header("Retry-After", "7")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    receipts = []
    try:
        for name, statuses, outcome in cases:
            state.update(statuses=statuses, requests=[])
            with capture_logs() as events, patch("asyncio.sleep", AsyncMock()) as sleep:
                await WebhookService().deliver(
                    f"http://127.0.0.1:{server.server_port}/audit-only",
                    {"event_type": "audit.callback", "case": name, "text": "Проверка"},
                    "isolated-audit-signing-key",
                )
            requests = state["requests"]
            assert len(requests) == len(statuses)
            assert len({r["delivery_id"] for r in requests}) == 1
            assert len({r["body"] for r in requests}) == 1
            assert all(r["signature"] == "sha256=" + hmac.new(
                b"isolated-audit-signing-key", r["body"], hashlib.sha256,
            ).hexdigest() for r in requests)
            assert events[-1]["outcome"] == outcome
            assert events[-1]["event"] == ("webhook.delivered" if outcome == "delivered" else "webhook.delivery_failed")
            receipts.append({"case": name, "httpStatuses": statuses, "attempts": len(requests),
                             "retryDelaysSeconds": [call.args[0] for call in sleep.await_args_list],
                             "signatureValid": True, "stableDeliveryId": True, "events": events})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert not thread.is_alive()
    return {"observedAt": datetime.now(timezone.utc).isoformat(), "transport": "real loopback HTTP",
            "retrySleepsOmitted": True, "externalRequests": False, "sphereTasksCreated": False,
            "receiverClosed": True, "cases": receipts}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe()), ensure_ascii=False, indent=2))
