import win32com.client
import pythoncom

pythoncom.CoInitialize()
app = win32com.client.Dispatch("CSTStudio.Application.2026")
print("App TypeInfo:")
try:
    ti = app._oleobj_.GetTypeInfo()
    attr = ti.GetTypeAttr()
    print("  Func count:", attr.cFuncs)
    for i in range(attr.cFuncs):
        f = ti.GetFuncDesc(i)
        name = ti.GetNames(f.memid)[0]
        print(f"  App method: {name}")
except Exception as e:
    print("App TypeInfo error:", e)

project = app.NewMWS()
print("\nProject TypeInfo:")
try:
    ti = project._oleobj_.GetTypeInfo()
    attr = ti.GetTypeAttr()
    print("  Func count:", attr.cFuncs)
    for i in range(attr.cFuncs):
        f = ti.GetFuncDesc(i)
        name = ti.GetNames(f.memid)[0]
        print(f"  Project method: {name}")
except Exception as e:
    print("Project TypeInfo error:", e)

app.Quit()
pythoncom.CoUninitialize()
