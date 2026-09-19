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

# Create 3 test macros
macros = {
    "m1": f"""
Sub Main()
    SelectTreeItem("1D Results\\S-Parameters\\S1,1")
    With Touchstone
        .Reset
        .FileName "{os.path.abspath('outputs/m1.s1p')}"
        .Format "MA"
        .Impedance "50"
        .Execute
    End With
End Sub
""",
    "m2": f"""
Sub Main()
    SelectTreeItem("1D Results\\S-Parameters\\S1,1")
    With Touchstone
        .Reset
        .FileName "{os.path.abspath('outputs/m2.s1p')}"
        .Format "MA"
        .Impedance "50"
        .Write
    End With
End Sub
""",
    "m3": f"""
Sub Main()
    SelectTreeItem("1D Results\\S-Parameters\\S1,1")
    With ASCIIExport
        .Reset
        .FileName "{os.path.abspath('outputs/m3.txt')}"
        .Execute
    End With
End Sub
""",
    "m4": f"""
Sub Main()
    SelectTreeItem("1D Results\\S-Parameters\\S1,1")
    Export1DResultFile("{os.path.abspath('outputs/m4.txt')}")
End Sub
""",
}

for name, code in macros.items():
    mcs_file = os.path.abspath(f"outputs/{name}.mcs")
    Path(mcs_file).write_text(code)
    print(f"Executing {name} ({mcs_file})...")
    try:
        project.RunScript(mcs_file)
        print(f"  {name} executed.")
    except Exception as e:
        print(f"  {name} error: {e}")

project.Save()
app.Quit()
pythoncom.CoUninitialize()

print("\n--- Output file check ---")
for f in ["m1.s1p", "m2.s1p", "m3.txt", "m4.txt"]:
    p = Path("outputs") / f
    if p.exists():
        print(f"SUCCESS! {f} ({p.stat().st_size} bytes)")
        print(p.read_text()[:200])
    else:
        print(f"MISSING: {f}")
