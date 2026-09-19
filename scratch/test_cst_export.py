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

print("Testing VBA export macros...")

# 1. Test ASCIIExport macro
out_txt = os.path.abspath("outputs/test_s11_ascii.txt")
vba_export_ascii = f"""
SelectTreeItem("1D Results\\S-Parameters\\S1,1")
With ASCIIExport
    .Reset
    .FileName "{out_txt}"
    .Execute
End With
"""

try:
    project.AddToHistory("Prompt2CST: Export S11 ASCII", vba_export_ascii)
    print("ASCIIExport history added.")
except Exception as e:
    print("ASCIIExport history error:", e)

# 2. Test TouchstoneExport macro
out_s1p = os.path.abspath("outputs/test_s11_touchstone.s1p")
vba_export_s1p = f"""
With TouchstoneExport
    .Reset
    .FileName "{out_s1p}"
    .Format "MA"
    .Impedance "50"
    .Mode "All"
    .Write
End With
"""

try:
    project.AddToHistory("Prompt2CST: Export Touchstone S1P", vba_export_s1p)
    print("TouchstoneExport history added.")
except Exception as e:
    print("TouchstoneExport history error:", e)

# 3. Test Z-Parameters ASCII Export
out_z_re = os.path.abspath("outputs/test_zre_ascii.txt")
vba_export_zre = f"""
SelectTreeItem("1D Results\\Z-Parameters\\Z1,1\\Real")
With ASCIIExport
    .Reset
    .FileName "{out_z_re}"
    .Execute
End With
"""

try:
    project.AddToHistory("Prompt2CST: Export Z11 Real ASCII", vba_export_zre)
    print("Z11 Real ASCII export history added.")
except Exception as e:
    print("Z11 Real ASCII export error:", e)

out_z_im = os.path.abspath("outputs/test_zim_ascii.txt")
vba_export_zim = f"""
SelectTreeItem("1D Results\\Z-Parameters\\Z1,1\\Imaginary")
With ASCIIExport
    .Reset
    .FileName "{out_z_im}"
    .Execute
End With
"""

try:
    project.AddToHistory("Prompt2CST: Export Z11 Imag ASCII", vba_export_zim)
    print("Z11 Imag ASCII export history added.")
except Exception as e:
    print("Z11 Imag ASCII export error:", e)

project.Save()

app.Quit()
pythoncom.CoUninitialize()

print("\n--- Checking exported files ---")
for p in [out_txt, out_s1p, out_z_re, out_z_im]:
    path = Path(p)
    if path.exists():
        print(f"FILE CREATED: {path.name} ({path.stat().st_size} bytes)")
        lines = path.read_text(errors="ignore").splitlines()
        print(f"  First 5 lines of {path.name}:")
        for line in lines[:5]:
            print(f"    {line}")
    else:
        print(f"FILE MISSING: {path.name}")
