"""Create or update admin user with given credentials."""
import asyncio
import os

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.getenv(
    "POSTGRES_URL",
    os.getenv("DATABASE_URL", "postgresql+asyncpg://sphere:spherepass@postgres:5432/sphereplatform"),
)

EMAIL = "NIFILIM1337@gmail.com"
PASSWORD = "dimas123321d"


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    hashed = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()

    async with engine.begin() as conn:
        # Ensure org exists
        org = await conn.execute(
            text("SELECT id FROM organizations WHERE slug = 'default' LIMIT 1")
        )
        row = org.fetchone()
        if row is None:
            org = await conn.execute(
                text(
                    "INSERT INTO organizations (name, slug) "
                    "VALUES ('Default', 'default') RETURNING id"
                )
            )
            org_id = org.fetchone()[0]
        else:
            org_id = row[0]

        # Upsert user
        existing = await conn.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": EMAIL},
        )
        if existing.fetchone():
            await conn.execute(
                text(
                    "UPDATE users SET password_hash = :h, role = 'super_admin', is_active = true "
                    "WHERE email = :email"
                ),
                {"h": hashed, "email": EMAIL},
            )
            print(f"Updated user: {EMAIL}")
        else:
            await conn.execute(
                text(
                    "INSERT INTO users (org_id, email, password_hash, role, is_active) "
                    "VALUES (:org_id, :email, :h, 'super_admin', true)"
                ),
                {"org_id": org_id, "email": EMAIL, "h": hashed},
            )
            print(f"Created user: {EMAIL}")

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
