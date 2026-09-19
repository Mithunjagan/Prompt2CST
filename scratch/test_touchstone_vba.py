import win32com.client
import pythoncom
import os
from pathlib import Path

pythoncom.CoInitialize()
app = win32com.client.Dispatch("CSTStudio.Application.2026")
app.SetQuietMode(True)

cst_path = os.path.abspath("outputs/test_dipole_comb.cst")
app.OpenFile(cst_path)
project = app.Active3D()

out_s1p = os.path.abspath("outputs/test_touchstone_export.s1p")

vba_touchstone = f"""
With Touchstone
    .Reset
    .FileName "{out_s1p}"
    .Format "MA"
    .Impedance "50"
    .Write
End With
"""

print("Executing Touchstone export macro...")
project.AddToHistory("Prompt2CST: Export Touchstone S1P", vba_touchstone)
project.Rebuild()
project.Save()

app.Quit()
pythoncom.CoUninitialize()

p = Path(out_s1p)
if p.exists():
    print(f"SUCCESS! {p.name} created! Size: {p.stat().st_size} bytes")
    print("Content preview:")
    print("\n".join(p.read_text().splitlines()[:20]))
else:
    print("Touchstone export failed, file missing.")
