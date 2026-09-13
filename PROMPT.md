# OrcaSlicer Matrix Tool — brief for Antigravity

You're in `G:\Claude\orcaslicer-matrix-tool`, a fresh, empty git repo. Your job: a **standalone,
token-free Python CLI** that slices a full matrix of OrcaSlicer setting permutations against
whatever's currently loaded on the plate, and writes a manifest that a separate native viewer
(built independently, in a different worktree, in C++ — you don't need its code, just its
contract) uses to show every variant side-by-side in 3D. Once this tool is written, running it
costs zero LLM tokens — no Claude, no MCP, nothing but this script talking to OrcaSlicer directly.

Read `COMPARE_MANIFEST_SCHEMA.md` in this same directory FIRST — it's the entire contract with the
other half of this project. Match it exactly; if you need to deviate, say so loudly in your
summary (and update the schema file in both places — the other copy lives in the C++ worktree at
`G:\Claude\OrcaBuild\OrcaSlicer-VFjr-compare-viewer\COMPARE_MANIFEST_SCHEMA.md`, you won't have
write access to it from here in practice, so just flag the deviation clearly for whoever's
coordinating instead of silently diverging).

## Why this exists / prior art to learn from, not copy

An existing tool, `orcaslicer-mcp` (installed from PyPI, source at
github.com/maxellis/orcaslicer-mcp — NOT in this repo) already does almost exactly this, but
*through an LLM* (it's an MCP server Claude calls tool-by-tool). Its `compare_slices` function is
the direct model for your slicing loop's logic (reset-to-baseline between variants, restore
config when done, cap at 8 variants, compute deltas) — but you are NOT calling that package or
going through Claude/MCP at all. You're re-implementing the relevant slice of its logic as a
direct REST client, so this tool has zero LLM dependency at runtime. `print_settings_schema.json`
in this directory is vendored from that package — use it to resolve human-readable setting names
("wall count") to real config keys (`wall_loops`) without needing an LLM to do that lookup.

## The REST API you're calling

OrcaSlicer's fork exposes a local REST API. From this machine's `.mcp.json`
(`G:\Claude\orcaslicer-mcp\.mcp.json`): base URL `http://127.0.0.1:13130`, header
`X-Api-Token: <token>` (don't hardcode the token — read it from an env var or a config file the
user points you at; the app's own Preferences > Remote API panel shows/regenerates it). Routes you
need (verify each against the running app — this list is from reading `orcaslicer-mcp`'s
`client.py`, not guaranteed complete or unchanged):

- `GET /api/v1/status` — current plate objects, presets, `slice_result_valid`.
- `GET /api/v1/config` — full config dict (values are strings). Filter client-side; the API's
  `keys` query param has a known encoding bug in at least one prior integration (comma-split
  before URL-decoding) — don't rely on it, fetch the whole config and index locally.
- `PUT /api/v1/config` — body `{key: value, ...}`, returns `{"applied": [...], "errors": {...}}`.
- `POST /api/v1/slice` — starts a slice (async).
- `GET /api/v1/slice/status` — poll this; look for a state field indicating done/error and the
  resulting stats (time, filament) plus warnings.
- `GET /api/v1/gcode` — returns the last successful slice's gcode as raw bytes. This is what you
  save to disk per variant, right after that variant's slice completes and BEFORE moving to the
  next one (there is no "give me variant #3's gcode later" — it's always "the last slice").

## Required flow

1. **Matrix input.** Accept a simple config (JSON or a small DSL, your call) mapping axis → list
   of values, e.g. `{"layer_height": ["0.16","0.2","0.24"], "wall_loops": ["2","3"]}`. Resolve
   each axis key against `print_settings_schema.json` if it's not already a raw config key (accept
   both a human label like "layer height" and the raw key `layer_height`). Reject (clear error,
   don't guess) an axis name you can't resolve.
2. **Cartesian product** → one named variant per permutation (name = human-readable axis=value
   list, e.g. `"layer_height=0.16, wall_loops=2"`). Hard cap at 8 total variants — refuse with a
   clear error above that (tell the user which axis to drop, don't silently truncate).
3. **Snapshot** the current value of every key that appears in any variant's changes (`GET
   /api/v1/config`, keep just those keys) so you can restore it exactly at the end, success or
   failure (try/finally).
4. **Baseline slice + ETA gate — this is a specifically requested feature, don't skip it:**
   - Apply the FIRST variant's changes, and force a real (non-cached) slice — don't trust
     `slice_result_valid` from status to skip it; if the API supports it, invalidate first, or at
     minimum measure wall-clock time around the slice call and treat a suspiciously-fast result
     (near-zero) as a sign you measured a cache hit, not a real slice, and say so rather than
     reporting a bogus per-variant estimate.
   - Time it (real wall-clock, `time.monotonic()`, not the reported print-time estimate — those
     are minutes-of-printing, not seconds-of-slicing, a completely different number).
   - `estimated_total = measured_seconds * variant_count` (+ a small fixed per-variant overhead
     for the config PUT/gcode fetch round trip if you want to measure that too — don't overthink
     it, the point is a usable estimate, not a precise one).
   - Print the estimate and the variant count, and **require interactive confirmation
     (`y/n`) before continuing** to the remaining variants. A `--yes`/non-interactive flag to skip
     the prompt is fine for scripting, but interactive-by-default is the point (the person who
     asked for this explicitly wants to back out of a 4-axis-deep matrix before committing an
     afternoon to it).
5. **Loop remaining variants:** restore the snapshot, apply this variant's changes (if `PUT`
   returns errors for an unknown/invalid key, record the variant as failed with that error, don't
   abort the whole run), slice, poll status to completion, fetch gcode bytes, write to
   `<output_dir>/<slug>.gcode` (slug the variant name into a filesystem-safe filename), record
   stats (`time_s`, `filament_g`) + warnings.
6. **Cost.** Pull `filament_cost` from config (USD/kg in this profile — confirm the unit isn't
   always safe to assume across every filament profile, note it if you can't verify). `cost_usd =
   filament_g * filament_cost / 1000`.
7. **Restore** the original snapshot when done (or on any exception/KeyboardInterrupt —
   try/finally, matching `compare_slices`' own restore-on-error behavior).
8. **Write `manifest.json`** matching `COMPARE_MANIFEST_SCHEMA.md` exactly, gcode files alongside
   it in the same output directory.
9. **Optional auto-launch:** if given a path to `orca-slicer.exe` (config option, not hardcoded),
   `subprocess.Popen([exe, "--compare", manifest_path])` when done. This flag may not work until
   the C++ side lands — make it opt-in and fail gracefully (clear message, not a crash) if the
   `--compare` flag doesn't exist yet in whatever binary is configured.

## Explicitly NOT in scope

- No parallel/concurrent slicing — one variant at a time, always (confirmed requirement, and the
  slicer engine isn't built for concurrent instances against one running app anyway).
- No LLM/MCP dependency at runtime, anywhere in this tool.
- No UI beyond a CLI — the viewer is the other worktree's job entirely.

## Acceptance criteria

- Run it against the actual running OrcaSlicer instance on this machine (Remote API already
  enabled, per the Preferences panel) with a real 2-3 axis matrix, and confirm: the ETA prompt
  appears with a plausible number before the bulk of the run, all gcode files + manifest.json get
  written, and the app's config is back to exactly what it was before you ran the tool.
- Don't claim done off "the script runs without throwing" alone — actually open the config in the
  app afterward (or `GET /api/v1/config` before/after) and confirm the restore was exact.
