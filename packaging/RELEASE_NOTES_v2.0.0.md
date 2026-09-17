# OrcaSlicer Matrix Studio v2.0.0 — Windows x64

This is the first complete prebuilt Windows release of Matrix Studio and its compatible OrcaSlicer integration. End users do **not** need Python, Visual Studio, CMake, or any other build tools.

## Downloads

### `OrcaSlicer-MatrixStudio-v2.0.0-Windows-x64.zip` (recommended)

Complete portable OrcaSlicer build with:

- Matrix Studio available directly from the OrcaSlicer menu
- embedded local slicing API
- paged synchronized Compare View for Matrix Studio run bundles
- all required OrcaSlicer profiles, resources, runtime DLLs, and the Matrix Studio companion

Extract the entire ZIP, then run `orca-slicer.exe`. Keep the `tools` and `resources` directories beside the executable.

### `OrcaMatrixStudio-v2.0.0-Windows-x64.zip`

Standalone portable Matrix Studio companion. Use this only if you already have the compatible Matrix Studio-enabled OrcaSlicer build. Extract the entire ZIP and run `OrcaMatrixStudio.exe`.

## Matrix Studio v2 highlights

- searchable coverage of 800+ OrcaSlicer settings
- 1–3 matrix dimensions with configurable safety limits
- favorites, value presets, and reusable saved matrix tests
- crash-resilient setting restoration
- ETA approval after the baseline slice
- sortable results and filament-by-line-type analysis
- recommendations, baseline deltas, Markdown, and HTML reports
- selective synchronized Compare View launch

## Verification and security

- Both archives were integrity-tested after creation.
- SHA-256 hashes are provided in `SHA256SUMS.txt`.
- QtCharts is not included; the previous QtCharts startup crash is eliminated.
- These community binaries are not code-signed, so Windows SmartScreen may show an **Unknown Publisher** warning.

## Source code

- Matrix Studio v2.0.0: https://github.com/schwaaaat/orcaslicer-matrix-tool/tree/v2.0.0
- Integrated OrcaSlicer source: https://github.com/schwaaaat/OrcaSlicer/tree/matrix-studio-v2.0.0

OrcaSlicer and included third-party components remain under their respective licenses. Matrix Studio is MIT licensed.
