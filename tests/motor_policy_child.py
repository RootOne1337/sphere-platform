"""Real disposable child process for IPC tests; never connects to a device."""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor_worker.model_stdio import serve  # noqa: E402
from motor_worker.process_policy import PROTOCOL  # noqa: E402

mode, adapter = sys.argv[1:3]
if any(os.environ.get(k) for k in ("SPHERE_ACCESS_TOKEN", "HF_TOKEN", "AWS_SECRET_ACCESS_KEY")):
    raise SystemExit("credentials_were_inherited")
if mode == "valid":
    counter = 0

    def reset():
        global counter
        counter = 0

    def predict(frame):
        global counter
        counter += 1
        print("private model progress", flush=True)
        if adapter == "open-p2p-150m-decoded-v1":
            return {
                "keys": ["w", "LeftShift"],
                "mouse_buttons": ["0"],
                "mouse_delta_x": counter,
                "mouse_delta_y": -frame.rgb24[-1],
            }
        return {
            "j_left": [[frame.rgb24[0] / 255, counter / 100]] * 18,
            "j_right": [[0, 0]] * 18,
            "buttons": [[0] * 21] * 18,
        }

    serve(predict, reset, adapter)
    raise SystemExit(0)

if mode == "startup_hang":
    time.sleep(10)
if mode == "startup_flood":
    print("x" * 70000, flush=True)
    time.sleep(10)
if mode == "wrong_ready":
    print(json.dumps({"kind": "ready", "protocol": "wrong", "adapter": adapter}), flush=True)
    time.sleep(10)

print(json.dumps({"kind": "ready", "protocol": PROTOCOL, "adapter": adapter}), flush=True)
header = json.loads(sys.stdin.buffer.readline())
pixels = sys.stdin.buffer.read(header["width"] * header["height"] * 3)
if mode == "eof":
    raise SystemExit(0)
if mode == "hang":
    time.sleep(10)
if mode == "slow":
    time.sleep(0.1)
if mode == "reply_flood":
    print("x" * 70000, flush=True)
    time.sleep(10)
if mode == "duplicate":
    print('{"requestId":1,"requestId":1}', flush=True)
    time.sleep(10)
reply = {k: header[k] for k in ("requestId", "epoch", "receiverSequence")}
reply.update(
    prediction={"j_left": [[0, 0]], "j_right": [[0, 0]], "buttons": [[0] * 21]}, inferenceWallMs=1
)
if mode == "wrong_request":
    reply["requestId"] += 1
if mode == "bool_request":
    reply["requestId"] = True
if mode == "wrong_sequence":
    reply["receiverSequence"] += 1
if mode == "wrong_epoch":
    reply["epoch"] = "753fd530-2f19-4e5e-98ba-769863678141"
if mode == "extra":
    reply["unrecognized"] = "private value"
if mode == "nan":
    reply["inferenceWallMs"] = float("nan")
if mode == "invalid_prediction":
    reply["prediction"]["buttons"] = [[0.5] * 21]
print(json.dumps(reply), flush=True)
time.sleep(10)
