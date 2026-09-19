import win32com.client
import pythoncom
import os
from pathlib import Path

pythoncom.CoInitialize()
app = win32com.client.Dispatch("CSTStudio.Application.2026")
app.SetQuietMode(True)

cst_path = os.path.abspath("outputs/test_dipole_td.cst")
app.OpenFile(cst_path)
project = app.Active3D()

out_dir = Path("outputs")

# Test 1: ExportSParameterTouchstone variations
tests = [
    ("ExportSParameterTouchstone", (os.path.abspath("outputs/test1.s1p"),)),
    ("ExportSParameterTouchstone", (os.path.abspath("outputs/test2.s1p"), "MA", "All", 50)),
    ("ExportSParameterTouchstone", (os.path.abspath("outputs/test3.s1p"), "MA", 1, 50)),
    ("Export1DResultToFile", (os.path.abspath("outputs/test4.txt"),)),
    ("Export1DResult", (os.path.abspath("outputs/test5.txt"),)),
]

for name, args in tests:
    try:
        fn = getattr(project, name, None)
        if fn:
            print(f"Calling project.{name}{args}...")
            res = fn(*args)
            print(f"  Result: {res}")
    except Exception as e:
        print(f"  Error calling {name}{args}: {e}")

app.Quit()
pythoncom.CoUninitialize()

print("\nResulting files:")
for f in ["test1.s1p", "test2.s1p", "test3.s1p", "test4.txt", "test5.txt"]:
    p = out_dir / f
    if p.exists():
        print(f"  CREATED: {f} ({p.stat().st_size} bytes)")
    else:
        print(f"  MISSING: {f}")
