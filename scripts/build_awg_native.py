"""Build a pinned diagnostic AWG library. Does not build/install an APK or route traffic.

The opt-in clock overlay ports upstream's BOOTTIME change to pinned Go sources
without modifying the installed Go toolchain. Artifacts remain diagnostic-only
until device/runtime and app-isolation acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import struct
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.pilot.resource_guard import collect, evaluate  # noqa: E402

TARGETS = {
    "x86_64": ("amd64", "x86_64-linux-android26", 62, 2),
    "arm64-v8a": ("arm64", "aarch64-linux-android26", 183, 2),
    "armeabi-v7a": ("arm", "armv7a-linux-androideabi26", 40, 1),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_elf_header(data: bytes, abi: str) -> None:
    if len(data) < 20 or data[:4] != b"\x7fELF" or data[4] != TARGETS[abi][3] or data[5] != 1:
        raise ValueError("Invalid Android ELF header/class/endianness")
    kind, machine = struct.unpack_from("<HH", data, 16)
    if kind != 3 or machine != TARGETS[abi][2]:
        raise ValueError("Android ELF ABI/type mismatch")


def checked_source(path: Path, expected: str, url: str) -> None:
    if path.exists():
        if not path.is_file() or sha(path.read_bytes()) != expected:
            raise ValueError("Existing upstream source differs from lock; refusing overwrite")
        return
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(131073)
    if len(data) > 131072 or sha(data) != expected:
        raise ValueError("Upstream source size/hash mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def prepare_clock_overlay(goroot: Path, output: Path, hashes: dict[str, str]) -> tuple[Path, dict]:
    """Only the three supported Linux assembly targets; no global Go writes."""
    expected_files = {"sys_linux_amd64.s", "sys_linux_arm64.s", "sys_linux_arm.s"}
    if set(hashes) != expected_files:
        raise ValueError("Incomplete Go clock source inventory")
    replacements, receipts = {}, {}
    directory = output / "android-clock-overlay"
    directory.mkdir(parents=True, exist_ok=True)
    for name in sorted(hashes):
        original = (goroot / "src/runtime" / name).resolve()
        data = original.read_bytes()
        if sha(data) != hashes[name]:
            raise ValueError("Go runtime source differs from clock lock")
        text = data.decode("utf-8")
        if name == "sys_linux_amd64.s":
            old, new = "MOVL\t$1, DI // CLOCK_MONOTONIC", "MOVL\t$7, DI // CLOCK_BOOTTIME"
            if text.count(old) != 1:
                raise ValueError("Unexpected amd64 nanotime source")
            text = text.replace(old, new)
        else:
            old = "#define CLOCK_MONOTONIC\t1" if name == "sys_linux_arm.s" else "#define CLOCK_MONOTONIC 1"
            new = old.replace("CLOCK_MONOTONIC", "CLOCK_BOOTTIME").replace("1", "7")
            if text.count(old) != 1 or text.count("$CLOCK_MONOTONIC") != 1:
                raise ValueError("Unexpected ARM nanotime source")
            text = text.replace(old, new).replace("$CLOCK_MONOTONIC", "$CLOCK_BOOTTIME")
        target = directory / name
        target.write_bytes(text.encode("utf-8"))
        replacements[original.as_posix()] = target.resolve().as_posix()
        receipts[name] = {"original_sha256": sha(data), "overlay_sha256": sha(target.read_bytes())}
    overlay = directory / "overlay.json"
    overlay.write_text(json.dumps({"Replace": replacements}, indent=2) + "\n", encoding="utf-8")
    return overlay, receipts


def prepare_jni_source(source: Path, output: Path, lock: dict) -> Path:
    patch = (ROOT / "android/awg-sdk/patches/android-jni-lifecycle.patch").read_bytes().replace(b"\r\n", b"\n")
    if sha(patch) != lock["android_jni_lifecycle_patch_sha256"]:
        raise ValueError("JNI lifecycle patch differs from lock")
    effective = output / "effective-libwg-go"
    effective.mkdir(parents=True, exist_ok=True)
    if any(p.name not in {"api-android.go", "jni.c", "go.mod", "go.sum"} for p in effective.iterdir()):
        raise ValueError("Unlisted effective JNI build input")
    for name in ("api-android.go", "jni.c", "go.mod", "go.sum"):
        original = (source / "tunnel/tools/libwg-go" / name).read_bytes()
        target = effective / name
        expected = lock["android_jni_effective_source_sha256"] if name == "api-android.go" else sha(original)
        if target.exists():
            existing = target.read_bytes().replace(b"\r\n", b"\n")
            if sha(existing) not in {sha(original), expected}:
                raise ValueError("Effective JNI source modified; refusing overwrite")
            target.write_bytes(existing)
        else:
            target.write_bytes(original)
    if sha((effective / "api-android.go").read_bytes()) != lock["android_jni_effective_source_sha256"]:
        patch_file = output / "android-jni-lifecycle.patch"
        patch_file.write_bytes(patch)
        # Apply as a standalone source directory, independent of the checkout's
        # Git prefix/attributes and Windows core.autocrlf setting.
        patch_env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(output))
        patch_env.pop("GIT_DIR", None)
        patch_env.pop("GIT_WORK_TREE", None)
        for extra in (["--check"], []):
            subprocess.run(["git", "-c", "core.autocrlf=false", "apply", *extra, str(patch_file)], cwd=effective, env=patch_env, timeout=15, check=True)
        api = effective / "api-android.go"
        api.write_bytes(api.read_bytes().replace(b"\r\n", b"\n"))
    if sha((effective / "api-android.go").read_bytes()) != lock["android_jni_effective_source_sha256"]:
        raise ValueError("Unexpected effective JNI source fingerprint")
    return effective


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ndk-root", type=Path, required=True)
    parser.add_argument("--go", default="go")
    parser.add_argument("--abi", choices=TARGETS, action="append")
    parser.add_argument("--android-clock", action="store_true", help="Use pinned BOOTTIME runtime overlay (no global toolchain changes)")
    parser.add_argument("--harden-jni", action="store_true", help="Apply the pinned JNI lifecycle patch in a private source copy")
    parser.add_argument("--output", type=Path, default=ROOT / ".local-pilot/awg-native-build")
    args = parser.parse_args()
    findings = evaluate(collect(ROOT))
    if findings:
        raise RuntimeError("Host resource guard rejected native build")
    lock = json.loads((ROOT / "android/awg-native.lock.json").read_text(encoding="utf-8"))
    version = subprocess.check_output([args.go, "version"], text=True, timeout=10).strip()
    if not version.startswith("go version go" + lock["go_version"] + " "):
        raise ValueError("Go toolchain version differs from native lock")
    ndk = args.ndk_root.resolve()
    props = (ndk / "source.properties").read_text(encoding="utf-8")
    if not re.search(r"(?m)^Pkg.Revision\s*=\s*" + re.escape(lock["ndk_version"]) + r"\s*$", props):
        raise ValueError("NDK version differs from native lock")
    host = {"Windows": "windows-x86_64", "Linux": "linux-x86_64", "Darwin": "darwin-x86_64"}[platform.system()]
    toolchain = ndk / "toolchains/llvm/prebuilt" / host
    suffix = ".exe" if platform.system() == "Windows" else ""
    clang = toolchain / ("bin/clang" + suffix)
    readelf = toolchain / ("bin/llvm-readelf" + suffix)
    nm = toolchain / ("bin/llvm-nm" + suffix)
    if not all(p.is_file() for p in (clang, readelf, nm)):
        raise ValueError("Missing NDK host tools")
    output = args.output.resolve()
    overlay, clock_receipt = None, {}
    if args.android_clock:
        goroot = Path(subprocess.check_output([args.go, "env", "GOROOT"], text=True, timeout=10).strip())
        overlay, clock_receipt = prepare_clock_overlay(goroot, output, lock["go_runtime_clock_sources"])
    source = output / "source"
    for path, expected in lock["sources"].items():
        if not (source / path).resolve().is_relative_to(source.resolve()):
            raise ValueError("Locked source path escapes output")
        url = f'https://raw.githubusercontent.com/{lock["upstream"]}/{lock["commit"]}/{path}'
        checked_source(source / path, expected, url)
    build_source = prepare_jni_source(source, output, lock) if args.harden_jni else source / "tunnel/tools/libwg-go"
    allowed_inputs = {"api-android.go", "jni.c", "go.mod", "go.sum", "goruntime-boottime-over-monotonic.diff"}
    if any(p.name not in allowed_inputs or not p.is_file() for p in build_source.iterdir()):
        raise ValueError("Unlisted native build input")
    artifacts = []
    for abi in args.abi or TARGETS:
        arch, target, _, _ = TARGETS[abi]
        folder = output / "jniLibs" / abi
        folder.mkdir(parents=True, exist_ok=True)
        library = folder / "libwg-go.so"
        env = dict(os.environ, GOOS="android", GOARCH=arch, GOARM="7", CGO_ENABLED="1", GOMAXPROCS="2",
                   GOTOOLCHAIN="local", GOFLAGS="-mod=readonly", GOCACHE=str(output / "go-cache"),
                   GOMODCACHE=str(output / "go-mod-cache"),
                   CC=f'"{clang.as_posix()}" --target={target} "--sysroot={(toolchain / "sysroot").as_posix()}"',
                   CGO_CFLAGS="", CGO_LDFLAGS="-Wl,-soname=libwg-go.so -Wl,-z,max-page-size=16384")
        flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if platform.system() == "Windows" else 0
        with (output / (abi + ".log")).open("w", encoding="utf-8") as log:
            subprocess.run([args.go, "build", *(["-overlay=" + str(overlay)] if overlay else []), "-tags", "linux", "-trimpath", "-buildvcs=false", "-ldflags=-buildid=",
                            "-buildmode=c-shared", "-o", str(library), "."],
                           cwd=build_source, env=env, stdout=log, stderr=subprocess.STDOUT,
                           timeout=600, check=True, creationflags=flags)
            subprocess.run([args.go, "mod", "verify"], cwd=build_source, env=env,
                           stdout=log, stderr=subprocess.STDOUT, timeout=60, check=True, creationflags=flags)
        data = library.read_bytes()
        verify_elf_header(data, abi)
        symbols = subprocess.check_output([str(nm), "-D", "--defined-only", str(library)], text=True, timeout=15)
        for name in ("awgTurnOn", "awgTurnOff", "awgGetSocketV4", "awgGetSocketV6", "awgGetConfig", "awgVersion"):
            if "Java_org_amnezia_awg_GoBackend_" + name not in symbols:
                raise ValueError("Native JNI export missing")
        segments = subprocess.check_output([str(readelf), "-lW", str(library)], text=True, timeout=15)
        alignments = [int(line.split()[-1], 16) for line in segments.splitlines() if line.strip().startswith("LOAD ")]
        if not alignments or any(n < 16384 for n in alignments):
            raise ValueError("Android load segments are not aligned to 16 KiB")
        artifacts.append({"abi": abi, "sha256": sha(data), "size": len(data), "jni_exports_verified": True, "load_alignment_16k_verified": True})
        print(json.dumps(artifacts[-1]), flush=True)
    for path, expected in lock["sources"].items():
        if sha((source / path).read_bytes()) != expected:
            raise ValueError("Build changed locked source")
    manifest = {"schema_version": 1, "upstream_commit": lock["commit"], "release": lock["release"],
                "go": version, "ndk": lock["ndk_version"], "diagnostic_only": True,
                "runtime_sleep_clock_patch_applied": bool(overlay), "runtime_clock_sources": clock_receipt,
                "jni_lifecycle_hardened": args.harden_jni,
                "jni_lifecycle_patch_sha256": lock["android_jni_lifecycle_patch_sha256"] if args.harden_jni else None,
                "native_library_loaded_on_device": False,
                "apk_built_or_installed": False, "artifacts": artifacts}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
