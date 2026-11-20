"""Render first-person RGB from the independently served full exterior scene."""

import base64
from contextlib import contextmanager
from urllib.parse import urlencode

import cv2
import numpy as np


@contextmanager
def open_eye(port, center, *, width, height, hfov, browser=None, radius=160):
    from playwright.sync_api import sync_playwright

    params = dict(zip(("x", "y", "z"), map(float, center), strict=True))
    params.update(view="first", capture=1, hfov=hfov, radius=radius)
    with sync_playwright() as pw:
        client = pw.chromium.launch(executable_path=browser, headless=True)
        try:
            page = client.new_page(
                viewport={"width": width, "height": height}, device_scale_factor=1
            )
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"http://127.0.0.1:{port}/detail?" + urlencode(params))
            page.wait_for_function(
                """() => /треугольников|Не удалось|моделей нет|требуется WebGL/.test(document.querySelector('#status').textContent)""",
                timeout=90000,
            )

            summary = page.locator("#status").inner_text()
            if "треугольников" not in summary:
                raise RuntimeError(f"first-person sector unavailable: {summary}")

            def frame(xyz, yaw, pitch, roll=0.0):
                pose = dict(
                    zip(("x", "y", "z"), map(float, xyz), strict=True),
                    yaw=yaw,
                    pitch=pitch,
                    roll=roll,
                )
                encoded = page.evaluate("(pose) => window.captureMapEye(pose)", pose)
                image = cv2.imdecode(
                    np.frombuffer(base64.b64decode(encoded.split(",", 1)[1]), np.uint8),
                    cv2.IMREAD_COLOR,
                )
                if errors or image is None or image.shape != (height, width, 3):
                    raise RuntimeError(f"failed to capture calibrated RGB: {errors}")
                return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

            meta = page.request.get(f"http://127.0.0.1:{port}/api/world")
            if not meta.ok:
                raise RuntimeError("cannot bind first-person capture to a map revision")
            frame.revision = meta.json()["drive"]["placementRevision"]
            yield frame
        finally:
            client.close()
