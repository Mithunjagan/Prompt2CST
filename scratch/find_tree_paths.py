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

all_paths = []

def explore(item_path):
    all_paths.append(item_path)
    try:
        child = tree.GetFirstChildName(item_path)
        while child:
            explore(child)
            child = tree.GetNextChildName(child)
    except Exception as e:
        pass

explore("1D Results")
print(f"Found {len(all_paths)} tree paths under '1D Results':")
for p in all_paths:
    print(f"  '{p}'")

# Also test GetFirstTreeItem / GetNextTreeItem
print("\nTesting GetFirstTreeItem / GetNextTreeItem:")
try:
    item = tree.GetFirstTreeItem()
    while item:
        print("  Tree item:", item)
        item = tree.GetNextTreeItem(item)
except Exception as e:
    print("GetFirstTreeItem error:", e)

app.Quit()
pythoncom.CoUninitialize()
