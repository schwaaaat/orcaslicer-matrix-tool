"""Unit tests for schema key resolution and setting lookup."""

import unittest
from orcaslicer_matrix.schema import (
    SettingsSchema,
    UnknownSettingError,
    get_default_schema,
    resolve_matrix_dict,
    resolve_setting,
)


class TestSettingsSchema(unittest.TestCase):
    def setUp(self):
        self.schema = get_default_schema()

    def test_exact_keys(self):
        self.assertEqual(self.schema.resolve_key("layer_height"), "layer_height")
        self.assertEqual(self.schema.resolve_key("wall_loops"), "wall_loops")
        self.assertEqual(self.schema.resolve_key("sparse_infill_density"), "sparse_infill_density")

    def test_case_and_symbol_normalization(self):
        self.assertEqual(self.schema.resolve_key("LAYER_HEIGHT"), "layer_height")
        self.assertEqual(self.schema.resolve_key("layer-height"), "layer_height")
        self.assertEqual(self.schema.resolve_key("wall-loops"), "wall_loops")

    def test_label_lookup(self):
        self.assertEqual(self.schema.resolve_key("Layer height"), "layer_height")
        self.assertEqual(self.schema.resolve_key("Wall loops"), "wall_loops")

    def test_common_slicer_aliases(self):
        self.assertEqual(self.schema.resolve_key("wall count"), "wall_loops")
        self.assertEqual(self.schema.resolve_key("walls"), "wall_loops")
        self.assertEqual(self.schema.resolve_key("infill density"), "sparse_infill_density")
        self.assertEqual(self.schema.resolve_key("infill"), "sparse_infill_density")
        self.assertEqual(self.schema.resolve_key("speed"), "outer_wall_speed")
        self.assertEqual(self.schema.resolve_key("nozzle temp"), "nozzle_temperature")
        self.assertEqual(self.schema.resolve_key("bed temp"), "hot_plate_temp")

    def test_unknown_setting_raises_error_with_suggestions(self):
        with self.assertRaises(UnknownSettingError) as ctx:
            self.schema.resolve_key("layr_height")
        err_msg = str(ctx.exception)
        self.assertIn("Unknown OrcaSlicer setting 'layr_height'", err_msg)
        self.assertIn("layer_height", err_msg)

    def test_resolve_matrix_dict(self):
        raw = {
            "layer height": [0.16, "0.20"],
            "wall count": [2, 3],
        }
        resolved = resolve_matrix_dict(raw)
        self.assertEqual(
            resolved,
            {
                "layer_height": ["0.16", "0.20"],
                "wall_loops": ["2", "3"],
            },
        )

    def test_resolve_matrix_dict_empty_values_raises(self):
        with self.assertRaises(ValueError):
            resolve_matrix_dict({"layer_height": []})


if __name__ == "__main__":
    unittest.main()
