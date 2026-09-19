import os
from pathlib import Path

root = Path("outputs/test_dipole_fd")
if not root.exists():
    root = Path("outputs/test_dipole_td")

print(f"Searching {root}...")
for p in root.rglob("*"):
    if p.is_file():
        rel = p.relative_to(root)
        print(f"  {rel} ({p.stat().st_size} bytes)")
