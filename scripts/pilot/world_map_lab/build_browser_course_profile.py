"""Build the HUD-free native camera observer for a local sa-engine browser server."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


def build(engine, destination, cargo):
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
                "--release",
                "--target",
                "wasm32-unknown-unknown",
                "--target-dir",
                artifacts,
            ],
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
            'api_version="1.16"\nentry="br_game_profile.wasm"\n[permissions]\nstate="write"\n',
            encoding="utf8",
        )
        mod.rename(target)
    return target


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--engine", required=True, type=Path)
    cli.add_argument("--mods", required=True, type=Path)
    cli.add_argument("--cargo", default="cargo")
    opts = cli.parse_args()
    print(build(opts.engine, opts.mods.resolve(), opts.cargo))
