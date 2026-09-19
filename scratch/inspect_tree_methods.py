import win32com.client
import pythoncom
import os

pythoncom.CoInitialize()
app = win32com.client.Dispatch("CSTStudio.Application.2026")
app.SetQuietMode(True)

cst_path = os.path.abspath("outputs/test_dipole_td.cst")
app.OpenFile(cst_path)
project = app.Active3D()

tree = project.Resulttree()

print("Resulttree object:", tree)

# Try calling GetResultFromTreeItem
for path in [
    "1D Results\\Port signals\\i1",
    "1D Results\\S-Parameters\\S1,1",
    "1D Results\\Z-Parameters\\Z1,1\\Real",
]:
    try:
        res = tree.GetResultFromTreeItem(path, "1D")
        print(f"GetResultFromTreeItem('{path}', '1D'):", res)
        if res:
            print("  N:", res.GetN())
            print("  First 3 X:", [res.GetX(i) for i in range(min(3, res.GetN()))])
            print("  First 3 Y:", [res.GetY(i) for i in range(min(3, res.GetN()))])
    except Exception as e:
        print(f"GetResultFromTreeItem('{path}') error:", e)

# Test ExportTouchstone method on project or tree
try:
    print("\nTesting project.ExportTouchstone:")
    res_ts = project.ExportTouchstone(os.path.abspath("outputs/test_out.s1p"))
    print("ExportTouchstone res:", res_ts)
except Exception as e:
    print("project.ExportTouchstone error:", e)

app.Quit()
pythoncom.CoUninitialize()
