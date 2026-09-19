import win32com.client
import pythoncom
import os

from prompt2cst.cst_bridge import CSTBridge
from prompt2cst.design import DipoleInputs, calculate_center_fed_dipole
from prompt2cst.adapters import dipole_to_design_ir
from prompt2cst.cst_compiler import compile_design

bridge = CSTBridge()
dipole = calculate_center_fed_dipole(DipoleInputs(frequency_ghz=2.45))
design_ir = dipole_to_design_ir(dipole, "test_dipole_fd")

# Execute compiled design
res = bridge.execute_compiled_design(compile_design(design_ir), "test_dipole_fd", overwrite=True)
print("Execute result:", res)

# Now open with COM context
pythoncom.CoInitialize()
app = win32com.client.Dispatch("CSTStudio.Application.2026")
app.SetQuietMode(True)

app.OpenFile(res["project_path"])
project = app.Active3D()

print("Active3D acquired. Running solver via COM...")
try:
    # Try Solver vs Fsolver
    solver = project.Solver()
    print("Solver object acquired:", solver)
    solver.Start()
    print("Solver finished successfully!")
    project.Save()
except Exception as e:
    print("Solver error:", e)

# Check Result1D / Touchstone export / ASCII export
print("\nChecking Result1D objects:")
items = [
    "1D Results\\S-Parameters\\S1,1",
    "1D Results\\Z-Parameters\\Z1,1\\Real",
    "1D Results\\Z-Parameters\\Z1,1\\Imaginary",
]
for item in items:
    try:
        r = project.Result1D(item)
        print(f"{item}:", r, "Points:", r.GetN() if r else "None")
        if r and r.GetN() > 0:
            print("  First 3 X:", [r.GetX(i) for i in range(min(3, r.GetN()))])
            print("  First 3 Y:", [r.GetY(i) for i in range(min(3, r.GetN()))])
    except Exception as e:
        print(f"Error {item}:", e)

# Check if Touchstone export method exists on project or Result1D
try:
    s11_res = project.Result1D("1D Results\\S-Parameters\\S1,1")
    if s11_res:
        print("s11_res dir:", [m for m in dir(s11_res) if not m.startswith("_")])
except Exception as e:
    print("s11_res dir error:", e)

app.Quit()
pythoncom.CoUninitialize()
