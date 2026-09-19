import win32com.client
import pythoncom
import os
from pathlib import Path

pythoncom.CoInitialize()
app = win32com.client.Dispatch("CSTStudio.Application.2026")
app.SetQuietMode(True)

cst_path = os.path.abspath("outputs/test_dipole_td.cst")
print("Opening project:", cst_path)
app.OpenFile(cst_path)
project = app.Active3D()

print("Running solver...")
solver = project.Solver()
solver.Start()
print("Solver completed.")

out_s1p = os.path.abspath("outputs/test_macro_out.s1p")
macro_path = os.path.abspath("outputs/test_export.mcs")

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

Path(macro_path).write_text(vba_code)
print("Created macro file:", macro_path)

print(f"Executing project.RunScript('{macro_path}')...")
try:
    project.RunScript(macro_path)
    print("RunScript executed without throwing exception!")
except Exception as e:
    print(f"RunScript error: {e}")

project.Save()

app.Quit()
pythoncom.CoUninitialize()

p = Path(out_s1p)
if p.exists():
    print(f"\nSUCCESS! Touchstone file created: {p.name} ({p.stat().st_size} bytes)")
    print("First 20 lines of Touchstone file:")
    print("\n".join(p.read_text().splitlines()[:20]))
else:
    print(f"\nFile missing: {p.name}")
