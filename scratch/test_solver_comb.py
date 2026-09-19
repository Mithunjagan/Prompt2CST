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
design_ir = dipole_to_design_ir(dipole, "test_dipole_comb")

# Update solver configuration VBA block
compiled = compile_design(design_ir)

res = bridge.execute_compiled_design(compiled, "test_dipole_comb", overwrite=True)
print("Execute result:", res)

pythoncom.CoInitialize()
app = win32com.client.Dispatch("CSTStudio.Application.2026")
app.SetQuietMode(True)

cst_path = res["project_path"]
app.OpenFile(cst_path)
project = app.Active3D()

# Add solver setup to history
vba = """
With Solver
    .Method "Hexahedral"
    .CalculationType "TD-S"
    .StimulationPort "All"
    .StimulationMode "All"
    .CalculateZAndY "True"
End With
"""
project.AddToHistory("Prompt2CST: Configure TD-S Solver", vba)
project.Save()

print("Starting solver via COM...")
solver = project.Solver()
solver.Start()
print("Solver finished successfully!")

project.Save()

# Now test exporting 1D result / Touchstone / ASCII via COM
export_vba = """
SelectTreeItem("1D Results\\S-Parameters\\S1,1")
With ASCIIExport
    .Reset
    .FileName "{out_s11}"
    .Execute
End With
With TouchstoneExport
    .Reset
    .FileName "{out_s1p}"
    .Format "MA"
    .Impedance "50"
    .Mode "All"
    .Write
End With
""".format(
    out_s11=os.path.abspath("outputs/comb_s11.txt"),
    out_s1p=os.path.abspath("outputs/comb_s11.s1p"),
)

project.AddToHistory("Prompt2CST: Export Results", export_vba)
project.Rebuild()
project.Save()

app.Quit()
pythoncom.CoUninitialize()

print("\n--- Checking generated files ---")
for f in ["comb_s11.txt", "comb_s11.s1p"]:
    p = Path("outputs") / f
    if p.exists():
        print(f"CREATED: {f} ({p.stat().st_size} bytes)")
        print("First 5 lines:")
        print("\n".join(p.read_text().splitlines()[:5]))
    else:
        print(f"MISSING: {f}")
