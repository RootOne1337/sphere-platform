"""Bound repeated OTA diagnostic warnings without changing receipt processing."""
from __future__ import annotations

from time import monotonic
from uuid import UUID

from structlog.stdlib import BoundLogger

from backend.metrics import android_ota_unrecognized_receipts_total

_WINDOW_SECONDS = 60
_MAX_DETAIL_WARNINGS = 8
_EVENT = "android_ws.ota_recovery_receipt_unrecognized"


class OtaReceiptWarnings:
    """One fixed-capacity window per worker, advanced by the next receipt."""

    def __init__(self) -> None:
        self._window_end = 0.0
        self._seen: set[tuple[str, str]] = set()
        self._suppressed = 0

    def record(
        self, logger: BoundLogger, *, device_id: str, grant_id: object, status: str, failure_code: str | None,
    ) -> None:
        now = monotonic()
        if now >= self._window_end:
            if self._suppressed:
                logger.warning(
                    f"{_EVENT}_summary", suppressed_count=self._suppressed,
                    detail_count=len(self._seen), window_seconds=_WINDOW_SECONDS,
                )
            self._window_end = now + _WINDOW_SECONDS
            self._seen.clear()
            self._suppressed = 0

        # Only UUID-shaped grant identifiers are retained or logged. Never place
        # identifiers or payload values in Prometheus labels.
        bounded_grant_id = "invalid"
        if isinstance(grant_id, str) and len(grant_id) <= 36:
            try:
                bounded_grant_id = str(UUID(grant_id))
            except ValueError:
                pass
        key = (device_id, bounded_grant_id)
        if key in self._seen or len(self._seen) >= _MAX_DETAIL_WARNINGS:
            self._suppressed += 1
            android_ota_unrecognized_receipts_total.labels(outcome="suppressed").inc()
            return

        self._seen.add(key)
        android_ota_unrecognized_receipts_total.labels(outcome="warning").inc()
        logger.warning(
            _EVENT, device_id=device_id, grant_id=bounded_grant_id,
            status=status, failure_code=failure_code,
        )
