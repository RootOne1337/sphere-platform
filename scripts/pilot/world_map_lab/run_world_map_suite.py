"""Run a reproducible source audit and bounded native-render batches on an isolated local game."""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path
from urllib.request import urlopen

from scripts.pilot.world_map_lab.check_world_fidelity import audit
from scripts.pilot.world_map_lab.export_full_game_world import digest
from scripts.pilot.world_map_lab.inspect_world_cells import (
    capture,
    mission,
    sample_sites,
    save_progress,
)


def share(path, into):
    target = into / path.name
    if path.is_dir():
        if os.name == "nt":
            # PowerShell receives literal paths through environment values, including spaces/apostrophes.
            env = {**os.environ, "BR_TEST_LINK": str(target), "BR_TEST_TARGET": str(path)}
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:BR_TEST_LINK -Target $env:BR_TEST_TARGET | Out-Null",
                ],
                check=True,
                env=env,
            )
        else:
            target.symlink_to(path, target_is_directory=True)
    else:
        shutil.copyfile(path, target)


def stage_assets(game, out):
    out.mkdir()
    for src in game.iterdir():
        if src.name != "data":
            share(src, out)
    data = out / "data"
    data.mkdir()
    for src in (game / "data").iterdir():
        if src.name != "script":
            share(src, data)
    scripts = data / "script"
    scripts.mkdir()
    shutil.copyfile(game / "data/script/script.img", scripts / "script.img")
    return scripts


@contextmanager
def game_server(script, web, game, mods, log_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with (
        (log_path).open("w", encoding="utf8") as log,
        subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(script),
                "--port",
                str(port),
                "--web",
                str(web),
                "--game",
                str(game),
                "--mods",
                str(mods),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        ) as server,
    ):
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and server.poll() is None:
                try:
                    with urlopen(url + "/", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.15)
            else:
                raise RuntimeError("isolated game server did not start")
            yield url
        finally:
            server.terminate()
            try:
                server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


def capture_batch(args, plan, base, out, start):
    subset = plan["sites"][start : start + args.batch_size]
    block = out / f"batch-{start:03}"
    block.mkdir()
    staged = block / "game"
    scripts = stage_assets(args.game.resolve(), staged)
    (scripts / "main.sc").write_text(mission(base, subset), encoding="ascii")
    subprocess.run(
        [
            str(args.compiler.resolve()),
            "compile",
            "--config=gtasa",
            "--guesser",
            "main.sc",
            "-o",
            "main.scm",
        ],
        cwd=scripts,
        check=True,
    )
    with game_server(args.server, args.web, staged, args.mods, block / "server.log") as url:
        stats = capture(url, {"sites": subset}, block / "frames", args.chrome)
    return start, block, stats


def run(args):
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    default = args.game / "sphere-world-cells.json"
    cells = {tuple(c["cell"]) for c in json.loads(default.read_bytes())}
    plan = sample_sites(cells, args.surfaces)
    (out / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf8")
    fidelity = audit(
        args.source.resolve(), args.game.resolve(), args.mods.resolve() / "br-game-profile"
    )
    (out / "fidelity.json").write_text(json.dumps(fidelity, indent=2), encoding="utf8")
    if not fidelity["transferPassed"]:
        raise RuntimeError("source transfer differs; inspect fidelity.json")
    if not 1 <= args.batch_size <= len(plan["sites"]):
        raise ValueError("invalid batch size")
    if not 1 <= args.workers <= 4:
        raise ValueError("workers must be between 1 and 4")
    base = args.scenario.read_text(encoding="ascii")
    observed = {}
    summary = dict(
        planned=len(plan["sites"]),
        cellsWithoutSurface=plan["cellsWithoutSample"],
        batches=[],
        indexSha256=digest(default),
        wasmSha256=digest(args.web / "pkg/sa_game_bg.wasm"),
        sourceComplete=not fidelity["unavailableSourceRows"]
        and not fidelity["materials"]["counts"].get("modelsWithUnresolvedDraws"),
        complete=False,
    )
    starts = range(0, len(plan["sites"]), args.batch_size)
    with ThreadPoolExecutor(max_workers=args.workers) as workers:
        runs = [workers.submit(capture_batch, args, plan, base, out, start) for start in starts]
        for finished in as_completed(runs):
            start, block, stats = finished.result()
            summary["batches"].append({"start": start, **stats})
            samples = block / "frames/samples.json"
            for local, row in json.loads(samples.read_bytes()).items() if samples.exists() else []:
                row["file"] = (Path(block.name) / "frames" / row["file"]).as_posix()
                observed[start + int(local)] = row
            save_progress(out / "samples.json", observed)
            summary["captured"] = len(observed)
            save_progress(out / "result.json", summary)
            print("native samples", len(observed), "/", len(plan["sites"]), flush=True)
    summary["batches"].sort(key=lambda b: b["start"])
    summary["complete"] = len(observed) == len(plan["sites"]) and all(
        not s["missing"]
        and not s["flatFrames"]
        and not s["ioFailures"]
        and not s.get("engineError")
        for s in summary["batches"]
    )
    save_progress(out / "result.json", summary)
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "game", "mods", "web", "scenario", "compiler", "server", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--surfaces", nargs="+", type=Path, required=True)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--batch-size", type=int, default=25)
    p.add_argument("--chrome", default="C:/Program Files/Google/Chrome/Application/chrome.exe")
    p.add_argument("--require-complete-source", action="store_true")
    opts = p.parse_args()
    result = run(opts)
    print("native batches passed", result["complete"], "complete source", result["sourceComplete"])
    raise SystemExit(
        int(
            not result["complete"]
            or (opts.require_complete_source and not result["sourceComplete"])
        )
    )
