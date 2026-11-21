"""NSSM entry point with process-owned, bounded diagnostics."""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loguru import Message

MAX_FILE_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 4
MAX_RECORD_BYTES = 16 * 1024


class ServiceLogHandler(logging.handlers.RotatingFileHandler):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record).replace("\r", "\\r").replace("\n", "\\n")
        data = text.encode("utf-8", errors="replace")
        suffix = b" [truncated]"
        if len(data) <= MAX_RECORD_BYTES:
            return data.decode("utf-8")
        prefix = data[: MAX_RECORD_BYTES - len(suffix)].decode("utf-8", errors="ignore")
        return prefix + suffix.decode()

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        # RotatingFileHandler counts characters. The service budget is in bytes,
        # including a possible CRLF from the Windows text stream.
        stream = self.stream
        if stream is None:
            stream = self.stream = self._open()
        size = os.fstat(stream.fileno()).st_size
        entry_size = len(self.format(record).encode("utf-8")) + len(os.linesep)
        return size > 0 and size + entry_size > self.maxBytes


def run_service(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = ServiceLogHandler(
        log_dir / "agent-service.log",
        maxBytes=MAX_FILE_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(name)s: %(message)s")
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    bootstrap = logging.Logger("agent.windows_service")
    bootstrap.addHandler(handler)
    sink_id = None
    try:
        bootstrap.info("PC Agent service bootstrap started")
        from loguru import logger

        logger.remove()

        def write_agent_log(message: Message) -> None:
            record = message.record
            level = record["level"]
            event = logging.LogRecord(
                record["name"] or "agent", level.no, "", record["line"],
                str(message).rstrip("\n"), (), None,
            )
            event.created = record["time"].timestamp()
            event.msecs = record["time"].microsecond // 1000
            event.levelname = level.name
            handler.handle(event)

        sink_id = logger.add(
            write_agent_log, level="INFO", format="{message}", backtrace=False, diagnose=False
        )

        # The agent loads deployment configuration at import time. The log
        # already exists if a dependency or a setting prevents startup.
        from .main import main

        asyncio.run(main())
    except Exception as error:
        # Configuration errors can contain input values. Record the type and
        # locations without copying exception values or local variables.
        frames = " > ".join(
            f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
            for frame in traceback.extract_tb(error.__traceback__)
        )
        bootstrap.error("PC Agent service failed (%s) at %s", type(error).__name__, frames)
        raise SystemExit(1) from None
    finally:
        if sink_id is not None:
            logger.remove(sink_id)
        handler.close()


if __name__ == "__main__":
    run_service(Path(__file__).resolve().parent.parent / "logs")
