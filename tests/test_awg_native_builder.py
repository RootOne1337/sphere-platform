import hashlib
import struct

import pytest

from scripts.build_awg_native import checked_source, verify_elf_header


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
