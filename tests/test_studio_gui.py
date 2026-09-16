from pathlib import Path

import pytest

from orcaslicer_matrix.studio import MatrixStudioWindow, _is_local_endpoint


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
