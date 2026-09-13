# OrcaSlicer Matrix Tool

A standalone, token-free Python tool with both a modern **Desktop GUI** and **CLI** that slices a matrix of OrcaSlicer setting permutations against whatever model is loaded on the plater, saves each variant's raw G-code, and generates a `manifest.json` conforming to `COMPARE_MANIFEST_SCHEMA.md`.

The generated manifest and G-code files are directly consumed by the native 3D multi-pane compare viewer (`orca-slicer.exe --compare manifest.json`).

## Key Features

- **Interactive Desktop GUI (`--gui`)**: Modern, native Tkinter/TTK graphical interface. Configure up to 3 dimensions, filter settings by OrcaSlicer Process tabs, click quick-add preset chips, inspect real-time permutation counts, preview variants table, monitor slice progress, and auto-launch the compare viewer.
- **Comprehensive Process Tab Coverage**: Directly mirrors OrcaSlicer's Process tabs (**Quality**, **Strength**, **Speed**, **Support**, **Others**, **Advanced**, plus **Extrusion & Flow** and **Filament & Cooling**), providing rich presets for common tests and searchable access to all 800+ settings from `print_settings_schema.json`.
- **Max 3 Dimensions Cap**: Restricts simultaneous matrix dimensions to at most 3 (e.g. Axis A, Axis B, Axis C) to prevent combinatorial explosion and keep comparisons meaningful and manageable.
- **Strict 8-Variant Hard Cap**: Enforces the maximum 8-variant limit specified in `COMPARE_MANIFEST_SCHEMA.md`. If a matrix produces >8 permutations, execution is refused with clear guidance detailing which axis to trim or drop.
- **Zero LLM / Runtime Dependencies**: Pure Python standard library (`urllib.request`, `json`, `argparse`, `tkinter`). Talks directly to OrcaSlicer's embedded REST API. No API keys, no Claude tokens, no third-party pip dependencies required.
- **Intelligent Setting Key Resolution**: Resolves human-friendly names (e.g., `"layer height"`, `"wall count"`, `"infill density"`) and raw config keys (`layer_height`, `wall_loops`) against `print_settings_schema.json`. Unrecognized settings are cleanly rejected with close match suggestions.
- **Baseline Wall-Clock Slice Timing & ETA Gate**: Slices the baseline variant first, measures true wall-clock slicing seconds with `time.monotonic()`, detects potential cache hits, calculates the estimated remaining and total time, and pauses for interactive approval before proceeding.
- **Configurable Auto-Approval Threshold**: Automatically skips approval and proceeds seamlessly if total estimated slicing time is under a configurable threshold (default: 30s, configurable via `--auto-confirm-under <seconds>` or in the GUI). Can also be completely bypassed via non-interactive mode (`--yes` in CLI or unchecking "Require approval" in GUI).
- **Guaranteed Config Snapshot & Safe Restoration**: Snapshots the baseline state of all targeted settings via `GET /api/v1/config`. Applies variants individually, resetting to baseline between slices to prevent permutation stacking, and guarantees exact restoration of the original plater configuration in a `try...finally` block under all circumstances (completion, variant error, or Ctrl+C).
- **Cost Calculation**: Accurately extracts `filament_cost` ($/kg) from the active filament preset and calculates `cost_usd = filament_g * filament_cost / 1000.0`.
- **Results & Analytics Dashboard**: Built-in interactive dashboard featuring Summary & Deltas comparison tables, G-code filament by line-type breakdown (inner/outer walls, infill, supports), visual bar/radar charts, and an automated recommendation banner.
- **Selective Compare Viewer Integration**: Auto-detects or lets you browse to your `orca-slicer.exe` executable. Launch the full comparison or select a subset of variants (via Ctrl+Click in tables or the checklist dialog) to inspect 2, 3, or more specific variants side-by-side.

---

## Quick Start: Launch GUI

Run without arguments (or with `--gui`) to launch the desktop interface:
```bash
python matrix_tool.py
# or
python matrix_tool.py --gui
```

In the GUI:
1. View live connection to OrcaSlicer and active plater details (printer, print preset, filament, model on bed).
2. Add up to 3 dimensions (Axis A, Axis B, Axis C).
3. Select any OrcaSlicer Process Tab (**Quality**, **Strength**, **Speed**, **Support**, **Others**, **Advanced**, **Extrusion**, **Filament**) or search all 800+ settings.
4. Click preset value chips or type custom values.
5. Watch the live permutation calculator enforce the 8-variant limit and preview the permutations table.
6. Click **Run Matrix Slices** to slice and optionally open the compare viewer!

---

## Usage Examples

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

## Output Manifest Structure

The tool outputs a `manifest.json` file in `<output_dir>` alongside the `.gcode` files:

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

The test suite requires zero external dependencies and runs with Python's built-in `unittest`:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Covers:
- `test_schema.py`: Setting resolution, human labels, synonyms, typo suggestions.
- `test_matrix.py`: Cartesian product, slugification, 8-variant limit enforcement and suggestions.
- `test_client.py`: Stdlib REST client against mock HTTP server, client-side filtering, 422 retry.
- `test_runner.py`: End-to-end orchestration, snapshot restoration, wall-clock ETA gate, cost calculation, and schema conformance.
