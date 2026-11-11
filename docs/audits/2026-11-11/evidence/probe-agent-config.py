"""Exercise the source CLI in a temp copy with generated input, no keys or ADB."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4] / "agent-config"


def run(folder):
    scripts = folder / "scripts"
    scripts.mkdir()
    executable = scripts / "generate_device_config.py"
    shutil.copyfile(ROOT / "scripts" / executable.name, executable)
    shutil.copyfile(ROOT / "schema.json", folder / "schema.json")
    envs = folder / "environments"
    envs.mkdir()
    fixture = {"config_version": 1, "server_url": "https://sphere.example.test",
               "enrollment_api_key": "sphr_fixture", "environment": "development"}

    def cli(case, config, *args):
        (envs / "development.json").write_text(json.dumps(config), encoding="utf-8")
        target = folder / case
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(executable), "--env", "development",
             "--output-dir", str(target), *args],
            cwd=folder, text=True, encoding="utf-8", capture_output=True, timeout=15,
        )
        files = sorted(target.glob("*.json"))
        configs = [json.loads(path.read_text(encoding="utf-8")) for path in files]
        count = re.search(r"Сгенерировано конфигов: (\d+)", result.stdout)
        return {
            "exit_code": result.returncode,
            "reported_count": int(count[1]) if count else None,
            "filenames": [path.name for path in files],
            "instance_indices": [item["instance_index"] for item in configs],
            "non_http_server_written": any(not item["server_url"].startswith(("http://", "https://"))
                                           for item in configs),
            "empty_enrollment_key_written": any(not item["enrollment_api_key"] for item in configs),
        }

    return {
        "batch_without_workstation": cli("batch", fixture, "--count", "3", "--instance-index", "7"),
        "documented_single_clone_index": cli("clone", fixture, "--workstation-id", "fixture",
                                             "--instance-index", "42"),
        "invalid_provisioning": cli("invalid", {**fixture, "server_url": "not-a-url", "enrollment_api_key": ""}),
    }


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="sphere-audit-agent-config-") as directory:
        print(json.dumps(run(Path(directory)), indent=2))
