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

print("Running solver...")
solver = project.Solver()
solver.Start()
print("Solver completed.")

z_re_txt = os.path.abspath("outputs/z11_real.txt")
z_im_txt = os.path.abspath("outputs/z11_imag.txt")

macro_z = f"""
Sub Main()
    SelectTreeItem("1D Results\\Z-Parameters\\Z1,1\\Real")
    With ASCIIExport
        .Reset
        .FileName "{z_re_txt}"
        .Execute
    End With
    SelectTreeItem("1D Results\\Z-Parameters\\Z1,1\\Imaginary")
    With ASCIIExport
        .Reset
        .FileName "{z_im_txt}"
        .Execute
    End With
End Sub
"""

mcs_file = os.path.abspath("outputs/export_z.mcs")
Path(mcs_file).write_text(macro_z)

print("Running Z-Parameter export script...")
project.RunScript(mcs_file)
print("RunScript completed.")

project.Save()
app.Quit()
pythoncom.CoUninitialize()

print("\n--- Checking exported Z files ---")
for f in ["z11_real.txt", "z11_imag.txt"]:
    p = Path("outputs") / f
    if p.exists():
        print(f"SUCCESS! {f} ({p.stat().st_size} bytes)")
        print(p.read_text()[:300])
    else:
        print(f"MISSING: {f}")
