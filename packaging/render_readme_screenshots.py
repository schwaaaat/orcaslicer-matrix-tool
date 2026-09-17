"""Render deterministic README screenshots from the real Matrix Studio widgets."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableWidgetItem

import orcaslicer_matrix.studio as studio


def _render(window: studio.MatrixStudioWindow, output: Path) -> None:
    window.resize(1440, 900)
    window.show()
    QApplication.processEvents()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(output), "PNG"):
        raise RuntimeError(f"Could not save {output}")


def main() -> int:
    output_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/assets")
    app = QApplication.instance() or QApplication([])

    with tempfile.TemporaryDirectory(prefix="orca-matrix-readme-") as temp_dir:
        os.environ["ORCA_MATRIX_DATA_DIR"] = temp_dir
        studio._stored_api_token = lambda _base_url: None

        def sample_connection(window: studio.MatrixStudioWindow) -> None:
            window.connection_label.setText("● Connected to OrcaSlicer")
            window.connection_label.setObjectName("good")
            window.profile_label.setText(
                "Example plate · 0.20 mm Standard · Generic PLA · 0.4 mm nozzle"
            )
            window.plate_preview.setText(
                "ACTIVE PLATE\n\nCalibration tower · 1 object\n256 × 256 mm build surface"
            )

        studio.MatrixStudioWindow.refresh_connection = sample_connection
        window = studio.MatrixStudioWindow(base_url="http://127.0.0.1:13130")
        window._apply_theme("dark")
        sample_connection(window)
        _render(window, output_dir / "matrix-builder.png")

        window._show_page(2)
        window.result_banner.setText("Sample run · Layer height × Wall loops · 4 variants")
        window.recommendation_title.setText("Recommended: 0.20 mm · 2 walls")
        window.recommendation_detail.setText(
            "Fastest warning-free result: 1h 42m, 18.6 g filament, $0.37 estimated material cost."
        )
        for button in (
            window.copy_summary_btn,
            window.copy_filament_btn,
            window.open_html_btn,
            window.open_compare,
        ):
            button.setEnabled(True)

        rows = [
            ("0.16 mm · 2 walls", "2h 06m", "20.8 g", "$0.42", "Complete", "+23.5%", "+11.8%"),
            ("0.16 mm · 3 walls", "2h 18m", "23.1 g", "$0.46", "Complete", "+35.3%", "+24.2%"),
            ("0.20 mm · 2 walls", "1h 42m", "18.6 g", "$0.37", "Best", "Baseline", "Baseline"),
            ("0.20 mm · 3 walls", "1h 55m", "21.2 g", "$0.42", "Complete", "+12.7%", "+14.0%"),
        ]
        window.results_table.setSortingEnabled(False)
        window.results_table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if value == "Best":
                    item.setForeground(Qt.GlobalColor.green)
                window.results_table.setItem(row_index, column_index, item)
        window.results_table.setSortingEnabled(True)
        window.chart_view.set_values(
            [126.0, 138.0, 102.0, 115.0],
            ["0.16 / 2", "0.16 / 3", "0.20 / 2", "0.20 / 3"],
            True,
        )
        _render(window, output_dir / "matrix-analysis.png")
        window.close()

    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
