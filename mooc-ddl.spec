from PyInstaller.utils.hooks import collect_all

playwright_data, playwright_binaries, playwright_hiddenimports = collect_all("playwright")
webview_data, webview_binaries, webview_hiddenimports = collect_all("webview")

app_hiddenimports = [
    "mooc_deadlines.desktop",
    "mooc_deadlines.materials",
    "mooc_deadlines.sections",
    "mooc_deadlines.server",
    "mooc_deadlines.worker",
]

a = Analysis(
    ["launcher.py"],
    pathex=["src"],
    binaries=playwright_binaries + webview_binaries,
    datas=playwright_data + webview_data + [("web", "web")],
    hiddenimports=playwright_hiddenimports + webview_hiddenimports + app_hiddenimports,
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MOOC-DDL",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
