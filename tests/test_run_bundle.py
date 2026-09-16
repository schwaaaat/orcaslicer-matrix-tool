import json
import tempfile
import unittest
from pathlib import Path

from orcaslicer_matrix.run_bundle import (
    AxisDefinition,
    RunBundle,
    RunBundleStore,
    RunLibrary,
    VariantRecord,
)


class TestRunBundle(unittest.TestCase):
    def make_bundle(self):
        return RunBundle.create(
            "Layer height × walls",
            [
                AxisDefinition("layer_height", "Layer height", ["0.16", "0.20"]),
                AxisDefinition("wall_loops", "Wall loops", ["2", "3"]),
            ],
            [
                VariantRecord("v1", 1, "0.16 / 2", {"layer_height": "0.16", "wall_loops": "2"}),
                VariantRecord("v2", 2, "0.20 / 3", {"layer_height": "0.20", "wall_loops": "3"}),
            ],
        )

    def test_round_trip_and_atomic_save(self):
        with tempfile.TemporaryDirectory() as temp:
            store = RunBundleStore(Path(temp))
            bundle = self.make_bundle()
            run_dir = store.create_directory(bundle)
            path = store.save(run_dir, bundle)
            loaded = store.load(path)
            self.assertEqual(loaded.schema_version, 2)
            self.assertEqual(loaded.run_id, bundle.run_id)
            self.assertEqual(loaded.axes[0].key, "layer_height")
            self.assertEqual(loaded.variants[1].changes["wall_loops"], "3")
            self.assertEqual(list(run_dir.glob(".run-*.tmp")), [])

    def test_rejects_unknown_schema(self):
        data = self.make_bundle().to_dict()
        data["schema_version"] = 99
        with self.assertRaises(ValueError):
            RunBundle.from_dict(data)

    def test_library_is_an_index_not_storage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = RunBundleStore(root / "runs")
            library = RunLibrary(root / "library.db")
            bundle = self.make_bundle()
            run_dir = store.create_directory(bundle)
            store.save(run_dir, bundle)
            library.upsert(bundle, run_dir)
            rows = library.list_runs("height")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["run_id"], bundle.run_id)
            self.assertTrue((Path(rows[0]["path"]) / "run.json").is_file())


if __name__ == "__main__":
    unittest.main()
