"""Orchestration engine for slicing matrix variants, enforcing snapshot/restore,
timing wall-clock baseline, ETA confirmation gate, and manifest generation.
"""

from __future__ import annotations

import datetime
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .client import OrcaApiError, OrcaClient
from .matrix import Variant, build_variants


TERMINAL_SLICE_STATES = frozenset({"done", "error", "idle"})
DEFAULT_FILAMENT_COST_USD_PER_KG = 25.0


def format_duration(seconds: float) -> str:
    """Format seconds into readable string (e.g. '14s', '1m 20s', '1h 05m')."""
    sec = int(round(seconds))
    if sec < 60:
        return f"{sec}s"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def parse_filament_cost(raw_cost: Any) -> float:
    """Parse filament cost in USD/kg from config.

    OrcaSlicer filament_cost is type coFloats (e.g. '25', '25.0', or '25.0,25.0').
    Returns cost per kg as float.
    """
    if raw_cost is None:
        return DEFAULT_FILAMENT_COST_USD_PER_KG
    cost_str = str(raw_cost).strip()
    if not cost_str:
        return DEFAULT_FILAMENT_COST_USD_PER_KG
    # Handle comma-separated multi-extruder values
    first_part = cost_str.split(",")[0].strip()
    try:
        val = float(first_part)
        return val if val > 0 else DEFAULT_FILAMENT_COST_USD_PER_KG
    except ValueError:
        return DEFAULT_FILAMENT_COST_USD_PER_KG


def wait_for_slice(
    client: OrcaClient,
    timeout: float = 300.0,
    poll_interval: float = 0.8,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> Dict[str, Any]:
    """Poll GET /api/v1/slice/status until terminal state (done/error/idle) or timeout."""
    deadline = time.monotonic() + timeout
    last_percent = -1
    while time.monotonic() < deadline:
        st = client.slice_status()
        state = st.get("state", "idle")
        percent = st.get("percent", 0)

        if percent != last_percent and progress_callback:
            progress_callback(percent, state)
            last_percent = percent

        if state in TERMINAL_SLICE_STATES:
            return st

        time.sleep(poll_interval)

    # If timed out, attempt cancel
    try:
        client.cancel_slice()
    except Exception:
        pass
    return {"state": "error", "message": f"Slice timed out after {int(timeout)} seconds"}


class MatrixRunner:
    """Coordinates matrix slicing across OrcaSlicer."""

    def __init__(
        self,
        client: OrcaClient,
        output_dir: Path,
        timeout: float = 300.0,
        non_interactive: bool = False,
        dry_run: bool = False,
        log_callback: Optional[Callable[[str], None]] = None,
        eta_confirm_fn: Optional[Callable[[float, int, float], bool]] = None,
        progress_callback: Optional[Callable[[int, int, Variant, str, float], None]] = None,
    ):
        self.client = client
        self.output_dir = Path(output_dir)
        self.timeout = timeout
        self.non_interactive = non_interactive
        self.dry_run = dry_run
        self.log_callback = log_callback
        self.eta_confirm_fn = eta_confirm_fn
        self.progress_callback = progress_callback

    def _log(self, msg: str = "") -> None:
        """Output log message to stdout and optional log_callback."""
        print(msg)
        if self.log_callback:
            try:
                self.log_callback(msg)
            except Exception:
                pass

    def run(
        self,
        resolved_matrix: Dict[str, List[str]],
        baseline_name: Optional[str] = None,
    ) -> Tuple[Path, Dict[str, Any]]:
        """Execute the full matrix slicing process.

        Returns:
            Tuple of (manifest_path, manifest_dict)
        """
        variants = build_variants(resolved_matrix)
        self._log(f"Planning matrix run with {len(variants)} variants across {len(resolved_matrix)} axes:")
        for axis, values in resolved_matrix.items():
            self._log(f"  - {axis}: {values}")
        self._log()

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Fetch current plater status & objects
        self._log("Connecting to OrcaSlicer...")
        status = self.client.get_status()
        objects = self.client.get_objects()

        app_name = status.get("app") or "OrcaSlicer"
        app_version = status.get("app_version") or status.get("version") or "2.4.2"
        presets = status.get("presets", {}) if isinstance(status.get("presets"), dict) else {}

        print_preset = presets.get("print") or presets.get("print_preset") or "Default"
        printer_preset = presets.get("printer") or presets.get("printer_preset") or "Default"

        fil_preset_raw = presets.get("filament") or presets.get("filaments") or presets.get("filament_preset")
        if isinstance(fil_preset_raw, list) and fil_preset_raw:
            filament_preset = str(fil_preset_raw[0])
        elif fil_preset_raw:
            filament_preset = str(fil_preset_raw)
        else:
            filament_preset = "Default"

        plate_objects = [str(o.get("name")) for o in objects if o.get("name")]
        if not plate_objects and "plate_objects" in status:
            plate_objects = [str(x) for x in status["plate_objects"]]

        self._log(f"Connected: {app_name} v{app_version}")
        self._log(f"  Printer:  {printer_preset}")
        self._log(f"  Print:    {print_preset}")
        self._log(f"  Filament: {filament_preset}")
        self._log(f"  Objects:  {plate_objects or '(none)'}")
        self._log()

        # 2. Fetch full config to snapshot keys and extract filament cost
        full_cfg = self.client.get_config()
        raw_cost = full_cfg.get("filament_cost")
        cost_per_kg = parse_filament_cost(raw_cost)
        if raw_cost is None:
            self._log(f"Note: 'filament_cost' not defined in active filament preset. Using default ${cost_per_kg:.2f}/kg.")
        else:
            self._log(f"Active filament cost: ${cost_per_kg:.2f}/kg")

        # Snapshot all keys that appear across all variants
        all_keys = sorted({k for v in variants for k in v.changes})
        snapshot = {k: full_cfg[k] for k in all_keys if k in full_cfg}
        self._log(f"Snapshotted {len(snapshot)} config keys to guarantee safe restoration.")
        self._log()

        if self.dry_run:
            self._log("[DRY-RUN] Matrix validation and snapshot successful. Exiting without slicing.")
            return self.output_dir / "manifest.json", {}

        variant_results: List[Dict[str, Any]] = []
        aborted_by_user = False

        try:
            # 3. Variant 0: Baseline Slice + Wall-Clock Timing + ETA Gate
            v0 = variants[0]
            self._log(f"--- Variant 1/{len(variants)} (Baseline): '{v0.name}' ---")
            if self.progress_callback:
                self.progress_callback(1, len(variants), v0, "slicing", 0.0)

            v0_result, wall_seconds = self._slice_single_variant(v0, snapshot, cost_per_kg)
            variant_results.append(v0_result)
            if self.progress_callback:
                self.progress_callback(1, len(variants), v0, "done" if not v0_result.get("error") else "error", 100.0)

            if wall_seconds < 0.5:
                self._log(
                    f"\n[WARNING] Baseline slice completed in {wall_seconds:.2f}s (suspiciously fast).\n"
                    "This likely indicates a cache hit or an empty plater. ETA estimates may be skewed.\n"
                )

            # ETA Gate: calculate remaining time and prompt user
            if len(variants) > 1:
                remaining_count = len(variants) - 1
                overhead_per_variant = 1.5
                est_remaining_sec = (wall_seconds + overhead_per_variant) * remaining_count
                est_total_sec = wall_seconds + est_remaining_sec

                self._log()
                self._log("=" * 68)
                self._log(f"[ETA Gate] Variant 1 sliced in {wall_seconds:.1f}s wall-clock time.")
                self._log(f"Remaining variants: {remaining_count}")
                self._log(
                    f"Estimated slicing time for remaining: ~{format_duration(est_remaining_sec)} "
                    f"(~{format_duration(est_total_sec)} total)"
                )
                self._log("=" * 68)

                if not self.non_interactive:
                    if self.eta_confirm_fn:
                        proceed = self.eta_confirm_fn(wall_seconds, remaining_count, est_remaining_sec)
                        if not proceed:
                            self._log("\nMatrix execution cancelled by user. Finalizing manifest with completed variants...")
                            aborted_by_user = True
                    else:
                        prompt = f"Proceed with remaining {remaining_count} variant(s)? [y/N]: "
                        sys.stdout.write(prompt)
                        sys.stdout.flush()
                        try:
                            ans = sys.stdin.readline().strip().lower()
                        except (KeyboardInterrupt, EOFError):
                            ans = "n"

                        if ans not in ("y", "yes"):
                            self._log("\nMatrix execution cancelled by user. Finalizing manifest with completed variants...")
                            aborted_by_user = True

            # 4. Loop Remaining Variants (if not cancelled)
            if not aborted_by_user:
                for idx, v in enumerate(variants[1:], start=2):
                    self._log(f"\n--- Variant {idx}/{len(variants)}: '{v.name}' ---")
                    if self.progress_callback:
                        self.progress_callback(idx, len(variants), v, "slicing", 0.0)
                    v_res, _ = self._slice_single_variant(v, snapshot, cost_per_kg)
                    variant_results.append(v_res)
                    if self.progress_callback:
                        self.progress_callback(idx, len(variants), v, "done" if not v_res.get("error") else "error", 100.0)

        finally:
            # 5. Safe Restoration: Guaranteed reset of snapshot config
            if snapshot:
                self._log("\nRestoring original plater configuration...")
                try:
                    self.client.put_config(snapshot)
                    self._log("[OK] Configuration successfully restored to baseline.")
                except Exception as e:
                    self._log(f"[ERROR] Restoring configuration to OrcaSlicer: {e}")

        # 6. Build and write manifest.json
        manifest_baseline = baseline_name or variants[0].name
        manifest_data = {
            "schema_version": 1,
            "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": {
                "app": app_name,
                "app_version": app_version,
                "plate_objects": plate_objects,
                "print_preset": print_preset,
                "printer_preset": printer_preset,
                "filament_preset": filament_preset,
            },
            "baseline": manifest_baseline,
            "matrix": resolved_matrix,
            "variants": variant_results,
        }

        manifest_path = self.output_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

        self._log(f"\nManifest successfully written: {manifest_path}")
        self._print_summary_table(variant_results, manifest_baseline)

        return manifest_path, manifest_data

    def _slice_single_variant(
        self,
        v: Variant,
        snapshot: Dict[str, str],
        cost_per_kg: float,
    ) -> Tuple[Dict[str, Any], float]:
        """Slice one variant: reset to snapshot, apply changes, slice, fetch gcode, compute stats."""
        # Step A: Reset to snapshot baseline first so settings don't accumulate
        if snapshot:
            self.client.put_config(snapshot)

        # Step B: Apply variant changes
        if v.changes:
            applied = self.client.put_config(v.changes)
            if applied.get("errors"):
                err_msg = f"Invalid config keys: {applied['errors']}"
                self._log(f"  [ERROR] {err_msg}")
                return {
                    "name": v.name,
                    "changes": v.changes,
                    "gcode_path": None,
                    "stats": None,
                    "warnings": [],
                    "error": err_msg,
                }, 0.0

        # Step C: Trigger slice with wall-clock measurement
        self._log("  Starting slice...")
        t0 = time.monotonic()
        try:
            self.client.slice(retry_on_not_started=True)
            slice_status = wait_for_slice(self.client, timeout=self.timeout)
        except OrcaApiError as e:
            err_msg = f"API error starting slice: {e}"
            self._log(f"  [ERROR] {err_msg}")
            return {
                "name": v.name,
                "changes": v.changes,
                "gcode_path": None,
                "stats": None,
                "warnings": [],
                "error": err_msg,
            }, 0.0

        wall_seconds = time.monotonic() - t0

        state = slice_status.get("state")
        if state != "done":
            err_msg = slice_status.get("message") or f"Slice ended with state '{state}'"
            self._log(f"  [ERROR] Slice failed: {err_msg}")
            return {
                "name": v.name,
                "changes": v.changes,
                "gcode_path": None,
                "stats": None,
                "warnings": slice_status.get("warnings", []),
                "error": err_msg,
            }, wall_seconds

        # Step D: Download G-code raw bytes immediately
        gcode_path = self.output_dir / v.gcode_filename
        try:
            gcode_bytes = self.client.get_gcode()
            with open(gcode_path, "wb") as f:
                f.write(gcode_bytes)
            size_kb = len(gcode_bytes) / 1024.0
            self._log(f"  Saved G-code: {v.gcode_filename} ({size_kb:.1f} KB)")
        except Exception as e:
            err_msg = f"Failed to download G-code: {e}"
            self._log(f"  [ERROR] {err_msg}")
            return {
                "name": v.name,
                "changes": v.changes,
                "gcode_path": None,
                "stats": None,
                "warnings": slice_status.get("warnings", []),
                "error": err_msg,
            }, wall_seconds

        # Step E: Parse stats
        stats_raw = slice_status.get("stats") or {}
        time_s = stats_raw.get("estimated_time_seconds")
        filament_g = stats_raw.get("filament_used_g")

        cost_usd = None
        if filament_g is not None:
            cost_usd = round((filament_g * cost_per_kg) / 1000.0, 2)

        stats_dict = {
            "time_s": time_s,
            "filament_g": round(filament_g, 2) if filament_g is not None else None,
            "cost_usd": cost_usd,
        }
        warnings = slice_status.get("warnings", [])

        time_str = format_duration(time_s) if time_s else "n/a"
        fil_str = f"{filament_g:.1f}g" if filament_g is not None else "n/a"
        cost_str = f"${cost_usd:.2f}" if cost_usd is not None else "n/a"
        self._log(f"  Result: print_time={time_str}, filament={fil_str}, cost={cost_str} (slice_time={wall_seconds:.1f}s)")

        return {
            "name": v.name,
            "changes": v.changes,
            "gcode_path": v.gcode_filename,
            "stats": stats_dict,
            "warnings": warnings,
            "error": None,
        }, wall_seconds

    def _print_summary_table(self, variant_results: List[Dict[str, Any]], baseline_name: str) -> None:
        """Print a clean Markdown summary table of results."""
        self._log("\n" + "=" * 78)
        self._log("RESULTS SUMMARY")
        self._log("=" * 78)
        header = f"{'Variant':<35} | {'Print Time':<10} | {'Filament':<9} | {'Cost':<7} | {'Status'}"
        self._log(header)
        self._log("-" * len(header))
        for r in variant_results:
            name = r["name"]
            if name == baseline_name:
                name += " (baseline)"
            if len(name) > 34:
                name = name[:31] + "..."

            if r.get("error"):
                self._log(f"{name:<35} | {'-':<10} | {'-':<9} | {'-':<7} | ERROR: {r['error']}")
            else:
                st = r.get("stats") or {}
                t_str = format_duration(st.get("time_s", 0)) if st.get("time_s") else "?"
                f_str = f"{st.get('filament_g', 0):.1f}g" if st.get("filament_g") is not None else "?"
                c_str = f"${st.get('cost_usd', 0):.2f}" if st.get("cost_usd") is not None else "?"
                warn_str = f" ({len(r['warnings'])} warnings)" if r.get("warnings") else ""
                self._log(f"{name:<35} | {t_str:<10} | {f_str:<9} | {c_str:<7} | OK{warn_str}")
        self._log("=" * 78)
