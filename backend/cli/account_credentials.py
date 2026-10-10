"""Offline credential maintenance. Default: verify only. Never print keys/values."""

import argparse
import asyncio
import json
import uuid

from backend.database.engine import AsyncSessionLocal, engine
from backend.services.account_credential_migration import process_credential_batch


async def run(args: argparse.Namespace) -> int:
    scanned = legacy = changed = 0
    cursor = None
    try:
        while True:
            async with AsyncSessionLocal() as db, db.begin():
                batch = await process_credential_batch(db, after_id=cursor, limit=args.batch_size,
                    apply=args.apply, rotate=args.rotate, org_id=args.org_id)
            # Advance only after a successful commit; reruns are safe after a crash.
            scanned += batch.scanned
            legacy += batch.legacy
            changed += batch.changed
            cursor = batch.cursor
            if batch.scanned < args.batch_size:
                break
        print(json.dumps({"scanned": scanned, "legacy_found": legacy, "changed": changed,
                          "mode": "rotate" if args.rotate else "backfill" if args.apply else "verify",
                          "scope": str(args.org_id) if args.org_id else "all-visible-organizations"}))
        return 1 if legacy and not args.apply else 0
    except Exception:
        # SQL errors may carry query parameters; never emit their text/traceback.
        print(json.dumps({"error": "Credential maintenance failed; verify again because the last commit outcome may be unknown",
                          "previously_committed_changes": changed}))
        return 2
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Encrypt legacy rows; requires quiesced writers")
    parser.add_argument("--rotate", action="store_true", help="Re-encrypt all rows under the first key; requires --apply")
    parser.add_argument("--org-id", type=uuid.UUID, help="Limit verification/maintenance to one organization")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1000 or (args.rotate and not args.apply):
        parser.error("batch-size must be 1..1000; --rotate requires --apply")
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print(json.dumps({"error": "Interrupted; restart from the beginning with the same key ring"}))
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
