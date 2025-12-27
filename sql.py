import sqlite3

conn = sqlite3.connect("documents.db")
cur = conn.cursor()

cur.execute("PRAGMA table_info(documents)")
cols = [c[1] for c in cur.fetchall()]

if "summary" not in cols:
    cur.execute("ALTER TABLE documents ADD COLUMN summary TEXT")

conn.commit()
conn.close()

print("✅ DB schema fixed")
