"""Create/update an administrator; --create-only preserves existing identities."""
import argparse
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

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--create-only", action="store_true",
    help="Create an absent administrator; retain existing credentials/state and report the committed outcome")
args = parser.parse_args()

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

    try:
        async with engine.begin() as conn:
            # The unique slug handles concurrent fresh installations; the row
            # lock serializes each organization before the user read/write.
            await conn.execute(
                text("INSERT INTO organizations (id, name, slug) VALUES (:id, 'Default', :slug) "
                     "ON CONFLICT (slug) DO NOTHING"),
                {"id": uuid.uuid4(), "slug": ORG_SLUG},
            )
            org_id = await conn.scalar(
                text("SELECT id FROM organizations WHERE slug = :slug FOR UPDATE"), {"slug": ORG_SLUG})
            existing = await conn.execute(
                text("SELECT id, org_id, role, is_active FROM users WHERE email = :email FOR UPDATE"),
                {"email": email},
            )
            existing_user = existing.fetchone()
            if existing_user:
                if existing_user.org_id != org_id:
                    raise RuntimeError("Admin already belongs to another organization; select its SPHERE_BOOTSTRAP_ORG_SLUG explicitly")
                if args.create_only:
                    if not existing_user.is_active or existing_user.role != "super_admin":
                        raise RuntimeError("Existing administrator is disabled or no longer super_admin; repair the account explicitly")
                    outcome = "existing"
                else:
                    await conn.execute(
                        text("UPDATE users SET password_hash = :h, role = 'super_admin', is_active = true "
                             "WHERE email = :email"),
                        {"h": hashed, "email": email},
                    )
                    outcome = "updated"
            else:
                await conn.execute(
                    text("INSERT INTO users (id, org_id, email, password_hash, role, is_active, mfa_enabled) "
                         "VALUES (:id, :org_id, :email, :h, 'super_admin', true, false)"),
                    {"id": uuid.uuid4(), "org_id": org_id, "email": email, "h": hashed},
                )
                outcome = "created"
    finally:
        await engine.dispose()

    # No success/outcome is emitted before the transaction commits. Launchers
    # only display their candidate password when this command created the user.
    print(f"Admin {outcome}: {email}")
    print("Done.")
    if args.create_only:
        print(f"SPHERE_ADMIN_BOOTSTRAP={outcome}")


if __name__ == "__main__":
    asyncio.run(main())
