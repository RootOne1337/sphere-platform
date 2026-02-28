import asyncio
import datetime
import secrets
import sys

import jwt

sys.path.insert(0, '/app')

async def main():
    from sqlalchemy import select

    from backend.core.config import settings
    from backend.database.engine import AsyncSessionLocal
    from backend.models.user import User
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).limit(1))).scalar_one()
        payload = {
            'sub': str(user.id),
            'org_id': str(user.org_id),
            'jti': secrets.token_hex(16),
            'type': 'access',
            'exp': datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
        }
        print(jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm='HS256'))

asyncio.run(main())
