"""Run the browser engine against the supplied files and save its own boot diagnostics."""

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
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


def check(
    url,
    folder,
    chrome,
    seconds,
    scenario,
    test_language=False,
    strict=False,
    start_game=False,
    startup_profile=False,
    backend="gl",
):
    records = []
    failed = []
    errors = []
    snapshots = []
    rendered = False
    requested = set()
    menu_inputs = []
    transitions = []
    state = None
    last_input_at = float("-inf")
    log = ""
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
        mods = (["sphere-journey"] if scenario else []) + (
            ["br-game-profile"] if startup_profile else []
        )
        page.goto(
            url.rstrip("/")
            + f"/?autostart=1&backend={backend}&cache_mb=64"
            + ("&mods=" + ",".join(mods) if mods else "")
            + ("&strict=1&inworld=0" if strict else ""),
            wait_until="commit",
            timeout=45000,
        )
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            page.wait_for_timeout(1200)
            telemetry = page.evaluate("""() => {
                const game = window.saGame;
                return {
                    row: document.getElementById('status')?.textContent ?? '',
                    state: game?.status ?? null,
                    log: game?.logs?.slice(-80).join('\\n').slice(-12000) ?? '',
                    panic: game?.panic ?? null
                };
            }""")
            row, state, log = telemetry["row"], telemetry["state"], telemetry["log"]
            if state and (state_id := state.get("state")) is not None:
                if not transitions or transitions[-1] != state_id:
                    transitions.append(state_id)
                    print(f"game state {state_id}: {row[:180]}", flush=True)
                # Only dismiss movies and select New Game before the world starts.
                if (
                    start_game
                    and state_id in (2, 4, 7)
                    and not state.get("error")
                    and not state.get("done")
                    and time.monotonic() - last_input_at > 2
                ):
                    page.keyboard.press("Enter", delay=100)
                    menu_inputs.append(state_id)
                    last_input_at = time.monotonic()
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
            if (
                rendered
                or telemetry["panic"]
                or (state and (state.get("done") or state.get("error")))
            ):
                break
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
        try:
            page.screenshot(path=str(folder / "engine-boot.png"), timeout=5000)
        except PlaywrightTimeoutError:
            records.append("engine screenshot timed out")
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
            startupMods=mods,
            backend=backend,
            menuInputStates=menu_inputs,
            stateTransitions=transitions,
            lastStatus=state,
            strictRequested=strict,
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
                    "status": snapshots[-1] if snapshots else None,
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
    cli.add_argument(
        "--strict", action="store_true", help="disable exploration overrides in the patched port"
    )
    cli.add_argument(
        "--start-game", action="store_true", help="press Enter at the logo, intro and New Game menu"
    )
    cli.add_argument(
        "--startup-profile",
        action="store_true",
        help="load the installed br-game-profile startup mod",
    )
    cli.add_argument("--backend", choices=("gl", "webgpu"), default="gl")
    a = cli.parse_args()
    a.output.mkdir(exist_ok=True, parents=True)
    check(
        a.url,
        a.output,
        a.chrome,
        a.seconds,
        a.scenario,
        a.test_language,
        a.strict,
        a.start_game,
        a.startup_profile,
        a.backend,
    )
