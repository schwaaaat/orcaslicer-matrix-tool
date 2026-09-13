"""OrcaSlicer Matrix Tool - Modern Desktop Graphical User Interface.

Provides an interactive, modern GUI to configure up to 3 matrix dimensions,
select from comprehensive OrcaSlicer Process Tab settings, inspect real-time
permutation counts, run matrix slices, and launch the compare viewer.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from .cli import find_viewer_executable, launch_compare_viewer


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

        # Permutations Table
        table_lbl = ttk.Label(right_frame, text="Permutation Variants Preview:", font=("Segoe UI", 9, "bold"))
        table_lbl.pack(anchor="w", pady=(0, 4))

        columns = ("index", "name", "gcode")
        self.perm_tree = ttk.Treeview(right_frame, columns=columns, show="headings", height=7)
        self.perm_tree.heading("index", text="#")
        self.perm_tree.heading("name", text="Variant Name")
        self.perm_tree.heading("gcode", text="G-code File")
        self.perm_tree.column("index", width=32, stretch=False, anchor="center")
        self.perm_tree.column("name", width=230, stretch=True)
        self.perm_tree.column("gcode", width=140, stretch=False)
        self.perm_tree.pack(fill="x", pady=(0, 8))

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
        )
        self.launch_viewer_chk.pack(anchor="w", pady=(2, 2))

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
                status = self.client.get_status()
                objects = self.client.get_objects()
                if not self._is_destroyed:
                    try:
                        self.after(0, lambda: self._on_connection_success(status, objects))
                    except Exception:
                        pass
            except Exception as e:
                if not self._is_destroyed:
                    try:
                        self.after(0, lambda: self._on_connection_failure(str(e)))
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
                    self.perm_tree.insert("", "end", values=(i, v.name, v.gcode_filename))
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
                    self.after(0, lambda: self._on_run_finished(manifest_path, dry_run))

            except Exception as e:
                if not self._is_destroyed:
                    self.after(0, lambda: self._on_run_error(str(e)))

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

        msg = f"Matrix slices successfully completed!\n\nManifest: {manifest_path}"
        # Launch viewer if requested
        if self.launch_viewer_var.get():
            viewer_exe = find_viewer_executable(None)
            if viewer_exe:
                self._log_message(f"[INFO] Launching compare viewer with: {viewer_exe}")
                launch_compare_viewer(viewer_exe, manifest_path)
                msg += "\n\nLaunched OrcaSlicer compare viewer."
            else:
                msg += "\n\nNote: OrcaSlicer executable not found to auto-launch viewer."

        messagebox.showinfo("Matrix Slice Succeeded", msg)

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
