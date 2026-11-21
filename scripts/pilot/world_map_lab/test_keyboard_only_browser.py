"""A trusted driving key in a hidden browser must never acquire the desktop pointer."""

import os
from pathlib import Path

import pytest

from scripts.pilot.world_map_lab.browser_test_input import NO_POINTER_LOCK


def test_game_key_and_click_cannot_capture_pointer():
    sync = pytest.importorskip("playwright.sync_api")
    chrome = (
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "Google/Chrome/Application/chrome.exe"
    )
    with sync.sync_playwright() as pw:
        executable = chrome if chrome.is_file() else Path(pw.chromium.executable_path)
        if not executable.is_file():
            pytest.skip("no local Chromium executable")
        browser = pw.chromium.launch(executable_path=str(executable), headless=True)
        try:
            page = browser.new_page()
            page.add_init_script(NO_POINTER_LOCK)
            page.goto("data:text/html,<canvas tabindex='0'></canvas><iframe></iframe>")
            handler = """() => {
                window.events = [];
                for (const kind of ['keydown', 'click']) {
                    document.addEventListener(kind, async event => {
                        try { await event.target.requestPointerLock(); }
                        catch (e) { events.push([event.type, event.isTrusted, e.name]); }
                    });
                }
            }"""
            page.evaluate(handler)
            canvas = page.locator("canvas")
            canvas.focus()
            canvas.press("w")
            canvas.click()
            page.wait_for_function("window.events.length === 2")
            assert page.evaluate("window.events") == [
                ["keydown", True, "NotAllowedError"],
                ["click", True, "NotAllowedError"],
            ]
            assert page.evaluate(
                "!document.pointerLockElement && window.spherePointerLockAttempts === 2"
            )
            child = page.frames[1]
            assert (
                child.evaluate(
                    "async () => {try {await document.body.requestPointerLock()} catch(e){return e.name}}"
                )
                == "NotAllowedError"
            )
            assert child.evaluate(
                "!document.pointerLockElement && window.spherePointerLockAttempts === 1"
            )
        finally:
            browser.close()
