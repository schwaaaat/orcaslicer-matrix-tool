import gc
import json
from pathlib import Path
import subprocess

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from orcaslicer_matrix.catalog import CAT_COMMON, CAT_FAVORITES, CURATED_OVERRIDES
from orcaslicer_matrix.run_bundle import AxisDefinition, RunBundle, VariantRecord
from orcaslicer_matrix.studio import (
    MatrixStudioWindow,
    ResultsChart,
    SortableTableWidgetItem,
    _is_local_endpoint,
    generate_bundle_html_report,
    get_favorite_settings,
    is_favorite_setting,
    set_favorite_settings,
    toggle_favorite_setting,
)
from orcaslicer_matrix.studio_client import Capabilities


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("ORCA_MATRIX_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(MatrixStudioWindow, "refresh_connection", lambda self: None)
    widget = MatrixStudioWindow()
    qtbot.addWidget(widget)
    return widget


def test_builder_starts_with_two_axes(window):
    assert len(window.axes) == 2
    assert window.pages.currentIndex() == 0
    assert window.add_axis_button.isEnabled()


def test_matrix_preview_and_soft_limit(window, qtbot):
    window.axes[0].setting.setCurrentIndex(
        next(i for i in range(window.axes[0].setting.count()) if window.axes[0].setting.itemData(i) == "layer_height")
    )
    window.axes[0].values.setText("0.16, 0.20")
    window.axes[1].setting.setCurrentIndex(
        next(i for i in range(window.axes[1].setting.count()) if window.axes[1].setting.itemData(i) == "wall_loops")
    )
    window.axes[1].values.setText("2, 3")
    qtbot.waitUntil(lambda: window.variant_table.rowCount() == 4)
    assert window.variant_summary.text() == "4 variants"


def test_axis_limit_is_three(window, qtbot):
    window._add_axis()
    assert len(window.axes) == 3
    assert not window.add_axis_button.isEnabled()


def test_local_endpoint_detection():
    assert _is_local_endpoint("http://127.0.0.1:13130")
    assert _is_local_endpoint("http://localhost:13130")
    assert _is_local_endpoint("http://[::1]:13130")
    assert not _is_local_endpoint("https://slicer.example.test")


def test_results_chart_renders_without_qtcharts(qtbot):
    chart = ResultsChart()
    qtbot.addWidget(chart)
    chart.resize(640, 260)
    chart.set_values([1.5, 2.25, 0.75], ["1", "2", "3"], dark=True)
    image = chart.grab().toImage()
    assert not image.isNull()
    assert image.width() == 640


def test_refresh_connection_worker_lifetime_regression(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("ORCA_MATRIX_DATA_DIR", str(tmp_path))

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def capabilities(self):
            return Capabilities(
                api_version="1.1",
                app_version="2.6.0",
                build_id="test_build",
                features=["status", "config", "slice"],
                max_matrix_variants=32,
                compare_bundle_versions=[1, 2],
            )

        def status(self):
            return {
                "presets": {"printer": "Voron 2.4", "print": "Standard"},
                "state": "idle",
            }

        def objects(self):
            return [{"name": "CalibrationCube"}]

        def plate_render(self):
            return b""

    monkeypatch.setattr("orcaslicer_matrix.studio.StudioClient", DummyClient)

    # Do not mock refresh_connection - let it run real thread/worker
    widget = MatrixStudioWindow()
    qtbot.addWidget(widget)

    # Explicitly trigger GC to ensure unreferenced PySide workers would be collected
    gc.collect()

    # Verify that worker runs and connection successfully transitions
    qtbot.waitUntil(lambda: "Connected" in widget.connection_label.text(), timeout=4000)
    assert "Connected" in widget.connection_label.text()
    assert "2.6.0" in widget.connection_label.text()
    assert widget.connection_caps is not None
    assert "Voron 2.4" in widget.profile_label.text()
    assert "1 object on plate" in widget.profile_label.text()

    # Verify worker and thread were cleaned up
    qtbot.waitUntil(lambda: len(widget._threads) == 0 and len(widget._workers) == 0, timeout=4000)
    assert len(widget._threads) == 0
    assert len(widget._workers) == 0


def test_refresh_connection_failed_updates_status(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("ORCA_MATRIX_DATA_DIR", str(tmp_path))

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def capabilities(self):
            raise ConnectionRefusedError("Connection refused by target")

    monkeypatch.setattr("orcaslicer_matrix.studio.StudioClient", FailingClient)

    widget = MatrixStudioWindow()
    qtbot.addWidget(widget)

    gc.collect()

    qtbot.waitUntil(lambda: "unavailable" in widget.connection_label.text(), timeout=4000)
    assert "unavailable" in widget.connection_label.text()
    assert widget.connection_caps is None
    assert "Connection refused" in widget.profile_label.text()

    qtbot.waitUntil(lambda: len(widget._threads) == 0 and len(widget._workers) == 0, timeout=4000)
    assert len(widget._threads) == 0
    assert len(widget._workers) == 0


def test_axis_card_process_tab_grouping_and_all_settings(window):
    card = window.axes[0]
    expected_categories = window.catalog.get_categories()
    combo_categories = [card.category_combo.itemText(i) for i in range(card.category_combo.count())]
    assert combo_categories == expected_categories

    # Select All Settings (800+)
    all_idx = card.category_combo.findText("All Settings (800+)")
    assert all_idx >= 0
    card.category_combo.setCurrentIndex(all_idx)
    assert card.setting.count() >= 800

    # Select Process: Speed
    speed_idx = card.category_combo.findText("Process: Speed")
    card.category_combo.setCurrentIndex(speed_idx)
    assert 40 <= card.setting.count() < 200


def test_axis_card_keyword_filtering(window):
    card = window.axes[0]
    all_idx = card.category_combo.findText("All Settings (800+)")
    card.category_combo.setCurrentIndex(all_idx)
    total_count = card.setting.count()

    card.filter_entry.setText("fan")
    filtered_count = card.setting.count()
    assert 0 < filtered_count < total_count

    # Clear filter restores full count
    card.filter_entry.setText("")
    assert card.setting.count() == total_count


def test_axis_card_auto_populates_presets_and_chips_toggle(window):
    card = window.axes[0]
    assert card.set_dimension_by_key("wall_generator")
    # Verify auto-populated presets
    assert "classic" in card.values.text()
    assert "arachne" in card.values.text()

    # Verify preset chips exist and are checked
    assert len(card._preset_chips) == 2
    classic_chip = next(c for c in card._preset_chips if c.property("preset_value") == "classic")
    arachne_chip = next(c for c in card._preset_chips if c.property("preset_value") == "arachne")
    assert classic_chip.isChecked()
    assert arachne_chip.isChecked()

    # Toggle classic off by clicking
    classic_chip.click()
    assert "classic" not in card.values.text()
    assert "arachne" in card.values.text()
    assert not classic_chip.isChecked()

    # Toggle classic back on
    classic_chip.click()
    assert "classic" in card.values.text()
    assert classic_chip.isChecked()


def test_axis_card_common_settings_tab(window):
    card = window.axes[0]
    common_idx = card.category_combo.findText(CAT_COMMON)
    assert common_idx >= 0
    card.category_combo.setCurrentIndex(common_idx)
    assert card.setting.count() == len(CURATED_OVERRIDES)

    items = [card.setting.itemData(i) for i in range(card.setting.count())]
    assert "layer_height" in items
    assert "wall_loops" in items
    assert "sparse_infill_density" in items


def test_favorite_settings_workflow(window):
    # Ensure fresh state
    set_favorite_settings([])
    card = window.axes[0]

    # Select layer_height
    assert card.set_dimension_by_key("layer_height")
    assert not is_favorite_setting("layer_height")
    assert card.fav_button.text() == "☆"

    # Toggle favorite ON
    card.fav_button.click()
    assert is_favorite_setting("layer_height")
    assert card.fav_button.text() == "★"

    # Also favorite wall_loops
    assert card.set_dimension_by_key("wall_loops")
    card.fav_button.click()
    assert is_favorite_setting("wall_loops")

    # Switch to Favorites tab
    fav_idx = card.category_combo.findText(CAT_FAVORITES)
    assert fav_idx >= 0
    card.category_combo.setCurrentIndex(fav_idx)
    assert card.setting.count() == 2
    fav_items = [card.setting.itemData(i) for i in range(card.setting.count())]
    assert "layer_height" in fav_items
    assert "wall_loops" in fav_items

    # Unfavorite current setting in Favorites tab
    cur_data = card.setting.currentData()
    assert cur_data in ("layer_height", "wall_loops")
    card.fav_button.click()
    assert not is_favorite_setting(cur_data)
    # Remaining favorite count is 1
    assert card.setting.count() == 1

    # Unfavorite the remaining one
    rem_data = card.setting.currentData()
    card.fav_button.click()
    assert not is_favorite_setting(rem_data)

    # Now favorites is empty; placeholder should display
    assert card.setting.count() == 1
    assert card.setting.itemData(0) == ""
    assert "No favorite" in card.setting.itemText(0)
    assert not card.fav_button.isEnabled()
    assert "No favorite" in card.meta_label.text()

    # Reset
    set_favorite_settings([])


def test_recent_runs_removal_keep_files(window, tmp_path):
    bundle = RunBundle.create(
        "Test Run Keep Files",
        [AxisDefinition("layer_height", "Layer Height", ["0.16", "0.20"])],
        [VariantRecord("v1", 1, "0.16", {"layer_height": "0.16"})],
    )
    run_dir = window.store.create_directory(bundle)
    window.store.save(run_dir, bundle)
    dummy_file = run_dir / "test_slice.gcode"
    dummy_file.write_text("M104 S200\n", encoding="utf-8")

    window.library.upsert(bundle, run_dir)
    window.refresh_library()
    assert window.run_list.count() == 1

    # Remove without deleting files
    window.remove_run(run_id=bundle.run_id, path=str(run_dir), delete_files=False)
    assert window.run_list.count() == 0
    assert len(window.library.list_runs()) == 0
    # Directory and files must still exist
    assert run_dir.exists()
    assert dummy_file.is_file()


def test_recent_runs_removal_delete_files(window, tmp_path):
    bundle = RunBundle.create(
        "Test Run Delete Files",
        [AxisDefinition("layer_height", "Layer Height", ["0.16", "0.20"])],
        [VariantRecord("v1", 1, "0.16", {"layer_height": "0.16"})],
    )
    run_dir = window.store.create_directory(bundle)
    window.store.save(run_dir, bundle)
    dummy_file = run_dir / "test_slice.gcode"
    dummy_file.write_text("M104 S200\n", encoding="utf-8")

    window.library.upsert(bundle, run_dir)
    window.refresh_library()
    assert window.run_list.count() == 1

    # Set as active run in analyze page
    window.current_bundle = bundle
    window.current_run_dir = run_dir

    # Remove with delete_files=True
    window.remove_run(run_id=bundle.run_id, path=str(run_dir), delete_files=True)
    assert window.run_list.count() == 0
    assert len(window.library.list_runs()) == 0
    # Directory and files must be deleted
    assert not run_dir.exists()
    assert not dummy_file.exists()
    # Active run state must be cleared
    assert window.current_bundle is None
    assert window.current_run_dir is None


def test_sortable_table_widget_item():
    item1 = SortableTableWidgetItem("100 min", 6000.0, user_data="v1")
    item2 = SortableTableWidgetItem("9 min", 540.0, user_data="v2")
    item3 = SortableTableWidgetItem("—", float("inf"), user_data="v3")
    item4 = SortableTableWidgetItem("none", None, user_data="v4")

    assert item2 < item1
    assert not (item1 < item2)
    assert item1 < item3
    assert item3 < item4

    assert item1.data(Qt.UserRole) == "v1"
    assert item2.data(Qt.UserRole) == "v2"

    # State sorting with tuple keys
    s_done = SortableTableWidgetItem("completed", (0, "v1"))
    s_running = SortableTableWidgetItem("running", (1, "v2"))
    s_fail = SortableTableWidgetItem("failed", (3, "v3"))
    assert s_done < s_running < s_fail


def test_results_table_column_sorting_and_compare_launch(window, tmp_path, monkeypatch):
    bundle = RunBundle.create(
        "Sort Test",
        [AxisDefinition("layer_height", "Layer Height", ["0.16", "0.20", "0.28"])],
        [
            VariantRecord("v1", 1, "0.16", {"layer_height": "0.16"}, state="completed", stats={"time_s": 3600, "filament_g": 50.0, "cost_usd": 1.50}),
            VariantRecord("v2", 2, "0.20", {"layer_height": "0.20"}, state="completed", stats={"time_s": 600, "filament_g": 10.0, "cost_usd": 0.30}),
            VariantRecord("v3", 3, "0.28", {"layer_height": "0.28"}, state="completed", stats={"time_s": 1800, "filament_g": 25.0, "cost_usd": 0.80}),
        ],
    )
    window.current_bundle = bundle
    window.current_run_dir = tmp_path
    window._populate_results(bundle)

    assert window.results_table.rowCount() == 3
    # Initial order: v1, v2, v3
    assert window.results_table.item(0, 0).text() == "0.16"
    assert window.results_table.item(1, 0).text() == "0.20"
    assert window.results_table.item(2, 0).text() == "0.28"

    # Sort column 1 (Print time) Ascending: should be v2 (10 min), v3 (30 min), v1 (60 min)
    window.results_table.sortItems(1, Qt.AscendingOrder)
    assert window.results_table.item(0, 0).text() == "0.20"
    assert window.results_table.item(0, 0).data(Qt.UserRole) == "v2"
    assert window.results_table.item(1, 0).text() == "0.28"
    assert window.results_table.item(1, 0).data(Qt.UserRole) == "v3"
    assert window.results_table.item(2, 0).text() == "0.16"
    assert window.results_table.item(2, 0).data(Qt.UserRole) == "v1"

    # Test compare launch with sorted selection: selecting row 0 should pass variant 'v2'
    launched_cmd = []
    def fake_popen(cmd, **kwargs):
        launched_cmd.append(cmd)
        return None

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    window.results_table.selectRow(0)
    window._launch_compare()

    assert len(launched_cmd) == 1
    assert "--compare-variants" in launched_cmd[0]
    variant_arg_idx = launched_cmd[0].index("--compare-variants") + 1
    assert launched_cmd[0][variant_arg_idx] == "v2"

    # Sort column 1 Descending: should be v1 (60 min), v3 (30 min), v2 (10 min)
    window.results_table.sortItems(1, Qt.DescendingOrder)
    assert window.results_table.item(0, 0).text() == "0.16"
    assert window.results_table.item(0, 0).data(Qt.UserRole) == "v1"
    assert window.results_table.item(2, 0).text() == "0.20"
    assert window.results_table.item(2, 0).data(Qt.UserRole) == "v2"


def test_filament_table_population_and_sorting(window, tmp_path):
    bundle = RunBundle.create(
        "Filament Test",
        [AxisDefinition("layer_height", "Layer Height", ["0.16", "0.20"])],
        [
            VariantRecord(
                "v1", 1, "0.16", {"layer_height": "0.16"},
                state="completed",
                stats={
                    "filament_g": 30.0,
                    "filament_by_role": {
                        "Inner wall": 5.0,
                        "Outer wall": 2.0,
                        "Sparse infill": 15.0,
                        "Solid infill": 3.0,
                        "Top surface": 2.0,
                        "Support": 2.0,
                        "Brim": 1.0,
                    },
                },
            ),
            VariantRecord(
                "v2", 2, "0.20", {"layer_height": "0.20"},
                state="completed",
                stats={
                    "filament_g": 10.0,
                    "filament_by_role": {
                        "Inner wall": 1.0,
                        "Outer wall": 0.5,
                        "Sparse infill": 5.0,
                        "Solid infill": 1.0,
                        "Top surface": 1.0,
                        "Support": 1.0,
                        "Brim": 0.5,
                    },
                },
            ),
        ],
    )
    window.current_bundle = bundle
    window.current_run_dir = tmp_path
    window._populate_results(bundle)

    assert window.filament_table.rowCount() == 2
    # Verify values populated in columns:
    # Col 0: Variant, Col 1: Inner wall, Col 2: Outer wall, Col 8: Total
    assert "5.00 g" in window.filament_table.item(0, 1).text()
    assert "1.00 g" in window.filament_table.item(1, 1).text()
    assert "30.0 g" in window.filament_table.item(0, 8).text()
    assert "10.0 g" in window.filament_table.item(1, 8).text()

    # Sort total ascending -> row 0 becomes v2 (10g)
    window.filament_table.sortItems(8, Qt.AscendingOrder)
    assert window.filament_table.item(0, 0).text() == "0.20"
    assert "10.0 g" in window.filament_table.item(0, 8).text()
    assert window.filament_table.item(1, 0).text() == "0.16"
    assert "30.0 g" in window.filament_table.item(1, 8).text()


def test_html_report_generation(tmp_path):
    bundle = RunBundle.create(
        "HTML Report Test",
        [AxisDefinition("layer_height", "Layer Height", ["0.16", "0.20"])],
        [
            VariantRecord(
                "v1", 1, "0.16", {"layer_height": "0.16"},
                state="completed",
                stats={
                    "time_s": 1200,
                    "filament_g": 20.0,
                    "cost_usd": 0.60,
                    "filament_by_role": {"Inner wall": 5.0, "Sparse infill": 15.0},
                },
            ),
            VariantRecord(
                "v2", 2, "0.20", {"layer_height": "0.20"},
                state="completed",
                stats={
                    "time_s": 900,
                    "filament_g": 18.0,
                    "cost_usd": 0.54,
                    "filament_by_role": {"Inner wall": 4.0, "Sparse infill": 14.0},
                },
            ),
        ],
    )
    report_file = generate_bundle_html_report(bundle, tmp_path)
    assert report_file.exists()
    assert report_file.name == "report.html"

    content = report_file.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content or "<html" in content
    assert "HTML Report Test" in content or "0.16" in content
    assert "<svg" in content
    assert "Pareto" in content or "pareto" in content.lower()


def test_copy_markdown_buttons(window, tmp_path):
    bundle = RunBundle.create(
        "Copy Test",
        [AxisDefinition("layer_height", "Layer Height", ["0.16", "0.20"])],
        [
            VariantRecord(
                "v1", 1, "0.16", {"layer_height": "0.16"},
                state="completed",
                stats={"time_s": 1200, "filament_g": 20.0, "filament_by_role": {"Inner wall": 5.0}},
            ),
        ],
    )
    window.current_bundle = bundle
    window.current_run_dir = tmp_path
    window._populate_results(bundle)

    window._copy_summary_markdown()
    copied_summary = QApplication.clipboard().text()
    assert "| Variant |" in copied_summary
    assert "0.16" in copied_summary
    assert "Summary Markdown copied" in window.result_banner.text()

    window._copy_filament_markdown()
    copied_filament = QApplication.clipboard().text()
    assert "| Variant |" in copied_filament
    assert "Inner wall" in copied_filament
    assert "Filament breakdown Markdown copied" in window.result_banner.text()


def test_save_and_load_matrix_test_file(window, tmp_path):
    # Configure axes on window
    assert window.axes[0].set_dimension_by_key("layer_height")
    window.axes[0].values.setText("0.16, 0.20")
    assert window.axes[1].set_dimension_by_key("wall_loops")
    window.axes[1].values.setText("2, 3")

    save_path = tmp_path / "speed_test.orcamatrix.json"
    result_path = window.save_matrix_test_file(save_path)
    assert result_path == save_path
    assert save_path.exists()

    with open(save_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["format"] == "orcaslicer_matrix_test"
    assert len(data["axes"]) == 2
    assert data["axes"][0]["key"] == "layer_height"
    assert data["axes"][0]["values"] == ["0.16", "0.20"]
    assert data["axes"][1]["key"] == "wall_loops"
    assert data["axes"][1]["values"] == ["2", "3"]

    # Clear axes and load back
    while window.axes:
        window._remove_axis(window.axes[0])
    assert len(window.axes) == 0

    success = window.load_matrix_test_file(save_path)
    assert success is True
    assert len(window.axes) == 2
    assert window.axes[0].setting.currentData() == "layer_height"
    assert window.axes[0].values.text() == "0.16, 0.20"
    assert window.axes[1].setting.currentData() == "wall_loops"
    assert window.axes[1].values.text() == "2, 3"


def test_load_matrix_from_run_json(window, tmp_path):
    run_file = tmp_path / "run.json"
    run_file.write_text(
        json.dumps({
            "matrix": {
                "sparse_infill_density": ["15%", "25%"],
                "sparse_infill_pattern": ["grid", "gyroid"],
            }
        }),
        encoding="utf-8",
    )

    success = window.load_matrix_test_file(run_file)
    assert success is True
    assert len(window.axes) == 2
    assert window.axes[0].setting.currentData() == "sparse_infill_density"
    assert "15%" in window.axes[0].values.text()
    assert window.axes[1].setting.currentData() == "sparse_infill_pattern"
    assert "gyroid" in window.axes[1].values.text()



