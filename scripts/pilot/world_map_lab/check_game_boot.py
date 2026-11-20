"""Run the browser engine against the supplied files and save its own boot diagnostics."""

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from scripts.pilot.world_map_lab.prepare_boot_probe import language_table


def install_test_language(context, url):
    # Supply one authored resource in the private browser context. Existing files
    # remain available from the upstream loopback server, including byte ranges.
    if urlsplit(url).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("local boot fixture required")
    base = url.rstrip("/")
    index = context.request.get(base + "/game-index.json").json()
    path = "text/american.gxt"
    if any(entry["path"].lower() == path for entry in index):
        raise ValueError("English dictionary already provided")
    blob = language_table()
    index.append({"path": path, "size": len(blob), "mtime": 1})
    context.route(base + "/game-index.json", lambda route: route.fulfill(json=index))

    def resource(route):
        requested = route.request.headers.get("range")
        if not requested:
            route.fulfill(body=blob, content_type="application/octet-stream")
            return
        bounds = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
        start, end = (
            (int(bounds[1]), min(int(bounds[2]) if bounds[2] else len(blob) - 1, len(blob) - 1))
            if bounds
            else (len(blob), -1)
        )
        if start > end:
            route.fulfill(status=416, headers={"Content-Range": f"bytes */{len(blob)}"})
            return
        route.fulfill(
            status=206,
            body=blob[start : end + 1],
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Range": f"bytes {start}-{end}/{len(blob)}",
            },
        )

    context.route(base + "/game/" + path, resource)


def check(url, folder, chrome, seconds, scenario, test_language=False):
    records = []
    failed = []
    errors = []
    snapshots = []
    rendered = False
    requested = set()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chrome, args=["--enable-gpu", "--use-angle=d3d11"]
        )
        page = browser.new_page(viewport={"width": 1280, "height": 850})
        if test_language:
            install_test_language(page.context, url)
        boot_steps = []
        file_opens = []

        def remember(message):
            line = str(message.text)[:1500]
            records.append(line)
            if "[boot]" in line and "rust: ok" in line:
                boot_steps.append(line.strip())
            if line.startswith("file open "):
                file_opens.append(line)

        page.on("console", remember)
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
            state = page.evaluate("() => window.saGame?.status ?? null")
            if (
                state
                and state.get("state") == 9
                and state.get("presents", 0) > 0
                and not state.get("error")
                and not state.get("inMenu")
            ):
                rendered = True
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
            testLanguage=test_language,
            completedBootSteps=boot_steps,
            fileOpens=file_opens,
            worldRendered=rendered,
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
                    "lastCompletedStep": boot_steps[-1] if boot_steps else None,
                    "fileOpens": file_opens[-3:],
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
    cli.add_argument("--test-language", action="store_true")
    a = cli.parse_args()
    check(a.url, a.output, a.chrome, a.seconds, a.scenario, a.test_language)
