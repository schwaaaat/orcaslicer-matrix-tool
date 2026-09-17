# OrcaSlicer Matrix Studio

A Windows-first PySide6 desktop workspace for designing, slicing, and analyzing OrcaSlicer setting matrices. Matrix Studio connects directly to the token-authenticated Remote API built into the companion OrcaSlicer branch, slices the active plate, preserves the original settings, and stores every experiment as a portable v2 run bundle.

The bundled native Compare View opens up to 32 stored variants in pages of eight synchronized G-code previews (`orca-slicer.exe --compare run.json`).

> Matrix Studio v2 is a clean-break desktop release. The legacy CLI and v1 manifest writer remain temporarily available for scripted compatibility, but new desktop runs use `run.json` schema version 2 and the local run library.

## Download for Windows

Prebuilt Windows x64 packages are available from the [latest GitHub release](https://github.com/schwaaaat/orcaslicer-matrix-tool/releases/latest):

- **OrcaSlicer + Matrix Studio** — recommended; a complete portable OrcaSlicer build with Matrix Studio integrated into the menu.
- **Matrix Studio standalone** — the companion desktop application only, for use with a compatible Matrix Studio-enabled OrcaSlicer build.

Extract the entire ZIP before running it. No Python environment, compiler, or source build is required.

See the [Windows v2.0.1 release guide](docs/WINDOWS_RELEASE.md) for installation, architecture, the complete change summary, verification details, and troubleshooting.

## Key Features

- **Modern Qt Desktop UI**: Dark technical-studio design with Build, Active Run, Analyze, Settings, and searchable run-history workspaces.
- **Comprehensive Process Tab Coverage**: Directly mirrors OrcaSlicer's Process tabs (**Quality**, **Strength**, **Speed**, **Support**, **Others**, **Advanced**, plus **Extrusion & Flow** and **Filament & Cooling**), providing rich presets for common tests and searchable access to all 800+ settings from `print_settings_schema.json`.
- **Max 3 Dimensions Cap**: Restricts simultaneous matrix dimensions to at most 3 (e.g. Axis A, Axis B, Axis C) to prevent combinatorial explosion and keep comparisons meaningful and manageable.
- **Configurable Matrix Safety**: A warning threshold defaults to 8 variants, with a hard first-release limit of 32. Compare View keeps no more than eight G-code datasets resident at once.
- **Direct OrcaSlicer Integration**: Uses the custom branch's embedded local API; no MCP process is required. The same API remains compatible with `orcaslicer-mcp` when AI automation is wanted.
- **Portable Run Library**: Atomic v2 run bundles remain usable when copied, while SQLite supplies fast local search and recent-run history.
- **Intelligent Setting Key Resolution**: Resolves human-friendly names (e.g., `"layer height"`, `"wall count"`, `"infill density"`) and raw config keys (`layer_height`, `wall_loops`) against `print_settings_schema.json`. Unrecognized settings are cleanly rejected with close match suggestions.
- **Baseline Wall-Clock Slice Timing & ETA Gate**: Slices the baseline variant first, measures real slicing time with `time.monotonic()`, estimates the remaining matrix, and pauses for approval before proceeding.
- **Crash-Resilient Config Restoration**: Snapshots every targeted setting, resets to baseline between slices, restores the original values in a `finally` block, and records `recovery_required` in `run.json` if restoration cannot be completed.
- **Cost Calculation**: Accurately extracts `filament_cost` ($/kg) from the active filament preset and calculates `cost_usd = filament_g * filament_cost / 1000.0`.
- **Results & Analytics Dashboard**: A results table and print-time chart summarize completed variants, while the run bundle retains computed deltas and G-code filament-by-role data for reporting.
- **Selective Compare Viewer Integration**: Auto-detects or lets you browse to `orca-slicer.exe`; select up to eight result rows to open directly in synchronized Compare View.

---

## Quick Start

Create an environment and install the desktop dependencies:
```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python matrix_tool.py
```

Enable **Remote API** in the custom OrcaSlicer build, load a model on the plate, and launch Matrix Studio from OrcaSlicer's menu or directly. Build a 1–3 axis matrix, review its variants, and start the run. The baseline slice supplies the remaining-time estimate before the tool continues.

For development packaging:

```powershell
./packaging/build_windows.ps1
```

The onedir result is written below `packaging/dist/OrcaMatrixStudio` and is intended to be installed beside OrcaSlicer under `tools/OrcaMatrix`.

---

## Legacy CLI Compatibility

### 1. Slicing with CLI Axis Flags
Slice a 2x2 matrix (4 variants) using canonical config keys:
```bash
python matrix_tool.py -a "layer_height=0.16,0.20" -a "wall_loops=2,3" -o ./compare_output
```

Using human-readable labels and aliases:
```bash
python matrix_tool.py -a "layer height=0.16,0.20" -a "wall count=2,3"
```

### 2. Slicing with JSON Config File
Create a JSON configuration file, e.g. `matrix_config.json`:
```json
{
  "layer height": ["0.16", "0.20", "0.24"],
  "wall count": ["2", "3"]
}
```
Run with:
```bash
python matrix_tool.py --config matrix_config.json -o ./my_run
```

### 3. Non-Interactive / Scripted Mode
Bypass the ETA confirmation prompt completely:
```bash
python matrix_tool.py -a "layer_height=0.16,0.20" -a "wall_loops=2,3" --yes
```

Or configure custom auto-approval threshold (e.g. skip prompt if total time < 45s):
```bash
python matrix_tool.py -a "layer_height=0.16,0.20" -a "wall_loops=2,3" --auto-confirm-under 45
```

### 4. Dry-Run Validation
Verify key resolution, permutation planning, plater connection, and snapshot without triggering slices:
```bash
python matrix_tool.py -a "layer_height=0.16,0.20" -a "wall_loops=2,3" --dry-run
```

---

## Remote API Configuration

The tool connects to OrcaSlicer's embedded REST API (default: `http://127.0.0.1:13130`).

API token resolution order:
1. `--token <token>` command-line flag.
2. `ORCA_API_TOKEN` environment variable.
3. Automatically discovered from `%APPDATA%\OrcaSlicer\OrcaSlicer.conf` (`remote_api_token`).
4. Local `.mcp.json` files.

---

## Legacy v1 Manifest Structure

Legacy CLI runs output a `manifest.json` file in `<output_dir>` alongside the `.gcode` files. New Matrix Studio runs write the v2 `run.json` bundle documented in `RUN_BUNDLE_SCHEMA.md`.

```json
{
  "schema_version": 1,
  "created_utc": "2026-09-13T05:20:00Z",
  "source": {
    "app": "OrcaSlicer",
    "app_version": "2.4.2",
    "plate_objects": ["Model.stl"],
    "print_preset": "0.20mm Standard @BBL X1C",
    "printer_preset": "Bambu Lab P1S 0.4 nozzle",
    "filament_preset": "Elegoo PETG Rapid"
  },
  "baseline": "layer_height=0.16, wall_loops=2",
  "matrix": {
    "layer_height": ["0.16", "0.20"],
    "wall_loops": ["2", "3"]
  },
  "variants": [
    {
      "name": "layer_height=0.16, wall_loops=2",
      "changes": { "layer_height": "0.16", "wall_loops": "2" },
      "gcode_path": "layer_height_0.16_wall_loops_2.gcode",
      "stats": {
        "time_s": 3600.0,
        "filament_g": 24.5,
        "cost_usd": 0.49
      },
      "warnings": [],
      "error": null
    }
  ]
}
```

---

## Running the Automated Test Suite

Install the development dependencies and run the complete suite with pytest:

```bash
python -m pytest -q
```

Covers:
- `test_schema.py`: Setting resolution, human labels, synonyms, typo suggestions.
- `test_matrix.py`: Cartesian product, slugification, configurable limit enforcement and suggestions.
- `test_run_bundle.py`: v2 schema round trips, atomic writes, and run-library indexing.
- `test_studio_client.py`: capabilities negotiation and compatibility rejection.
- `test_studio_gui.py`: Qt builder layout, axis limits, and live permutation preview.
- `test_client.py`: Stdlib REST client against mock HTTP server, client-side filtering, 422 retry.
- `test_runner.py`: End-to-end orchestration, snapshot restoration, wall-clock ETA gate, cost calculation, and schema conformance.
