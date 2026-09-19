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

out_txt = os.path.abspath("outputs/test_rebuild_s11.txt")
vba_export = f"""
SelectTreeItem("1D Results\\Port signals\\i1")
With ASCIIExport
    .Reset
    .FileName "{out_txt}"
    .Execute
End With
"""

print("Adding export to history and calling Rebuild...")
project.AddToHistory("Prompt2CST: Export i1 Signal", vba_export)
project.Rebuild()
project.Save()

app.Quit()
pythoncom.CoUninitialize()

if Path(out_txt).exists():
    print("SUCCESS! File created:", out_txt, "Size:", Path(out_txt).stat().st_size)
    print("Content preview:")
    print(Path(out_txt).read_text(errors="ignore")[:300])
else:
    print("FILE MISSING:", out_txt)
