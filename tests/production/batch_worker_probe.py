"""Disposable process for OS-kill recovery tests; no device or network commands."""

import asyncio
import os
import sys
import uuid

from sqlalchemy.engine import make_url


async def main():
    assert os.environ.get("SPHERE_RUN_INTEGRATION") == "1"
    url = make_url(os.environ["POSTGRES_URL"])
    assert url.host in {"127.0.0.1", "localhost", "::1"} and "audit" in (url.database or "")
    from backend.database.engine import AsyncSessionLocal, engine
    from backend.services.batch_admission import BatchAdmissionWorker

    tenant = uuid.UUID(sys.argv[1])
    try:
        while True:
            await BatchAdmissionWorker(AsyncSessionLocal).poll(org_id=tenant)
            await asyncio.sleep(0.1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
