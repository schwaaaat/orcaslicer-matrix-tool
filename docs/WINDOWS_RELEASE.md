# Windows v2.0.2 release guide

Matrix Studio v2.0.2 is distributed as a portable Windows x64 application. No Python runtime, compiler, or repository checkout is required.

## Recommended installation

1. Open the [latest GitHub release](https://github.com/schwaaaat/orcaslicer-matrix-tool/releases/latest).
2. Download `OrcaSlicer-MatrixStudio-v2.0.2-Windows-x64.zip` and `SHA256SUMS.txt`.
3. Verify the ZIP's SHA-256 hash.
4. Extract the **entire** ZIP to a normal writable folder.
5. Run `orca-slicer.exe`.
6. Load a model, then select **Matrix Studio** from OrcaSlicer's menu.

The package is portable. To uninstall it, close both applications and remove the extracted folder. User-created Matrix Studio runs are stored separately in the configured run-library location.

## Package layout

```text
OrcaSlicer-MatrixStudio-v2.0.2-Windows-x64/
├── orca-slicer.exe
├── OrcaSlicer.dll
├── resources/
├── tools/
│   └── OrcaMatrix/
│       ├── OrcaMatrixStudio.exe
│       ├── print_settings_schema.json
│       └── _internal/
└── README-MATRIX-STUDIO.txt
```

Keep this layout intact. OrcaSlicer discovers the companion under `tools/OrcaMatrix`, and both applications depend on adjacent runtime files.

## Standalone package

`OrcaMatrixStudio-v2.0.2-Windows-x64.zip` contains only the companion application. It is useful when updating Matrix Studio independently, but it still requires a running compatible OrcaSlicer build for slicing.

## Architecture

Matrix Studio connects to OrcaSlicer's loopback-only API at `http://127.0.0.1:13130`. It reads the current plate and active configuration, applies one variant at a time, retrieves G-code/statistics, and restores the original settings after the run. Results are stored in portable schema-v2 run directories and can be opened in OrcaSlicer's synchronized native Compare View.

The API uses a local token, secure token generation, constant-time comparison, and serialization around mutable slicer state. Matrix Studio does not require an external MCP process for normal desktop use.

## Troubleshooting

### Matrix Studio is not found

Confirm that `tools\OrcaMatrix\OrcaMatrixStudio.exe` exists relative to `orca-slicer.exe`. Re-extract the full integrated ZIP if files were moved individually. `ORCA_MATRIX_STUDIO` may be set to an explicit companion executable as an advanced override.

### Windows shows Unknown Publisher

The community build is currently unsigned. Verify the SHA-256 hash against the release's `SHA256SUMS.txt`, then use Windows' **More info** flow only if the hash matches the official GitHub release.

### Matrix Studio cannot connect

Use the integrated OrcaSlicer build, keep OrcaSlicer running, and verify that its Remote API is enabled. Stock OrcaSlicer releases do not include the Matrix Studio v2 API.

In v2.0.2 and newer, the local API token is read from OrcaSlicer's current configuration and shown in the masked API-token field automatically. A manually entered token is stored in Windows Credential Manager when **Save settings** is pressed and is restored on the next launch.

### QtCore reports "The specified procedure could not be found"

This was a packaging defect in the original v2.0.0 Windows binaries. Download v2.0.1 or newer; its PySide6/Qt runtime is pinned to the verified 6.8.3 release and every Windows build now runs a frozen-runtime smoke test before packaging succeeds.

### Compare View does not open

In Matrix Studio Settings, select the `orca-slicer.exe` from the integrated package. Run bundles may contain up to 32 variants; Compare View loads them in pages of eight.

## Complete change summary

The token-discovery and persistence fix is documented on the [v2.0.2 release page](https://github.com/schwaaaat/orcaslicer-matrix-tool/releases/tag/v2.0.2). The Qt runtime packaging fix is on the [v2.0.1 release page](https://github.com/schwaaaat/orcaslicer-matrix-tool/releases/tag/v2.0.1).
