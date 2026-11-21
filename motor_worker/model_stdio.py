"""Opt-in child entry point after a trusted local model has loaded and warmed.

Callbacks receive original RGB bytes; preprocessing is the adapter's obligation.
No Torch/desktop capture/Android/control dependency is imported here.
"""

from __future__ import annotations

import contextlib
import json
import sys
import time

from motor_worker.policy import PolicyFrame, epoch_valid
from motor_worker.process_policy import ADAPTERS, PROTOCOL, _json_object
from motor_worker.protocol import ProtocolError, integer


def serve(predict, reset, adapter: str, *, max_requests: int = 6000) -> None:
    if adapter not in ADAPTERS or not integer(max_requests, 1, 6000):
        raise ProtocolError("invalid_policy_stdio_config")
    source, sink = sys.stdin.buffer, sys.stdout.buffer
    sink.write(
        json.dumps({"protocol": PROTOCOL, "kind": "ready", "adapter": adapter}).encode() + b"\n"
    )
    sink.flush()
    previous_epoch, previous_sequence, previous_request = None, 0, 0
    for _ in range(max_requests):
        raw = source.readline(4097)
        if not raw:
            return
        if len(raw) > 4096 or not raw.endswith(b"\n"):
            raise ProtocolError("invalid_policy_stdio_header")
        header = _json_object(raw)
        if (
            header.keys() != {"requestId", "epoch", "receiverSequence", "width", "height"}
            or not integer(header["requestId"], previous_request + 1, 2**53 - 1)
            or not epoch_valid(header["epoch"])
            or not integer(header["receiverSequence"], 1, 2**53 - 1)
            or not integer(header["width"], 1, 4096)
            or not integer(header["height"], 1, 4096)
            or header["width"] * header["height"] > 8 * 1024 * 1024
            or header["epoch"] == previous_epoch
            and header["receiverSequence"] <= previous_sequence
        ):
            raise ProtocolError("invalid_policy_stdio_header")
        expected = header["width"] * header["height"] * 3
        pixels = source.read(expected)
        if len(pixels) != expected:
            raise ProtocolError("policy_stdio_truncated_frame")
        frame = PolicyFrame(
            header["epoch"],
            header["receiverSequence"],
            time.perf_counter(),
            header["width"],
            header["height"],
            pixels,
        )
        started = time.perf_counter()
        # Model progress/log prints must not become response messages.
        with contextlib.redirect_stdout(sys.stderr):
            if previous_epoch != header["epoch"]:
                reset()
            prediction = predict(frame)
        previous_epoch, previous_sequence, previous_request = (
            header["epoch"],
            header["receiverSequence"],
            header["requestId"],
        )
        reply = {
            "requestId": previous_request,
            "epoch": previous_epoch,
            "receiverSequence": previous_sequence,
            "prediction": prediction,
            "inferenceWallMs": (time.perf_counter() - started) * 1000,
        }
        try:
            encoded = json.dumps(reply, allow_nan=False).encode("utf-8") + b"\n"
        except (ValueError, TypeError, RecursionError) as exc:
            raise ProtocolError("invalid_policy_stdio_prediction") from exc
        if len(encoded) > 32768:
            raise ProtocolError("policy_stdio_prediction_too_large")
        sink.write(encoded)
        sink.flush()
