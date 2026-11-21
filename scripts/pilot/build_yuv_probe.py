"""Build finite Android YUV diagnostics against the verified, already used WebRTC AAR.

No download, APK installation, emulator action or server modification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

AAR_SHA256 = "8650f62de6bf8ae930ce72a70e999f1ce2a1dfb87dddca2bbe0cb3317dc6fd28"
PROBES = ("NativeYuvBench", "NativeYuvGpuBench", "GpuYuvConverterBench")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--webrtc-aar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--probe", choices=PROBES, required=True)
    parser.add_argument("--platform", default="android-35")
    parser.add_argument("--build-tools", default="37.0.0")
    args = parser.parse_args()
    source = Path(__file__).with_name("android") / (args.probe + ".java")
    platform = args.sdk / "platforms" / args.platform / "android.jar"
    d8 = args.sdk / "build-tools" / args.build_tools / "lib/d8.jar"
    suffix = ".exe" if (args.java_home / "bin/java.exe").is_file() else ""
    java, javac = (args.java_home / "bin" / (name + suffix) for name in ("java", "javac"))
    for path in (source, platform, d8, java, javac, args.webrtc_aar):
        if not path.is_file() or path.is_symlink():
            parser.error(f"Regular input file required: {path}")
    if hashlib.sha256(args.webrtc_aar.read_bytes()).hexdigest() != AAR_SHA256:
        parser.error("WebRTC 146.7.0 AAR checksum mismatch")
    destination = args.output.resolve()
    if destination.exists() or destination.suffix != ".jar":
        parser.error("Choose a fresh .jar output; existing results are never overwritten")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sphere-yuv-build-", dir=destination.parent) as temporary:
        work = Path(temporary)
        with zipfile.ZipFile(args.webrtc_aar) as archive:
            raw = archive.read("classes.jar")
        dependency = work / "webrtc-classes.jar"
        dependency.write_bytes(raw)
        classes = work / "classes"
        classes.mkdir()
        subprocess.run([str(javac), "--release", "8", "-cp", str(dependency) +
                        (";" if suffix else ":") + str(platform), "-d", str(classes), str(source)],
                       check=True, timeout=60)
        subprocess.run([str(java), "-Xmx512m", "-cp", str(d8), "com.android.tools.r8.D8",
                        "--min-api", "28", "--lib", str(platform), "--output", str(destination),
                        *map(str, sorted(classes.rglob("*.class"))), str(dependency)],
                       check=True, timeout=60)
    print(json.dumps({"artifact": str(destination), "probe": args.probe,
                      "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                      "bytes": destination.stat().st_size, "webrtcAarSha256": AAR_SHA256,
                      "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                      "deviceCommandsSent": False}))


if __name__ == "__main__":
    main()
