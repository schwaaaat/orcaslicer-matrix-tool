"""PySide6 desktop application for OrcaSlicer Matrix Studio."""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import keyring
from keyring.errors import KeyringError, PasswordDeleteError
from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal, Slot
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
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .catalog import DimensionDefinition, get_default_catalog
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
QPushButton#nav { text-align: left; border: 0; background: transparent; padding: 10px 12px; }
QPushButton#nav:checked { background: #d9eee8; color: #096e5e; border-left: 3px solid #0a8c76; }
QLineEdit, QComboBox, QSpinBox { background: white; border: 1px solid #bac5ce; border-radius: 6px; padding: 7px; }
QTableWidget, QListWidget { background: white; alternate-background-color: #f1f4f6; border: 1px solid #ccd4db; border-radius: 7px; }
QHeaderView::section { background: #e8edf1; border: 0; border-bottom: 1px solid #c4cdd5; padding: 8px; }
QProgressBar::chunk { background: #15977f; }
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
    remove_requested = Signal(object)

    def __init__(self, definitions: List[DimensionDefinition], index: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.definitions = definitions
        self.index_label = QLabel(f"AXIS {chr(65 + index)}")
        self.index_label.setObjectName("muted")
        self.setting = QComboBox()
        self.setting.setEditable(True)
        self.setting.setInsertPolicy(QComboBox.NoInsert)
        self.setting.completer().setFilterMode(Qt.MatchContains)
        self.setting.completer().setCaseSensitivity(Qt.CaseInsensitive)
        for definition in definitions:
            self.setting.addItem(definition.full_display_name, definition.key)
        self.values = QLineEdit()
        self.values.setPlaceholderText("Values separated by commas, e.g. 0.16, 0.20, 0.24")
        self.remove = QToolButton()
        self.remove.setText("Remove")

        header = QHBoxLayout()
        header.addWidget(self.index_label)
        header.addStretch()
        header.addWidget(self.remove)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addLayout(header)
        layout.addWidget(self.setting)
        layout.addWidget(self.values)

        self.setting.currentIndexChanged.connect(self._setting_changed)
        self.values.textChanged.connect(self.changed)
        self.remove.clicked.connect(lambda: self.remove_requested.emit(self))
        self._setting_changed()

    def _setting_changed(self) -> None:
        definition = self.definition()
        if definition and not self.values.text().strip() and definition.presets:
            self.values.setText(", ".join(item.value for item in definition.presets[:4]))
        if definition:
            self.setToolTip(definition.tooltip)
        self.changed.emit()

    def definition(self) -> Optional[DimensionDefinition]:
        key = self.setting.currentData()
        return next((item for item in self.definitions if item.key == key), None)

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

        self.setWindowTitle("OrcaSlicer Matrix Studio")
        self.resize(1440, 900)
        self.setMinimumSize(1120, 720)
        self._build_ui()
        self._apply_theme(str(self.settings.value("theme", "dark")))
        self._add_axis()
        self._add_axis()
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
        self.run_list.itemDoubleClicked.connect(self._open_library_item)
        layout.addWidget(self.run_list, 1)

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
        section = QLabel("Experiment axes")
        section.setObjectName("section")
        self.add_axis_button = QPushButton("+ Add axis")
        self.add_axis_button.clicked.connect(self._add_axis)
        axis_header.addWidget(section)
        axis_header.addStretch()
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
        self.result_banner = QLabel("Complete a run or open one from the library.")
        self.result_banner.setObjectName("muted")
        self.open_compare = QPushButton("Open selected in Compare View")
        self.open_compare.setEnabled(False)
        self.open_compare.clicked.connect(self._launch_compare)
        top.addWidget(self.result_banner)
        top.addStretch()
        top.addWidget(self.open_compare)
        layout.addLayout(top)
        split = QSplitter(Qt.Vertical)
        self.results_table = QTableWidget(0, 5)
        self.results_table.setHorizontalHeaderLabels(["Variant", "Print time", "Filament", "Cost", "State"])
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.results_table.itemSelectionChanged.connect(self._result_selection_changed)
        split.addWidget(self.results_table)
        self.chart_view = ResultsChart()
        split.addWidget(self.chart_view)
        split.setSizes([400, 340])
        layout.addWidget(split, 1)
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

    def _add_axis(self) -> None:
        if len(self.axes) >= 3:
            return
        card = AxisCard(self.definitions, len(self.axes))
        card.changed.connect(self._update_preview)
        card.remove_requested.connect(self._remove_axis)
        self.axes.append(card)
        self.axis_container.insertWidget(self.axis_container.count() - 1, card)
        self.add_axis_button.setEnabled(len(self.axes) < 3)
        self._update_preview()

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
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._connection_succeeded)
        worker.failed.connect(self._connection_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._threads.remove(thread) if thread in self._threads else None)
        self._threads.append(thread)
        thread.start()

    @Slot(object, object, object, bytes)
    def _connection_succeeded(self, caps: Capabilities, status: Dict[str, Any], objects: List[Dict[str, Any]], preview: bytes) -> None:
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
        thread.started.connect(worker.run)
        worker.progress.connect(self._run_progress)
        worker.eta_requested.connect(self._eta_requested)
        worker.completed.connect(self._run_completed)
        worker.failed.connect(self._run_failed)
        self.cancel_requested.connect(worker.cancel, Qt.DirectConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._threads.remove(thread) if thread in self._threads else None)
        self._threads.append(thread)
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
        self.results_table.setRowCount(len(bundle.variants))
        chart_values: List[float] = []
        categories: List[str] = []
        for row, variant in enumerate(bundle.variants):
            stats = variant.stats or {}
            seconds = stats.get("time_s")
            mass = stats.get("filament_g")
            cost = stats.get("cost_usd")
            values = [
                variant.name,
                f"{float(seconds) / 60:.1f} min" if seconds is not None else "—",
                f"{float(mass):.1f} g" if mass is not None else "—",
                f"${float(cost):.2f}" if cost is not None else "—",
                variant.state,
            ]
            for column, value in enumerate(values):
                self.results_table.setItem(row, column, QTableWidgetItem(value))
            chart_values.append(float(seconds or 0) / 60.0)
            categories.append(str(variant.ordinal))
        self.chart_view.set_values(chart_values, categories, self.theme.currentText() == "dark")
        completed = sum(1 for item in bundle.variants if item.state == "completed")
        self.result_banner.setText(f"{completed}/{len(bundle.variants)} variants completed · {bundle.state.replace('_', ' ').title()}")

    def _result_selection_changed(self) -> None:
        selected = sorted({index.row() for index in self.results_table.selectedIndexes()})
        self.open_compare.setEnabled(bool(selected) and len(selected) <= 8 and self.current_run_dir is not None)

    def _launch_compare(self) -> None:
        if not self.current_bundle or not self.current_run_dir:
            return
        rows = sorted({index.row() for index in self.results_table.selectedIndexes()})
        ids = [self.current_bundle.variants[row].id for row in rows[:8]]
        executable = self.viewer_executable_edit.text().strip() or _default_viewer_executable()
        try:
            subprocess.Popen(
                [executable, "--compare", str(self.current_run_dir / "run.json"), "--compare-variants", ",".join(ids)],
                cwd=self.current_run_dir,
            )
        except OSError as exc:
            QMessageBox.warning(self, "Could not open Compare View", str(exc))

    def refresh_library(self) -> None:
        if not hasattr(self, "run_list"):
            return
        self.run_list.clear()
        for row in self.library.list_runs(self.run_search.text() if hasattr(self, "run_search") else ""):
            item = QListWidgetItem(f"{row['name']}\n{row['variant_count']} variants · {row['state']}")
            item.setData(Qt.UserRole, row["path"])
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
