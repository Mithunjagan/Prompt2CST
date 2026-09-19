import sqlite3
from pathlib import Path

for db_name in ["Model.db", "Model-fmf.msqlite", "Storage.sdb"]:
    p = Path("outputs/test_dipole_fd/Result") / db_name
    if not p.exists():
        p = Path("outputs/test_dipole_td/Result") / db_name
    if p.exists():
        print(f"=== {db_name} ===")
        try:
            conn = sqlite3.connect(p)
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
            print("Tables:", [t[0] for t in tables])
            for t in tables:
                tname = t[0]
                count = conn.execute(f"SELECT count(*) FROM [{tname}]").fetchone()[0]
                print(f"  Table '{tname}': {count} rows")
                if count > 0 and count < 20:
                    rows = conn.execute(f"SELECT * FROM [{tname}] LIMIT 5").fetchall()
                    print(f"    Sample: {rows[:2]}")
            conn.close()
        except Exception as e:
            print(f"Error opening {db_name}:", e)
