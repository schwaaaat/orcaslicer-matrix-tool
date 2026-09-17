# PyInstaller specification for the Windows companion bundled with OrcaSlicer.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("orcaslicer_matrix")
datas.append(("../print_settings_schema.json", "."))
datas.append(("../print_settings_schema.json", "orcaslicer_matrix"))
hiddenimports = collect_submodules("keyring.backends")

a = Analysis(
    ["../matrix_tool.py"],
    pathex=[".."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OrcaMatrixStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="OrcaMatrixStudio",
)
