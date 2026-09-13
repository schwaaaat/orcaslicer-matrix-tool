# Compare manifest schema (v1)

This is the ONLY contract between the two halves of this feature: the standalone matrix-slicing
tool (Python, produces this file) and the compare viewer (C++/OrcaSlicer, consumes this file).
Neither side needs to know anything about the other's internals or language — just this JSON
shape. If either side needs to change it, update this file in BOTH workspaces and say so loudly
in your PR/commit — it's the one thing that isn't allowed to silently drift.

```json
{
  "schema_version": 1,
  "created_utc": "2026-09-13T04:30:00Z",
  "source": {
    "app": "OrcaSlicer",
    "app_version": "2.4.2",
    "plate_objects": ["60mm Main Hook single color.stl", "Screw 60mm.stl", "Cap.stl"],
    "print_preset": "0.20mm Standard @BBL X1C - Fast PETG",
    "printer_preset": "Bambu Lab P1S 0.4 nozzle - 04282026",
    "filament_preset": "Elegoo PETG Rapid @Bambu Lab P1S 0.4 hardened nozzle"
  },
  "baseline": "0.20mm / 2 walls",
  "matrix": {
    "layer_height": ["0.16", "0.2", "0.24"],
    "wall_loops": ["2", "3"]
  },
  "variants": [
    {
      "name": "0.16mm / 2 walls",
      "changes": { "layer_height": "0.16", "wall_loops": "2" },
      "gcode_path": "0.16mm_2_walls.gcode",
      "stats": {
        "time_s": 7200,
        "filament_g": 37.0,
        "cost_usd": 0.92
      },
      "warnings": [{ "code": "1000C001", "message": "bed_temperature_too_high_than_filament" }],
      "error": null
    }
  ]
}
```

## Field notes

- `gcode_path` is relative to the manifest file's own directory (so the pair travels together —
  copy/zip the manifest + its gcode files as one unit and it still resolves). An absolute path is
  also acceptable; the viewer must support both.
- `variants` order is display order (left-to-right, top-to-bottom in the grid). Cap at **8**
  entries — same limit `orcaslicer-mcp`'s `compare_slices` tool already enforces, chosen so a
  2x4/3x3 grid stays readable and GPU memory per pane stays bounded. The tool should refuse (loud
  error, not silent truncation) to write a manifest with more than 8 variants.
- `error` is non-null and `gcode_path`/`stats` may be absent/null for a variant whose slice
  failed (invalid config keys, slice error, etc.) — the viewer must render a clear "failed to
  slice" placeholder for that pane rather than crashing or silently skipping it.
- `changes` values are always strings (OrcaSlicer's config API takes/returns config values as
  strings regardless of underlying type — don't assume numeric JSON types will round-trip).
- The manifest and every `gcode_path` file are plain, static, already-finished artifacts by the
  time the viewer ever sees them. The viewer never talks to the REST API, never triggers a slice,
  and does not need OrcaSlicer's Remote API enabled to open a manifest.

## Invocation contract

`orca-slicer.exe --compare <path-to-manifest.json>` opens the app directly into compare mode
(skip the normal startup-project flow) with all variants loaded. Exact flag name/behavior is the
C++ worktree's call — if it changes, update this file and mention it to whoever's coordinating so
the Python side's optional "auto-launch the viewer when done" step still works.
