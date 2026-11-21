"""Build the HUD-free native camera observer for a local sa-engine browser server."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


def build(engine, destination, cargo, world_ide=None, stream_mib=640):
    if not 64 <= stream_mib <= 1024:
        raise ValueError("streaming budget outside 64–1024 MiB")
    sdk = (engine / "crates/sa-mod").resolve(strict=True)
    target = destination / "br-game-profile"
    if target.exists():
        raise FileExistsError(target)
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination) as temp:
        project = Path(temp) / "profile"
        (project / "src").mkdir(parents=True)
        source = Path(__file__).with_name("browser_course_profile.rs")
        shutil.copyfile(source, project / "src/lib.rs")
        (project / "Cargo.toml").write_text(
            '[package]\nname="br-game-profile"\nversion="0.1.0"\nedition="2024"\n'
            "[features]\nfull-world=[]\n"
            '[lib]\ncrate-type=["cdylib"]\n[dependencies]\n'
            f"sa-mod={{path={json.dumps(sdk.as_posix(), ensure_ascii=False)}}}\n",
            encoding="utf8",
        )
        artifacts = Path(temp) / "target"
        subprocess.run(
            [
                cargo,
                "build",
                "--offline",
                *(["--features", "full-world"] if world_ide else []),
                "--release",
                "--target",
                "wasm32-unknown-unknown",
                "--target-dir",
                artifacts,
            ],
            env={**os.environ, "SPHERE_WORLD_STREAM_MIB": str(stream_mib)},
            cwd=project,
            check=True,
        )
        mod = Path(temp) / "mod"
        mod.mkdir()
        shutil.copyfile(
            artifacts / "wasm32-unknown-unknown/release/br_game_profile.wasm",
            mod / "br_game_profile.wasm",
        )
        (mod / "mod.toml").write_text(
            '[mod]\nid="br-game-profile"\nname="Black Russia course startup"\nversion="0.1.0"\n'
            'api_version="1.16"\nentry="br_game_profile.wasm"\n[permissions]\nstate="write"\nrender=true\n'
            + ('[data]\nide=["brworld.ide"]\n' if world_ide else ""),
            encoding="utf8",
        )
        if world_ide:
            shutil.copyfile(world_ide, mod / "brworld.ide")
        mod.rename(target)
    return target


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--engine", required=True, type=Path)
    cli.add_argument("--mods", required=True, type=Path)
    cli.add_argument("--cargo", default="cargo")
    cli.add_argument("--world-ide", type=Path)
    cli.add_argument("--stream-mib", type=int, default=640)
    opts = cli.parse_args()
    print(build(opts.engine, opts.mods.resolve(), opts.cargo, opts.world_ide, opts.stream_mib))
