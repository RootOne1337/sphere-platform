# pc-agent/main.py
# Launcher shim — delegates to the real agent package.
# The full implementation lives in pc-agent/agent/main.py
# (WS client, LDPlayerManager, ADB Bridge, Telemetry, Topology).
#
# This file exists for convenience: `python main.py` from pc-agent/ root.
from __future__ import annotations

import asyncio
import sys

from agent.main import main  # noqa: E402

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
