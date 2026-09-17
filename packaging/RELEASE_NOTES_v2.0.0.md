# OrcaSlicer Matrix Studio v2.0.0 — Windows x64

This is the first complete prebuilt Windows release of Matrix Studio and its compatible OrcaSlicer integration. End users do **not** need Python, Visual Studio, CMake, or any other build tools.

## Which file should I download?

### `OrcaSlicer-MatrixStudio-v2.0.0-Windows-x64.zip` — recommended

The complete portable application suite. It contains the custom Matrix Studio-enabled OrcaSlicer build, all required runtime DLLs/resources/profiles, Matrix Studio under `tools/OrcaMatrix`, the embedded local slicing API, and native paged Compare View.

Extract the entire ZIP, run `orca-slicer.exe`, load a model, and choose **Matrix Studio** from OrcaSlicer's menu. Do not move only the EXE out of the extracted folder.

### `OrcaMatrixStudio-v2.0.0-Windows-x64.zip` — standalone companion

Matrix Studio without OrcaSlicer. Download this only if you already have the compatible custom OrcaSlicer build. Extract the entire ZIP and run `OrcaMatrixStudio.exe`.

## What changed in Matrix Studio

### Desktop workflow and setting coverage

- Replaced the original narrow matrix form with a Windows-first PySide6 Studio containing **Build**, **Active Run**, **Analyze**, and **Settings** workspaces.
- Added searchable coverage for 800+ OrcaSlicer settings from the packaged settings schema.
- Organized settings by OrcaSlicer's Quality, Strength, Speed, Support, Others, Advanced, Extrusion & Flow, and Filament & Cooling process tabs.
- Added setting favorites, curated presets, clickable value chips, keyword filtering, and stale-value protection when switching settings.
- Supports one to three matrix dimensions, Cartesian variant previews, a configurable warning limit, and a hard safety ceiling of 32 variants.
- Added reusable `.orcamatrix.json` test definitions.

### Safe slicing orchestration

- Captures active printer/process/filament presets, plate objects, and every setting affected by the matrix.
- Slices a baseline first, measures real wall-clock duration, estimates the remaining run, and optionally pauses for approval.
- Added configurable automatic approval for short estimated runs.
- Resets to the original baseline before every variant and restores all changed settings after completion, cancellation, or error.
- Records interrupted and `recovery_required` states instead of silently leaving the slicer modified.
- Writes runs atomically using documented schema-v2 `run.json` bundles and indexes recent runs locally.

### Analysis and reporting

- Added sortable time, filament, cost, state, baseline-time-delta, and baseline-mass-delta results.
- Parses G-code extrusion by line type, including walls, sparse/solid infill, top surfaces, support, and brim.
- Added filament breakdowns, a print-time chart, warning-aware recommendation, fastest/lightest indicators, and selective Compare View launch.
- Generates self-contained HTML reports and Markdown summaries automatically.
- Added copy actions for summary and filament-breakdown tables.

### Startup and packaging fixes

- Removed QtCharts, eliminating the earlier `DLL load failed while importing QtCharts` startup crash. Charts are painted directly with Qt.
- Bundles the settings schema in every required frozen-app location.
- Corrected entrypoint routing so OrcaSlicer's `--connect` command launches Studio instead of the legacy CLI.
- Includes explicit MIT licensing and portable Windows instructions.

## What changed in the custom OrcaSlicer build

### Embedded local API

- Added the Matrix Studio v2 capability handshake and endpoints for status, plate objects, configuration, slicing, cancellation, G-code retrieval, and plate rendering.
- Generates API tokens cryptographically and compares them in constant time.
- Serializes API mutations against the automatic backup exporter to avoid configuration/export races.
- Returns clearer non-editable-setting errors and URL-decodes configuration keys.
- Revalidates the plate before reslicing so corrected models clear latched validation errors.
- Detects stuck slices, supports cancellation, and reports boundary warnings and per-role filament breakdowns.
- Adds `.step`/`.stp` model loading with suppressed import dialogs and an extended timeout.
- Provides offscreen plate PNG rendering plus object world bounds and on-plate state.
- Disables upstream self-update in this fork so the custom build cannot replace itself with stock OrcaSlicer.

### Native Compare View and menu integration

- Reads legacy v1 manifests and Matrix Studio schema-v2 run bundles.
- Supports selected variant IDs and paged groups of eight synchronized G-code previews, with up to 32 variants per run.
- Adds Matrix Studio entries to the top and Tools menus.
- Searches installed, side-by-side, and development locations while preserving `ORCA_MATRIX_STUDIO` as an override.
- CMake now stages and installs the companion under `tools/OrcaMatrix`.
- Missing-companion messages list every searched path.

## Build and release verification

- **107 unique Python tests passed:** 22 Qt GUI tests and 85 non-GUI/runner/entrypoint tests.
- Rebuilt the Release OrcaSlicer executable and DLL after compiling the integration.
- Smoke-tested the clean integrated package: OrcaSlicer, the exact menu command, and standalone Matrix Studio all launched successfully.
- Verified the integrated tree contains 14,593 files and all expected runtime/profile resources.
- Integrity-tested both final ZIPs with 7-Zip after compression.
- Confirmed there are **zero QtCharts files** in either distribution.
- SHA-256 hashes are supplied in `SHA256SUMS.txt`.

## Security and known limitations

- These community binaries are **not code-signed**. Windows SmartScreen may show an **Unknown Publisher** warning.
- Verify downloads with `SHA256SUMS.txt` and only use binaries from this GitHub release.
- This is a portable release, not an MSI installer. Extract the complete directory before launching.
- Matrix Studio requires this compatible OrcaSlicer fork; stock OrcaSlicer does not expose the required API contract.

## Source code

- Matrix Studio tag: https://github.com/schwaaaat/orcaslicer-matrix-tool/tree/v2.0.0
- Integrated OrcaSlicer source: https://github.com/schwaaaat/OrcaSlicer/tree/matrix-studio-v2.0.0
- Windows installation and troubleshooting guide: https://github.com/schwaaaat/orcaslicer-matrix-tool/blob/master/docs/WINDOWS_RELEASE.md

OrcaSlicer and included third-party components remain under their respective licenses. Matrix Studio is MIT licensed.
