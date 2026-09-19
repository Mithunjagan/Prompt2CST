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

out_s1p = os.path.abspath("outputs/test_touchstone_direct.s1p")

vba_code = f"""
Sub Main()
    With Touchstone
        .Reset
        .FileName "{out_s1p}"
        .Format "MA"
        .Impedance "50"
        .Write
    End With
End Sub
"""

# Try various execution methods on app / project / Report
for obj_name, obj in [("project", project), ("app", app)]:
    for method in ["ExecuteVBAString", "ExecuteVBA", "RunMacro", "RunVBA", "ExecuteScript"]:
        if hasattr(obj, method):
            print(f"Testing {obj_name}.{method}...")
            try:
                fn = getattr(obj, method)
                res = fn(vba_code)
                print(f"  {obj_name}.{method} returned: {res}")
            except Exception as e:
                print(f"  {obj_name}.{method} error: {e}")

app.Quit()
pythoncom.CoUninitialize()

p = Path(out_s1p)
if p.exists():
    print(f"\nSUCCESS! File created: {p.name} ({p.stat().st_size} bytes)")
else:
    print(f"\nFile missing: {p.name}")
