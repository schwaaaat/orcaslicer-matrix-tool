from orcaslicer_matrix.run_bundle import AxisDefinition, RunBundle, RunBundleStore, VariantRecord
from orcaslicer_matrix.studio_runner import StudioRunner


class FakeStudioClient:
    def __init__(self):
        self.applied = []

    def capabilities(self):
        return object()

    def status(self):
        return {
            "app": "OrcaSlicer",
            "app_version": "test",
            "presets": {"printer": "Test Printer", "print": "Test Process", "filaments": ["PLA"]},
        }

    def objects(self):
        return [{"name": "calibration cube"}]

    def config(self):
        return {"layer_height": "0.20", "filament_cost": "25"}

    def apply_config(self, changes):
        self.applied.append(dict(changes))
        return {"applied": list(changes), "errors": {}}

    def start_slice(self):
        return {"started": True}

    def slice_status(self):
        return {
            "state": "done",
            "stats": {"estimated_time_seconds": 600, "filament_used_g": 8.0},
            "warnings": [],
        }

    def gcode(self):
        return b"; FEATURE: Outer wall\nG1 X1 E1\n; FEATURE: Sparse infill\nG1 X2 E2\n"

    def cancel_slice(self):
        return {"cancelled": True}


def test_runner_writes_v2_reports_and_restores_config(tmp_path):
    variants = [
        VariantRecord("v1", 1, "layer_height=0.16", {"layer_height": "0.16"}),
        VariantRecord("v2", 2, "layer_height=0.20", {"layer_height": "0.20"}),
    ]
    bundle = RunBundle.create(
        "Layer height",
        [AxisDefinition("layer_height", "Layer height", ["0.16", "0.20"])],
        variants,
    )
    store = RunBundleStore(tmp_path)
    run_dir = store.create_directory(bundle)
    client = FakeStudioClient()

    result = StudioRunner(client, store, poll_interval=0).run(
        bundle,
        run_dir,
        confirm_eta=lambda *_: True,
    )

    assert result.state == "completed"
    assert result.restoration["completed"] is True
    assert client.applied[-1] == {"layer_height": "0.20"}
    assert (run_dir / "report.html").is_file()
    assert (run_dir / "report.md").is_file()
    assert result.comparison["recommended"]
    assert result.comparison["html_report"] == "report.html"
