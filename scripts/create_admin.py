"""Create or update admin user with given credentials."""
import asyncio
import getpass
import os
import sys
import uuid
from pathlib import Path

import bcrypt
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATABASE_URL = os.getenv(
    "POSTGRES_URL",
    os.getenv("DATABASE_URL", "postgresql+asyncpg://sphere:spherepass@postgres:5432/sphereplatform"),
)

# Читаем из env-переменных (для CI / Docker) или запрашиваем интерактивно
EMAIL = os.getenv("ADMIN_EMAIL", "")
PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ORG_SLUG = os.getenv("SPHERE_BOOTSTRAP_ORG_SLUG", "default").strip()
if not ORG_SLUG:
    raise ValueError("SPHERE_BOOTSTRAP_ORG_SLUG must not be empty")

if not EMAIL:
    EMAIL = input("Admin email: ").strip()
    if not EMAIL:
        print("Error: email is required", file=sys.stderr)
        sys.exit(1)

if not PASSWORD:
    PASSWORD = getpass.getpass("Admin password: ").strip()
    if len(PASSWORD) < 8:
        print("Error: password must be at least 8 characters", file=sys.stderr)
        sys.exit(1)


async def main() -> None:
    from backend.schemas.auth import LoginRequest

    try:
        credentials = LoginRequest(email=EMAIL, password=PASSWORD)
    except ValidationError:
        # Pydantic's ordinary error text includes the rejected input/password.
        print("Invalid admin credentials: use a valid email and an 8-128 character password", file=sys.stderr)
        raise SystemExit(1) from None
    engine = create_async_engine(DATABASE_URL, echo=False)
    hashed = bcrypt.hashpw(credentials.password.encode(), bcrypt.gensalt()).decode()
    email = str(credentials.email)

    async with engine.begin() as conn:
        # Ensure org exists
        org = await conn.execute(
            text("SELECT id FROM organizations WHERE slug = :slug LIMIT 1"), {"slug": ORG_SLUG}
        )
        row = org.fetchone()
        if row is None:
            org = await conn.execute(
                text(
                    "INSERT INTO organizations (id, name, slug) "
                    "VALUES (:id, 'Default', :slug) RETURNING id"
                ), {"id": uuid.uuid4(), "slug": ORG_SLUG}
            )
            org_id = org.fetchone()[0]
        else:
            org_id = row[0]

        # Upsert user
        existing = await conn.execute(
            text("SELECT id, org_id FROM users WHERE email = :email"),
            {"email": email},
        )
        existing_user = existing.fetchone()
        if existing_user:
            if existing_user.org_id != org_id:
                raise RuntimeError("Admin already belongs to another organization; select its SPHERE_BOOTSTRAP_ORG_SLUG explicitly")
            await conn.execute(
                text(
                    "UPDATE users SET password_hash = :h, role = 'super_admin', is_active = true "
                    "WHERE email = :email"
                ),
                {"h": hashed, "email": email},
            )
            print(f"Updated user: {email}")
        else:
            await conn.execute(
                text(
                    "INSERT INTO users (id, org_id, email, password_hash, role, is_active, mfa_enabled) "
                    "VALUES (:id, :org_id, :email, :h, 'super_admin', true, false)"
                ),
                {"id": uuid.uuid4(), "org_id": org_id, "email": email, "h": hashed},
            )
            print(f"Created user: {email}")

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
