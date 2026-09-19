import win32com.client
import pythoncom
import os
from pathlib import Path

from prompt2cst.cst_bridge import CSTBridge
from prompt2cst.design import DipoleInputs, calculate_center_fed_dipole
from prompt2cst.adapters import dipole_to_design_ir
from prompt2cst.cst_compiler import compile_design

bridge = CSTBridge()
dipole = calculate_center_fed_dipole(DipoleInputs(frequency_ghz=2.45))
design_ir = dipole_to_design_ir(dipole, "test_dipole_export_auto")

res = bridge.execute_compiled_design(compile_design(design_ir), "test_dipole_export_auto", overwrite=True)

out_s1p = os.path.abspath("outputs/test_dipole_export_auto.s1p")

pythoncom.CoInitialize()
app = win32com.client.Dispatch("CSTStudio.Application.2026")
app.SetQuietMode(True)

cst_path = res["project_path"]
app.OpenFile(cst_path)
project = app.Active3D()

# Add Touchstone export step after solver setup
vba = f"""
With Touchstone
    .Reset
    .FileName "{out_s1p}"
    .Format "MA"
    .Impedance "50"
    .Write
End With
"""

project.AddToHistory("Prompt2CST: Postprocessing Touchstone Export", vba)
project.Save()

print("Starting solver via COM...")
solver = project.Solver()
solver.Start()
print("Solver completed.")

project.Save()

app.Quit()
pythoncom.CoUninitialize()

p = Path(out_s1p)
if p.exists():
    print(f"\nSUCCESS! Touchstone file created: {p.name}")
    print(f"Size: {p.stat().st_size} bytes")
    lines = p.read_text().splitlines()
    print("First 15 lines:")
    print("\n".join(lines[:15]))
else:
    print("\nFile missing:", out_s1p)
