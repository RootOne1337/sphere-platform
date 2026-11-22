"""Frozen schema-free VPN batch delta from the installed catalog baseline."""
from __future__ import annotations

import hashlib
import subprocess

from scripts.pilot.install_reviewed_backend import PACKAGED_PATHS, ROOT, command
from scripts.pilot.reviewed_image_archive import require

BASELINE = "7d2a684625c6f0620358ca20604fadcf6e82a6cb"
HEAD = "20261021_vpn_profiles"
FILES = {
    "backend/api/v1/vpn/profile_input.py": "87e243657ec5d50d4c1942e4b81721416b0b6fb60d0308a311a72e781e386cc8",
    "backend/api/v1/vpn/profile_router.py": "afca273a5ec5a3b321311502f29a75a9c4c2d6f86f35fd8d3b60822191e9d62c",
    "backend/api/v1/vpn/runtime_router.py": "7f4673b5cd6edd8f7b1cb84fd057b637536c740939959d71660d73955fa90a25",
    "backend/schemas/vpn/bulk_profiles.py": "bf1b5db3d1dbee56c2f1fbf791a0192634fad22cdce31d55ac938c5cee73ea61",
    "backend/schemas/vpn/runtime.py": "dc9a4f997877c8413f0dbf405c3b5d2bf091912ec14a2eff05fa85e5d5f4e1b7",
    "backend/services/vpn/profile_batch.py": "662966d3af7424333188eaeb7f26052dcec1dda0318e4b79200c67fe2ffde341",
    "backend/services/vpn/profile_catalog.py": "b8f3b60af681972294d51b2b9157765028966898c54f9b83be09e7fdc6446c02",
    "backend/services/vpn/profile_delivery.py": "d9113dfbe2bd674f479527f0d6feca9a121afc11e47cf988b6469aefb827e786",
}


def source_boundary(current: str, source: str, receipt: dict) -> list[str]:
    require(current == BASELINE, "Catalog batch baseline differs from reviewed installation")
    require(receipt.get("migrationHeads") == [HEAD], "Catalog batch may not migrate the database")
    changes = command(["git", "diff", "--name-only", current, source, "--", *PACKAGED_PATHS]).splitlines()
    require(set(changes) == set(FILES), "Catalog batch packaged delta differs from reviewed files")
    inventory = {**FILES, "backend/requirements.txt": receipt.get("requirementsSha256"),
                 "backend/schemas/action_contract.v1.json": receipt.get("actionContractSha256")}
    for path, expected in inventory.items():
        result = subprocess.run(["git", "show", f"{source}:{path}"], cwd=ROOT, capture_output=True, timeout=15, check=False)
        require(result.returncode == 0 and 0 < len(result.stdout) <= 256 * 1024
                and hashlib.sha256(result.stdout).hexdigest() == expected, "Catalog batch source fingerprint mismatch")
    return changes
