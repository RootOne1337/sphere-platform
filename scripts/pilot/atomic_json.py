"""Replace local evidence snapshots without retrying any device/server action."""
from __future__ import annotations

import json
import time
from pathlib import Path


def write_json(path: Path, data: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except PermissionError as exc:
            # Windows readers/scanners may briefly deny deletion of the old file.
            # Keep its complete JSON visible; permanent denials still fail after
            # at most 310 ms of backoff. No HTTP or Android action is repeated.
            if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 5:
                raise
            time.sleep(0.01 * 2**attempt)
