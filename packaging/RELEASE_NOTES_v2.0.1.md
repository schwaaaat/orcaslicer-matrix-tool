# OrcaSlicer Matrix Studio v2.0.1 — Windows x64

This patch release fixes the Windows startup failure in v2.0.0:

> `ImportError: DLL load failed while importing QtCore: The specified procedure could not be found.`

## What was fixed

- Pinned the frozen desktop runtime to the verified PySide6/Qt 6.8.3 release instead of allowing an unbounded upgrade to Qt 6.11.2.
- Rebuilt both the standalone companion and the copy included with OrcaSlicer.
- Added a packaged-runtime smoke-test entrypoint that imports QtCore and QtWidgets, creates a real `QApplication`, and exits cleanly.
- Updated the Windows build script to run that smoke test automatically and fail packaging if the frozen Qt runtime cannot start.

## Verification

- All 107 Python tests pass.
- The final PyInstaller build passed the new frozen-runtime smoke test.
- The standalone executable was launch-tested from the packaged directory.
- OrcaSlicer's exact `--connect http://127.0.0.1:13130` launch command was tested.
- The running frozen process loaded `shiboken6.abi3.dll`, `pyside6.abi3.dll`, `Qt6Core.dll`, `Qt6Gui.dll`, and `Qt6Widgets.dll` successfully.
- Both final archives were integrity-tested after compression.

## Checksums

- Integrated package: `C208E4DAA9B23F69D84A6CFC668C5B189EAE0C94B1EF065BD9FCBD27CA3D5890`
- Standalone package: `8AE967A9877F9E514854FC137D54943308E78506622C138EC28EDE1637F7B8DD`

## Which file should I download?

### `OrcaSlicer-MatrixStudio-v2.0.1-Windows-x64.zip` — recommended

The complete portable OrcaSlicer and Matrix Studio suite. Extract the entire ZIP, run `orca-slicer.exe`, load a model, and choose **Matrix Studio** from OrcaSlicer's menu.

### `OrcaMatrixStudio-v2.0.1-Windows-x64.zip` — standalone companion

Matrix Studio without OrcaSlicer. Use this only with the compatible Matrix Studio-enabled OrcaSlicer build.

These community binaries are not code-signed, so Windows SmartScreen may show an **Unknown Publisher** warning.

## Source code

- Matrix Studio v2.0.1: https://github.com/schwaaaat/orcaslicer-matrix-tool/tree/v2.0.1
- Integrated OrcaSlicer source: https://github.com/schwaaaat/OrcaSlicer/tree/matrix-studio-v2.0.1
