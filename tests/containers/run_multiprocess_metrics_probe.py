"""Accept packaged multiprocess instrumentation without touching live services."""
import argparse
import json
import subprocess
import uuid
from pathlib import Path


def docker(*args, timeout=60):
    result = subprocess.run(["docker", *args], capture_output=True, text=True,
        encoding="utf-8", timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Docker {args[0]} failed: {result.stdout}\n{result.stderr}")
    return (result.stdout + result.stderr if args[0] == "logs" else result.stdout).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--recycles", type=int, default=16)
    args = parser.parse_args()
    if not 0 <= args.recycles <= 512:
        parser.error("--recycles must be between 0 and 512")
    image = docker("image", "inspect", args.image, "--format", "{{.Id}}")
    owner = "sphere-metrics-audit-" + uuid.uuid4().hex[:12]
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    directory = Path(__file__).resolve().parent
    mounts = [part for name in ("metrics_canary_app.py", "multiprocess_metrics_probe.py")
        for part in ("--mount", f"type=bind,source={directory / name},target=/tmp/{name},readonly")]
    container = None
    summary = {"image_id": image, "host_ports": [], "network": "none", "backend_source_mount": False,
        "pilot_modified": False, "receipts": [], "container_removed": False}
    try:
        container = docker("run", "-d", "--name", owner, "--label", f"sphere.audit.metrics={owner}",
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", "384m", "--cpus", "1", "--tmpfs", "/tmp:rw,nosuid,nodev,size=32m",
            "-e", "PYTHONPATH=/app:/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", *mounts,
            image, "gunicorn", "metrics_canary_app:app", "--config", "backend/gunicorn_conf.py",
            "--worker-class", "uvicorn.workers.UvicornWorker", "--workers", "4",
            "--keep-alive", "65", "--bind", "127.0.0.1:8000")
        for run in range(2):
            output = docker("exec", container, "python", "/tmp/multiprocess_metrics_probe.py",
                "--recycles", str(args.recycles), timeout=90 + args.recycles * 25)
            receipt = json.loads(output)
            summary["receipts"].append(receipt)
            print(json.dumps({"run": run + 1, **receipt}), flush=True)
            if run == 0:
                docker("restart", "--time", "10", container)
        assert summary["receipts"][0]["directory"] != summary["receipts"][1]["directory"]
        summary["passed"] = True
    finally:
        if container:
            info = json.loads(docker("inspect", container))[0]
            assert info["Id"] == container and info["Config"]["Labels"].get("sphere.audit.metrics") == owner
            (evidence / "gunicorn.log").write_text(docker("logs", container), encoding="utf-8")
            docker("rm", "-f", "-v", container)
            summary["container_removed"] = True
        (evidence / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
