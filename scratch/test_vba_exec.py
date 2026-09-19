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

print("Testing direct VBA execution via COM...")

# Test 1: project.ExecuteVBA
vba_code = """
Sub Main()
    SelectTreeItem("1D Results")
End Sub
"""

for method in ["ExecuteVBA", "ExecuteVBAString", "RunVBA", "ExecuteMacro"]:
    try:
        fn = getattr(project, method, None)
        if fn:
            print(f"Found method {method} on project object")
            fn(vba_code)
            print(f"{method} executed successfully!")
    except Exception as e:
        print(f"Method {method} error:", e)

# Test Export1DResult / ExportSParameterTouchstone methods on project
out_txt = os.path.abspath("outputs/test_direct_s11.txt")
try:
    print("Trying project.SelectTreeItem + Export1DResult:")
    project.SelectTreeItem("1D Results\\S-Parameters\\S1,1")
    project.Export1DResult(out_txt)
    print("Export1DResult executed.")
except Exception as e:
    print("Export1DResult error:", e)

app.Quit()
pythoncom.CoUninitialize()

if Path(out_txt).exists():
    print("FILE CREATED:", out_txt)
else:
    print("FILE MISSING:", out_txt)
