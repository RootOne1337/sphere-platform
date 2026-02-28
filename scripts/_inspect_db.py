import os
import sys

import psycopg2

_db_password = os.environ.get("DB_PASSWORD")
if not _db_password:
    sys.exit("Ошибка: переменная окружения DB_PASSWORD обязательна")

conn = psycopg2.connect(
    host=os.environ.get("DB_HOST", "localhost"),
    port=int(os.environ.get("DB_PORT", "5432")),
    dbname=os.environ.get("DB_NAME", "sphereplatform"),
    user=os.environ.get("DB_USER", "sphere"),
    password=_db_password,
)
cur = conn.cursor()
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='organizations' ORDER BY ordinal_position")
print('organizations cols:', [r[0] for r in cur.fetchall()])
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='users' ORDER BY ordinal_position")
print('users cols:', [r[0] for r in cur.fetchall()])
cur.execute("SELECT id, name, slug FROM organizations LIMIT 5")
print('orgs:', cur.fetchall())
cur.close()
conn.close()
