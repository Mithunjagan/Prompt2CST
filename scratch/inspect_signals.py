import sqlite3
from pathlib import Path

p = Path("outputs/test_dipole_fd/Result/Model-fmf.msqlite")
if not p.exists():
    p = Path("outputs/test_dipole_td/Result/Model-fmf.msqlite")

conn = sqlite3.connect(p)
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
print("Tables in Model-fmf.msqlite:", [t[0] for t in tables])
for t in tables:
    tname = t[0]
    cols = [d[0] for d in conn.execute(f"SELECT * FROM [{tname}] LIMIT 1;").description]
    print(f"Table '{tname}' ({cols}):")
    rows = conn.execute(f"SELECT * FROM [{tname}] LIMIT 10;").fetchall()
    for r in rows:
        print("  ", r)

conn.close()
