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

def dump(item_path, depth=0):
    print("  " * depth + f"Item: '{item_path}'")
    try:
        child = tree.GetFirstChildName(item_path)
        while child:
            dump(child, depth + 1)
            child = tree.GetNextChildName(child)
    except Exception as e:
        print("  " * depth + f"  Child error: {e}")

print("Root tree dump:")
dump("")

app.Quit()
pythoncom.CoUninitialize()
