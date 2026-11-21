"""Build a silent, original PCM/Vorbis sound pack for an isolated SA driving test."""

import argparse
import subprocess
from pathlib import Path
from struct import pack
from tempfile import TemporaryDirectory

import imageio_ffmpeg


def make_files():
    rate = 24000
    samples = 480
    # Each logical SFX id gets its own valid 20-ms mono sample.
    count = 400
    descriptor = b"".join(pack("<IiHh", i * samples * 2, -1, rate, 0) for i in range(count))
    raw_size = count * samples * 2
    bank = pack("<I", count) + descriptor + bytes(raw_size)
    slot = pack("<IIii", 0, len(bank), -1, -1) + bytes(4820 - 16)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    capture = subprocess.run(
        [
            ff,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=stereo",
            "-t",
            "1",
            "-f",
            "ogg",
            "-c:a",
            "libvorbis",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    ogg = capture.stdout
    assert ogg.startswith(b"OggS")
    header = (
        pack("<Ii", 0xFFFFFFFF, 0) * 1000 + pack("<II", len(ogg), rate) + bytes(56) + pack("<I", 1)
    )
    assert len(header) == 8068
    # Storage transform of the PC audio stream container.
    mask = bytes.fromhex("ea3ac4a19aa814f348b0d7239de8fff1")
    stream = bytes(b ^ mask[i % len(mask)] for i, b in enumerate(header + ogg))
    return {
        "config/BankSlot.dat": pack("<H", 45) + slot * 45,
        "config/BankLkup.dat": pack("<B3xII", 0, 0, raw_size) * 710,
        "config/PakFiles.dat": b"QUIETSFX".ljust(52, bytes(1)),
        "config/EventVol.dat": bytes([128]) * 45402,
        "config/StrmPaks.dat": b"QUIETRAD".ljust(16, bytes(1)),
        "config/TrakLkup.dat": pack("<B3xII", 0, 0, len(ogg)) * 1922,
        "sfx/QUIETSFX": bank,
        "streams/QUIETRAD": stream,
    }


def install(root):
    if root.exists():
        raise ValueError("select a new audio directory")
    root.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=root.parent) as temp:
        staging = Path(temp) / "audio"
        for name, blob in make_files().items():
            path = staging / name
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_bytes(blob)
        staging.rename(root)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "destination", type=Path, help="new audio directory inside the isolated test game"
    )
    install(cli.parse_args().destination)
