"""OrcaSlicer Matrix Tool - Modern Desktop Graphical User Interface.

Provides an interactive, modern GUI to configure up to 3 matrix dimensions,
select from comprehensive OrcaSlicer Process Tab settings, inspect real-time
permutation counts, run matrix slices, and launch the compare viewer.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import re
import shutil
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .catalog import DimensionCatalog, DimensionDefinition, PresetValue, get_default_catalog
from .client import OrcaAuthError, OrcaClient, OrcaConnectionError, OrcaError
from .matrix import (
    MAX_DIMENSIONS,
    MAX_VARIANTS,
    DimensionLimitExceededError,
    Variant,
    VariantLimitExceededError,
    build_variants,
)
from .runner import MatrixRunner, format_duration
from .cli import KNOWN_VIEWER_LOCATIONS, find_viewer_executable, launch_compare_viewer
from .analytics import ROLE_COLORS, format_clean_variant_name, format_compact_label, get_role_color


# User Settings Persistence (~/.orcaslicer_matrix/settings.json)
SETTINGS_DIR = Path.home() / ".orcaslicer_matrix"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


def load_user_settings() -> Dict[str, Any]:
    """Load persistent user settings (such as viewer executable path)."""
    try:
        if SETTINGS_FILE.is_file():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_user_settings(settings: Dict[str, Any]) -> None:
    """Save persistent user settings."""
    try:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        current = load_user_settings()
        current.update(settings)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
    except Exception:
        pass


# Enable DPI awareness on Windows if available
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass


class DimensionCard(ttk.Frame):
    """UI Card for a single matrix dimension (Axis)."""

    def __init__(
        self,
        master: tk.Widget,
        index: int,
        catalog: DimensionCatalog,
        on_change_callback: Any,
        on_remove_callback: Any,
    ):
        super().__init__(master, padding="10", style="Card.TFrame")
        self.index = index
        self.catalog = catalog
        self.on_change_callback = on_change_callback
        self.on_remove_callback = on_remove_callback

        self.current_dim: Optional[DimensionDefinition] = None
        self._current_key: Optional[str] = None
        self.selected_values: List[str] = []
        self._category_dims: List[DimensionDefinition] = []

        self._build_ui()

    def _build_ui(self) -> None:
        # Header Row: Dimension Badge + Remove Button
        header_frame = ttk.Frame(self, style="CardHeader.TFrame")
        header_frame.pack(fill="x", pady=(0, 6))

        axis_letter = chr(65 + self.index)
        self.title_lbl = ttk.Label(
            header_frame,
            text=f"Dimension #{self.index + 1}  •  Axis {axis_letter}",
            font=("Segoe UI", 10, "bold"),
            foreground="#1e293b",
        )
        self.title_lbl.pack(side="left")

        self.summary_badge = ttk.Label(
            header_frame,
            text="",
            font=("Segoe UI", 8, "bold"),
            foreground="#475569",
        )
        self.summary_badge.pack(side="left", padx=(10, 0))

        self.remove_btn = ttk.Button(
            header_frame,
            text="✕ Remove",
            width=10,
            command=lambda: self.on_remove_callback(self),
        )
        self.remove_btn.pack(side="right")

        # Category & Live Filter Row
        cat_filter_row = ttk.Frame(self)
        cat_filter_row.pack(fill="x", pady=(2, 4))

        ttk.Label(cat_filter_row, text="Process Tab:", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.cat_var = tk.StringVar()
        categories = self.catalog.get_categories()
        self.cat_combo = ttk.Combobox(
            cat_filter_row,
            textvariable=self.cat_var,
            values=categories,
            state="readonly",
            width=26,
        )
        self.cat_combo.set(categories[0] if categories else "")
        self.cat_combo.pack(side="left", padx=(0, 12))
        self.cat_combo.bind("<<ComboboxSelected>>", self._on_category_changed)

        ttk.Label(cat_filter_row, text="🔍 Filter:", font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        self.filter_var = tk.StringVar()
        self.filter_entry = ttk.Entry(cat_filter_row, textvariable=self.filter_var, width=18)
        self.filter_entry.pack(side="left", fill="x", expand=True)
        self.filter_entry.bind("<KeyRelease>", self._on_filter_changed)

        # Setting Selector Row
        setting_row = ttk.Frame(self)
        setting_row.pack(fill="x", pady=(2, 4))

        ttk.Label(setting_row, text="Setting:", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.dim_var = tk.StringVar()
        self.dim_combo = ttk.Combobox(
            setting_row,
            textvariable=self.dim_var,
            state="readonly",
        )
        self.dim_combo.pack(side="left", fill="x", expand=True)
        self.dim_combo.bind("<<ComboboxSelected>>", self._on_dimension_changed)

        # Setting Description / Tooltip Info Box
        self.desc_frame = ttk.Frame(self, padding="6", relief="solid", borderwidth=1)
        self.desc_frame.pack(fill="x", pady=(4, 6))

        self.meta_lbl = ttk.Label(
            self.desc_frame,
            text="",
            font=("Segoe UI", 8, "bold"),
            foreground="#2563eb",
        )
        self.meta_lbl.pack(anchor="w")

        self.desc_lbl = ttk.Label(
            self.desc_frame,
            text="",
            wraplength=620,
            font=("Segoe UI", 8),
            foreground="#334155",
        )
        self.desc_lbl.pack(anchor="w", pady=(2, 0))

        # Preset Quick-Add Chips Area
        self.presets_frame = ttk.Frame(self)
        self.presets_frame.pack(fill="x", pady=(2, 4))

        self.presets_title_lbl = ttk.Label(
            self.presets_frame,
            text="Quick-Add Presets (click to toggle):",
            font=("Segoe UI", 8, "bold"),
            foreground="#475569",
        )
        self.presets_title_lbl.pack(anchor="w", pady=(0, 2))

        self.presets_chips_box = ttk.Frame(self.presets_frame)
        self.presets_chips_box.pack(fill="x")

        # Active Selected Values Display & Add Row
        val_action_row = ttk.Frame(self)
        val_action_row.pack(fill="x", pady=(6, 2))

        ttk.Label(val_action_row, text="Active Values:", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))

        self.custom_val_var = tk.StringVar()
        self.custom_val_entry = ttk.Entry(val_action_row, textvariable=self.custom_val_var, width=18)
        self.custom_val_entry.pack(side="right", padx=(4, 0))
        self.custom_val_entry.bind("<Return>", lambda e: self._add_custom_value())

        self.add_val_btn = ttk.Button(val_action_row, text="+ Add Value", width=11, command=self._add_custom_value)
        self.add_val_btn.pack(side="right")

        self.values_container = ttk.Frame(self)
        self.values_container.pack(fill="x", pady=(2, 2))

        # Initial populate
        self._populate_dimensions_for_category()

    def _on_filter_changed(self, event: Any = None) -> None:
        self._populate_dimensions_for_category(preserve_selection=False)

    def _on_category_changed(self, event: Any = None) -> None:
        self.filter_var.set("")
        self._populate_dimensions_for_category(preserve_selection=False)

    def _populate_dimensions_for_category(self, preserve_selection: bool = True) -> None:
        cat = self.cat_var.get()
        dims = self.catalog.get_dimensions_for_category(cat)
        q = self.filter_var.get().strip().lower()
        if q:
            dims = [
                d for d in dims
                if q in d.key.lower() or q in d.label.lower() or (d.tooltip and q in d.tooltip.lower())
            ]

        self._category_dims = dims
        display_names = [d.full_display_name for d in dims]
        self.dim_combo["values"] = display_names

        if display_names:
            # Check if current selection is still valid in filtered list
            current_key = self.current_dim.key if self.current_dim else None
            match_idx = -1
            if preserve_selection and current_key:
                for idx, d in enumerate(dims):
                    if d.key == current_key:
                        match_idx = idx
                        break

            if match_idx >= 0:
                self.dim_combo.current(match_idx)
            else:
                self.dim_combo.current(0)
                self._on_dimension_changed()
        else:
            self.current_dim = None
            self._current_key = None
            self.dim_var.set("(No settings match filter)")
            self.meta_lbl.config(text="")
            self.desc_lbl.config(text="")
            self.summary_badge.config(text="")
            self._refresh_presets_ui()

    def _on_dimension_changed(self, event: Any = None) -> None:
        idx = self.dim_combo.current()
        if 0 <= idx < len(self._category_dims):
            self.current_dim = self._category_dims[idx]
            new_key = self.current_dim.key

            # Update Metadata and Description text
            meta_parts = [f"Key: {self.current_dim.key}", f"Type: {self.current_dim.type}"]
            if self.current_dim.unit:
                meta_parts.append(f"Unit: {self.current_dim.unit}")
            if self.current_dim.default_val is not None:
                meta_parts.append(f"Default: {self.current_dim.default_val}")
            self.meta_lbl.config(text="  •  ".join(meta_parts))

            desc_text = self.current_dim.tooltip.strip() if self.current_dim.tooltip else "(No tooltip provided in schema)"
            self.desc_lbl.config(text=desc_text)
            self.summary_badge.config(text=f"[{self.current_dim.category}]")

            # CRITICAL: If the setting key has changed, reset previously selected values
            # and auto-select sensible presets for the NEW setting.
            if new_key != self._current_key:
                self._current_key = new_key
                if self.current_dim.presets:
                    # Pick up to first 2 presets of the new setting
                    first_presets = [p.value for p in self.current_dim.presets[:2]]
                    self.selected_values = list(dict.fromkeys(first_presets))
                else:
                    self.selected_values = []

            self._refresh_presets_ui()
            self._render_selected_values()
            self.on_change_callback()

    def _refresh_presets_ui(self) -> None:
        for w in self.presets_chips_box.winfo_children():
            w.destroy()

        if not self.current_dim or not self.current_dim.presets:
            self.presets_title_lbl.pack_forget()
            return

        self.presets_title_lbl.pack(anchor="w", pady=(0, 2))
        for p in self.current_dim.presets:
            is_active = p.value in self.selected_values
            prefix = "✓ " if is_active else ""
            btn_text = f"{prefix}{p.display_name()}"

            btn = ttk.Button(
                self.presets_chips_box,
                text=btn_text,
                command=lambda val=p.value: self._toggle_preset_value(val),
            )
            btn.pack(side="left", padx=2, pady=1)

    def _toggle_preset_value(self, val: str) -> None:
        val = str(val).strip()
        if not val:
            return
        if val in self.selected_values:
            self.selected_values.remove(val)
        else:
            self.selected_values.append(val)
        self._refresh_presets_ui()
        self._render_selected_values()
        self.on_change_callback()

    def _add_custom_value(self) -> None:
        raw = self.custom_val_var.get().strip()
        if not raw:
            return
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        for p in parts:
            if p not in self.selected_values:
                self.selected_values.append(p)
        self.custom_val_var.set("")
        self._refresh_presets_ui()
        self._render_selected_values()
        self.on_change_callback()

    def _remove_value(self, val: str) -> None:
        if val in self.selected_values:
            self.selected_values.remove(val)
            self._refresh_presets_ui()
            self._render_selected_values()
            self.on_change_callback()

    def _render_selected_values(self) -> None:
        for w in self.values_container.winfo_children():
            w.destroy()

        if not self.selected_values:
            ttk.Label(
                self.values_container,
                text="(No values selected — click a preset above or enter a custom value)",
                font=("Segoe UI", 8, "italic"),
                foreground="#64748b",
            ).pack(side="left")
            return

        for val in self.selected_values:
            chip = ttk.Frame(self.values_container, padding=(6, 2), style="Chip.TFrame")
            chip.pack(side="left", padx=3, pady=2)
            ttk.Label(chip, text=val, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(2, 4))
            del_btn = ttk.Label(chip, text="✕", foreground="#dc2626", cursor="hand2", font=("Segoe UI", 9, "bold"))
            del_btn.pack(side="right", padx=(0, 2))
            del_btn.bind("<Button-1>", lambda e, v=val: self._remove_value(v))

    def get_axis_config(self) -> Optional[tuple[str, List[str]]]:
        if not self.current_dim or not self.selected_values:
            return None
        return self.current_dim.key, list(self.selected_values)

    def set_dimension_by_key(self, key: str, values: List[str]) -> bool:
        dim = self.catalog.get_dimension(key)
        if not dim:
            return False

        self.cat_var.set(dim.category)
        self.filter_var.set("")
        self._populate_dimensions_for_category(preserve_selection=False)

        # Match dimension in combo
        for i, d in enumerate(self._category_dims):
            if d.key == dim.key:
                self.dim_combo.current(i)
                self.current_dim = d
                self._current_key = d.key
                break

        self.selected_values = [str(v) for v in values]

        meta_parts = [f"Key: {dim.key}", f"Type: {dim.type}"]
        if dim.unit:
            meta_parts.append(f"Unit: {dim.unit}")
        self.meta_lbl.config(text="  •  ".join(meta_parts))
        self.desc_lbl.config(text=dim.tooltip or "(No tooltip provided in schema)")
        self.summary_badge.config(text=f"[{dim.category}]")

        self._refresh_presets_ui()
        self._render_selected_values()
        self.on_change_callback()
        return True


class SubsetSelectionDialog(tk.Toplevel):
    """Modal dialog allowing user to pick a subset of sliced variants/files to open in compare viewer."""

    def __init__(
        self,
        parent: tk.Tk,
        variants: List[Dict[str, Any]],
        on_confirm: Callable[[List[Dict[str, Any]]], None],
        initial_selected_names: Optional[Set[str]] = None,
    ):
        super().__init__(parent)
        self.title("Select Variants to Compare")
        self.geometry("540x440")
        self.minsize(460, 320)
        self.transient(parent)
        self.grab_set()

        self.variants = variants
        self.on_confirm = on_confirm

        self._build_ui(initial_selected_names or set())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())

    def _build_ui(self, initial_selected: Set[str]) -> None:
        main_frame = ttk.Frame(self, padding="14")
        main_frame.pack(fill="both", expand=True)

        ttk.Label(
            main_frame,
            text="Select Files for Compare Viewer",
            font=("Segoe UI", 12, "bold"),
            foreground="#0f172a",
        ).pack(anchor="w", pady=(0, 2))

        ttk.Label(
            main_frame,
            text="Choose which sliced files to open side-by-side (1 to 8 variants):",
            font=("Segoe UI", 9),
            foreground="#64748b",
        ).pack(anchor="w", pady=(0, 8))

        # Action row: live counter and Select All / Clear All
        action_row = ttk.Frame(main_frame)
        action_row.pack(fill="x", pady=(0, 6))

        self.count_lbl = ttk.Label(action_row, text="Selected: 0", font=("Segoe UI", 9, "bold"))
        self.count_lbl.pack(side="left")

        ttk.Button(action_row, text="Select All", width=10, command=self._select_all).pack(side="right", padx=(4, 0))
        ttk.Button(action_row, text="Clear All", width=10, command=self._clear_all).pack(side="right")

        # Scrollable checklist frame
        list_container = ttk.Frame(main_frame, relief="solid", borderwidth=1)
        list_container.pack(fill="both", expand=True, pady=(0, 10))

        canvas = tk.Canvas(list_container, highlightthickness=0, bg="#ffffff")
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollable_frame = ttk.Frame(canvas, padding="6")
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def _on_canvas_configure(event: Any) -> None:
            canvas.itemconfig(canvas_window, width=event.width)

        def _on_frame_configure(event: Any) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        canvas.bind("<Configure>", _on_canvas_configure)
        scrollable_frame.bind("<Configure>", _on_frame_configure)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.checkbox_vars: List[Tuple[Dict[str, Any], tk.BooleanVar]] = []

        for v in self.variants:
            var_name = v.get("name", "Unknown")
            gcode_file = v.get("gcode_path") or "no gcode"
            stats = v.get("stats") or {}
            stats_parts = []
            if stats.get("time_s"):
                stats_parts.append(format_duration(stats["time_s"]))
            if stats.get("filament_g") is not None:
                stats_parts.append(f"{stats['filament_g']:.1f}g")
            if stats.get("cost_usd") is not None:
                stats_parts.append(f"${stats['cost_usd']:.2f}")

            stats_str = f"  [{' • '.join(stats_parts)}]" if stats_parts else ""
            clean_name = format_clean_variant_name(var_name)
            label_text = f"{clean_name}  •  {gcode_file}{stats_str}"

            is_checked = True if not initial_selected else (
                var_name in initial_selected
                or gcode_file in initial_selected
                or clean_name in initial_selected
                or Path(gcode_file).name in initial_selected
            )
            bvar = tk.BooleanVar(value=is_checked)
            bvar.trace_add("write", lambda *args: self._update_count())

            chk = ttk.Checkbutton(
                scrollable_frame,
                text=label_text,
                variable=bvar,
            )
            chk.pack(anchor="w", pady=3, padx=4)
            self.checkbox_vars.append((v, bvar))

        # Bottom Button Row
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x")

        self.launch_btn = ttk.Button(
            btn_frame,
            text="🔍 Open in Compare Viewer",
            style="Primary.TButton",
            command=self._on_launch,
        )
        self.launch_btn.pack(side="right", padx=(6, 0))

        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="right")

        self._update_count()

    def _update_count(self) -> None:
        count = sum(1 for _, bvar in self.checkbox_vars if bvar.get())
        total = len(self.checkbox_vars)
        self.count_lbl.config(text=f"Selected: {count} of {total}")
        if count == 0:
            self.launch_btn.config(state="disabled", text="Select at least 1 variant")
        elif count > 8:
            self.launch_btn.config(state="disabled", text=f"Max 8 variants (selected: {count})")
        else:
            self.launch_btn.config(state="normal", text=f"🔍 Open in Compare Viewer ({count})")

    def _select_all(self) -> None:
        for _, bvar in self.checkbox_vars:
            bvar.set(True)

    def _clear_all(self) -> None:
        for _, bvar in self.checkbox_vars:
            bvar.set(False)

    def _on_launch(self) -> None:
        selected = [v for v, bvar in self.checkbox_vars if bvar.get()]
        if not selected:
            return
        self.destroy()
        if self.on_confirm:
            self.on_confirm(selected)


class OrcaMatrixApp(tk.Tk):
    """Main OrcaSlicer Matrix Tool Application Window."""

    def __init__(self, client: Optional[OrcaClient] = None, auto_connect: bool = True):
        super().__init__()

        self._is_destroyed = False
        self.title("OrcaSlicer Matrix Slicer & Comparison Tool")
        self.geometry("1100x880")
        self.minsize(980, 720)

        # Style configuration
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self._configure_styles()

        self.catalog = get_default_catalog()
        self.client: Optional[OrcaClient] = client
        self.active_dimension_cards: List[DimensionCard] = []

        self.is_running = False
        self.runner_thread: Optional[threading.Thread] = None
        self._last_comparison: Optional[Dict[str, Any]] = None
        self._last_manifest_path: Optional[Path] = None
        self._last_html_report: Optional[Path] = None
        self._compare_sel_buttons: List[ttk.Button] = []

        self._build_main_ui()

        # Connect to OrcaSlicer in background if requested
        if auto_connect:
            self.after(100, self._check_connection_async)

    def destroy(self) -> None:
        """Cleanly mark application as destroyed and cleanup."""
        self._is_destroyed = True
        try:
            super().destroy()
        except Exception:
            pass

    def _configure_styles(self) -> None:
        self.style.configure(".", font=("Segoe UI", 9))
        self.style.configure("Header.TLabel", font=("Segoe UI", 15, "bold"), foreground="#0f172a")
        self.style.configure("SubHeader.TLabel", font=("Segoe UI", 9), foreground="#64748b")
        self.style.configure("Card.TFrame", relief="solid", borderwidth=1)
        self.style.configure("CardHeader.TFrame", background="#f8fafc")
        self.style.configure("Chip.TFrame", relief="solid", borderwidth=1)
        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"))
        self.style.configure("StatusConnected.TLabel", foreground="#16a34a", font=("Segoe UI", 9, "bold"))
        self.style.configure("StatusDisconnected.TLabel", foreground="#dc2626", font=("Segoe UI", 9, "bold"))
        self.style.configure("RecBanner.TFrame", background="#0369a1", relief="solid", borderwidth=1)
        self.style.configure("RecTitle.TLabel", font=("Segoe UI", 9, "bold"), foreground="#e0f2fe", background="#0369a1")
        self.style.configure("RecDesc.TLabel", font=("Segoe UI", 8), foreground="#bae6fd", background="#0369a1")

    def _build_main_ui(self) -> None:
        # Top Header Bar: Title, Subtitle, and Connection Status Card
        top_frame = ttk.Frame(self, padding="14")
        top_frame.pack(fill="x")

        title_box = ttk.Frame(top_frame)
        title_box.pack(side="left", fill="y")
        ttk.Label(title_box, text="OrcaSlicer Matrix Tool", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            title_box,
            text="Multi-dimensional slicer matrix & visual compare generator  •  Max 3 Dimensions, Max 8 Permutations",
            style="SubHeader.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        # Connection Status Box
        conn_box = ttk.Frame(top_frame, padding="8", relief="solid", borderwidth=1)
        conn_box.pack(side="right", fill="y")

        self.conn_dot_lbl = ttk.Label(conn_box, text="● Checking connection...", style="SubHeader.TLabel")
        self.conn_dot_lbl.pack(anchor="e")

        self.plater_info_lbl = ttk.Label(
            conn_box,
            text="Plater: Connecting to 127.0.0.1:13130...",
            font=("Segoe UI", 8),
            foreground="#475569",
        )
        self.plater_info_lbl.pack(anchor="e")

        btn_row = ttk.Frame(conn_box)
        btn_row.pack(anchor="e", pady=(3, 0))
        self.refresh_btn = ttk.Button(btn_row, text="🔄 Refresh Plater", width=15, command=self._check_connection_async)
        self.refresh_btn.pack(side="right")

        # Main Paned / Split Layout: Left is Matrix Builder, Right is Permutations & Run
        main_split = ttk.PanedWindow(self, orient="horizontal")
        main_split.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        # LEFT PANE: Matrix Dimensions Builder
        left_frame = ttk.Frame(main_split, padding="4")
        main_split.add(left_frame, weight=3)

        dim_header = ttk.Frame(left_frame)
        dim_header.pack(fill="x", pady=(0, 6))

        self.dim_count_badge = ttk.Label(
            dim_header,
            text="Matrix Dimensions (0 / 3 active)",
            font=("Segoe UI", 11, "bold"),
            foreground="#0f172a",
        )
        self.dim_count_badge.pack(side="left")

        self.add_dim_btn = ttk.Button(
            dim_header,
            text="+ Add Dimension",
            command=self._add_dimension,
        )
        self.add_dim_btn.pack(side="right")

        # Scrollable container for up to 3 Dimension Cards
        scroll_outer = ttk.Frame(left_frame)
        scroll_outer.pack(fill="both", expand=True)

        self.dim_scroll_canvas = tk.Canvas(scroll_outer, highlightthickness=0)
        self.dim_scrollbar = ttk.Scrollbar(scroll_outer, orient="vertical", command=self.dim_scroll_canvas.yview)
        self.dim_cards_box = ttk.Frame(self.dim_scroll_canvas)

        # Dynamic canvas window matching canvas width on resize
        self.dim_cards_window = self.dim_scroll_canvas.create_window(
            (0, 0),
            window=self.dim_cards_box,
            anchor="nw",
        )

        def _on_canvas_configure(event: Any) -> None:
            # Dynamically stretch the card container to full width minus scrollbar padding
            self.dim_scroll_canvas.itemconfig(self.dim_cards_window, width=event.width)

        def _on_frame_configure(event: Any) -> None:
            self.dim_scroll_canvas.configure(scrollregion=self.dim_scroll_canvas.bbox("all"))

        def _on_mousewheel(event: Any) -> None:
            if not self._is_destroyed and self.dim_scroll_canvas.winfo_exists():
                self.dim_scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self.dim_scroll_canvas.bind("<Configure>", _on_canvas_configure)
        self.dim_cards_box.bind("<Configure>", _on_frame_configure)
        self.dim_scroll_canvas.bind("<MouseWheel>", _on_mousewheel)
        self.dim_cards_box.bind("<MouseWheel>", _on_mousewheel)

        self.dim_scroll_canvas.configure(yscrollcommand=self.dim_scrollbar.set)
        self.dim_scroll_canvas.pack(side="left", fill="both", expand=True)
        self.dim_scrollbar.pack(side="right", fill="y")

        # RIGHT PANE: Permutations Preview & Execution Panel
        right_frame = ttk.Frame(main_split, padding="4")
        main_split.add(right_frame, weight=2)

        # Permutation Status Banner Card
        self.perm_banner = ttk.Frame(right_frame, padding="10", relief="solid", borderwidth=1)
        self.perm_banner.pack(fill="x", pady=(0, 8))

        self.perm_formula_lbl = ttk.Label(
            self.perm_banner,
            text="Formula: 0 variants",
            font=("Segoe UI", 10, "bold"),
            foreground="#1e293b",
        )
        self.perm_formula_lbl.pack(anchor="w")

        self.perm_status_lbl = ttk.Label(
            self.perm_banner,
            text="Status: Please add at least one dimension.",
            font=("Segoe UI", 9, "bold"),
            foreground="#64748b",
        )
        self.perm_status_lbl.pack(anchor="w", pady=(3, 0))

        self.perm_suggestions_lbl = ttk.Label(
            self.perm_banner,
            text="",
            wraplength=380,
            font=("Segoe UI", 8),
            foreground="#dc2626",
        )
        self.perm_suggestions_lbl.pack(anchor="w", pady=(3, 0))

        # Results & Analytics Notebook
        self.results_notebook = ttk.Notebook(right_frame)
        self.results_notebook.pack(fill="x", pady=(0, 8))

        # --- TAB 0: Variants Preview (Pre-slice) ---
        self.tab_preview = ttk.Frame(self.results_notebook, padding="4")
        self.results_notebook.add(self.tab_preview, text="Variants Preview")

        self.perm_tree_frame = ttk.Frame(self.tab_preview)
        self.perm_tree_frame.pack(fill="both", expand=True)

        columns = ("index", "name", "gcode")
        self.perm_tree = ttk.Treeview(self.perm_tree_frame, columns=columns, show="headings", height=7)
        self.perm_tree.heading("index", text="#")
        self.perm_tree.heading("name", text="Variant Name")
        self.perm_tree.heading("gcode", text="G-code File")
        self.perm_tree.column("index", width=38, stretch=False, anchor="center")
        self.perm_tree.column("name", width=250, stretch=True, anchor="w")
        self.perm_tree.column("gcode", width=160, stretch=False, anchor="w")

        perm_vscroll = ttk.Scrollbar(self.perm_tree_frame, orient="vertical", command=self.perm_tree.yview)
        self.perm_tree.configure(yscrollcommand=perm_vscroll.set)
        self.perm_tree.grid(row=0, column=0, sticky="nsew")
        perm_vscroll.grid(row=0, column=1, sticky="ns")
        self.perm_tree_frame.rowconfigure(0, weight=1)
        self.perm_tree_frame.columnconfigure(0, weight=1)
        self._make_treeview_sortable(self.perm_tree)

        prev_btn_row = ttk.Frame(self.tab_preview)
        prev_btn_row.pack(fill="x", pady=(4, 0))
        self.preview_open_all_btn = ttk.Button(
            prev_btn_row,
            text="🔍 Open All in Viewer",
            command=lambda: self._open_compare_viewer(selected_only=False),
        )
        self.preview_open_all_btn.pack(side="left", padx=(0, 4))
        self.preview_open_sel_btn = ttk.Button(
            prev_btn_row,
            text="🔍 Open Selected in Viewer...",
            command=lambda: self._open_compare_viewer(selected_only=True),
        )
        self.preview_open_sel_btn.pack(side="left", padx=(0, 4))
        self.preview_sel_hint_lbl = ttk.Label(
            prev_btn_row,
            text="Tip: Ctrl+Click or Shift+Click rows to select a subset",
            font=("Segoe UI", 8),
            foreground="#64748b",
        )
        self.preview_sel_hint_lbl.pack(side="left", padx=(4, 0))

        # --- TAB 1: Summary & Deltas (Image 1) ---
        self.tab_summary = ttk.Frame(self.results_notebook, padding="4")
        self.results_notebook.add(self.tab_summary, text="Summary & Deltas")

        self.rec_banner_frame = ttk.Frame(self.tab_summary, padding="6", style="RecBanner.TFrame")
        self.rec_banner_frame.pack(fill="x", pady=(0, 4))
        self.rec_banner_title = ttk.Label(self.rec_banner_frame, text="★ Recommended Choice: None", style="RecTitle.TLabel")
        self.rec_banner_title.pack(anchor="w")
        self.rec_banner_desc = ttk.Label(self.rec_banner_frame, text="Run slices to compute optimal trade-offs and recommendations.", style="RecDesc.TLabel")
        self.rec_banner_desc.pack(anchor="w")

        self.sum_tree_frame = ttk.Frame(self.tab_summary)
        self.sum_tree_frame.pack(fill="both", expand=True, pady=(2, 4))

        sum_cols = ("variant", "time", "filament", "cost", "delta")
        self.summary_tree = ttk.Treeview(self.sum_tree_frame, columns=sum_cols, show="headings", height=6)
        self.summary_tree.heading("variant", text="Variant")
        self.summary_tree.heading("time", text="Print Time")
        self.summary_tree.heading("filament", text="Filament")
        self.summary_tree.heading("cost", text="Cost")
        self.summary_tree.heading("delta", text="vs Baseline")
        self.summary_tree.column("variant", width=200, minwidth=150, stretch=True, anchor="w")
        self.summary_tree.column("time", width=85, minwidth=70, stretch=False, anchor="center")
        self.summary_tree.column("filament", width=85, minwidth=70, stretch=False, anchor="center")
        self.summary_tree.column("cost", width=65, minwidth=55, stretch=False, anchor="center")
        self.summary_tree.column("delta", width=110, minwidth=95, stretch=False, anchor="center")

        sum_vscroll = ttk.Scrollbar(self.sum_tree_frame, orient="vertical", command=self.summary_tree.yview)
        sum_hscroll = ttk.Scrollbar(self.sum_tree_frame, orient="horizontal", command=self.summary_tree.xview)
        self.summary_tree.configure(yscrollcommand=sum_vscroll.set, xscrollcommand=sum_hscroll.set)
        self.summary_tree.grid(row=0, column=0, sticky="nsew")
        sum_vscroll.grid(row=0, column=1, sticky="ns")
        sum_hscroll.grid(row=1, column=0, sticky="ew")
        self.sum_tree_frame.rowconfigure(0, weight=1)
        self.sum_tree_frame.columnconfigure(0, weight=1)
        self._make_treeview_sortable(self.summary_tree)

        sum_btn_row = ttk.Frame(self.tab_summary)
        sum_btn_row.pack(fill="x")
        self.copy_summary_btn = ttk.Button(sum_btn_row, text="📋 Copy Summary Markdown", command=self._copy_summary_markdown)
        self.copy_summary_btn.pack(side="left", padx=(0, 4))
        self.open_html_btn = ttk.Button(sum_btn_row, text="🌐 Open HTML Report", command=self._open_html_report)
        self.open_html_btn.pack(side="left", padx=(0, 4))
        self.open_viewer_btn = ttk.Button(
            sum_btn_row,
            text="🔍 Open All in Viewer",
            command=lambda: self._open_compare_viewer(selected_only=False),
        )
        self.open_viewer_btn.pack(side="left", padx=(0, 4))
        self.open_sel_viewer_btn = ttk.Button(
            sum_btn_row,
            text="🔍 Open Selected in Viewer...",
            command=lambda: self._open_compare_viewer(selected_only=True),
        )
        self.open_sel_viewer_btn.pack(side="left")

        # --- TAB 2: Filament by Line Type (Image 2) ---
        self.tab_line_types = ttk.Frame(self.results_notebook, padding="4")
        self.results_notebook.add(self.tab_line_types, text="Filament by Line Type")

        self.lt_tree_frame = ttk.Frame(self.tab_line_types)
        self.lt_tree_frame.pack(fill="both", expand=True, pady=(0, 4))

        lt_cols = ("variant", "inner_wall", "outer_wall", "infill", "brim", "total")
        self.line_type_tree = ttk.Treeview(self.lt_tree_frame, columns=lt_cols, show="headings", height=6)
        self.line_type_tree.heading("variant", text="Variant")
        self.line_type_tree.heading("inner_wall", text="Inner wall")
        self.line_type_tree.heading("outer_wall", text="Outer wall")
        self.line_type_tree.heading("infill", text="Infill")
        self.line_type_tree.heading("brim", text="Brim")
        self.line_type_tree.heading("total", text="Total")
        self.line_type_tree.column("variant", width=180, minwidth=140, stretch=True, anchor="w")
        self.line_type_tree.column("inner_wall", width=95, minwidth=75, stretch=False, anchor="center")
        self.line_type_tree.column("outer_wall", width=95, minwidth=75, stretch=False, anchor="center")
        self.line_type_tree.column("infill", width=85, minwidth=70, stretch=False, anchor="center")
        self.line_type_tree.column("brim", width=75, minwidth=60, stretch=False, anchor="center")
        self.line_type_tree.column("total", width=85, minwidth=70, stretch=False, anchor="center")

        lt_vscroll = ttk.Scrollbar(self.lt_tree_frame, orient="vertical", command=self.line_type_tree.yview)
        lt_hscroll = ttk.Scrollbar(self.lt_tree_frame, orient="horizontal", command=self.line_type_tree.xview)
        self.line_type_tree.configure(yscrollcommand=lt_vscroll.set, xscrollcommand=lt_hscroll.set)
        self.line_type_tree.grid(row=0, column=0, sticky="nsew")
        lt_vscroll.grid(row=0, column=1, sticky="ns")
        lt_hscroll.grid(row=1, column=0, sticky="ew")
        self.lt_tree_frame.rowconfigure(0, weight=1)
        self.lt_tree_frame.columnconfigure(0, weight=1)
        self._make_treeview_sortable(self.line_type_tree)

        lt_btn_row = ttk.Frame(self.tab_line_types)
        lt_btn_row.pack(fill="x")
        self.copy_lt_btn = ttk.Button(lt_btn_row, text="📋 Copy Line Types Markdown", command=self._copy_line_types_markdown)
        self.copy_lt_btn.pack(side="left", padx=(0, 4))
        self.lt_open_sel_btn = ttk.Button(
            lt_btn_row,
            text="🔍 Open Selected in Viewer...",
            command=lambda: self._open_compare_viewer(selected_only=True),
        )
        self.lt_open_sel_btn.pack(side="left")

        # Register buttons for dynamic selection count updates
        self._compare_sel_buttons.extend([
            self.preview_open_sel_btn,
            self.open_sel_viewer_btn,
            self.lt_open_sel_btn,
        ])

        # Bind row selection, right-click context menu, and double-click to trees
        for tree in (self.perm_tree, self.summary_tree, self.line_type_tree):
            tree.bind("<<TreeviewSelect>>", lambda e, t=tree: self._on_tree_selection_changed(t))
            tree.bind("<Button-3>", lambda e, t=tree: self._on_tree_right_click(e, t))
            tree.bind("<Double-1>", lambda e, t=tree: self._on_tree_double_click(e, t))

        # --- TAB 3: Visual Charts (Canvas) ---
        self.tab_charts = ttk.Frame(self.results_notebook, padding="4")
        self.results_notebook.add(self.tab_charts, text="Visual Charts")

        chart_controls_row = ttk.Frame(self.tab_charts)
        chart_controls_row.pack(fill="x", pady=(0, 4))
        self.chart_type_var = tk.StringVar(value="stacked")
        ttk.Radiobutton(chart_controls_row, text="Filament Breakdown", variable=self.chart_type_var, value="stacked", command=self._redraw_charts).pack(side="left", padx=(0, 6))
        ttk.Radiobutton(chart_controls_row, text="Pareto Frontier", variable=self.chart_type_var, value="pareto", command=self._redraw_charts).pack(side="left")

        self.compact_labels_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(chart_controls_row, text="Compact Labels", variable=self.compact_labels_var, command=self._redraw_charts).pack(side="right")

        self._chart_hover_items: List[Dict[str, Any]] = []

        self.charts_canvas = tk.Canvas(self.tab_charts, height=230, background="#1e293b", highlightthickness=0)
        self.charts_canvas.pack(fill="both", expand=True)
        self.charts_canvas.bind("<Configure>", lambda e: self._redraw_charts())
        self.charts_canvas.bind("<Motion>", self._on_chart_motion)
        self.charts_canvas.bind("<Leave>", self._on_chart_leave)

        self.chart_hover_lbl = ttk.Label(
            self.tab_charts,
            text="Hover over any bar segment or chart point to inspect detailed metrics.",
            font=("Segoe UI", 8),
            foreground="#94a3b8",
        )
        self.chart_hover_lbl.pack(fill="x", pady=(3, 1))

        # Output & Options Frame
        opts_frame = ttk.LabelFrame(right_frame, text="Execution Options", padding="10")
        opts_frame.pack(fill="x", pady=(0, 8))

        dir_row = ttk.Frame(opts_frame)
        dir_row.pack(fill="x", pady=(0, 4))
        ttk.Label(dir_row, text="Output Dir:").pack(side="left", padx=(0, 4))
        self.output_dir_var = tk.StringVar(value=str(Path("./compare_output").resolve()))
        self.output_dir_entry = ttk.Entry(dir_row, textvariable=self.output_dir_var)
        self.output_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.browse_btn = ttk.Button(dir_row, text="Browse...", width=9, command=self._browse_output_dir)
        self.browse_btn.pack(side="right")

        # ETA Gate & Approval controls
        self.require_approval_var = tk.BooleanVar(value=True)
        self.require_approval_chk = ttk.Checkbutton(
            opts_frame,
            text="Require approval after slicing baseline variant",
            variable=self.require_approval_var,
            command=self._on_approval_toggle,
        )
        self.require_approval_chk.pack(anchor="w", pady=(3, 1))

        auto_skip_row = ttk.Frame(opts_frame)
        auto_skip_row.pack(anchor="w", padx=(20, 0), pady=(1, 2))

        self.auto_skip_var = tk.BooleanVar(value=True)
        self.auto_skip_chk = ttk.Checkbutton(
            auto_skip_row,
            text="Auto-skip approval if total time is under",
            variable=self.auto_skip_var,
            command=self._on_auto_skip_toggle,
        )
        self.auto_skip_chk.pack(side="left")

        self.auto_skip_threshold_var = tk.StringVar(value="30")
        self.auto_skip_entry = ttk.Spinbox(
            auto_skip_row,
            from_=1,
            to=3600,
            width=4,
            textvariable=self.auto_skip_threshold_var,
        )
        self.auto_skip_entry.pack(side="left", padx=(4, 4))

        self.auto_skip_unit_lbl = ttk.Label(auto_skip_row, text="sec")
        self.auto_skip_unit_lbl.pack(side="left")

        self.launch_viewer_var = tk.BooleanVar(value=True)
        self.launch_viewer_chk = ttk.Checkbutton(
            opts_frame,
            text="Launch OrcaSlicer Compare Viewer upon completion",
            variable=self.launch_viewer_var,
            command=self._on_launch_viewer_toggle,
        )
        self.launch_viewer_chk.pack(anchor="w", pady=(3, 1))

        viewer_path_row = ttk.Frame(opts_frame)
        viewer_path_row.pack(fill="x", padx=(20, 0), pady=(1, 2))

        detected_viewers = self._get_detected_viewer_paths()
        initial_viewer = self._get_initial_viewer_path(detected_viewers)
        combo_values = list(detected_viewers)
        if initial_viewer and initial_viewer not in combo_values:
            combo_values.insert(0, initial_viewer)

        self.viewer_path_var = tk.StringVar(value=initial_viewer)
        self.viewer_combo = ttk.Combobox(
            viewer_path_row,
            textvariable=self.viewer_path_var,
            values=combo_values,
            font=("Segoe UI", 8),
        )
        self.viewer_combo.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.viewer_combo.bind("<<ComboboxSelected>>", lambda e: self._on_viewer_path_changed())
        self.viewer_combo.bind("<KeyRelease>", lambda e: self._on_viewer_path_changed())

        self.browse_viewer_btn = ttk.Button(
            viewer_path_row,
            text="Browse...",
            width=9,
            command=self._browse_viewer_exe,
        )
        self.browse_viewer_btn.pack(side="right")

        self.viewer_status_lbl = ttk.Label(opts_frame, font=("Segoe UI", 8))
        self.viewer_status_lbl.pack(anchor="w", padx=(20, 0), pady=(0, 3))
        self._update_viewer_status()

        # Action Buttons
        actions_frame = ttk.Frame(right_frame)
        actions_frame.pack(fill="x", pady=(0, 8))

        self.dry_run_btn = ttk.Button(actions_frame, text="Dry Run (Validate)", command=self._start_dry_run)
        self.dry_run_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.run_btn = ttk.Button(
            actions_frame,
            text="🚀 Run Matrix Slices",
            style="Primary.TButton",
            command=self._start_matrix_run,
        )
        self.run_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # Bottom Frame: Execution Progress & Log Window
        bottom_frame = ttk.LabelFrame(self, text="Execution Progress & Log", padding="10")
        bottom_frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        prog_row = ttk.Frame(bottom_frame)
        prog_row.pack(fill="x", pady=(0, 4))

        self.progress_bar = ttk.Progressbar(prog_row, orient="horizontal", mode="determinate")
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.progress_lbl = ttk.Label(prog_row, text="Ready", font=("Segoe UI", 9, "bold"))
        self.progress_lbl.pack(side="right")

        self.log_text = ScrolledText(bottom_frame, height=8, font=("Consolas", 8), background="#18181b", foreground="#e4e4e7")
        self.log_text.pack(fill="both", expand=True)

        # Configure log tag colors
        self.log_text.tag_config("info", foreground="#60a5fa")
        self.log_text.tag_config("ok", foreground="#34d399")
        self.log_text.tag_config("warn", foreground="#fbbf24")
        self.log_text.tag_config("err", foreground="#f87171")

        # Add 2 default dimensions to start
        self._add_dimension(default_key="layer_height", default_values=["0.16", "0.20"])
        self._add_dimension(default_key="wall_loops", default_values=["2", "3"])

    def _browse_output_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if chosen:
            self.output_dir_var.set(chosen)

    def _on_approval_toggle(self) -> None:
        """Enable or disable sub-controls based on approval requirement."""
        if self.require_approval_var.get():
            self.auto_skip_chk.config(state="normal")
            if self.auto_skip_var.get():
                self.auto_skip_entry.config(state="normal")
            else:
                self.auto_skip_entry.config(state="disabled")
        else:
            self.auto_skip_chk.config(state="disabled")
            self.auto_skip_entry.config(state="disabled")

    def _on_auto_skip_toggle(self) -> None:
        """Enable or disable threshold entry based on auto-skip checkbox."""
        if self.auto_skip_var.get() and self.require_approval_var.get():
            self.auto_skip_entry.config(state="normal")
        else:
            self.auto_skip_entry.config(state="disabled")

    def _get_detected_viewer_paths(self) -> List[str]:
        """Detect existing OrcaSlicer executables on the system."""
        found: List[str] = []
        seen = set()

        for loc in KNOWN_VIEWER_LOCATIONS:
            try:
                p = Path(loc)
                if p.is_file():
                    resolved = str(p.resolve())
                    if resolved.lower() not in seen:
                        seen.add(resolved.lower())
                        found.append(str(p))
            except Exception:
                pass

        for cmd in ["orca-slicer", "OrcaSlicer", "orca_slicer"]:
            try:
                which_path = shutil.which(cmd)
                if which_path and Path(which_path).is_file():
                    resolved = str(Path(which_path).resolve())
                    if resolved.lower() not in seen:
                        seen.add(resolved.lower())
                        found.append(str(which_path))
            except Exception:
                pass

        return found

    def _get_initial_viewer_path(self, detected: List[str]) -> str:
        """Get the initial viewer path from saved settings or detected builds."""
        saved = load_user_settings().get("viewer_path")
        if saved and isinstance(saved, str):
            saved_str = saved.strip()
            if saved_str:
                return saved_str

        if detected:
            return detected[0]
        return ""

    def _browse_viewer_exe(self) -> None:
        """Open a file dialog to locate the OrcaSlicer executable."""
        curr = self.viewer_path_var.get().strip()
        initialdir = str(Path(curr).parent) if curr and Path(curr).parent.is_dir() else None
        chosen = filedialog.askopenfilename(
            title="Select OrcaSlicer Executable",
            initialdir=initialdir,
            filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")],
        )
        if chosen:
            self.viewer_path_var.set(chosen)
            vals = list(self.viewer_combo["values"])
            if chosen not in vals:
                vals.insert(0, chosen)
                self.viewer_combo["values"] = vals
            self._on_viewer_path_changed()

    def _on_viewer_path_changed(self) -> None:
        """Handle change in viewer executable path, update status and save settings."""
        self._update_viewer_status()
        val = self.viewer_path_var.get().strip()
        save_user_settings({"viewer_path": val})

    def _update_viewer_status(self) -> None:
        """Update the validation label below the viewer path entry."""
        raw = self.viewer_path_var.get().strip()
        if not raw:
            self.viewer_status_lbl.config(
                text="⚠ No viewer executable specified (will search default paths)",
                foreground="#f59e0b",
            )
            return

        p = Path(raw)
        if p.is_file():
            parent_display = str(p.parent)
            if len(parent_display) > 40:
                parent_display = "..." + parent_display[-37:]
            self.viewer_status_lbl.config(
                text=f"✓ Ready: {p.name} ({parent_display})",
                foreground="#16a34a",
            )
        else:
            self.viewer_status_lbl.config(
                text=f"⚠ File not found: {raw}",
                foreground="#dc2626",
            )

    def _on_launch_viewer_toggle(self) -> None:
        """Enable or disable viewer configuration controls based on launch toggle."""
        if self.launch_viewer_var.get():
            self.viewer_combo.config(state="normal")
            self.browse_viewer_btn.config(state="normal")
            self.viewer_status_lbl.config(state="normal")
        else:
            self.viewer_combo.config(state="disabled")
            self.browse_viewer_btn.config(state="disabled")
            self.viewer_status_lbl.config(state="disabled")

    def _on_tree_selection_changed(self, tree: ttk.Treeview) -> None:
        """Update compare button labels dynamically based on row selection count."""
        selected_count = len(tree.selection())
        if selected_count > 0:
            btn_text = f"🔍 Open Selected ({selected_count}) in Viewer"
        else:
            btn_text = "🔍 Open Selected in Viewer..."

        for btn in getattr(self, "_compare_sel_buttons", []):
            try:
                if btn.winfo_exists():
                    btn.config(text=btn_text)
            except Exception:
                pass

    def _on_tree_right_click(self, event: Any, tree: ttk.Treeview) -> None:
        """Context menu on right-clicking treeview rows."""
        row_id = tree.identify_row(event.y)
        if row_id:
            if row_id not in tree.selection():
                tree.selection_set(row_id)
                self._on_tree_selection_changed(tree)

        n = len(tree.selection())
        menu = tk.Menu(self, tearoff=0)
        if n > 0:
            menu.add_command(
                label=f"🔍 Open Selected ({n}) in Compare Viewer",
                command=lambda: self._open_compare_viewer(selected_only=True),
            )
        menu.add_command(
            label="🔍 Open All in Compare Viewer",
            command=lambda: self._open_compare_viewer(selected_only=False),
        )
        menu.add_command(
            label="Select Files / Variants to Compare...",
            command=self._show_subset_dialog,
        )
        menu.add_separator()
        menu.add_command(
            label="Select All",
            command=lambda: (tree.selection_set(tree.get_children()), self._on_tree_selection_changed(tree)),
        )
        menu.add_command(
            label="Clear Selection",
            command=lambda: (tree.selection_set(()), self._on_tree_selection_changed(tree)),
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_tree_double_click(self, event: Any, tree: ttk.Treeview) -> None:
        """Double-clicking a row selects it and opens it in compare viewer."""
        row_id = tree.identify_row(event.y)
        if row_id:
            tree.selection_set(row_id)
            self._on_tree_selection_changed(tree)
            self._open_compare_viewer(selected_only=True)

    def _get_selected_variant_names(self) -> List[str]:
        """Return the variant identifiers currently selected across treeviews."""
        active_tab = None
        try:
            active_tab = self.results_notebook.select()
        except Exception:
            pass

        trees_to_check = [self.summary_tree, self.perm_tree, self.line_type_tree]
        if hasattr(self, "tab_preview") and active_tab == str(self.tab_preview):
            trees_to_check = [self.perm_tree, self.summary_tree, self.line_type_tree]
        elif hasattr(self, "tab_summary") and active_tab == str(self.tab_summary):
            trees_to_check = [self.summary_tree, self.perm_tree, self.line_type_tree]
        elif hasattr(self, "tab_line_types") and active_tab == str(self.tab_line_types):
            trees_to_check = [self.line_type_tree, self.summary_tree, self.perm_tree]

        for tree in trees_to_check:
            selected_items = tree.selection()
            if selected_items:
                results: List[str] = []
                for item_id in selected_items:
                    item_data = tree.item(item_id)
                    tags = item_data.get("tags") or ()
                    for t in tags:
                        results.append(str(t))
                    vals = item_data.get("values") or ()
                    for v in vals:
                        results.append(str(v))
                return results

        return []

    def _get_selected_variants(self, manifest_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find matching variants from the manifest based on active tree selection."""
        variants = manifest_data.get("variants", [])
        if not variants:
            return []

        selected_identifiers = set(self._get_selected_variant_names())
        if not selected_identifiers:
            return []

        matched: List[Dict[str, Any]] = []
        for v in variants:
            name = v.get("name", "")
            gcode = v.get("gcode_path", "")
            clean = format_clean_variant_name(name)
            gcode_name = Path(gcode).name if gcode else ""
            if (
                name in selected_identifiers
                or gcode in selected_identifiers
                or gcode_name in selected_identifiers
                or clean in selected_identifiers
            ):
                matched.append(v)

        return matched

    def _launch_subset_manifest(
        self,
        viewer_exe: Path,
        manifest_path: Path,
        manifest_data: Dict[str, Any],
        selected_variants: List[Dict[str, Any]],
    ) -> None:
        """Create a subset manifest and launch compare viewer with selected variants."""
        if not selected_variants:
            messagebox.showwarning("Compare Viewer", "Please select at least 1 variant to compare.")
            return

        if len(selected_variants) > 8:
            messagebox.showwarning(
                "Variant Limit Exceeded",
                f"A maximum of 8 variants can be viewed in compare mode (selected {len(selected_variants)}).\n"
                "Please reduce your selection to 8 or fewer variants.",
            )
            return

        all_variants = manifest_data.get("variants", [])
        if len(selected_variants) == len(all_variants):
            self._log_message(f"[INFO] Launching compare viewer with all {len(all_variants)} variant(s): {viewer_exe}")
            launch_compare_viewer(viewer_exe, manifest_path)
            return

        orig_baseline = manifest_data.get("baseline")
        new_baseline = (
            orig_baseline
            if any(v.get("name") == orig_baseline for v in selected_variants)
            else selected_variants[0].get("name", "")
        )

        subset_manifest_data = {
            "schema_version": manifest_data.get("schema_version", 1),
            "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": manifest_data.get("source", {}),
            "baseline": new_baseline,
            "matrix": manifest_data.get("matrix", {}),
            "variants": selected_variants,
        }

        try:
            from .analytics import compute_matrix_comparison
            subset_manifest_data["comparison"] = compute_matrix_comparison(selected_variants, new_baseline)
        except Exception:
            pass

        subset_path = manifest_path.parent / "manifest_subset.json"
        try:
            with open(subset_path, "w", encoding="utf-8") as f:
                json.dump(subset_manifest_data, f, indent=2)
        except Exception as e:
            messagebox.showerror("Compare Viewer", f"Could not write subset manifest:\n{e}")
            return

        names_summary = ", ".join(format_clean_variant_name(v.get("name", "")) for v in selected_variants)
        self._log_message(
            f"[INFO] Launching compare viewer with subset ({len(selected_variants)} of {len(all_variants)} variants): {names_summary}"
        )
        launch_compare_viewer(viewer_exe, subset_path)

    def _show_subset_dialog(
        self,
        viewer_exe: Optional[Path] = None,
        manifest_path: Optional[Path] = None,
        manifest_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Open modal dialog allowing the user to select a subset of variants via checkboxes."""
        if manifest_path is None or manifest_data is None:
            manifest_path = getattr(self, "_last_manifest_path", None)
            if not manifest_path or not Path(manifest_path).is_file():
                candidate = Path(self.output_dir_var.get()) / "manifest.json"
                if candidate.is_file():
                    manifest_path = candidate
                    self._last_manifest_path = candidate
                else:
                    messagebox.showinfo(
                        "Compare Viewer",
                        "No completed matrix manifest available yet. Run a matrix slice first.",
                    )
                    return

            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
            except Exception as e:
                messagebox.showerror("Compare Viewer", f"Could not read manifest:\n{e}")
                return

        if viewer_exe is None:
            explicit_path = self.viewer_path_var.get().strip() or None
            viewer_exe = find_viewer_executable(explicit_path)
            if not viewer_exe:
                messagebox.showerror(
                    "Compare Viewer",
                    f"OrcaSlicer executable not found.\n\n"
                    f"Configured path: {explicit_path or '(None)'}\n\n"
                    "Please select or browse for a valid orca-slicer.exe under Execution Options.",
                )
                return

        variants = manifest_data.get("variants", [])
        if not variants:
            messagebox.showwarning("Compare Viewer", "The manifest contains no variants to compare.")
            return

        initial_selected = set(self._get_selected_variant_names())

        def on_confirm(chosen_variants: List[Dict[str, Any]]) -> None:
            self._launch_subset_manifest(viewer_exe, manifest_path, manifest_data, chosen_variants)

        SubsetSelectionDialog(
            self,
            variants=variants,
            on_confirm=on_confirm,
            initial_selected_names=initial_selected,
        )

    def _open_compare_viewer(self, selected_only: bool = False) -> None:
        """Launch the OrcaSlicer compare viewer on all or a selected subset of variants."""
        manifest_path = getattr(self, "_last_manifest_path", None)
        if not manifest_path or not Path(manifest_path).is_file():
            candidate = Path(self.output_dir_var.get()) / "manifest.json"
            if candidate.is_file():
                manifest_path = candidate
                self._last_manifest_path = candidate
            else:
                messagebox.showinfo(
                    "Compare Viewer",
                    "No completed matrix manifest available yet. Run a matrix slice first.",
                )
                return

        explicit_path = self.viewer_path_var.get().strip() or None
        viewer_exe = find_viewer_executable(explicit_path)
        if not viewer_exe:
            messagebox.showerror(
                "Compare Viewer",
                f"OrcaSlicer executable not found.\n\n"
                f"Configured path: {explicit_path or '(None)'}\n\n"
                "Please select or browse for a valid orca-slicer.exe under Execution Options.",
            )
            return

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
        except Exception as e:
            messagebox.showerror("Compare Viewer", f"Could not read manifest at {manifest_path}:\n{e}")
            return

        all_variants = manifest_data.get("variants", [])
        if not all_variants:
            messagebox.showwarning("Compare Viewer", "The manifest contains no variants to compare.")
            return

        if not selected_only:
            self._log_message(f"[INFO] Launching compare viewer with all {len(all_variants)} variant(s): {viewer_exe}")
            launch_compare_viewer(viewer_exe, Path(manifest_path))
            return

        selected_variants = self._get_selected_variants(manifest_data)
        if selected_variants:
            self._launch_subset_manifest(viewer_exe, Path(manifest_path), manifest_data, selected_variants)
        else:
            self._show_subset_dialog(viewer_exe, Path(manifest_path), manifest_data)

    def _log_message(self, message: str) -> None:
        """Append line to the log text widget thread-safely."""
        def append() -> None:
            if self._is_destroyed:
                return
            tag = None
            if "[OK]" in message or "successfully" in message.lower():
                tag = "ok"
            elif "[WARN" in message or "warning" in message.lower():
                tag = "warn"
            elif "[ERROR]" in message or "error" in message.lower() or "fail" in message.lower():
                tag = "err"
            elif "[INFO]" in message or "planning" in message.lower():
                tag = "info"

            self.log_text.insert(tk.END, message + "\n", tag)
            self.log_text.see(tk.END)

        if not self._is_destroyed:
            try:
                self.after(0, append)
            except Exception:
                pass

    def _check_connection_async(self) -> None:
        """Asynchronously connect to OrcaSlicer to prevent blocking UI."""
        if self._is_destroyed:
            return
        self.conn_dot_lbl.config(text="● Checking connection...", style="SubHeader.TLabel")
        self.plater_info_lbl.config(text="Polling http://127.0.0.1:13130...")
        self.refresh_btn.config(state="disabled")

        def worker() -> None:
            try:
                if not self.client:
                    self.client = OrcaClient()
                status = self.client.get_status(timeout=2.0)
                objects = self.client.get_objects(timeout=2.0)
                if not self._is_destroyed:
                    try:
                        self.after(0, lambda s=status, o=objects: self._on_connection_success(s, o))
                    except Exception:
                        pass
            except Exception as e:
                err_msg = str(e)
                if not self._is_destroyed:
                    try:
                        self.after(0, lambda err=err_msg: self._on_connection_failure(err))
                    except Exception:
                        pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_connection_success(self, status: Dict[str, Any], objects: List[Dict[str, Any]]) -> None:
        if self._is_destroyed:
            return
        self.refresh_btn.config(state="normal")
        app_name = status.get("app") or "OrcaSlicer"
        app_ver = status.get("app_version") or status.get("version") or "2.4.2"
        presets = status.get("presets", {}) if isinstance(status.get("presets"), dict) else {}

        printer = presets.get("printer") or "Default"
        print_p = presets.get("print") or "Default"
        fil_raw = presets.get("filament") or "Default"
        fil = fil_raw[0] if isinstance(fil_raw, list) and fil_raw else str(fil_raw)

        obj_names = [str(o.get("name")) for o in objects if o.get("name")]
        obj_str = ", ".join(obj_names) if obj_names else "(Bed is empty)"

        self.conn_dot_lbl.config(text=f"● Connected: {app_name} v{app_ver}", style="StatusConnected.TLabel")
        self.plater_info_lbl.config(
            text=f"Printer: {printer} | Print: {print_p} | Filament: {fil} | Object: {obj_str}"
        )
        self._log_message(f"[OK] Connected to {app_name} v{app_ver} on port 13130. Plater: {obj_str}")

    def _on_connection_failure(self, err_msg: str) -> None:
        if self._is_destroyed:
            return
        self.refresh_btn.config(state="normal")
        self.conn_dot_lbl.config(text="○ Disconnected from OrcaSlicer", style="StatusDisconnected.TLabel")
        self.plater_info_lbl.config(text=f"127.0.0.1:13130 offline ({err_msg[:60]})")
        self._log_message(f"[WARNING] OrcaSlicer not reachable: {err_msg}")

    # --- Dimension Management (Hard Capped at 3 Dimensions) ---

    def _add_dimension(
        self,
        default_key: Optional[str] = None,
        default_values: Optional[List[str]] = None,
        silent: bool = False,
    ) -> None:
        if len(self.active_dimension_cards) >= MAX_DIMENSIONS:
            if not silent:
                messagebox.showwarning(
                    "Dimension Limit Reached",
                    f"A maximum of {MAX_DIMENSIONS} simultaneous matrix dimensions is supported.\n"
                    "Higher dimensional matrices become unmanageable to compare.",
                )
            return

        idx = len(self.active_dimension_cards)
        card = DimensionCard(
            self.dim_cards_box,
            index=idx,
            catalog=self.catalog,
            on_change_callback=self._on_dimensions_changed,
            on_remove_callback=self._remove_dimension,
        )
        card.pack(fill="x", pady=6, padx=4)
        self.active_dimension_cards.append(card)

        if default_key:
            card.set_dimension_by_key(default_key, default_values or [])

        self._update_dimension_count_ui()
        self._on_dimensions_changed()

    def _remove_dimension(self, card: DimensionCard) -> None:
        if card in self.active_dimension_cards:
            self.active_dimension_cards.remove(card)
            card.destroy()

            # Re-index remaining cards
            for i, c in enumerate(self.active_dimension_cards):
                c.index = i
                c.title_lbl.config(text=f"Dimension #{i + 1}  •  Axis {chr(65 + i)}")

            self._update_dimension_count_ui()
            self._on_dimensions_changed()

    def _update_dimension_count_ui(self) -> None:
        count = len(self.active_dimension_cards)
        self.dim_count_badge.config(text=f"Matrix Dimensions ({count} / {MAX_DIMENSIONS} active)")
        if count >= MAX_DIMENSIONS:
            self.add_dim_btn.config(state="disabled", text="Max 3 Dimensions Reached")
        else:
            self.add_dim_btn.config(state="normal", text="+ Add Dimension")

    # --- Permutation Calculation & Limit Validation ---

    def _on_dimensions_changed(self) -> None:
        """Recalculate permutations, update badge, table, and button states."""
        resolved_matrix: Dict[str, List[str]] = {}
        factors: List[str] = []
        total = 1 if self.active_dimension_cards else 0

        for card in self.active_dimension_cards:
            cfg = card.get_axis_config()
            if cfg:
                k, vals = cfg
                resolved_matrix[k] = vals
                factors.append(f"{len(vals)} ({k})")
                total *= len(vals)

        # Clear treeview
        for item in self.perm_tree.get_children():
            self.perm_tree.delete(item)

        if not resolved_matrix or total == 0:
            self.perm_formula_lbl.config(text="Formula: 0 variants")
            self.perm_status_lbl.config(text="Status: Add values to active dimensions.", foreground="#64748b")
            self.perm_suggestions_lbl.config(text="")
            self.run_btn.config(state="disabled")
            self.dry_run_btn.config(state="disabled")
            return

        formula_str = " × ".join(factors) + f" = {total} Variants"
        self.perm_formula_lbl.config(text=f"Formula: {formula_str}")

        if total <= MAX_VARIANTS:
            # Valid permutation count
            self.perm_status_lbl.config(
                text=f"Status: ✓ {total} of {MAX_VARIANTS} variants [Ready to slice]",
                foreground="#16a34a",
            )
            self.perm_suggestions_lbl.config(text="")
            if not self.is_running:
                self.run_btn.config(state="normal")
                self.dry_run_btn.config(state="normal")

            # Populate Treeview
            try:
                variants = build_variants(resolved_matrix)
                for i, v in enumerate(variants, start=1):
                    clean_name = format_clean_variant_name(v.name)
                    self.perm_tree.insert(
                        "",
                        "end",
                        values=(i, clean_name, v.gcode_filename),
                        tags=(v.name, v.gcode_filename),
                    )
                self._make_treeview_sortable(self.perm_tree)
            except Exception as e:
                self.perm_status_lbl.config(text=f"Error: {e}", foreground="#dc2626")
        else:
            # Limit exceeded (>8)
            self.perm_status_lbl.config(
                text=f"Status: ⚠ {total} Variants Exceeds Hard Cap of {MAX_VARIANTS} Variants!",
                foreground="#dc2626",
            )
            self.run_btn.config(state="disabled")
            self.dry_run_btn.config(state="disabled")

            # Compute suggestions
            try:
                build_variants(resolved_matrix)
            except VariantLimitExceededError as err:
                suggestions = getattr(err, "suggestions", [])
                s_text = "Suggestions to stay within 8:\n" + "\n".join(
                    f"• {s}" for s in err._calculate_reduction_suggestions(resolved_matrix, MAX_VARIANTS)
                )
                self.perm_suggestions_lbl.config(text=s_text)
            except Exception:
                pass

    # --- Slicing Execution ---

    def _get_active_matrix(self) -> Dict[str, List[str]]:
        matrix: Dict[str, List[str]] = {}
        for card in self.active_dimension_cards:
            cfg = card.get_axis_config()
            if cfg:
                k, vals = cfg
                matrix[k] = vals
        return matrix

    def _start_dry_run(self) -> None:
        self._execute_runner(dry_run=True)

    def _start_matrix_run(self) -> None:
        self._execute_runner(dry_run=False)

    def _execute_runner(self, dry_run: bool) -> None:
        if self.is_running:
            return

        matrix = self._get_active_matrix()
        if not matrix:
            messagebox.showerror("Error", "No matrix dimensions configured.")
            return

        try:
            variants = build_variants(matrix)
        except Exception as e:
            messagebox.showerror("Matrix Error", str(e))
            return

        out_dir = Path(self.output_dir_var.get())
        self.is_running = True
        self.run_btn.config(state="disabled")
        self.dry_run_btn.config(state="disabled")
        self.progress_bar["value"] = 0
        self.progress_lbl.config(text="Starting matrix execution...")

        # Determine non_interactive and auto_confirm_under_seconds
        require_approval = self.require_approval_var.get()
        non_interactive = not require_approval

        auto_confirm_under: Optional[float] = None
        if require_approval and self.auto_skip_var.get():
            try:
                val = float(self.auto_skip_threshold_var.get().strip())
                if val > 0:
                    auto_confirm_under = val
            except (ValueError, TypeError):
                auto_confirm_under = 30.0

        def eta_confirm_dialog(wall_sec: float, remaining: int, est_rem_sec: float) -> bool:
            """Interactive modal asking user whether to proceed past ETA gate."""
            result_holder = [False]
            event = threading.Event()

            def ask() -> None:
                if self._is_destroyed:
                    result_holder[0] = False
                    event.set()
                    return
                total_est = wall_sec + est_rem_sec
                msg = (
                    f"Baseline variant 1 sliced in {wall_sec:.1f}s wall-clock time.\n\n"
                    f"Remaining variants to slice: {remaining}\n"
                    f"Estimated remaining time: ~{format_duration(est_rem_sec)}\n"
                    f"Estimated total time: ~{format_duration(total_est)}\n\n"
                    f"Do you want to proceed with slicing the remaining {remaining} variants?"
                )
                res = messagebox.askyesno("ETA Confirmation Gate", msg, parent=self)
                result_holder[0] = res
                event.set()

            if not self._is_destroyed:
                try:
                    self.after(0, ask)
                except Exception:
                    result_holder[0] = False
                    event.set()
            else:
                return False

            event.wait()
            return result_holder[0]

        def progress_cb(curr: int, total: int, variant: Variant, status: str, pct: float) -> None:
            def update_ui() -> None:
                if self._is_destroyed:
                    return
                overall_pct = ((curr - 1) / total) * 100 + (pct / total)
                self.progress_bar["value"] = overall_pct
                self.progress_lbl.config(text=f"Variant {curr}/{total}: {variant.name[:35]}... [{status}]")
            if not self._is_destroyed:
                try:
                    self.after(0, update_ui)
                except Exception:
                    pass

        def worker() -> None:
            try:
                if not self.client:
                    self.client = OrcaClient()

                runner = MatrixRunner(
                    client=self.client,
                    output_dir=out_dir,
                    non_interactive=non_interactive,
                    dry_run=dry_run,
                    auto_confirm_under_seconds=auto_confirm_under,
                    log_callback=self._log_message,
                    eta_confirm_fn=eta_confirm_dialog,
                    progress_callback=progress_cb,
                )

                manifest_path, manifest_data = runner.run(matrix)
                if not self._is_destroyed:
                    self.after(0, lambda p=manifest_path, d=dry_run: self._on_run_finished(p, d))

            except Exception as e:
                err_str = str(e)
                if not self._is_destroyed:
                    self.after(0, lambda err=err_str: self._on_run_error(err))

        self.runner_thread = threading.Thread(target=worker, daemon=True)
        self.runner_thread.start()

    def _on_run_finished(self, manifest_path: Path, dry_run: bool) -> None:
        if self._is_destroyed:
            return
        self.is_running = False
        self.progress_bar["value"] = 100
        self.progress_lbl.config(text="Complete!")
        self._on_dimensions_changed()

        if dry_run:
            messagebox.showinfo("Dry Run Complete", f"Matrix dry run succeeded!\nManifest target: {manifest_path}")
            return

        self._last_manifest_path = manifest_path

        # Populate results dashboard
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "comparison" in data:
                self._populate_results_dashboard(data["comparison"], manifest_path)
        except Exception as e:
            self._log_message(f"[WARNING] Could not populate results dashboard: {e}")

        msg = f"Matrix slices successfully completed!\n\nManifest: {manifest_path}"
        # Launch viewer if requested
        if self.launch_viewer_var.get():
            explicit_path = self.viewer_path_var.get().strip() or None
            viewer_exe = find_viewer_executable(explicit_path)
            if viewer_exe:
                self._log_message(f"[INFO] Launching compare viewer with: {viewer_exe}")
                launch_compare_viewer(viewer_exe, manifest_path)
                msg += f"\n\nLaunched OrcaSlicer compare viewer ({viewer_exe.name})."
            else:
                self._log_message(
                    f"[WARNING] Could not launch compare viewer: executable not found at '{explicit_path}'"
                )
                msg += f"\n\nNote: OrcaSlicer executable not found at '{explicit_path or 'default locations'}'. You can set the viewer path in Execution Options."

        messagebox.showinfo("Matrix Slice Succeeded", msg)

    @staticmethod
    def _parse_sort_key(raw_val: Any) -> Tuple[int, float, str]:
        """Convert a Treeview cell string into a tuple for robust, type-safe sorting.

        Tuples are formatted as:
        - Numbers: (1, float_value, "")
        - Strings: (2, 0.0, string_value_lower)
        - Missing: (3, 0.0, "")
        """
        if raw_val is None:
            return (3, 0.0, "")
        s = str(raw_val).strip()
        if s in ("", "-", "None", "ERROR"):
            return (3, 0.0, "")

        # Try parsing grams: e.g. "0.84g", "15.2 g"
        if s.endswith("g") or " g" in s:
            num_part = s.replace("g", "").strip()
            try:
                return (1, float(num_part), "")
            except ValueError:
                pass

        # Try parsing currency: e.g. "$1.08", "$0.91"
        if s.startswith("$"):
            try:
                return (1, float(s.lstrip("$").strip()), "")
            except ValueError:
                pass

        # Try parsing percentage: e.g. "15%"
        if s.endswith("%"):
            try:
                return (1, float(s.rstrip("%").strip()), "")
            except ValueError:
                pass

        # Try parsing duration format: e.g. "1h 45m", "45s", "2m", "+19m", "-12m"
        time_match = re.match(r"^([+-]?)(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?$", s)
        if time_match and any(time_match.groups()[1:]):
            sign = -1.0 if time_match.group(1) == "-" else 1.0
            h = int(time_match.group(2) or 0)
            m = int(time_match.group(3) or 0)
            sec = int(time_match.group(4) or 0)
            total_sec = sign * (h * 3600 + m * 60 + sec)
            return (1, total_sec, "")

        # Try general float or integer: e.g. "1", "2.5"
        try:
            return (1, float(s), "")
        except ValueError:
            pass

        # Fallback to case-insensitive string comparison
        return (2, 0.0, s.lower())

    def _sort_treeview_column(self, tree: ttk.Treeview, col_name: str) -> None:
        """Sort treeview rows by a specified column name."""
        if not hasattr(tree, "_sort_state"):
            tree._sort_state = {}
        if not hasattr(tree, "_orig_headings"):
            tree._orig_headings = {}

        current_desc = tree._sort_state.get(col_name, None)
        descending = True if current_desc is False else False
        tree._sort_state = {col_name: descending}

        # Update headings with sort indicator
        for other_col in tree["columns"]:
            orig = tree._orig_headings.get(other_col, other_col)
            if other_col == col_name:
                arrow = " ▼" if descending else " ▲"
                tree.heading(other_col, text=f"{orig}{arrow}")
            else:
                tree.heading(other_col, text=orig)

        # Sort items in place
        col_idx = list(tree["columns"]).index(col_name)
        item_ids = tree.get_children("")
        item_data = []
        for item_id in item_ids:
            vals = tree.item(item_id, "values")
            raw = vals[col_idx] if col_idx < len(vals) else ""
            item_data.append((self._parse_sort_key(raw), item_id))

        item_data.sort(key=lambda x: x[0], reverse=descending)

        for new_idx, (_, item_id) in enumerate(item_data):
            tree.move(item_id, "", new_idx)

    def _make_treeview_sortable(self, tree: ttk.Treeview) -> None:
        """Enable interactive column sorting on a Treeview.

        Clicking a column header sorts ascending (▲); clicking again reverses to descending (▼).
        Supports numeric sorting (grams, seconds, currency, percentages) and text sorting.
        """
        if not hasattr(tree, "_orig_headings"):
            tree._orig_headings = {}
        if not hasattr(tree, "_sort_state"):
            tree._sort_state = {}

        cols = list(tree["columns"])
        for col in cols:
            curr_text = tree.heading(col, "text") or ""
            clean_text = curr_text.rstrip(" ▲▼").strip()
            tree._orig_headings[col] = clean_text
            tree.heading(col, text=clean_text, command=lambda c=col: self._sort_treeview_column(tree, c))

    def _populate_results_dashboard(self, comparison: Dict[str, Any], manifest_path: Path) -> None:
        """Populate Summary, Line-Type breakdown, and Visual Charts with post-slice analytics."""
        self._last_comparison = comparison
        self._last_manifest_path = manifest_path
        self._last_html_report = manifest_path.parent / "report.html"

        # Update recommendation banner
        rec = comparison.get("recommended") or "None"
        reason = comparison.get("recommendation_reason") or ""
        self.rec_banner_title.config(text=f"★ Recommended Choice: {rec}")
        self.rec_banner_desc.config(text=reason)

        # Clear and populate Summary Treeview
        for item in self.summary_tree.get_children():
            self.summary_tree.delete(item)

        for r in comparison.get("summary_rows", []):
            disp = r.get("display_name") or format_clean_variant_name(r["name"])
            self.summary_tree.insert(
                "",
                "end",
                values=(
                    disp,
                    r["print_time"],
                    r["filament"],
                    r["cost"],
                    r["vs_baseline"],
                ),
                tags=(r["name"],),
            )
        self._make_treeview_sortable(self.summary_tree)

        # Clear and populate Line Type Treeview
        for item in self.line_type_tree.get_children():
            self.line_type_tree.delete(item)

        lt_data = comparison.get("line_type_matrix", {})
        cols = lt_data.get("columns", [])
        rows = lt_data.get("rows", [])

        if cols:
            all_cols = ["variant"] + [c.lower().replace(" ", "_") for c in cols] + ["total"]
            self.line_type_tree["columns"] = all_cols
            self.line_type_tree.heading("variant", text="Variant")
            self.line_type_tree.column("variant", width=180, minwidth=140, stretch=True, anchor="w")
            for c in cols:
                c_id = c.lower().replace(" ", "_")
                self.line_type_tree.heading(c_id, text=c)
                col_w = max(85, len(c) * 9 + 25)
                self.line_type_tree.column(c_id, width=col_w, minwidth=col_w, stretch=False, anchor="center")
            self.line_type_tree.heading("total", text="Total")
            self.line_type_tree.column("total", width=85, minwidth=75, stretch=False, anchor="center")

            for r in rows:
                c_name = r.get("clean_name") or format_clean_variant_name(r["name"])
                vals = [c_name] + [f"{r['roles'].get(c, 0.0):.2f}g" for c in cols] + [f"{r['total_g']:.1f}g"]
                self.line_type_tree.insert("", "end", values=vals, tags=(r["name"],))

            self._make_treeview_sortable(self.line_type_tree)

        # Redraw visual charts
        self._redraw_charts()

        # Switch notebook focus to Summary tab
        self.results_notebook.select(self.tab_summary)

    def _copy_summary_markdown(self) -> None:
        """Copy the exact Image 1 summary markdown table to system clipboard."""
        if hasattr(self, "_last_comparison") and self._last_comparison:
            md = self._last_comparison.get("summary_markdown", "")
            if md:
                self.clipboard_clear()
                self.clipboard_append(md)
                self._log_message("[INFO] Copied summary markdown table to clipboard.")
                messagebox.showinfo("Clipboard", "Summary table copied to clipboard!")
        else:
            messagebox.showinfo("Clipboard", "No slice summary data available yet.")

    def _copy_line_types_markdown(self) -> None:
        """Copy the exact Image 2 line-types markdown table to system clipboard."""
        if hasattr(self, "_last_comparison") and self._last_comparison:
            md = self._last_comparison.get("line_type_markdown", "")
            if md:
                self.clipboard_clear()
                self.clipboard_append(md)
                self._log_message("[INFO] Copied filament line types markdown to clipboard.")
                messagebox.showinfo("Clipboard", "Filament line types table copied to clipboard!")
        else:
            messagebox.showinfo("Clipboard", "No filament line-type data available yet.")

    def _open_html_report(self) -> None:
        """Open the generated standalone HTML report in default browser."""
        if hasattr(self, "_last_html_report") and self._last_html_report and self._last_html_report.is_file():
            import webbrowser
            webbrowser.open(self._last_html_report.as_uri())
        else:
            messagebox.showinfo("HTML Report", "No HTML report available yet. Run a matrix slice first.")

    def _redraw_charts(self) -> None:
        """Redraw current selected visual chart on self.charts_canvas."""
        if self._is_destroyed or not self.charts_canvas.winfo_exists():
            return

        if not hasattr(self, "_last_comparison") or not self._last_comparison:
            self.charts_canvas.delete("all")
            w = self.charts_canvas.winfo_width() or 400
            h = self.charts_canvas.winfo_height() or 180
            self.charts_canvas.create_text(
                w / 2,
                h / 2,
                text="Slice matrix variants to render visual charts.",
                fill="#94a3b8",
                font=("Segoe UI", 9, "italic"),
            )
            return

        mode = self.chart_type_var.get()
        if mode == "stacked":
            self._draw_stacked_bar_chart()
        elif mode == "pareto":
            self._draw_pareto_chart()

    def _draw_stacked_bar_chart(self) -> None:
        """Render horizontal stacked bars on Tkinter canvas for filament breakdown."""
        if self._is_destroyed or not self.charts_canvas.winfo_exists():
            return

        self.charts_canvas.delete("all")
        self._chart_hover_items = []
        w = self.charts_canvas.winfo_width() or 520
        h = self.charts_canvas.winfo_height() or 230

        if not hasattr(self, "_last_comparison") or not self._last_comparison:
            self.charts_canvas.create_text(
                w / 2,
                h / 2,
                text="Slice matrix variants to render visual charts.",
                fill="#94a3b8",
                font=("Segoe UI", 9, "italic"),
            )
            return

        lt_data = self._last_comparison.get("line_type_matrix", {})
        columns = lt_data.get("columns", [])
        rows = lt_data.get("rows", [])
        if not rows or not columns:
            self.charts_canvas.create_text(
                w / 2,
                h / 2,
                text="No filament line-type data available for current variants.",
                fill="#94a3b8",
                font=("Segoe UI", 9, "italic"),
            )
            return

        # 1. Responsive multi-row wrapping legend at top
        leg_x = 12
        leg_y = 10
        leg_line_h = 16
        for col in columns:
            c = get_role_color(col)
            item_w = len(col) * 6 + 22
            if leg_x + item_w > w - 12 and leg_x > 12:
                leg_x = 12
                leg_y += leg_line_h
            self.charts_canvas.create_rectangle(leg_x, leg_y, leg_x + 9, leg_y + 9, fill=c, outline="")
            self.charts_canvas.create_text(leg_x + 13, leg_y + 4, text=col, fill="#cbd5e1", font=("Segoe UI", 8), anchor="w")
            leg_x += item_w + 10

        legend_bottom = leg_y + 16

        # 2. Dynamic margin based on Compact Labels toggle
        compact = self.compact_labels_var.get() if hasattr(self, "compact_labels_var") else True
        margin_l = max(110, min(150, int(w * 0.26))) if compact else max(160, min(240, int(w * 0.40)))
        margin_r = 52
        plot_w = max(100, w - margin_l - margin_r)

        # 3. Bar heights and layout
        avail_h = max(60, h - legend_bottom - 10)
        num_rows = len(rows)
        bar_h = min(22, max(12, int(avail_h / num_rows) - 6))
        bar_gap = max(4, int((avail_h - (bar_h * num_rows)) / max(1, num_rows)))
        start_y = legend_bottom + 6

        max_mass = max(r["total_g"] for r in rows) if rows else 100.0
        scale = plot_w / (max_mass + 1e-6)

        # 4. Render each variant's bar
        for i, r in enumerate(rows):
            y = start_y + i * (bar_h + bar_gap)
            name = r["name"]
            total = r["total_g"]

            disp_label = format_compact_label(name) if compact else name
            if not compact and len(disp_label) > 28:
                disp_label = disp_label[:26] + ".."

            self.charts_canvas.create_text(
                margin_l - 8,
                y + bar_h / 2,
                text=disp_label,
                fill="#f8fafc",
                font=("Segoe UI", 8, "bold"),
                anchor="e",
            )

            # Subtle background track
            self.charts_canvas.create_rectangle(
                margin_l,
                y,
                margin_l + plot_w,
                y + bar_h,
                fill="#0f172a",
                outline="#334155",
                width=1,
            )

            curr_x = margin_l
            for col in columns:
                val = r["roles"].get(col, 0.0)
                if val <= 0.001:
                    continue
                seg_w = val * scale
                c = get_role_color(col)
                self.charts_canvas.create_rectangle(
                    curr_x,
                    y,
                    curr_x + seg_w,
                    y + bar_h,
                    fill=c,
                    outline="#0f172a",
                    width=1,
                )

                pct = (val / total * 100.0) if total > 0 else 0.0
                self._chart_hover_items.append({
                    "type": "segment",
                    "bbox": (curr_x, y, curr_x + seg_w, y + bar_h),
                    "variant": name,
                    "compact_variant": disp_label,
                    "role": col,
                    "mass": val,
                    "total": total,
                    "pct": pct,
                })

                if seg_w >= 28:
                    self.charts_canvas.create_text(
                        curr_x + seg_w / 2,
                        y + bar_h / 2,
                        text=f"{val:.1f}g",
                        fill="#ffffff",
                        font=("Segoe UI", 7, "bold"),
                        anchor="center",
                    )

                curr_x += seg_w

            # Total mass right-aligned in dedicated column
            self.charts_canvas.create_text(
                w - 6,
                y + bar_h / 2,
                text=f"{total:.1f}g",
                fill="#cbd5e1",
                font=("Segoe UI", 8, "bold"),
                anchor="e",
            )

    def _draw_pareto_chart(self) -> None:
        """Render 2D Pareto frontier scatter plot on Tkinter canvas."""
        if self._is_destroyed or not self.charts_canvas.winfo_exists():
            return

        self.charts_canvas.delete("all")
        self._chart_hover_items = []
        w = self.charts_canvas.winfo_width() or 520
        h = self.charts_canvas.winfo_height() or 230

        if not hasattr(self, "_last_comparison") or not self._last_comparison:
            self.charts_canvas.create_text(
                w / 2,
                h / 2,
                text="Slice matrix variants to render visual charts.",
                fill="#94a3b8",
                font=("Segoe UI", 9, "italic"),
            )
            return

        summary_rows = self._last_comparison.get("summary_rows", [])
        valid_pts = [r for r in summary_rows if r.get("time_s") and r.get("filament_g") and not r.get("error")]
        if not valid_pts:
            self.charts_canvas.create_text(
                w / 2,
                h / 2,
                text="Not enough data points for Pareto analysis.",
                fill="#94a3b8",
                font=("Segoe UI", 9, "italic"),
            )
            return

        margin_l, margin_r, margin_t, margin_b = 60, 30, 22, 34
        plot_w = max(100, w - margin_l - margin_r)
        plot_h = max(60, h - margin_t - margin_b)

        times = [p["time_s"] / 60.0 for p in valid_pts]
        masses = [p["filament_g"] for p in valid_pts]

        min_t, max_t = min(times), max(times)
        min_m, max_m = min(masses), max(masses)
        t_pad = max(2, (max_t - min_t) * 0.2)
        m_pad = max(0.4, (max_m - min_m) * 0.2)

        x_min, x_max = max(0, min_m - m_pad), max_m + m_pad
        y_min, y_max = max(0, min_t - t_pad), max_t + t_pad

        def to_x(m: float) -> float:
            return margin_l + ((m - x_min) / (x_max - x_min + 1e-6)) * plot_w

        def to_y(t: float) -> float:
            return margin_t + plot_h - ((t - y_min) / (y_max - y_min + 1e-6)) * plot_h

        # Grid lines and ticks
        for i in range(4):
            xt = x_min + (x_max - x_min) * (i / 3.0)
            gx = to_x(xt)
            self.charts_canvas.create_line(gx, margin_t, gx, margin_t + plot_h, fill="#334155", dash=(2, 3))
            self.charts_canvas.create_text(gx, margin_t + plot_h + 10, text=f"{xt:.1f}g", fill="#94a3b8", font=("Segoe UI", 7))

        for i in range(4):
            yt = y_min + (y_max - y_min) * (i / 3.0)
            gy = to_y(yt)
            self.charts_canvas.create_line(margin_l, gy, margin_l + plot_w, gy, fill="#334155", dash=(2, 3))
            self.charts_canvas.create_text(margin_l - 6, gy, text=format_duration(yt * 60), fill="#94a3b8", font=("Segoe UI", 7), anchor="e")

        # Axes
        self.charts_canvas.create_line(margin_l, margin_t + plot_h, margin_l + plot_w, margin_t + plot_h, fill="#64748b", width=1.5)
        self.charts_canvas.create_line(margin_l, margin_t, margin_l, margin_t + plot_h, fill="#64748b", width=1.5)
        self.charts_canvas.create_text(margin_l + plot_w / 2, h - 6, text="Filament Mass (g) → (lower is better)", fill="#cbd5e1", font=("Segoe UI", 8, "bold"))
        self.charts_canvas.create_text(16, margin_t + plot_h / 2, text="Time\n↓\n(faster)", fill="#cbd5e1", font=("Segoe UI", 7, "bold"), justify="center")

        # Pareto Frontier Line
        pts_sorted = sorted(valid_pts, key=lambda p: (p["filament_g"], p["time_s"]))
        frontier = []
        curr_min_t = float("inf")
        for p in pts_sorted:
            t_val = p["time_s"] / 60.0
            if t_val <= curr_min_t:
                frontier.append((p["filament_g"], t_val))
                curr_min_t = t_val

        if len(frontier) > 1:
            for j in range(len(frontier) - 1):
                x1, y1 = to_x(frontier[j][0]), to_y(frontier[j][1])
                x2, y2 = to_x(frontier[j + 1][0]), to_y(frontier[j + 1][1])
                self.charts_canvas.create_line(x1, y1, x2, y2, fill="#38bdf8", dash=(3, 3), width=2)

        compact = self.compact_labels_var.get() if hasattr(self, "compact_labels_var") else True
        # Plot points
        for p in valid_pts:
            cx = to_x(p["filament_g"])
            cy = to_y(p["time_s"] / 60.0)
            is_base = p.get("is_baseline", False)
            is_fast = p.get("is_fastest", False)
            is_rec = p.get("is_recommended", False)

            col = "#38bdf8"
            rad = 5
            if is_base:
                col = "#60a5fa"
                rad = 6
            if is_fast:
                col = "#fbbf24"
                rad = 7
            if is_rec:
                col = "#34d399"
                rad = 7

            self.charts_canvas.create_oval(cx - rad, cy - rad, cx + rad, cy + rad, fill=col, outline="#0f172a", width=1.5)

            lbl = format_compact_label(p["name"]) if compact else p["name"]
            if is_base:
                lbl += " (base)"
            elif is_fast:
                lbl += " ★"
            elif is_rec:
                lbl += " ★ rec"

            if not compact and len(lbl) > 16:
                lbl = lbl[:14] + ".."

            self.charts_canvas.create_text(cx + rad + 4, cy - 2, text=lbl, fill="#f8fafc", font=("Segoe UI", 7, "bold"), anchor="w")

            self._chart_hover_items.append({
                "type": "point",
                "cx": cx,
                "cy": cy,
                "radius": 12,
                "data": p,
            })

    def _on_chart_motion(self, event: Any) -> None:
        """Update hover detail label when mouse moves over chart elements."""
        if not hasattr(self, "_chart_hover_items") or not self._chart_hover_items:
            return

        mx, my = event.x, event.y
        mode = self.chart_type_var.get()

        if mode == "stacked":
            for item in self._chart_hover_items:
                if item["type"] == "segment":
                    x1, y1, x2, y2 = item["bbox"]
                    if x1 <= mx <= x2 and y1 <= my <= y2:
                        var = item["compact_variant"]
                        role = item["role"]
                        mass = item["mass"]
                        pct = item["pct"]
                        total = item["total"]
                        self.chart_hover_lbl.config(
                            text=f"📊 {var}  •  {role}: {mass:.2f}g ({pct:.1f}%)  •  Total: {total:.1f}g",
                            foreground="#38bdf8",
                        )
                        return
        elif mode == "pareto":
            for item in self._chart_hover_items:
                if item["type"] == "point":
                    dist_sq = (mx - item["cx"]) ** 2 + (my - item["cy"]) ** 2
                    if dist_sq <= item["radius"] ** 2:
                        p = item["data"]
                        name = p.get("name", "")
                        compact_n = format_compact_label(name)
                        t_str = p.get("print_time", "-")
                        f_str = p.get("filament", "-")
                        c_str = p.get("cost", "-")
                        vs_b = p.get("vs_baseline", "-")
                        self.chart_hover_lbl.config(
                            text=f"🎯 {compact_n} ({name})  •  Time: {t_str}  •  Filament: {f_str}  •  Cost: {c_str}  •  vs Base: {vs_b}",
                            foreground="#38bdf8",
                        )
                        return
            self.chart_hover_lbl.config(
                text="Hover over any bar segment or chart point to inspect detailed metrics.",
                foreground="#94a3b8",
            )

    def _on_chart_leave(self, event: Any) -> None:
        """Reset hover detail label when mouse leaves canvas."""
        if hasattr(self, "chart_hover_lbl"):
            self.chart_hover_lbl.config(
                text="Hover over any bar segment or chart point to inspect detailed metrics.",
                foreground="#94a3b8",
            )

    def _on_run_error(self, error_str: str) -> None:
        if self._is_destroyed:
            return
        self.is_running = False
        self.progress_lbl.config(text="Failed")
        self._on_dimensions_changed()
        self._log_message(f"[ERROR] Matrix run failed: {error_str}")
        messagebox.showerror("Execution Error", f"Matrix slice operation failed:\n\n{error_str}")


def launch_gui() -> int:
    """Launch the Tkinter GUI application."""
    app = OrcaMatrixApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(launch_gui())
