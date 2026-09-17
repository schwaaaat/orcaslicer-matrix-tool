"""PySide6 desktop application for OrcaSlicer Matrix Studio."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlsplit

import keyring
from keyring.errors import KeyringError, PasswordDeleteError
from PySide6.QtCore import QObject, QPoint, QSettings, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .catalog import (
    CAT_ALL,
    CAT_COMMON,
    CAT_FAVORITES,
    DimensionCatalog,
    DimensionDefinition,
    PresetValue,
    get_default_catalog,
)
from .matrix import VariantLimitExceededError, build_variants
from .run_bundle import (
    AxisDefinition,
    HARD_VARIANT_LIMIT,
    RunBundle,
    RunBundleStore,
    RunLibrary,
    VariantRecord,
)
from .studio_client import Capabilities, StudioClient
from .studio_runner import StudioRunner


DARK_STYLESHEET = """
QWidget { background: #111418; color: #dce3ea; font-family: "Segoe UI"; font-size: 10pt; }
QMainWindow, QDialog { background: #0d1014; }
QFrame#rail { background: #0a0d10; border-right: 1px solid #262c33; }
QFrame#card { background: #171b20; border: 1px solid #2a3139; border-radius: 10px; }
QLabel#title { font-size: 22pt; font-weight: 650; color: #f5f8fa; }
QLabel#section { font-size: 13pt; font-weight: 650; color: #edf3f7; }
QLabel#muted { color: #85919d; }
QLabel#good { color: #43d3a2; font-weight: 600; }
QLabel#warning { color: #f4bd62; font-weight: 600; }
QPushButton, QToolButton { background: #1c2229; border: 1px solid #343d47; border-radius: 7px; padding: 8px 12px; }
QPushButton:hover, QToolButton:hover { background: #252d36; border-color: #4a5866; }
QPushButton:pressed { background: #151a1f; }
QPushButton#primary { background: #0f806f; border-color: #23a991; color: white; font-weight: 650; }
QPushButton#primary:hover { background: #149580; }
QPushButton#chip { background: #1c2229; border: 1px solid #343d47; border-radius: 12px; padding: 2px 9px; font-size: 8.5pt; color: #aeb8c2; }
QPushButton#chip:hover { background: #252d36; border-color: #4a5866; color: #dce3ea; }
QPushButton#chip:checked { background: #183d33; border-color: #2eb896; color: #43d3a2; font-weight: 600; }
QPushButton#nav { text-align: left; border: 0; background: transparent; padding: 10px 12px; color: #aab4be; }
QPushButton#nav:checked { background: #172721; color: #63ddba; border-left: 3px solid #37caa4; }
QLineEdit, QComboBox, QSpinBox { background: #0f1317; border: 1px solid #323a43; border-radius: 6px; padding: 7px; selection-background-color: #167f6e; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #3dc6a7; }
QTableWidget, QListWidget { background: #101419; alternate-background-color: #151a20; border: 1px solid #293039; border-radius: 7px; gridline-color: #252c34; }
QHeaderView::section { background: #1b2128; color: #aeb8c2; border: 0; border-bottom: 1px solid #323a43; padding: 8px; }
QProgressBar { background: #0e1216; border: 1px solid #303842; border-radius: 6px; text-align: center; }
QProgressBar::chunk { background: #24ae93; border-radius: 5px; }
QScrollArea { border: 0; }
QSplitter::handle { background: #242b32; width: 1px; }
QTabWidget::pane { border: 1px solid #2a3139; background: #111418; border-radius: 8px; }
QTabBar::tab { background: #171b20; color: #85919d; border: 1px solid #2a3139; border-bottom: 0; padding: 7px 16px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; font-weight: 600; }
QTabBar::tab:selected { background: #1a2420; color: #43d3a2; border-bottom: 2px solid #37caa4; }
QTabBar::tab:hover:!selected { background: #222932; color: #dce3ea; }
"""

KEYRING_SERVICE = "OrcaSlicer Matrix Studio Remote API"

LIGHT_STYLESHEET = """
QWidget { background: #f4f6f8; color: #1d2730; font-family: "Segoe UI"; font-size: 10pt; }
QFrame#rail { background: #e8edf1; border-right: 1px solid #cad2d9; }
QFrame#card { background: white; border: 1px solid #d4dbe1; border-radius: 10px; }
QLabel#title { font-size: 22pt; font-weight: 650; }
QLabel#section { font-size: 13pt; font-weight: 650; }
QLabel#muted { color: #66737e; }
QLabel#good { color: #087963; font-weight: 600; }
QLabel#warning { color: #9b6107; font-weight: 600; }
QPushButton, QToolButton { background: #fff; border: 1px solid #bcc7d0; border-radius: 7px; padding: 8px 12px; }
QPushButton#primary { background: #087d6b; color: white; font-weight: 650; }
QPushButton#chip { background: #f0f3f6; border: 1px solid #d0d7de; border-radius: 12px; padding: 2px 9px; font-size: 8.5pt; color: #475569; }
QPushButton#chip:hover { background: #e2e8f0; border-color: #cbd5e1; color: #1e293b; }
QPushButton#chip:checked { background: #d9eee8; border-color: #0a8c76; color: #087963; font-weight: 600; }
QPushButton#nav { text-align: left; border: 0; background: transparent; padding: 10px 12px; }
QPushButton#nav:checked { background: #d9eee8; color: #096e5e; border-left: 3px solid #0a8c76; }
QLineEdit, QComboBox, QSpinBox { background: white; border: 1px solid #bac5ce; border-radius: 6px; padding: 7px; }
QTableWidget, QListWidget { background: white; alternate-background-color: #f1f4f6; border: 1px solid #ccd4db; border-radius: 7px; }
QHeaderView::section { background: #e8edf1; border: 0; border-bottom: 1px solid #c4cdd5; padding: 8px; }
QProgressBar::chunk { background: #15977f; }
QTabWidget::pane { border: 1px solid #ccd4db; background: white; border-radius: 8px; }
QTabBar::tab { background: #e8edf1; color: #66737e; border: 1px solid #ccd4db; border-bottom: 0; padding: 7px 16px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 4px; font-weight: 600; }
QTabBar::tab:selected { background: white; color: #087d6b; border-bottom: 2px solid #0a8c76; }
QTabBar::tab:hover:!selected { background: #f0f3f6; color: #1d2730; }
"""


def _app_paths() -> tuple[Path, Path]:
    override = os.environ.get("ORCA_MATRIX_DATA_DIR")
    if override:
        root = Path(override)
        return root / "library.db", root / "Runs"
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local")) / "OrcaMatrix"
    documents = Path.home() / "Documents" / "OrcaMatrix" / "Runs"
    return local / "library.db", documents


def _is_local_endpoint(base_url: str) -> bool:
    return (urlsplit(base_url).hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}


def _stored_api_token(base_url: str) -> Optional[str]:
    if _is_local_endpoint(base_url):
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, base_url)
    except KeyringError:
        return None


def _default_viewer_executable() -> str:
    configured = os.environ.get("ORCA_SLICER_EXE")
    if configured:
        return configured
    if getattr(sys, "frozen", False):
        packaged = Path(sys.executable).resolve().parents[2] / "orca-slicer.exe"
        if packaged.is_file():
            return str(packaged)
    return shutil.which("orca-slicer.exe") or "orca-slicer.exe"


FAVORITE_SETTINGS_KEY = "favorite_settings"


def get_favorite_settings() -> List[str]:
    """Retrieve saved favorite setting keys from QSettings."""
    settings = QSettings("OrcaMatrix", "Studio")
    val = settings.value(FAVORITE_SETTINGS_KEY, [])
    if val is None:
        return []
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
        except Exception:
            return [s.strip() for s in val.split(",") if s.strip()]
    elif isinstance(val, (list, tuple)):
        return [str(v) for v in val if v]
    return []


def set_favorite_settings(keys: List[str]) -> None:
    """Persist favorite setting keys to QSettings."""
    settings = QSettings("OrcaMatrix", "Studio")
    unique_keys = sorted(list({k.strip() for k in keys if k and k.strip()}))
    settings.setValue(FAVORITE_SETTINGS_KEY, json.dumps(unique_keys))


def is_favorite_setting(key: str) -> bool:
    """Return True if the given setting key is in saved favorites."""
    if not key:
        return False
    return key in set(get_favorite_settings())


def toggle_favorite_setting(key: str) -> bool:
    """Toggle a setting key in saved favorites. Returns True if now favorite, False if removed."""
    if not key:
        return False
    favs = set(get_favorite_settings())
    if key in favs:
        favs.remove(key)
        is_fav = False
    else:
        favs.add(key)
        is_fav = True
    set_favorite_settings(list(favs))
    return is_fav


class SortableTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem supporting custom typed sort keys for numeric and state sorting."""

    def __init__(self, text: str, sort_key: Any, user_data: Any = None):
        super().__init__(text)
        self.sort_key = sort_key
        if user_data is not None:
            self.setData(Qt.UserRole, user_data)

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, SortableTableWidgetItem):
            a = self.sort_key
            b = other.sort_key
            if a is None and b is None:
                return False
            if a is None:
                return False
            if b is None:
                return True
            try:
                return a < b
            except TypeError:
                return str(a) < str(b)
        return super().__lt__(other)


def generate_bundle_html_report(bundle: RunBundle, run_dir: Path) -> Path:
    """Generate a rich self-contained HTML report with Pareto and line-type SVG charts."""
    from .analytics import compute_matrix_comparison, generate_html_report

    run_path = Path(run_dir)
    html_path = run_path / "report.html"

    presets = bundle.source.get("presets", {}) if isinstance(bundle.source, dict) else {}
    source_dict = dict(bundle.source) if isinstance(bundle.source, dict) else {}
    if "printer" in presets and "printer_preset" not in source_dict:
        source_dict["printer_preset"] = presets["printer"]
    if "print" in presets and "print_preset" not in source_dict:
        source_dict["print_preset"] = presets["print"]
    if "filament" in presets and "filament_preset" not in source_dict:
        source_dict["filament_preset"] = presets["filament"]

    matrix_dict = {axis.key: list(axis.values) for axis in bundle.axes}

    variant_dicts = [
        {
            "name": v.name,
            "changes": v.changes,
            "gcode_path": v.gcode_path,
            "stats": v.stats,
            "warnings": v.warnings,
            "error": v.error,
        }
        for v in bundle.variants
    ]

    comparison = bundle.comparison
    if not comparison or not comparison.get("summary_rows"):
        completed = [v for v in variant_dicts if v.get("stats") and v["stats"].get("time_s") is not None]
        if completed:
            comparison = compute_matrix_comparison(completed, completed[0]["name"])
        elif variant_dicts:
            comparison = compute_matrix_comparison(variant_dicts, variant_dicts[0]["name"])
        else:
            comparison = {}

    manifest_data = {
        "schema_version": 2,
        "source": source_dict,
        "baseline": bundle.variants[0].name if bundle.variants else None,
        "matrix": matrix_dict,
        "variants": variant_dicts,
        "comparison": comparison,
    }

    return generate_html_report(manifest_data, comparison, html_path)


class ConnectionWorker(QObject):
    succeeded = Signal(object, object, object, bytes)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, base_url: str, token: Optional[str] = None):
        super().__init__()
        self.base_url = base_url
        self.token = token

    @Slot()
    def run(self) -> None:
        try:
            with StudioClient(base_url=self.base_url, token=self.token) as client:
                caps = client.capabilities()
                status = client.status()
                objects = client.objects()
                try:
                    preview = client.plate_render()
                except Exception:
                    preview = b""
            self.succeeded.emit(caps, status, objects, preview)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


@dataclass
class EtaRequest:
    baseline_seconds: float
    remaining: int
    estimated_seconds: float
    event: threading.Event
    accepted: bool = False


class RunWorker(QObject):
    progress = Signal(object, object, str, float)
    eta_requested = Signal(object)
    completed = Signal(object, str)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        base_url: str,
        token: Optional[str],
        bundle: RunBundle,
        run_dir: Path,
        store: RunBundleStore,
    ):
        super().__init__()
        self.base_url = base_url
        self.token = token
        self.bundle = bundle
        self.run_dir = run_dir
        self.store = store
        self.runner: Optional[StudioRunner] = None

    @Slot()
    def run(self) -> None:
        try:
            with StudioClient(base_url=self.base_url, token=self.token) as client:
                self.runner = StudioRunner(client, self.store, progress=self.progress.emit)
                result = self.runner.run(self.bundle, self.run_dir, self._confirm_eta)
            self.completed.emit(result, str(self.run_dir))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()

    def _confirm_eta(self, baseline: float, remaining: int, estimate: float) -> bool:
        request = EtaRequest(baseline, remaining, estimate, threading.Event())
        self.eta_requested.emit(request)
        request.event.wait()
        return request.accepted

    @Slot()
    def cancel(self) -> None:
        if self.runner:
            self.runner.cancel()


class ResultsChart(QWidget):
    """Small dependency-free bar chart drawn with QtGui only."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._values: List[float] = []
        self._labels: List[str] = []
        self._dark = True
        self.setMinimumHeight(240)

    def set_values(self, values: List[float], labels: List[str], dark: bool) -> None:
        self._values = values
        self._labels = labels
        self._dark = dark
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802 - Qt virtual method name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        foreground = QColor("#dce3ea" if self._dark else "#26323b")
        muted = QColor("#85919d" if self._dark else "#66737e")
        grid = QColor("#303842" if self._dark else "#d8e0e6")
        accent = QColor("#38c7a4" if self._dark else "#15977f")
        painter.setPen(foreground)
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        painter.drawText(18, 26, "Print-time comparison")

        left, top, right, bottom = 58, 44, self.width() - 18, self.height() - 38
        plot_width = max(1, right - left)
        plot_height = max(1, bottom - top)
        maximum = max(self._values, default=0.0)
        maximum = max(maximum, 1.0)
        painter.setFont(QFont("Segoe UI", 8))

        for tick in range(5):
            y = bottom - round(plot_height * tick / 4)
            painter.setPen(grid)
            painter.drawLine(left, y, right, y)
            painter.setPen(muted)
            painter.drawText(4, y + 4, f"{maximum * tick / 4:.1f}")

        if not self._values:
            painter.setPen(muted)
            painter.drawText(left + 12, top + 28, "No completed slice data yet")
            return

        slot = plot_width / len(self._values)
        bar_width = max(3, min(42, round(slot * 0.62)))
        label_step = max(1, math.ceil(len(self._values) / max(1, plot_width // 34)))
        for index, value in enumerate(self._values):
            height = round(plot_height * max(0.0, value) / maximum)
            x = round(left + index * slot + (slot - bar_width) / 2)
            painter.fillRect(x, bottom - height, bar_width, height, accent)
            if index % label_step == 0:
                painter.setPen(muted)
                label = self._labels[index] if index < len(self._labels) else str(index + 1)
                painter.drawText(x, bottom + 18, label)


class AxisCard(QFrame):
    changed = Signal()
    favorites_changed = Signal()
    remove_requested = Signal(object)

    def __init__(
        self,
        definitions: Optional[List[DimensionDefinition]] = None,
        index: int = 0,
        parent: Optional[QWidget] = None,
        catalog: Optional[DimensionCatalog] = None,
    ):
        super().__init__(parent)
        self.setObjectName("card")
        self.catalog = catalog or get_default_catalog()
        self.definitions = definitions or self.catalog.get_all_available_dimensions()
        self.categories = self.catalog.get_categories()
        self._category_dims: List[DimensionDefinition] = []
        self._current_key: Optional[str] = None
        self._preset_chips: List[QPushButton] = []

        # Header: Axis label, category badge, and Remove button
        header = QHBoxLayout()
        self.index_label = QLabel(f"AXIS {chr(65 + index)}")
        self.index_label.setObjectName("muted")
        header.addWidget(self.index_label)

        self.category_badge = QLabel()
        self.category_badge.setObjectName("muted")
        header.addWidget(self.category_badge)
        header.addStretch()

        self.remove = QToolButton()
        self.remove.setText("Remove")
        header.addWidget(self.remove)

        # Category (Process Tab) and Keyword Filter Row
        cat_filter_row = QHBoxLayout()
        cat_filter_row.setSpacing(8)

        cat_label = QLabel("Tab:")
        cat_label.setStyleSheet("font-weight: 600; font-size: 9pt;")
        cat_filter_row.addWidget(cat_label)

        self.category_combo = QComboBox()
        self.category_combo.addItems(self.categories)
        self.category_combo.setMinimumWidth(180)
        cat_filter_row.addWidget(self.category_combo)

        filter_label = QLabel("Filter:")
        filter_label.setStyleSheet("font-weight: 600; font-size: 9pt;")
        cat_filter_row.addWidget(filter_label)

        self.filter_entry = QLineEdit()
        self.filter_entry.setPlaceholderText("Filter settings by keyword...")
        self.filter_entry.setClearButtonEnabled(True)
        cat_filter_row.addWidget(self.filter_entry, 1)

        # Setting Selector Row
        setting_row = QHBoxLayout()
        setting_label = QLabel("Setting:")
        setting_label.setStyleSheet("font-weight: 600; font-size: 9pt;")
        setting_row.addWidget(setting_label)

        self.setting = QComboBox()
        self.setting.setEditable(True)
        self.setting.setInsertPolicy(QComboBox.NoInsert)
        self.setting.completer().setFilterMode(Qt.MatchContains)
        self.setting.completer().setCaseSensitivity(Qt.CaseInsensitive)
        setting_row.addWidget(self.setting, 1)

        self.fav_button = QToolButton()
        self.fav_button.setCursor(Qt.PointingHandCursor)
        self.fav_button.clicked.connect(self._toggle_favorite_clicked)
        setting_row.addWidget(self.fav_button)

        # Metadata & Tooltip Box
        self.meta_box = QFrame()
        self.meta_box.setStyleSheet("background: transparent; border: 0; padding: 0;")
        meta_layout = QVBoxLayout(self.meta_box)
        meta_layout.setContentsMargins(0, 2, 0, 2)
        meta_layout.setSpacing(2)

        self.meta_label = QLabel()
        self.meta_label.setObjectName("muted")
        self.meta_label.setStyleSheet("font-size: 8.5pt;")
        meta_layout.addWidget(self.meta_label)

        self.desc_label = QLabel()
        self.desc_label.setObjectName("muted")
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("font-size: 8.5pt;")
        meta_layout.addWidget(self.desc_label)

        # Presets Area
        self.presets_header = QLabel("Quick-Add Presets (click to toggle):")
        self.presets_header.setStyleSheet("font-size: 8.5pt; font-weight: 600;")
        self.presets_header.setObjectName("muted")

        self.chips_scroll = QScrollArea()
        self.chips_scroll.setWidgetResizable(True)
        self.chips_scroll.setFixedHeight(36)
        self.chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chips_scroll.setStyleSheet("background: transparent; border: 0;")

        self.chips_container = QWidget()
        self.chips_layout = QHBoxLayout(self.chips_container)
        self.chips_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_layout.setSpacing(6)
        self.chips_layout.addStretch()
        self.chips_scroll.setWidget(self.chips_container)

        # Values Row
        values_row = QHBoxLayout()
        val_label = QLabel("Values:")
        val_label.setStyleSheet("font-weight: 600; font-size: 9pt;")
        values_row.addWidget(val_label)

        self.values = QLineEdit()
        self.values.setPlaceholderText("Values separated by commas, e.g. 0.16, 0.20, 0.24")
        values_row.addWidget(self.values, 1)

        # Master Card Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addLayout(cat_filter_row)
        layout.addLayout(setting_row)
        layout.addWidget(self.meta_box)
        layout.addWidget(self.presets_header)
        layout.addWidget(self.chips_scroll)
        layout.addLayout(values_row)

        # Connect Signals
        self.category_combo.currentIndexChanged.connect(self._on_category_changed)
        self.filter_entry.textChanged.connect(self._on_filter_changed)
        self.setting.currentIndexChanged.connect(self._setting_changed)
        self.values.textChanged.connect(self._on_values_text_changed)
        self.remove.clicked.connect(lambda: self.remove_requested.emit(self))

        # Initial populate
        self._populate_settings()
        self._setting_changed()

    def _on_category_changed(self) -> None:
        self.filter_entry.blockSignals(True)
        self.filter_entry.clear()
        self.filter_entry.blockSignals(False)
        self._populate_settings()

    def _on_filter_changed(self) -> None:
        self._populate_settings()

    def _populate_settings(self, preserve_key: Optional[str] = None) -> None:
        cat = self.category_combo.currentText()
        if cat == CAT_ALL or "All Settings" in cat:
            dims = self.catalog.get_all_available_dimensions()
        elif cat == CAT_FAVORITES:
            dims = self.catalog.get_dimensions_for_category(cat, favorite_keys=get_favorite_settings())
        else:
            dims = self.catalog.get_dimensions_for_category(cat)

        q = self.filter_entry.text().strip().lower()
        if q:
            dims = [
                d for d in dims
                if q in d.key.lower() or q in d.label.lower() or (d.tooltip and q in d.tooltip.lower())
            ]

        self._category_dims = dims
        target_key = preserve_key or self.setting.currentData() or (dims[0].key if dims else None)

        self.setting.blockSignals(True)
        self.setting.clear()
        selected_idx = -1
        if not dims and cat == CAT_FAVORITES:
            self.setting.addItem("(No favorite settings saved yet)", "")
        else:
            for idx, d in enumerate(dims):
                self.setting.addItem(d.full_display_name, d.key)
                if d.key == target_key:
                    selected_idx = idx

        if selected_idx >= 0:
            self.setting.setCurrentIndex(selected_idx)
        elif dims:
            self.setting.setCurrentIndex(0)
        elif cat == CAT_FAVORITES:
            self.setting.setCurrentIndex(0)
        self.setting.blockSignals(False)
        self._setting_changed()

    def _setting_changed(self) -> None:
        key = self.setting.currentData()
        definition = self.catalog.get_dimension(key) if key else None
        self._update_favorite_button()
        if not definition:
            if self.category_combo.currentText() == CAT_FAVORITES:
                self.meta_label.setText("No favorite settings saved yet")
                self.desc_label.setText(
                    "To save a favorite setting, browse any category (like Common Settings or Process tabs) "
                    "and click the star (☆) button next to the setting name."
                )
            else:
                self.meta_label.setText("")
                self.desc_label.setText("")
            self.category_badge.setText("")
            self.presets_header.hide()
            self.chips_scroll.hide()
            self.changed.emit()
            return

        parts = [f"Key: {definition.key}", f"Type: {definition.type}"]
        if definition.unit:
            parts.append(f"Unit: {definition.unit}")
        if definition.default_val is not None:
            parts.append(f"Default: {definition.default_val}")
        self.meta_label.setText("  ·  ".join(parts))
        self.desc_label.setText(definition.tooltip.strip() if definition.tooltip else "(No description in schema)")
        self.category_badge.setText(f"[{definition.category}]")
        self.setToolTip(definition.tooltip or "")

        # Auto-populate suggested presets when changing to a different setting!
        if definition.key != self._current_key:
            self._current_key = definition.key
            if definition.presets:
                suggested = [p.value for p in definition.presets[:2]]
                self.values.setText(", ".join(suggested))
            else:
                self.values.clear()

        self._rebuild_preset_chips(definition.presets)
        self._sync_chips_with_values()
        self.changed.emit()

    def _toggle_favorite_clicked(self) -> None:
        key = self.setting.currentData()
        if not key:
            return
        toggle_favorite_setting(key)
        self._update_favorite_button()
        self.favorites_changed.emit()
        if self.category_combo.currentText() == CAT_FAVORITES:
            self._populate_settings()

    def _update_favorite_button(self) -> None:
        key = self.setting.currentData()
        if not key:
            self.fav_button.setEnabled(False)
            self.fav_button.setText("☆")
            self.fav_button.setStyleSheet("font-size: 13pt; padding: 2px 7px; color: #555e68;")
            self.fav_button.setToolTip("Select a setting to save as favorite")
            return
        is_fav = is_favorite_setting(key)
        self.fav_button.setEnabled(True)
        self.fav_button.setText("★" if is_fav else "☆")
        if is_fav:
            self.fav_button.setStyleSheet("font-size: 13pt; padding: 2px 7px; color: #f4bd62; font-weight: bold;")
            self.fav_button.setToolTip(f"Remove '{key}' from Favorites (★)")
        else:
            self.fav_button.setStyleSheet("font-size: 13pt; padding: 2px 7px; color: #85919d;")
            self.fav_button.setToolTip(f"Save '{key}' to Favorites (☆)")

    def update_favorite_state(self) -> None:
        self._update_favorite_button()
        if self.category_combo.currentText() == CAT_FAVORITES:
            self._populate_settings()

    def _rebuild_preset_chips(self, presets: List[PresetValue]) -> None:
        while self.chips_layout.count() > 1:
            item = self.chips_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._preset_chips.clear()

        if not presets:
            self.presets_header.hide()
            self.chips_scroll.hide()
            return

        self.presets_header.show()
        self.chips_scroll.show()

        for p in presets:
            btn = QPushButton(p.display_name())
            btn.setObjectName("chip")
            btn.setCheckable(True)
            btn.setProperty("preset_value", p.value)
            btn.setProperty("display_name", p.display_name())
            btn.setToolTip(p.description or f"Preset value: {p.value}")
            btn.clicked.connect(lambda checked, val=p.value: self._toggle_preset_chip(val))
            self.chips_layout.insertWidget(self.chips_layout.count() - 1, btn)
            self._preset_chips.append(btn)

    def _toggle_preset_chip(self, val: str) -> None:
        val = str(val).strip()
        if not val:
            return
        current_values = [v.strip() for v in self.values.text().split(",") if v.strip()]
        if val in current_values:
            current_values = [v for v in current_values if v != val]
        else:
            current_values.append(val)
        self.values.setText(", ".join(current_values))

    def _sync_chips_with_values(self) -> None:
        current_values = {v.strip() for v in self.values.text().split(",") if v.strip()}
        for chip in self._preset_chips:
            val = chip.property("preset_value")
            disp = chip.property("display_name") or val
            is_active = val in current_values
            chip.blockSignals(True)
            chip.setChecked(is_active)
            chip.setText(f"✓ {disp}" if is_active else disp)
            chip.blockSignals(False)

    def _on_values_text_changed(self) -> None:
        self._sync_chips_with_values()
        self.changed.emit()

    def set_dimension_by_key(self, key: str, values: Optional[List[str]] = None) -> bool:
        dim = self.catalog.get_dimension(key)
        if not dim:
            return False

        current_cat = self.category_combo.currentText()
        cat_dims = (
            self.catalog.get_all_available_dimensions()
            if (current_cat == CAT_ALL or "All Settings" in current_cat)
            else (
                self.catalog.get_dimensions_for_category(current_cat, favorite_keys=get_favorite_settings())
                if current_cat == CAT_FAVORITES
                else self.catalog.get_dimensions_for_category(current_cat)
            )
        )
        if not any(d.key == key for d in cat_dims):
            cat_idx = self.category_combo.findText(dim.category)
            if cat_idx >= 0:
                self.category_combo.blockSignals(True)
                self.category_combo.setCurrentIndex(cat_idx)
                self.category_combo.blockSignals(False)

        self.filter_entry.blockSignals(True)
        self.filter_entry.clear()
        self.filter_entry.blockSignals(False)

        self._populate_settings(preserve_key=dim.key)

        if values is not None:
            self.values.setText(", ".join(str(v) for v in values))
        elif dim.presets:
            self.values.setText(", ".join(p.value for p in dim.presets[:2]))

        self.changed.emit()
        return True

    def definition(self) -> Optional[DimensionDefinition]:
        key = self.setting.currentData()
        if not key:
            return None
        return self.catalog.get_dimension(key)

    def axis(self) -> Optional[AxisDefinition]:
        definition = self.definition()
        values = [part.strip() for part in self.values.text().split(",") if part.strip()]
        if not definition or not values:
            return None
        return AxisDefinition(definition.key, definition.label, values)

    def set_index(self, index: int) -> None:
        self.index_label.setText(f"AXIS {chr(65 + index)}")


class MatrixStudioWindow(QMainWindow):
    cancel_requested = Signal()

    def __init__(self, base_url: Optional[str] = None):
        super().__init__()
        self.catalog = get_default_catalog()
        self.definitions = self.catalog.get_all_available_dimensions()
        self.settings = QSettings("OrcaMatrix", "Studio")
        self.base_url = (
            base_url
            or str(self.settings.value("api_url", "http://127.0.0.1:13130"))
        ).rstrip("/")
        self.api_token = _stored_api_token(self.base_url)
        database, runs = _app_paths()
        self.runs_root = Path(self.settings.value("runs_root", str(runs)))
        self.store = RunBundleStore(self.runs_root)
        self.library = RunLibrary(database)
        self.axes: List[AxisCard] = []
        self.current_bundle: Optional[RunBundle] = None
        self.current_run_dir: Optional[Path] = None
        self.connection_data: Dict[str, Any] = {}
        self.connection_caps: Optional[Capabilities] = None
        self._threads: List[QThread] = []
        self._workers: List[QObject] = []
        self.connection_worker: Optional[ConnectionWorker] = None
        self.current_run_worker: Optional[RunWorker] = None

        self.setWindowTitle("OrcaSlicer Matrix Studio")
        self.resize(1440, 900)
        self.setMinimumSize(1120, 720)
        self._build_ui()
        self._apply_theme(str(self.settings.value("theme", "dark")))
        self._add_axis("layer_height", ["0.16", "0.20"])
        self._add_axis("wall_loops", ["2", "3"])
        self.refresh_library()
        self.refresh_connection()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_rail())

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_builder_page())
        self.pages.addWidget(self._build_run_page())
        self.pages.addWidget(self._build_results_page())
        self.pages.addWidget(self._build_settings_page())
        root_layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)

    def _build_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(255)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(16, 20, 16, 16)
        brand = QLabel("MATRIX\nSTUDIO")
        brand.setObjectName("section")
        layout.addWidget(brand)
        subtitle = QLabel("OrcaSlicer experiment workspace")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(20)

        self.nav_buttons: List[QPushButton] = []
        for text, index in (("New matrix", 0), ("Active run", 1), ("Analyze", 2), ("Settings", 3)):
            button = QPushButton(text)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, i=index: self._show_page(i))
            self.nav_buttons.append(button)
            layout.addWidget(button)
        self.nav_buttons[0].setChecked(True)

        layout.addSpacing(22)
        label = QLabel("RECENT RUNS")
        label.setObjectName("muted")
        layout.addWidget(label)
        self.run_search = QLineEdit()
        self.run_search.setPlaceholderText("Search runs")
        self.run_search.textChanged.connect(self.refresh_library)
        layout.addWidget(self.run_search)
        self.run_list = QListWidget()
        self.run_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.run_list.customContextMenuRequested.connect(self._run_list_context_menu)
        self.run_list.itemDoubleClicked.connect(self._open_library_item)
        self.run_list.keyPressEvent = self._run_list_key_press
        layout.addWidget(self.run_list, 1)

        run_actions_layout = QHBoxLayout()
        self.remove_run_button = QPushButton("Remove run…")
        self.remove_run_button.setToolTip("Remove selected run from history (with option to delete files)")
        self.remove_run_button.clicked.connect(self._remove_selected_run)
        run_actions_layout.addWidget(self.remove_run_button)
        layout.addLayout(run_actions_layout)

        self.connection_label = QLabel("● Connecting…")
        self.connection_label.setObjectName("warning")
        layout.addWidget(self.connection_label)
        return rail

    def _page_header(self, title: str, subtitle: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("title")
        layout.addWidget(heading)
        sub = QLabel(subtitle)
        sub.setObjectName("muted")
        layout.addWidget(sub)
        return layout

    def _build_builder_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(26, 22, 26, 22)
        header = self._page_header("Build a matrix", "Choose up to three settings and review every permutation before slicing.")
        status_row = QHBoxLayout()
        self.profile_label = QLabel("Waiting for OrcaSlicer…")
        self.profile_label.setObjectName("muted")
        refresh = QPushButton("Refresh plate")
        refresh.clicked.connect(self.refresh_connection)
        status_row.addWidget(self.profile_label)
        status_row.addStretch()
        status_row.addWidget(refresh)
        header.addLayout(status_row)
        outer.addLayout(header)
        outer.addSpacing(14)

        splitter = QSplitter(Qt.Horizontal)
        axis_host = QWidget()
        axis_layout = QVBoxLayout(axis_host)
        axis_layout.setContentsMargins(0, 0, 10, 0)
        axis_header = QHBoxLayout()
        axis_header.setSpacing(6)
        section = QLabel("Experiment axes")
        section.setObjectName("section")
        self.load_matrix_button = QPushButton("📂 Load Test…")
        self.load_matrix_button.setToolTip("Load a saved matrix test file (.orcamatrix.json) to repeat with this model")
        self.load_matrix_button.clicked.connect(lambda: self.load_matrix_test_file())

        self.save_matrix_button = QPushButton("💾 Save Test…")
        self.save_matrix_button.setToolTip("Save this matrix configuration to repeat with other models")
        self.save_matrix_button.clicked.connect(lambda: self.save_matrix_test_file())

        self.add_axis_button = QPushButton("+ Add axis")
        self.add_axis_button.clicked.connect(self._add_axis)
        axis_header.addWidget(section)
        axis_header.addStretch()
        axis_header.addWidget(self.load_matrix_button)
        axis_header.addWidget(self.save_matrix_button)
        axis_header.addWidget(self.add_axis_button)
        axis_layout.addLayout(axis_header)
        self.plate_preview = QLabel("Plate preview unavailable")
        self.plate_preview.setObjectName("muted")
        self.plate_preview.setAlignment(Qt.AlignCenter)
        self.plate_preview.setMinimumHeight(150)
        self.plate_preview.setMaximumHeight(210)
        self.plate_preview.setStyleSheet("border: 1px solid #2a3139; border-radius: 8px; padding: 6px;")
        axis_layout.addWidget(self.plate_preview)
        self.axis_container = QVBoxLayout()
        self.axis_container.setSpacing(10)
        self.axis_container.addStretch()
        axis_inner = QWidget()
        axis_inner.setLayout(self.axis_container)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(axis_inner)
        axis_layout.addWidget(scroll, 1)
        splitter.addWidget(axis_host)

        preview = QFrame()
        preview.setObjectName("card")
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(16, 14, 16, 14)
        self.variant_summary = QLabel("0 variants")
        self.variant_summary.setObjectName("section")
        self.variant_hint = QLabel("Add complete axes to preview the matrix.")
        self.variant_hint.setObjectName("muted")
        preview_layout.addWidget(self.variant_summary)
        preview_layout.addWidget(self.variant_hint)
        self.variant_table = QTableWidget(0, 3)
        self.variant_table.setHorizontalHeaderLabels(["#", "Variant", "Changed settings"])
        self.variant_table.setAlternatingRowColors(True)
        self.variant_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.variant_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.variant_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.variant_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        preview_layout.addWidget(self.variant_table, 1)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Warn above"))
        self.soft_limit = QSpinBox()
        self.soft_limit.setRange(2, HARD_VARIANT_LIMIT)
        self.soft_limit.setValue(int(self.settings.value("soft_limit", 8)))
        controls.addWidget(self.soft_limit)
        controls.addStretch()
        self.run_button = QPushButton("Review and run")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self._start_run)
        controls.addWidget(self.run_button)
        preview_layout.addLayout(controls)
        splitter.addWidget(preview)
        splitter.setSizes([620, 700])
        outer.addWidget(splitter, 1)
        return page

    def _build_run_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addLayout(self._page_header("Active run", "Live slicing progress with guaranteed configuration restoration."))
        layout.addSpacing(18)
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        self.run_state = QLabel("No run is active")
        self.run_state.setObjectName("section")
        self.run_detail = QLabel("Build a matrix to begin.")
        self.run_detail.setObjectName("muted")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.cancel_button = QPushButton("Cancel safely")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_requested)
        card_layout.addWidget(self.run_state)
        card_layout.addWidget(self.run_detail)
        card_layout.addWidget(self.progress_bar)
        card_layout.addWidget(self.cancel_button, alignment=Qt.AlignRight)
        layout.addWidget(card)
        self.run_variants = QTableWidget(0, 4)
        self.run_variants.setHorizontalHeaderLabels(["#", "Variant", "State", "Slice time"])
        self.run_variants.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.run_variants, 1)
        return page

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addLayout(self._page_header("Analyze", "Compare time, material, and cost; open up to eight variants in synchronized Compare View."))

        top = QHBoxLayout()
        top.setSpacing(8)
        self.result_banner = QLabel("Complete a run or open one from the library.")
        self.result_banner.setObjectName("muted")
        top.addWidget(self.result_banner, 1)

        self.copy_summary_btn = QPushButton("📋 Copy Summary")
        self.copy_summary_btn.setToolTip("Copy Summary Markdown table to clipboard")
        self.copy_summary_btn.setEnabled(False)
        self.copy_summary_btn.clicked.connect(self._copy_summary_markdown)
        top.addWidget(self.copy_summary_btn)

        self.copy_filament_btn = QPushButton("📋 Copy Breakdown")
        self.copy_filament_btn.setToolTip("Copy Filament Breakdown Markdown table to clipboard")
        self.copy_filament_btn.setEnabled(False)
        self.copy_filament_btn.clicked.connect(self._copy_filament_markdown)
        top.addWidget(self.copy_filament_btn)

        self.open_html_btn = QPushButton("🌐 Open HTML Report")
        self.open_html_btn.setToolTip("Open full interactive dark-mode HTML report in browser with SVG Pareto and breakdown charts")
        self.open_html_btn.setEnabled(False)
        self.open_html_btn.clicked.connect(self._open_html_report)
        top.addWidget(self.open_html_btn)

        self.open_compare = QPushButton("Open selected in Compare View")
        self.open_compare.setEnabled(False)
        self.open_compare.clicked.connect(self._launch_compare)
        top.addWidget(self.open_compare)
        layout.addLayout(top)

        # Tab widget for multiple report views
        self.results_tabs = QTabWidget()

        # --- TAB 1: Slicing Summary & Print-Time Chart ---
        tab_summary = QWidget()
        tab_summary_layout = QVBoxLayout(tab_summary)
        tab_summary_layout.setContentsMargins(0, 10, 0, 0)
        split = QSplitter(Qt.Vertical)

        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(["Variant", "Print time", "Filament", "Cost", "State"])
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.results_table.horizontalHeader().setSortIndicator(0, Qt.AscendingOrder)
        self.results_table.setSortingEnabled(True)
        self.results_table.horizontalHeader().setSortIndicatorShown(True)
        self.results_table.itemSelectionChanged.connect(self._result_selection_changed)
        split.addWidget(self.results_table)

        self.chart_view = ResultsChart()
        split.addWidget(self.chart_view)
        split.setSizes([400, 340])
        tab_summary_layout.addWidget(split)
        self.results_tabs.addTab(tab_summary, "Slicing Summary")

        # --- TAB 2: Filament by Line Type ---
        tab_filament = QWidget()
        tab_filament_layout = QVBoxLayout(tab_filament)
        tab_filament_layout.setContentsMargins(0, 10, 0, 0)

        self.filament_table = QTableWidget(0, 9)
        self.filament_table.setHorizontalHeaderLabels([
            "Variant", "Inner wall", "Outer wall", "Infill", "Solid infill", "Top surface", "Support", "Brim", "Total"
        ])
        self.filament_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.filament_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.filament_table.horizontalHeader().setSortIndicator(0, Qt.AscendingOrder)
        self.filament_table.setSortingEnabled(True)
        self.filament_table.horizontalHeader().setSortIndicatorShown(True)
        tab_filament_layout.addWidget(self.filament_table)
        self.results_tabs.addTab(tab_filament, "Filament by Line Type")

        layout.addWidget(self.results_tabs, 1)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addLayout(self._page_header("Settings", "Connection, appearance, storage, and safety limits."))
        card = QFrame()
        card.setObjectName("card")
        form = QFormLayout(card)
        self.api_url = QLineEdit(self.base_url)
        self.api_token_edit = QLineEdit(self.api_token or "")
        self.api_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_token_edit.setPlaceholderText("Auto-discovered for local OrcaSlicer")
        self.viewer_executable_edit = QLineEdit(
            str(self.settings.value("viewer_executable", _default_viewer_executable()))
        )
        viewer_browse = QPushButton("Browse…")
        viewer_browse.clicked.connect(self._browse_viewer_executable)
        viewer_row = QHBoxLayout()
        viewer_row.addWidget(self.viewer_executable_edit, 1)
        viewer_row.addWidget(viewer_browse)
        self.theme = QComboBox()
        self.theme.addItems(["dark", "light"])
        self.theme.setCurrentText(str(self.settings.value("theme", "dark")))
        self.theme.currentTextChanged.connect(self._apply_theme)
        self.run_root_edit = QLineEdit(str(self.runs_root))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_runs_root)
        root_row = QHBoxLayout()
        root_row.addWidget(self.run_root_edit, 1)
        root_row.addWidget(browse)
        form.addRow("OrcaSlicer API", self.api_url)
        form.addRow("API token", self.api_token_edit)
        form.addRow("Compare Viewer", viewer_row)
        form.addRow("Theme", self.theme)
        form.addRow("Run library", root_row)
        save = QPushButton("Save settings")
        save.setObjectName("primary")
        save.clicked.connect(self._save_settings)
        form.addRow("", save)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)

    def _add_axis(self, default_key: Optional[str] = None, default_values: Optional[List[str]] = None) -> None:
        if len(self.axes) >= 3:
            return
        if default_key is None:
            existing_keys = {c.definition().key for c in self.axes if c.definition()}
            defaults = [
                ("layer_height", ["0.16", "0.20"]),
                ("wall_loops", ["2", "3"]),
                ("sparse_infill_density", ["15%", "25%"]),
                ("wall_generator", ["classic", "arachne"]),
            ]
            for candidate_key, candidate_vals in defaults:
                if candidate_key not in existing_keys:
                    default_key = candidate_key
                    default_values = candidate_vals
                    break
        card = AxisCard(self.definitions, len(self.axes), catalog=self.catalog)
        if default_key:
            card.set_dimension_by_key(default_key, default_values)
        card.changed.connect(self._update_preview)
        card.remove_requested.connect(self._remove_axis)
        card.favorites_changed.connect(self._on_favorites_changed)
        self.axes.append(card)
        self.axis_container.insertWidget(self.axis_container.count() - 1, card)
        self.add_axis_button.setEnabled(len(self.axes) < 3)
        self._update_preview()

    def _on_favorites_changed(self) -> None:
        for card in self.axes:
            card.update_favorite_state()

    def _remove_axis(self, card: AxisCard) -> None:
        if card not in self.axes:
            return
        self.axes.remove(card)
        card.deleteLater()
        for index, item in enumerate(self.axes):
            item.set_index(index)
        self.add_axis_button.setEnabled(True)
        self._update_preview()

    def _axis_definitions(self) -> List[AxisDefinition]:
        return [axis for card in self.axes if (axis := card.axis()) is not None]

    def _variants(self) -> List[Any]:
        axes = self._axis_definitions()
        if len(axes) != len(self.axes) or not axes:
            return []
        keys = [axis.key for axis in axes]
        if len(set(keys)) != len(keys):
            raise ValueError("Each axis must use a different setting.")
        matrix = {axis.key: axis.values for axis in axes}
        return build_variants(matrix, max_variants=HARD_VARIANT_LIMIT)

    def _update_preview(self) -> None:
        try:
            variants = self._variants()
            count = len(variants)
            self.variant_table.setRowCount(count)
            for row, variant in enumerate(variants):
                self.variant_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
                self.variant_table.setItem(row, 1, QTableWidgetItem(variant.name))
                self.variant_table.setItem(row, 2, QTableWidgetItem(" · ".join(f"{k}={v}" for k, v in variant.changes.items())))
            self.variant_summary.setText(f"{count} variants")
            if count > self.soft_limit.value():
                self.variant_hint.setText(f"Large run: confirmation required above your soft limit of {self.soft_limit.value()}.")
                self.variant_hint.setObjectName("warning")
            else:
                self.variant_hint.setText("Ready to review and slice.")
                self.variant_hint.setObjectName("muted")
            self.variant_hint.style().unpolish(self.variant_hint)
            self.variant_hint.style().polish(self.variant_hint)
            self.run_button.setEnabled(count >= 2 and self.connection_caps is not None)
        except (ValueError, VariantLimitExceededError) as exc:
            self.variant_table.setRowCount(0)
            self.variant_summary.setText("Matrix needs attention")
            self.variant_hint.setText(str(exc).splitlines()[0])
            self.run_button.setEnabled(False)

    def refresh_connection(self) -> None:
        self.connection_label.setText("● Connecting…")
        thread = QThread(self)
        worker = ConnectionWorker(self.base_url, self.api_token)
        worker.moveToThread(thread)
        thread._worker = worker
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._connection_succeeded)
        worker.failed.connect(self._connection_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)

        def _cleanup() -> None:
            if thread in self._threads:
                self._threads.remove(thread)
            if worker in self._workers:
                self._workers.remove(worker)
            if getattr(self, "connection_worker", None) is worker:
                self.connection_worker = None
            if hasattr(thread, "_worker"):
                thread._worker = None

        thread.finished.connect(_cleanup)
        thread.finished.connect(thread.deleteLater)
        self.connection_worker = worker
        self._threads.append(thread)
        self._workers.append(worker)
        thread.start()

    @Slot(object, object, object, bytes)
    def _connection_succeeded(self, caps: Capabilities, status: Dict[str, Any], objects: List[Dict[str, Any]], preview: bytes) -> None:
        sender = self.sender()
        if sender is not None and getattr(self, "connection_worker", None) is not None and sender is not self.connection_worker:
            return
        self.connection_caps = caps
        self.connection_data = status
        self.connection_label.setText(f"● Connected · {caps.app_version}")
        self.connection_label.setObjectName("good")
        presets = status.get("presets", {})
        names = [item.get("name", "") for item in objects if item.get("name")]
        self.profile_label.setText(
            f"{presets.get('printer', 'Printer')}  ·  {presets.get('print', 'Process')}  ·  "
            f"{len(names)} object{'s' if len(names) != 1 else ''} on plate"
        )
        image = QPixmap()
        if preview and image.loadFromData(preview):
            self.plate_preview.setPixmap(
                image.scaled(self.plate_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self.plate_preview.setText("")
        else:
            self.plate_preview.setPixmap(QPixmap())
            self.plate_preview.setText("Plate preview unavailable")
        self._update_preview()

    @Slot(str)
    def _connection_failed(self, message: str) -> None:
        sender = self.sender()
        if sender is not None and getattr(self, "connection_worker", None) is not None and sender is not self.connection_worker:
            return
        self.connection_caps = None
        self.connection_label.setText("● OrcaSlicer unavailable")
        self.connection_label.setObjectName("warning")
        self.profile_label.setText(message)
        self.plate_preview.setPixmap(QPixmap())
        self.plate_preview.setText("Plate preview unavailable")
        self._update_preview()

    def _start_run(self) -> None:
        try:
            variants = self._variants()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid matrix", str(exc))
            return
        if len(variants) > self.soft_limit.value():
            answer = QMessageBox.question(
                self,
                "Confirm large run",
                f"This matrix contains {len(variants)} variants. Slice the baseline and estimate the remaining time?",
            )
            if answer != QMessageBox.Yes:
                return
        axes = self._axis_definitions()
        records = [
            VariantRecord(str(uuid.uuid4()), index + 1, item.name, item.changes)
            for index, item in enumerate(variants)
        ]
        name = " × ".join(f"{axis.label} ({len(axis.values)})" for axis in axes)
        bundle = RunBundle.create(name, axes, records)
        bundle.settings["soft_variant_limit"] = self.soft_limit.value()
        run_dir = self.store.create_directory(bundle)
        self.store.save(run_dir, bundle)
        self.library.upsert(bundle, run_dir)
        self.current_bundle = bundle
        self.current_run_dir = run_dir
        self._populate_run_table(bundle)
        self._show_page(1)
        self.cancel_button.setEnabled(True)

        thread = QThread(self)
        worker = RunWorker(self.base_url, self.api_token, bundle, run_dir, self.store)
        worker.moveToThread(thread)
        thread._worker = worker
        thread.started.connect(worker.run)
        worker.progress.connect(self._run_progress)
        worker.eta_requested.connect(self._eta_requested)
        worker.completed.connect(self._run_completed)
        worker.failed.connect(self._run_failed)
        self.cancel_requested.connect(worker.cancel, Qt.DirectConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)

        def _cleanup() -> None:
            try:
                self.cancel_requested.disconnect(worker.cancel)
            except (RuntimeError, TypeError):
                pass
            if thread in self._threads:
                self._threads.remove(thread)
            if worker in self._workers:
                self._workers.remove(worker)
            if getattr(self, "current_run_worker", None) is worker:
                self.current_run_worker = None
            if hasattr(thread, "_worker"):
                thread._worker = None

        thread.finished.connect(_cleanup)
        thread.finished.connect(thread.deleteLater)
        self.current_run_worker = worker
        self._threads.append(thread)
        self._workers.append(worker)
        thread.start()

    @Slot(object, object, str, float)
    def _run_progress(self, bundle: RunBundle, variant: Optional[VariantRecord], message: str, value: float) -> None:
        self.current_bundle = bundle
        self.run_state.setText(message)
        self.run_detail.setText(variant.name if variant else bundle.state.replace("_", " ").title())
        self.progress_bar.setValue(round(value * 1000))
        self._populate_run_table(bundle)

    @Slot(object)
    def _eta_requested(self, request: EtaRequest) -> None:
        minutes = math.ceil(request.estimated_seconds / 60)
        answer = QMessageBox.question(
            self,
            "Baseline complete",
            f"Baseline sliced in {request.baseline_seconds:.1f}s. The remaining {request.remaining} variants are estimated at about {minutes} minute(s). Continue?",
        )
        request.accepted = answer == QMessageBox.Yes
        request.event.set()

    @Slot(object, str)
    def _run_completed(self, bundle: RunBundle, run_dir: str) -> None:
        self.current_bundle = bundle
        self.current_run_dir = Path(run_dir)
        self.cancel_button.setEnabled(False)
        self.library.upsert(bundle, Path(run_dir))
        self.refresh_library()
        try:
            generate_bundle_html_report(bundle, Path(run_dir))
        except Exception:
            pass
        self._populate_results(bundle)
        self._show_page(2)

    @Slot(str)
    def _run_failed(self, message: str) -> None:
        self.cancel_button.setEnabled(False)
        QMessageBox.critical(self, "Run failed", message)

    def _populate_run_table(self, bundle: RunBundle) -> None:
        self.run_variants.setRowCount(len(bundle.variants))
        for row, variant in enumerate(bundle.variants):
            values = [str(variant.ordinal), variant.name, variant.state, f"{variant.slice_wall_seconds:.1f}s" if variant.slice_wall_seconds else "—"]
            for column, value in enumerate(values):
                self.run_variants.setItem(row, column, QTableWidgetItem(value))

    def _populate_results(self, bundle: RunBundle) -> None:
        # Populate Tab 1: Slicing Summary table
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(len(bundle.variants))
        chart_values: List[float] = []
        categories: List[str] = []

        state_prio = {"completed": 0, "running": 1, "pending": 2, "failed": 3, "cancelled": 4}

        for row, variant in enumerate(bundle.variants):
            stats = variant.stats or {}
            seconds = stats.get("time_s")
            mass = stats.get("filament_g")
            cost = stats.get("cost_usd")

            # Variant name
            var_sort = variant.ordinal if variant.ordinal is not None else row
            var_item = SortableTableWidgetItem(variant.name, sort_key=var_sort, user_data=variant.id)
            var_item.setToolTip(variant.name)
            self.results_table.setItem(row, 0, var_item)

            # Print time (sorted numerically by seconds)
            if seconds is not None:
                time_item = SortableTableWidgetItem(f"{float(seconds) / 60:.1f} min", sort_key=float(seconds), user_data=variant.id)
            else:
                time_item = SortableTableWidgetItem("—", sort_key=float("inf"), user_data=variant.id)
            time_item.setTextAlignment(Qt.AlignCenter)
            self.results_table.setItem(row, 1, time_item)

            # Filament mass (sorted numerically by grams)
            if mass is not None:
                mass_item = SortableTableWidgetItem(f"{float(mass):.1f} g", sort_key=float(mass), user_data=variant.id)
            else:
                mass_item = SortableTableWidgetItem("—", sort_key=float("inf"), user_data=variant.id)
            mass_item.setTextAlignment(Qt.AlignCenter)
            self.results_table.setItem(row, 2, mass_item)

            # Cost (sorted numerically by USD)
            if cost is not None:
                cost_item = SortableTableWidgetItem(f"${float(cost):.2f}", sort_key=float(cost), user_data=variant.id)
            else:
                cost_item = SortableTableWidgetItem("—", sort_key=float("inf"), user_data=variant.id)
            cost_item.setTextAlignment(Qt.AlignCenter)
            self.results_table.setItem(row, 3, cost_item)

            # State
            prio = state_prio.get(variant.state, 9)
            state_item = SortableTableWidgetItem(variant.state, sort_key=(prio, variant.name), user_data=variant.id)
            state_item.setTextAlignment(Qt.AlignCenter)
            self.results_table.setItem(row, 4, state_item)

            chart_values.append(float(seconds or 0) / 60.0)
            categories.append(str(variant.ordinal))

        self.results_table.setSortingEnabled(True)
        self.chart_view.set_values(chart_values, categories, self.theme.currentText() == "dark")

        # Populate Tab 2: Filament by Line Type table
        self.filament_table.setSortingEnabled(False)
        self.filament_table.setRowCount(len(bundle.variants))

        role_keys = [
            ("Inner wall", ["Inner wall"]),
            ("Outer wall", ["Outer wall"]),
            ("Infill", ["Sparse infill", "Infill"]),
            ("Solid infill", ["Internal solid infill", "Solid infill"]),
            ("Top surface", ["Top surface"]),
            ("Support", ["Support", "Support interface"]),
            ("Brim", ["Brim"]),
        ]

        for row, variant in enumerate(bundle.variants):
            stats = variant.stats or {}
            by_role = stats.get("filament_by_role") or {}
            total_mass = stats.get("filament_g")

            var_sort = variant.ordinal if variant.ordinal is not None else row
            var_item = SortableTableWidgetItem(variant.name, sort_key=var_sort, user_data=variant.id)
            var_item.setToolTip(variant.name)
            self.filament_table.setItem(row, 0, var_item)

            col_idx = 1
            for header_name, lookup_roles in role_keys:
                role_val = sum(float(by_role.get(r, 0.0)) for r in lookup_roles if r in by_role)
                if role_val > 0.001:
                    cell_item = SortableTableWidgetItem(f"{role_val:.2f} g", sort_key=role_val, user_data=variant.id)
                elif by_role:
                    cell_item = SortableTableWidgetItem("0.00 g", sort_key=0.0, user_data=variant.id)
                else:
                    cell_item = SortableTableWidgetItem("—", sort_key=float("inf"), user_data=variant.id)
                cell_item.setTextAlignment(Qt.AlignCenter)
                self.filament_table.setItem(row, col_idx, cell_item)
                col_idx += 1

            if total_mass is not None:
                tot_item = SortableTableWidgetItem(f"{float(total_mass):.1f} g", sort_key=float(total_mass), user_data=variant.id)
            else:
                tot_item = SortableTableWidgetItem("—", sort_key=float("inf"), user_data=variant.id)
            tot_item.setTextAlignment(Qt.AlignCenter)
            self.filament_table.setItem(row, col_idx, tot_item)

        self.filament_table.setSortingEnabled(True)

        completed = sum(1 for item in bundle.variants if item.state == "completed")
        self.result_banner.setText(f"{completed}/{len(bundle.variants)} variants completed · {bundle.state.replace('_', ' ').title()}")
        self.open_html_btn.setEnabled(True)
        self.copy_summary_btn.setEnabled(True)
        self.copy_filament_btn.setEnabled(True)

    def _result_selection_changed(self) -> None:
        selected = sorted({index.row() for index in self.results_table.selectedIndexes()})
        self.open_compare.setEnabled(bool(selected) and len(selected) <= 8 and self.current_run_dir is not None)

    def _launch_compare(self) -> None:
        if not self.current_bundle or not self.current_run_dir:
            return
        selected_rows = sorted({index.row() for index in self.results_table.selectedIndexes()})
        ids: List[str] = []
        for row in selected_rows[:8]:
            item = self.results_table.item(row, 0)
            if item:
                var_id = item.data(Qt.UserRole)
                if var_id:
                    ids.append(str(var_id))
        if not ids:
            return
        executable = self.viewer_executable_edit.text().strip() or _default_viewer_executable()
        try:
            subprocess.Popen(
                [executable, "--compare", str(self.current_run_dir / "run.json"), "--compare-variants", ",".join(ids)],
                cwd=self.current_run_dir,
            )
        except OSError as exc:
            QMessageBox.warning(self, "Could not open Compare View", str(exc))

    def _copy_summary_markdown(self) -> None:
        if not self.current_bundle:
            return
        md = self.current_bundle.comparison.get("summary_markdown", "")
        if not md:
            from .analytics import compute_matrix_comparison
            from .studio_runner import StudioRunner
            completed = [StudioRunner._variant_for_analytics(v) for v in self.current_bundle.variants if v.state == "completed"]
            if completed:
                comp = compute_matrix_comparison(completed, completed[0]["name"])
                md = comp.get("summary_markdown", "")
        if md:
            QApplication.clipboard().setText(md)
            self.result_banner.setText("✓ Summary Markdown copied to clipboard!")

    def _copy_filament_markdown(self) -> None:
        if not self.current_bundle:
            return
        md = self.current_bundle.comparison.get("line_type_markdown", "")
        if not md:
            from .analytics import compute_matrix_comparison
            from .studio_runner import StudioRunner
            completed = [StudioRunner._variant_for_analytics(v) for v in self.current_bundle.variants if v.state == "completed"]
            if completed:
                comp = compute_matrix_comparison(completed, completed[0]["name"])
                md = comp.get("line_type_markdown", "")
        if md:
            QApplication.clipboard().setText(md)
            self.result_banner.setText("✓ Filament breakdown Markdown copied to clipboard!")

    def _open_html_report(self) -> None:
        if not self.current_bundle or not self.current_run_dir:
            QMessageBox.information(self, "No Run Selected", "Select or complete a run first to view its report.")
            return
        try:
            report_path = generate_bundle_html_report(self.current_bundle, self.current_run_dir)
            import webbrowser
            webbrowser.open(report_path.as_uri())
            self.result_banner.setText(f"✓ Opened HTML report: {report_path.name}")
        except Exception as exc:
            QMessageBox.warning(self, "Could not open HTML report", str(exc))

    def save_matrix_test_file(self, target_path: Optional[Union[str, Path]] = None) -> Optional[Path]:
        axes_defs = self._axis_definitions()
        if not axes_defs:
            QMessageBox.warning(self, "No Axes Configured", "Please configure at least one axis with valid values before saving.")
            return None

        if target_path is None:
            slug = "_x_".join(a.key for a in axes_defs)
            default_name = f"matrix_{slug}.orcamatrix.json"
            documents_dir = Path.home() / "Documents" / "OrcaMatrix"
            documents_dir.mkdir(parents=True, exist_ok=True)
            default_path = str(documents_dir / default_name)
            chosen, _ = QFileDialog.getSaveFileName(
                self,
                "Save Matrix Test",
                default_path,
                "OrcaSlicer Matrix Test (*.orcamatrix.json *.json);;All Files (*)",
            )
            if not chosen:
                return None
            target_path = Path(chosen)
        else:
            target_path = Path(target_path)

        recipe = {
            "format": "orcaslicer_matrix_test",
            "schema_version": 1,
            "name": " × ".join(a.label for a in axes_defs),
            "created_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "axes": [
                {
                    "key": a.key,
                    "label": a.label,
                    "values": list(a.values),
                }
                for a in axes_defs
            ],
        }

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(recipe, f, indent=2)

        self.profile_label.setText(f"Saved matrix test: {target_path.name}")
        return target_path

    def load_matrix_test_file(self, source_path: Optional[Union[str, Path]] = None) -> bool:
        if source_path is None:
            documents_dir = Path.home() / "Documents" / "OrcaMatrix"
            chosen, _ = QFileDialog.getOpenFileName(
                self,
                "Load Matrix Test",
                str(documents_dir) if documents_dir.exists() else "",
                "OrcaSlicer Matrix Test (*.orcamatrix.json *.json);;All Files (*)",
            )
            if not chosen:
                return False
            source_path = Path(chosen)
        else:
            source_path = Path(source_path)

        if not source_path.is_file():
            QMessageBox.warning(self, "File Not Found", f"Could not find file: {source_path}")
            return False

        try:
            with open(source_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            QMessageBox.critical(self, "Failed to read file", f"Invalid JSON file: {exc}")
            return False

        axes_data: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            if "axes" in data and isinstance(data["axes"], list):
                axes_data = data["axes"]
            elif "matrix" in data and isinstance(data["matrix"], dict):
                axes_data = [{"key": k, "values": v} for k, v in data["matrix"].items()]
        elif isinstance(data, list):
            axes_data = data

        if not axes_data:
            QMessageBox.warning(self, "Invalid Matrix Test", "The selected file does not contain any matrix axes configurations.")
            return False

        # Clear existing axis cards
        while self.axes:
            self._remove_axis(self.axes[0])

        loaded_count = 0
        for axis_info in axes_data[:3]:
            if not isinstance(axis_info, dict):
                continue
            key = axis_info.get("key")
            vals = axis_info.get("values")
            if not key or not self.catalog.get_dimension(key):
                continue
            if isinstance(vals, (list, tuple)):
                str_vals = [str(v).strip() for v in vals if str(v).strip()]
            elif isinstance(vals, str):
                str_vals = [v.strip() for v in vals.split(",") if v.strip()]
            else:
                str_vals = []
            self._add_axis(default_key=key, default_values=str_vals)
            loaded_count += 1

        if loaded_count == 0:
            QMessageBox.warning(self, "No Valid Settings Found", "None of the settings in the matrix file matched available settings in OrcaSlicer.")
            return False

        self._show_page(0)
        self.profile_label.setText(f"Loaded matrix test: {source_path.name} ({loaded_count} axes)")
        return True

    def _run_list_key_press(self, event: Any) -> None:
        if event.key() == Qt.Key_Delete:
            self._remove_selected_run()
            return
        QListWidget.keyPressEvent(self.run_list, event)

    def _run_list_context_menu(self, pos: QPoint) -> None:
        item = self.run_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        open_action = menu.addAction("Open / Analyze")
        reuse_action = menu.addAction("Load Matrix into Builder")
        remove_action = menu.addAction("Remove Run…")
        chosen = menu.exec(self.run_list.mapToGlobal(pos))
        if chosen == open_action:
            self._open_library_item(item)
        elif chosen == reuse_action:
            run_path = Path(item.data(Qt.UserRole))
            self.load_matrix_test_file(run_path / "run.json")
        elif chosen == remove_action:
            self._remove_run_item(item)

    def _remove_selected_run(self) -> None:
        item = self.run_list.currentItem()
        if not item:
            if self.run_list.count() > 0:
                item = self.run_list.item(0)
            else:
                return
        self._remove_run_item(item)

    def _remove_run_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        run_id = item.data(Qt.UserRole + 1)
        name = item.data(Qt.UserRole + 2) or "this run"

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle("Remove Run")
        msg.setText(f"Remove '{name}' from recent runs?")
        msg.setInformativeText(
            "Would you also like to permanently delete the run folder and sliced files from disk?"
        )
        delete_files_btn = msg.addButton("Delete Files & Remove", QMessageBox.DestructiveRole)
        remove_only_btn = msg.addButton("Remove from List Only", QMessageBox.ActionRole)
        cancel_btn = msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.setDefaultButton(cancel_btn)

        msg.exec()
        clicked = msg.clickedButton()
        if clicked == cancel_btn:
            return

        delete_files = (clicked == delete_files_btn)
        self.remove_run(run_id=run_id, path=path, delete_files=delete_files)

    def remove_run(
        self,
        run_id: Optional[str] = None,
        path: Optional[str] = None,
        delete_files: bool = False,
    ) -> None:
        """Remove run from library database and optionally delete run folder from disk."""
        if delete_files and path:
            run_path = Path(path)
            if run_path.exists() and run_path.is_dir():
                shutil.rmtree(run_path, ignore_errors=True)

        self.library.delete_run(run_id=run_id, path=path)

        if getattr(self, "current_run_dir", None) and path and str(self.current_run_dir) == str(Path(path)):
            self.current_bundle = None
            self.current_run_dir = None
            if hasattr(self, "results_table"):
                self.results_table.setRowCount(0)
            if hasattr(self, "filament_table"):
                self.filament_table.setRowCount(0)
            if hasattr(self, "chart_view"):
                self.chart_view.set_values([], [], self.theme.currentText() == "dark")
            if hasattr(self, "result_banner"):
                self.result_banner.setText("Complete a run or open one from the library.")
            if hasattr(self, "open_compare"):
                self.open_compare.setEnabled(False)
            if hasattr(self, "open_html_btn"):
                self.open_html_btn.setEnabled(False)
            if hasattr(self, "copy_summary_btn"):
                self.copy_summary_btn.setEnabled(False)
            if hasattr(self, "copy_filament_btn"):
                self.copy_filament_btn.setEnabled(False)

        self.refresh_library()

    def refresh_library(self) -> None:
        if not hasattr(self, "run_list"):
            return
        self.run_list.clear()
        for row in self.library.list_runs(self.run_search.text() if hasattr(self, "run_search") else ""):
            item = QListWidgetItem(f"{row['name']}\n{row['variant_count']} variants · {row['state']}")
            item.setData(Qt.UserRole, row["path"])
            item.setData(Qt.UserRole + 1, row.get("run_id", ""))
            item.setData(Qt.UserRole + 2, row["name"])
            self.run_list.addItem(item)

    def _open_library_item(self, item: QListWidgetItem) -> None:
        try:
            run_dir = Path(item.data(Qt.UserRole))
            bundle = self.store.load(run_dir)
            self.current_bundle = bundle
            self.current_run_dir = run_dir
            self._populate_results(bundle)
            self._show_page(2)
        except Exception as exc:
            QMessageBox.warning(self, "Could not open run", str(exc))

    def _browse_runs_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose run-library folder", self.run_root_edit.text())
        if path:
            self.run_root_edit.setText(path)

    def _browse_viewer_executable(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose OrcaSlicer executable",
            self.viewer_executable_edit.text(),
            "Applications (*.exe);;All files (*)",
        )
        if path:
            self.viewer_executable_edit.setText(path)

    def _save_settings(self) -> None:
        previous_url = self.base_url
        self.base_url = self.api_url.text().strip().rstrip("/")
        token = self.api_token_edit.text().strip()
        self.api_token = token or None
        if not _is_local_endpoint(self.base_url):
            try:
                if token:
                    keyring.set_password(KEYRING_SERVICE, self.base_url, token)
                else:
                    keyring.delete_password(KEYRING_SERVICE, self.base_url)
            except PasswordDeleteError:
                pass
            except KeyringError as exc:
                QMessageBox.warning(
                    self,
                    "Credential storage unavailable",
                    f"The API token will be used for this session but could not be stored securely: {exc}",
                )
        elif previous_url != self.base_url:
            self.api_token = None
        self.runs_root = Path(self.run_root_edit.text()).expanduser()
        self.store = RunBundleStore(self.runs_root)
        self.settings.setValue("api_url", self.base_url)
        self.settings.setValue("viewer_executable", self.viewer_executable_edit.text().strip())
        self.settings.setValue("runs_root", str(self.runs_root))
        self.settings.setValue("theme", self.theme.currentText())
        self.settings.setValue("soft_limit", self.soft_limit.value())
        self.refresh_connection()

    def _apply_theme(self, theme: str) -> None:
        QApplication.instance().setStyleSheet(DARK_STYLESHEET if theme == "dark" else LIGHT_STYLESHEET)
        self.settings.setValue("theme", theme)
        if hasattr(self, "current_bundle") and self.current_bundle:
            self._populate_results(self.current_bundle)

    def closeEvent(self, event: Any) -> None:
        self.cancel_requested.emit()
        for thread in list(self._threads):
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(2000)
            except RuntimeError:
                pass
        super().closeEvent(event)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OrcaSlicer Matrix Studio")
    parser.add_argument("--connect", default=os.getenv("ORCA_API_URL"))
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("OrcaSlicer Matrix Studio")
    app.setOrganizationName("OrcaMatrix")
    app.setFont(QFont("Segoe UI", 10))
    window = MatrixStudioWindow(args.connect)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
