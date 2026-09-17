"""Crash-resilient Matrix Studio v2 orchestration."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .analytics import compute_matrix_comparison, generate_html_report, parse_gcode_filament_by_role
from .run_bundle import RunBundle, RunBundleStore, VariantRecord
from .studio_client import StudioApiError, StudioClient


ProgressCallback = Callable[[RunBundle, Optional[VariantRecord], str, float], None]
EtaCallback = Callable[[float, int, float], bool]


class RunCancelled(RuntimeError):
    pass


class StudioRunner:
    def __init__(
        self,
        client: StudioClient,
        store: RunBundleStore,
        progress: Optional[ProgressCallback] = None,
        poll_interval: float = 0.35,
        slice_timeout: float = 3600.0,
    ):
        self.client = client
        self.store = store
        self.progress = progress
        self.poll_interval = poll_interval
        self.slice_timeout = slice_timeout
        self._cancel = threading.Event()

    def cancel(self) -> None:
        # The runner may live on a worker thread while the UI calls this method
        # directly.  Only signal here; the polling loop owns the HTTP client and
        # sends the cancellation request from that same worker thread.
        self._cancel.set()

    def _emit(self, bundle: RunBundle, variant: Optional[VariantRecord], message: str, value: float) -> None:
        if self.progress:
            self.progress(bundle, variant, message, value)

    def _save(self, bundle: RunBundle, run_dir: Path, state: Optional[str] = None) -> None:
        bundle.touch(state)
        self.store.save(run_dir, bundle)

    def run(
        self,
        bundle: RunBundle,
        run_dir: Path,
        confirm_eta: Optional[EtaCallback] = None,
    ) -> RunBundle:
        if not 2 <= len(bundle.variants) <= int(bundle.settings.get("hard_variant_limit", 32)):
            raise ValueError("A run must contain between 2 and the configured hard limit of variants.")

        self.client.capabilities()
        status = self.client.status()
        objects = self.client.objects()
        config = self.client.config()
        target_keys = sorted({key for variant in bundle.variants for key in variant.changes})
        missing = [key for key in target_keys if key not in config]
        if missing:
            raise StudioApiError(f"Settings are not available in the active profile: {', '.join(missing)}")

        presets = status.get("presets", {})
        filaments = presets.get("filaments", [])
        bundle.source = {
            "app": status.get("app", "OrcaSlicer"),
            "app_version": status.get("app_version") or status.get("version", "unknown"),
            "presets": presets,
            "printer_preset": presets.get("printer", "Default"),
            "print_preset": presets.get("print", "Default"),
            "filament_preset": ", ".join(str(item) for item in filaments) if isinstance(filaments, list) else str(filaments),
            "plate_objects": [item.get("name", "") for item in objects if item.get("name")],
        }
        bundle.baseline_snapshot = {key: config[key] for key in target_keys}
        bundle.restoration = {"required": True, "completed": False, "error": None}
        self._save(bundle, run_dir, "running")

        filament_cost = self._filament_cost(config.get("filament_cost"))
        baseline_wall = 0.0
        terminal_state = "completed"
        try:
            for index, variant in enumerate(bundle.variants):
                if self._cancel.is_set():
                    raise RunCancelled("Run cancelled")
                variant.state = "running"
                self._save(bundle, run_dir)
                self._emit(bundle, variant, f"Slicing {variant.name}", index / len(bundle.variants))
                wall = self._slice_variant(bundle, variant, run_dir, filament_cost)
                self._save(bundle, run_dir)

                if index == 0:
                    baseline_wall = wall
                    if variant.error:
                        raise StudioApiError(f"Baseline slice failed: {variant.error}")
                    remaining = len(bundle.variants) - 1
                    estimate = max(0.0, baseline_wall + 1.5) * remaining
                    if remaining and confirm_eta and not confirm_eta(baseline_wall, remaining, estimate):
                        raise RunCancelled("Run stopped after baseline")
        except RunCancelled:
            terminal_state = "cancelled"
        except Exception as exc:
            terminal_state = "interrupted"
            bundle.comparison["run_error"] = str(exc)
        finally:
            try:
                if bundle.baseline_snapshot:
                    result = self.client.apply_config(bundle.baseline_snapshot)
                    errors = result.get("errors") if isinstance(result, dict) else None
                    if errors:
                        raise StudioApiError(str(errors))
                bundle.restoration = {"required": False, "completed": True, "error": None}
            except Exception as exc:
                bundle.restoration = {"required": True, "completed": False, "error": str(exc)}
                terminal_state = "recovery_required"

        run_error = bundle.comparison.get("run_error")
        analytics_variants = [self._variant_for_analytics(item) for item in bundle.variants]
        completed = [item for item in analytics_variants if not item.get("error") and (item.get("stats") or {}).get("time_s") is not None]
        if completed:
            bundle.comparison = compute_matrix_comparison(analytics_variants, completed[0]["name"])
            if run_error:
                bundle.comparison["run_error"] = run_error
        self._save(bundle, run_dir, terminal_state)
        if completed:
            try:
                html_path = generate_html_report(bundle.to_dict(), bundle.comparison, Path(run_dir) / "report.html")
                markdown = "\n\n".join(
                    part for part in (
                        bundle.comparison.get("summary_markdown", ""),
                        bundle.comparison.get("line_type_markdown", ""),
                    ) if part
                )
                markdown_path = Path(run_dir) / "report.md"
                markdown_path.write_text(markdown + "\n", encoding="utf-8")
                bundle.comparison["html_report"] = str(html_path.relative_to(run_dir)).replace("\\", "/")
                bundle.comparison["markdown_report"] = str(markdown_path.relative_to(run_dir)).replace("\\", "/")
            except Exception as exc:
                bundle.comparison["report_error"] = str(exc)
            self._save(bundle, run_dir)
        self._emit(bundle, None, terminal_state.replace("_", " ").title(), 1.0)
        return bundle

    def _slice_variant(
        self,
        bundle: RunBundle,
        variant: VariantRecord,
        run_dir: Path,
        filament_cost: float,
    ) -> float:
        started = time.monotonic()
        try:
            self.client.apply_config(bundle.baseline_snapshot)
            applied = self.client.apply_config(variant.changes)
            if applied.get("errors"):
                raise StudioApiError(str(applied["errors"]))
            self.client.start_slice()
            result = self._wait_for_slice()
            if result.get("state") != "done":
                raise StudioApiError(result.get("message") or f"Slice ended as {result.get('state')}")
            payload = self.client.gcode()
            gcode_dir = Path(run_dir) / "gcode"
            gcode_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{variant.ordinal:02d}-{variant.id[:8]}.gcode"
            path = gcode_dir / filename
            path.write_bytes(payload)
            stats = result.get("stats", {})
            mass = stats.get("filament_used_g")
            variant.gcode_path = str(path.relative_to(run_dir)).replace("\\", "/")
            variant.stats = {
                "time_s": stats.get("estimated_time_seconds"),
                "filament_g": mass,
                "cost_usd": round(float(mass) * filament_cost / 1000.0, 2) if mass is not None else None,
                "filament_by_role": parse_gcode_filament_by_role(path, fallback_mass_g=mass),
            }
            variant.warnings = list(result.get("warnings", []))
            variant.state = "completed"
        except RunCancelled:
            raise
        except Exception as exc:
            variant.state = "failed"
            variant.error = str(exc)
        variant.slice_wall_seconds = time.monotonic() - started
        return variant.slice_wall_seconds

    def _wait_for_slice(self) -> Dict[str, Any]:
        deadline = time.monotonic() + self.slice_timeout
        while time.monotonic() < deadline:
            if self._cancel.is_set():
                self.client.cancel_slice()
                raise RunCancelled("Run cancelled")
            status = self.client.slice_status()
            state = status.get("state")
            if state in {"done", "error"}:
                return status
            time.sleep(self.poll_interval)
        self.client.cancel_slice()
        raise StudioApiError("Slice timed out")

    @staticmethod
    def _filament_cost(raw: Any) -> float:
        try:
            return float(str(raw).split(",", 1)[0])
        except (TypeError, ValueError):
            return 25.0

    @staticmethod
    def _variant_for_analytics(item: VariantRecord) -> Dict[str, Any]:
        return {
            "name": item.name,
            "changes": item.changes,
            "gcode_path": item.gcode_path,
            "stats": item.stats,
            "warnings": item.warnings,
            "error": item.error,
        }
