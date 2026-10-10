"""Compile the standalone Android codec diagnostic; no APK or device changes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", default="android-35")
    parser.add_argument("--build-tools", default="35.0.0")
    parser.add_argument("--probe", choices=("MediaCodecProbe", "PlanarViewerRefreshProbe"), default="MediaCodecProbe")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent / "android" / (args.probe + ".java")
    android = args.sdk / "platforms" / args.platform / "android.jar"
    d8 = args.sdk / "build-tools" / args.build_tools / "lib/d8.jar"
    suffix = ".exe" if os.name == "nt" else ""
    javac = args.java_home / "bin" / ("javac" + suffix)
    java = args.java_home / "bin" / ("java" + suffix)
    for path in (source, android, d8, javac, java):
        if not path.is_file():
            parser.error(f"Required file does not exist: {path}")
    destination = args.output.resolve()
    if destination.exists():
        parser.error("Output already exists; choose a fresh artifact path.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    options = {"check": True}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    # Remove only this automatically owned temporary compilation directory.
    with tempfile.TemporaryDirectory(prefix="sphere-codec-build-", dir=destination.parent) as temporary:
        classes = Path(temporary)
        subprocess.run([str(javac), "--release", "8", "-cp", str(android), "-d", str(classes), str(source)], **options)
        subprocess.run([str(java), "-cp", str(d8), "com.android.tools.r8.D8", "--min-api", "26",
            "--lib", str(android), "--output", str(destination),
            *map(str, (classes / "com/sphereplatform/audit").glob(args.probe + "*.class"))], **options)
    print(json.dumps({"artifact": str(destination), "bytes": destination.stat().st_size,
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
