"""Install the frozen catalog batch update only; no migration, secrets or VPN dispatch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.pilot import install_reviewed_backend as live
from scripts.pilot.vpn_catalog_batch_release import BASELINE


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = live.execute(args.artifact, args.source, args.expected_image_id, BASELINE,
                          args.apply, _vpn_catalog_batch=True)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
