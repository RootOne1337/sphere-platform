"""Run the browser engine against the supplied files and save its own boot diagnostics."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def check(url, folder, chrome, seconds, scenario):
    records = []
    failed = []
    errors = []
    snapshots = []
    requested = set()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chrome, args=["--enable-gpu", "--use-angle=d3d11"]
        )
        page = browser.new_page(viewport={"width": 1280, "height": 850})
        page.on("console", lambda m: records.append(str(m.text)[:1500]))
        page.on("pageerror", lambda e: errors.append(str(e)))
        module_responses = {}

        def response_seen(response):
            path = response.url.split("?")[0]
            if not response.ok:
                failed.append([response.status, response.url])
                return
            requested.add(path)
            name = path.rsplit("/", 1)[-1]
            if name in ("sa_game_bg.wasm", "sphere_journey.wasm"):
                module_responses[name] = response

        page.context.on("response", response_seen)
        page.goto(
            url.rstrip("/")
            + "/?autostart=1&backend=gl&cache_mb=64"
            + ("&mods=sphere-journey" if scenario else ""),
            timeout=45000,
        )
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            page.wait_for_timeout(1200)
            row = page.locator("#status").inner_text()
            if not snapshots or snapshots[-1] != row:
                snapshots.append(row)
            log = page.locator("#log").inner_text()
            if any(
                t in (row + " " + log[-500:]).lower()
                for t in (
                    "panicked",
                    "unreachable",
                    "fatal error",
                    "aborted",
                    "runtimeerror",
                    "initialization failed",
                    "init failed",
                )
            ):
                break
        page.screenshot(path=str(folder / "engine-boot.png"))
        loaded = any(u.endswith("sa_game_bg.wasm") for u in requested)
        module_hashes = {}
        for name, response in module_responses.items():
            try:
                contents = response.body()
            except Exception:
                # Large worker responses can be evicted from Chrome's devtools cache.
                reread = page.request.get(response.url)
                if not reread.ok:
                    raise RuntimeError(f"module response no longer available: {name}")
                contents = reread.body()
                source = "same-url-reread"
                reread.dispose()
            else:
                source = "browser-response"
            module_hashes[name] = {"sha256": hashlib.sha256(contents).hexdigest(), "source": source}
        proof = dict(
            modules=module_hashes,
            moduleRequested=loaded,
            scenarioRequested=any(u.endswith("sphere_journey.wasm") for u in requested),
            states=snapshots,
            console=records[-100:],
            engineLog=log[-12000:],
            httpErrors=failed[-30:],
            pageErrors=errors,
            gameDriveVerified=False,
        )
        (folder / "engine-boot.json").write_text(
            json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf8"
        )
        print(
            json.dumps(
                {
                    "moduleRequested": loaded,
                    "status": snapshots[-1],
                    "logTail": log[-450:],
                    "pageErrors": errors,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        browser.close()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--url", default="http://127.0.0.1:8819")
    cli.add_argument("--output", required=True, type=Path)
    cli.add_argument("--chrome", default="C:/Program Files/Google/Chrome/Application/chrome.exe")
    cli.add_argument("--seconds", type=float, default=40)
    cli.add_argument("--scenario", action="store_true")
    a = cli.parse_args()
    check(a.url, a.output, a.chrome, a.seconds, a.scenario)
