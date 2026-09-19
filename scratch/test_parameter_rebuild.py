import win32com.client
import pythoncom
import os
from pathlib import Path

pythoncom.CoInitialize()
app = win32com.client.Dispatch("CSTStudio.Application.2026")
app.SetQuietMode(True)

cst_path = os.path.abspath("outputs/test_param_dipole_vba.cst")

vba_init = """
With Units
    .Geometry "mm"
    .Frequency "GHz"
    .Time "ns"
End With

StoreParameter "arm_length", "28.0"
StoreParameter "feed_gap", "1.5"
StoreParameter "wire_radius", "0.5"

With Cylinder
    .Reset
    .Name "Lower_Arm"
    .Component "component1"
    .Material "PEC"
    .OuterRadius "wire_radius"
    .InnerRadius "0"
    .Axis "z"
    .Zrange "-feed_gap/2 - arm_length", "-feed_gap/2"
    .Xcenter "0"
    .Ycenter "0"
    .Segments "0"
    .Create
End With

With Cylinder
    .Reset
    .Name "Upper_Arm"
    .Component "component1"
    .Material "PEC"
    .OuterRadius "wire_radius"
    .InnerRadius "0"
    .Axis "z"
    .Zrange "feed_gap/2", "feed_gap/2 + arm_length"
    .Xcenter "0"
    .Ycenter "0"
    .Segments "0"
    .Create
End With

With DiscretePort
    .Reset
    .PortNumber "1"
    .Type "SParameter"
    .Label "Dipole_Feed"
    .Impedance "50"
    .SetP1 "False", "0", "0", "-feed_gap/2"
    .SetP2 "False", "0", "0", "feed_gap/2"
    .Create
End With

Solver.FrequencyRange "2.0", "3.0"

With Boundary
    .Xmin "expanded open"
    .Xmax "expanded open"
    .Ymin "expanded open"
    .Ymax "expanded open"
    .Zmin "expanded open"
    .Zmax "expanded open"
End With
"""

print("Creating project with symbolic VBA expressions...")
project = app.NewMWS()
project.AddToHistory("Prompt2CST: Build Symbolic Dipole", vba_init)
project.SaveAs(cst_path, True)

def solve_and_extract(label, param_val):
    app.OpenFile(cst_path)
    proj = app.Active3D()
    
    print(f"\n--- [{label}] Updating arm_length to {param_val} mm ---")
    proj.StoreParameter("arm_length", float(param_val))
    proj.Rebuild()
    proj.Save()
    
    print("Running solver...")
    solver = proj.Solver()
    solver.Start()
    print("Solver completed.")
    
    s11_txt = os.path.abspath(f"outputs/s11_{label}.txt")
    export_vba = f"""
Sub Main()
    SelectTreeItem("1D Results\\S-Parameters\\S1,1")
    With ASCIIExport
        .Reset
        .FileName "{s11_txt}"
        .Execute
    End With
End Sub
"""
    mcs = os.path.abspath(f"outputs/export_{label}.mcs")
    Path(mcs).write_text(export_vba)
    proj.RunScript(mcs)
    proj.Save()
    
    lines = Path(s11_txt).read_text().splitlines()
    data = []
    for line in lines:
        pts = line.strip().split()
        if len(pts) == 2:
            try:
                data.append((float(pts[0]), float(pts[1])))
            except ValueError:
                pass
    min_pt = min(data, key=lambda x: x[1])
    print(f"[{label}] arm_length={param_val} mm => Resonance f_res = {min_pt[0]:.4f} GHz (S11 = {min_pt[1]:.2f} dB)")
    return min_pt

res1 = solve_and_extract("run1_short", 28.0)
res2 = solve_and_extract("run2_long", 38.0)

app.Quit()
pythoncom.CoUninitialize()

print("\n=== VERIFICATION SUMMARY ===")
print(f"Run 1 (arm=28.0 mm): f_res = {res1[0]:.4f} GHz (S11 = {res1[1]:.2f} dB)")
print(f"Run 2 (arm=38.0 mm): f_res = {res2[0]:.4f} GHz (S11 = {res2[1]:.2f} dB)")
shift = res1[0] - res2[0]
print(f"Frequency shift: {shift:+.4f} GHz")
if abs(shift) > 0.05:
    print("SUCCESS: Symbolic CST parameter update changed geometry and resonance!")
else:
    print("WARNING: Resonance shift was small or unexpected.")
