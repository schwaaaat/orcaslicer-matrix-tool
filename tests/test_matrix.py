"""Unit tests for matrix permutations, variant naming, slugs, and 8-variant limit."""

import json
import tempfile
import unittest
from pathlib import Path

from orcaslicer_matrix.matrix import (
    VariantLimitExceededError,
    build_variants,
    parse_axis_string,
    parse_matrix_input,
    slugify_name,
)


class TestMatrix(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(
            slugify_name("layer_height=0.16, wall_loops=2"),
            "layer_height_0.16_wall_loops_2",
        )
        self.assertEqual(
            slugify_name("0.20mm / 2 walls"),
            "0.20mm_2_walls",
        )

    def test_build_variants_cartesian_product(self):
        matrix = {
            "layer_height": ["0.16", "0.20"],
            "wall_loops": ["2", "3"],
        }
        variants = build_variants(matrix)
        self.assertEqual(len(variants), 4)

        # Names check
        names = [v.name for v in variants]
        self.assertIn("layer_height=0.16, wall_loops=2", names)
        self.assertIn("layer_height=0.16, wall_loops=3", names)
        self.assertIn("layer_height=0.20, wall_loops=2", names)
        self.assertIn("layer_height=0.20, wall_loops=3", names)

        # Gcode filenames check
        for v in variants:
            self.assertTrue(v.gcode_filename.endswith(".gcode"))
            self.assertNotIn("=", v.gcode_filename)
            self.assertNotIn(",", v.gcode_filename)
            self.assertNotIn(" ", v.gcode_filename)

    def test_eight_variants_allowed(self):
        matrix = {
            "layer_height": ["0.16", "0.20"],
            "wall_loops": ["2", "3"],
            "sparse_infill_density": ["15%", "20%"],
        }
        # 2 * 2 * 2 = 8 variants (at the exact limit)
        variants = build_variants(matrix)
        self.assertEqual(len(variants), 8)

    def test_exceed_eight_variants_rejected_with_suggestions(self):
        matrix = {
            "layer_height": ["0.16", "0.20", "0.24"],
            "wall_loops": ["2", "3", "4"],
        }
        # 3 * 3 = 9 variants > 8
        with self.assertRaises(VariantLimitExceededError) as ctx:
            build_variants(matrix)

        err_msg = str(ctx.exception)
        self.assertIn("produces 9 variants, which exceeds the hard cap of 8 variants", err_msg)
        self.assertIn("Suggestions to stay within the limit:", err_msg)
        self.assertIn("layer_height", err_msg)
        self.assertIn("wall_loops", err_msg)

    def test_parse_axis_string(self):
        k, vals = parse_axis_string("layer_height=0.16,0.20,0.24")
        self.assertEqual(k, "layer_height")
        self.assertEqual(vals, ["0.16", "0.20", "0.24"])

    def test_parse_matrix_input_from_args(self):
        m = parse_matrix_input(axis_args=["layer height=0.16,0.20", "wall count=2,3"])
        self.assertEqual(
            m,
            {
                "layer_height": ["0.16", "0.20"],
                "wall_loops": ["2", "3"],
            },
        )

    def test_parse_matrix_input_from_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"layer_height": ["0.16", "0.20"], "wall_loops": ["2", "3"]}, f)
            temp_path = f.name

        try:
            m = parse_matrix_input(config_file=temp_path)
            self.assertEqual(
                m,
                {
                    "layer_height": ["0.16", "0.20"],
                    "wall_loops": ["2", "3"],
                },
            )
        finally:
            Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
