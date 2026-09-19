import win32com.client
import pythoncom
import os

pythoncom.CoInitialize()
app = win32com.client.Dispatch("CSTStudio.Application.2026")
app.SetQuietMode(True)

cst_path = os.path.abspath("outputs/test_dipole_phase1.cst")
print("Opening:", cst_path)
app.OpenFile(cst_path)
project = app.Active3D()
print("Active3D acquired.")

# Export Touchstone via COM
# In CST 2026 COM, project.SelectTreeItem("1D Results\\S-Parameters\\S1,1")
# then export
touchstone_path = os.path.abspath("outputs/test_dipole_phase1.s1p")

vba_export = f"""
SelectTreeItem("1D Results\\S-Parameters\\S1,1")
With TouchstoneExport
    .Reset
    .FileName "{touchstone_path}"
    .Format "MA"
    .Impedance "50"
    .Mode "All"
    .Write
End With
"""

print("Executing export macro...")
project.AddToHistory("Prompt2CST: Export Touchstone", vba_export)
project.Rebuild()
project.Save()

app.Quit()
pythoncom.CoUninitialize()
print("Done.")
