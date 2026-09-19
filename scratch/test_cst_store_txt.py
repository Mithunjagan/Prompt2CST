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
design_ir = dipole_to_design_ir(dipole, "test_dipole_store")

res = bridge.execute_compiled_design(compile_design(design_ir), "test_dipole_store", overwrite=True)
print("Execute result:", res)

pythoncom.CoInitialize()
app = win32com.client.Dispatch("CSTStudio.Application.2026")
app.SetQuietMode(True)

cst_path = res["project_path"]
app.OpenFile(cst_path)
project = app.Active3D()

# Set solver with StoreInTxt and CalculateZAndY
vba = """
With Solver
    .CalculationType "TD-S"
    .StimulationPort "1"
    .StimulationMode "1"
    .CalculateZAndY "True"
    .StoreInTxt "True"
    .Start
End With
"""

print("Running solver with StoreInTxt...")
project.AddToHistory("Prompt2CST: Run Solver and Store Text", vba)
project.Save()

app.Quit()
pythoncom.CoUninitialize()

print("\n--- Searching project folder for newly created files ---")
project_dir = Path(cst_path).parent / "test_dipole_store"
if project_dir.exists():
    for p in project_dir.rglob("*"):
        if p.is_file() and p.suffix in [".txt", ".s1p", ".csv", ".dat", ".sig"]:
            print(f"FOUND FILE: {p.name} ({p.stat().st_size} bytes) at {p}")
