import bcrypt, os, asyncio, asyncpg

async def main():
    db_url = os.environ["POSTGRES_URL"]
    # asyncpg uses postgresql:// not postgresql+asyncpg://
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    h = bcrypt.hashpw(b"Sphere2026!", bcrypt.gensalt(12)).decode()
    conn = await asyncpg.connect(db_url)
    row = await conn.fetchrow(
        "UPDATE users SET password_hash=$1 WHERE email=$2 RETURNING email",
        h, "NIFILIM1337@gmail.com"
    )
    await conn.close()
    print("Updated:", row, "| hash:", h[:25])

asyncio.run(main())
