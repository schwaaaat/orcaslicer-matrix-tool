# Matrix Studio run bundle schema v2

`run.json` is the authoritative, portable record for a Matrix Studio experiment. Paths are relative to the folder containing `run.json`; copying that folder preserves the run. The local SQLite library is only an index and can always be rebuilt from bundles.

```json
{
  "schema_version": 2,
  "run_id": "8c5f1c54-b1c5-4bb5-897e-d9758328ce83",
  "name": "Layer height (2) × Wall loops (2)",
  "created_utc": "2026-09-16T20:10:00Z",
  "updated_utc": "2026-09-16T20:14:00Z",
  "state": "completed",
  "source": {
    "app": "OrcaSlicer",
    "app_version": "2.6.0",
    "presets": {},
    "plate_objects": ["Benchy.stl"]
  },
  "axes": [
    {"key": "layer_height", "label": "Layer height", "values": ["0.16", "0.20"]}
  ],
  "variants": [
    {
      "id": "b29f2015-71d9-45ea-9270-873bb60a1eb4",
      "ordinal": 1,
      "name": "layer_height=0.16",
      "changes": {"layer_height": "0.16"},
      "state": "completed",
      "gcode_path": "gcode/01-b29f2015.gcode",
      "stats": {"time_s": 3200, "filament_g": 18.2, "cost_usd": 0.46},
      "warnings": [],
      "error": null,
      "slice_wall_seconds": 12.4
    }
  ],
  "baseline_snapshot": {"layer_height": "0.20"},
  "restoration": {"required": false, "completed": true, "error": null},
  "settings": {"soft_variant_limit": 8, "hard_variant_limit": 32, "viewer_page_size": 8},
  "comparison": {}
}
```

## Invariants

- `schema_version` is exactly `2`; incompatible versions are rejected.
- `run_id` and every variant `id` are stable UUID strings.
- Runs contain 2–32 variants and 1–3 axes. Compare View loads at most eight variants per page.
- Configuration values remain strings because this matches OrcaSlicer's canonical serialization.
- A variant state is `pending`, `running`, `completed`, or `failed`. Completed variants have a relative `gcode_path`; failed variants have `error`.
- A run state is `draft`, `running`, `completed`, `cancelled`, `interrupted`, or `recovery_required`.
- `restoration.required=true` means OrcaSlicer's saved baseline may still need to be reapplied.
- Writers update the file atomically after every material state transition.
