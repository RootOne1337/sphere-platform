import psycopg2
conn = psycopg2.connect(
    host='localhost', port=5432, dbname='sphereplatform',
    user='sphere', password='A80fXnwMLNmwa-ebjhUm5RV_2evs1BLq'
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
