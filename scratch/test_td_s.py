import win32com.client
import pythoncom
import os

pythoncom.CoInitialize()
app = win32com.client.Dispatch('CSTStudio.Application.2026')
app.SetQuietMode(True)
cst_path = os.path.abspath('outputs/test_dipole_td.cst')
app.OpenFile(cst_path)
project = app.Active3D()

vba_solver = """
With Solver
    .CalculationType "TD-S"
    .StimulationPort "1"
    .StimulationMode "1"
    .CalculateZAndY "True"
    .Start
End With
"""
project.AddToHistory("Prompt2CST: Run TD Solver with Z and Y", vba_solver)
project.Save()

print("Solver completed via History VBA.")

items = [
    "1D Results\\S-Parameters\\S1,1",
    "1D Results\\Z-Parameters\\Z1,1\\Real",
    "1D Results\\Z-Parameters\\Z1,1\\Imaginary",
]
for item in items:
    try:
        r = project.Result1D(item)
        print(f"{item}:", r.GetN() if r else "None")
        if r and r.GetN() > 0:
            print("  First 3 X:", [r.GetX(i) for i in range(min(3, r.GetN()))])
            print("  First 3 Y:", [r.GetY(i) for i in range(min(3, r.GetN()))])
    except Exception as e:
        print(f"Error {item}:", e)

app.Quit()
pythoncom.CoUninitialize()
