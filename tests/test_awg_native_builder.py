import hashlib
import struct

import pytest

from scripts.build_awg_native import (
    checked_source,
    prepare_clock_overlay,
    prepare_jni_source,
    verify_elf_header,
)


@pytest.mark.parametrize("abi,machine,elf_class", [("x86_64", 62, 2), ("arm64-v8a", 183, 2), ("armeabi-v7a", 40, 1)])
def test_android_library_cannot_be_mislabelled_as_another_abi(abi, machine, elf_class):
    header = bytearray(64)
    header[:6] = b"\x7fELF" + bytes([elf_class, 1])
    struct.pack_into("<HH", header, 16, 3, machine)
    verify_elf_header(header, abi)
    struct.pack_into("<H", header, 18, 999)
    with pytest.raises(ValueError, match="ABI/type"):
        verify_elf_header(header, abi)


def test_mismatched_cached_upstream_source_is_not_overwritten_or_built(tmp_path):
    path = tmp_path / "go.mod"
    path.write_bytes(b"unexpected-source")
    with pytest.raises(ValueError, match="refusing overwrite"):
        checked_source(path, hashlib.sha256(b"locked-source").hexdigest(), "https://invalid.example/never-called")
    assert path.read_bytes() == b"unexpected-source"


def test_clock_overlay_changes_only_pinned_copies_and_keeps_goroot_untouched(tmp_path):
    import json

    folder = tmp_path / "go/src/runtime"
    folder.mkdir(parents=True)
    originals = {
        "sys_linux_amd64.s": b"MOVL\t$1, DI // CLOCK_MONOTONIC\n",
        "sys_linux_arm64.s": b"#define CLOCK_MONOTONIC 1\nMOVW $CLOCK_MONOTONIC, R0\n",
        "sys_linux_arm.s": b"#define CLOCK_MONOTONIC\t1\nMOVW $CLOCK_MONOTONIC, R0\n",
    }
    for name, data in originals.items():
        (folder / name).write_bytes(data)
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in originals.items()}
    overlay, receipt = prepare_clock_overlay(tmp_path / "go", tmp_path / "build", hashes)
    assert len(json.loads(overlay.read_text())["Replace"]) == len(receipt) == 3
    for name, data in originals.items():
        assert (folder / name).read_bytes() == data
        assert b"CLOCK_BOOTTIME" in (overlay.parent / name).read_bytes()
        assert b"CLOCK_MONOTONIC" not in (overlay.parent / name).read_bytes()
    (folder / "sys_linux_arm.s").write_bytes(b"unexpected toolchain source")
    with pytest.raises(ValueError, match="differs from clock lock"):
        prepare_clock_overlay(tmp_path / "go", tmp_path / "build", hashes)


def test_jni_patch_is_checked_and_never_modifies_locked_upstream(tmp_path, monkeypatch):
    from scripts import build_awg_native as builder

    upstream = tmp_path / "source/tunnel/tools/libwg-go"
    upstream.mkdir(parents=True)
    for name in ["api-android.go", "jni.c", "go.mod", "go.sum"]:
        (upstream / name).write_bytes(b"old\n")
    patch = b"--- a/api-android.go\n+++ b/api-android.go\n@@ -1 +1 @@\n-old\n+new\n"
    root = tmp_path / "repo"
    patch_path = root / "android/awg-sdk/patches/android-jni-lifecycle.patch"
    patch_path.parent.mkdir(parents=True)
    patch_path.write_bytes(patch)
    monkeypatch.setattr(builder, "ROOT", root)
    lock = {"android_jni_lifecycle_patch_sha256": hashlib.sha256(patch).hexdigest(),
            "android_jni_effective_source_sha256": hashlib.sha256(b"new\n").hexdigest()}
    output = prepare_jni_source(tmp_path / "source", tmp_path / "build", lock)
    assert (output / "api-android.go").read_bytes() == b"new\n"
    assert (upstream / "api-android.go").read_bytes() == b"old\n"
    (output / "api-android.go").write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="refusing overwrite"):
        prepare_jni_source(tmp_path / "source", tmp_path / "build", lock)
