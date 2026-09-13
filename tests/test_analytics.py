"""Unit tests for the analytics, line-type parsing, delta calculations, and HTML reporting."""

import tempfile
import unittest
from pathlib import Path

from orcaslicer_matrix.analytics import (
    _generate_3d_lattice_svg,
    compute_matrix_comparison,
    format_compact_label,
    format_duration,
    generate_html_report,
    get_role_color,
    parse_gcode_filament_by_role,
    signed_mass_delta,
    signed_time_delta,
)


class TestAnalyticsHelpers(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(format_duration(None), "-")
        self.assertEqual(format_duration(-5), "-")
        self.assertEqual(format_duration(0), "0s")
        self.assertEqual(format_duration(45), "45s")
        self.assertEqual(format_duration(60), "1m")
        self.assertEqual(format_duration(125), "2m")
        self.assertEqual(format_duration(3600), "1h 00m")
        self.assertEqual(format_duration(3665), "1h 01m")
        self.assertEqual(format_duration(7320), "2h 02m")

    def test_signed_time_delta(self):
        self.assertEqual(signed_time_delta(0), "0m")
        self.assertEqual(signed_time_delta(15), "0m")
        self.assertEqual(signed_time_delta(-25), "0m")
        self.assertEqual(signed_time_delta(60), "+1m")
        self.assertEqual(signed_time_delta(-120), "-2m")
        self.assertEqual(signed_time_delta(3600), "+1h 00m")
        self.assertEqual(signed_time_delta(-3660), "-1h 01m")

    def test_signed_mass_delta(self):
        self.assertEqual(signed_mass_delta(0.0), "0.0g")
        self.assertEqual(signed_mass_delta(0.02), "0.0g")
        self.assertEqual(signed_mass_delta(-0.04), "0.0g")
        self.assertEqual(signed_mass_delta(0.7), "+0.7g")
        self.assertEqual(signed_mass_delta(-0.3), "-0.3g")
        self.assertEqual(signed_mass_delta(15.26), "+15.3g")

    def test_format_compact_label(self):
        self.assertEqual(format_compact_label(""), "")
        self.assertEqual(format_compact_label("layer_height=0.16"), "0.16mm")
        self.assertEqual(format_compact_label("layer_height=0.16, wall_loops=2"), "0.16mm • 2w")
        self.assertEqual(format_compact_label("sparse_infill_density=15%"), "15%")
        self.assertEqual(format_compact_label("wall_generator=arachne"), "arac")
        self.assertEqual(format_compact_label("seam_position=aligned"), "seam:ali")

    def test_get_role_color(self):
        c_wall = get_role_color("Inner wall")
        self.assertTrue(c_wall.startswith("#"))
        self.assertEqual(len(c_wall), 7)
        c_unknown = get_role_color("MysteriousCustomFeature")
        self.assertTrue(c_unknown.startswith("#"))
        self.assertEqual(len(c_unknown), 7)


class TestGcodeLineTypeParser(unittest.TestCase):
    def test_parse_nonexistent_file(self):
        result = parse_gcode_filament_by_role(Path("non_existent_gcode_file.gcode"))
        self.assertEqual(result, {})

    def test_parse_gcode_relative_e_with_footer(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            gcode_file = Path(tmp_dir) / "test_model.gcode"
            content = """
; OrcaSlicer G-code test
; filament_density: 1.25
; filament_diameter: 1.75
M83
; FEATURE: Inner wall
G1 X10 Y10 E1.5 F1200
G1 X20 Y10 E1.5 F1200
; FEATURE: Outer wall
G1 X30 Y10 E1.0 F800
; FEATURE: Sparse infill
G1 X40 Y10 E6.0 F3000
; filament used [g] = 20.0
"""
            gcode_file.write_text(content.strip(), encoding="utf-8")

            roles = parse_gcode_filament_by_role(gcode_file)
            # Total E = 1.5 + 1.5 + 1.0 + 6.0 = 10.0
            # Target mass = 20.0g
            # Inner wall: 3.0 / 10.0 * 20 = 6.0g
            # Outer wall: 1.0 / 10.0 * 20 = 2.0g
            # Sparse infill: 6.0 / 10.0 * 20 = 12.0g
            self.assertIn("Inner wall", roles)
            self.assertIn("Outer wall", roles)
            self.assertIn("Sparse infill", roles)
            self.assertAlmostEqual(roles["Inner wall"], 6.0, places=1)
            self.assertAlmostEqual(roles["Outer wall"], 2.0, places=1)
            self.assertAlmostEqual(roles["Sparse infill"], 12.0, places=1)

    def test_parse_gcode_absolute_e_and_fallback_mass(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            gcode_file = Path(tmp_dir) / "test_abs.gcode"
            content = """
M82
; FEATURE: Brim
G1 X10 E2.0
G1 X20 E4.0
; FEATURE: Support
G1 X30 E8.0
G92 E0
; FEATURE: Top surface
G1 X40 E2.0
"""
            gcode_file.write_text(content.strip(), encoding="utf-8")

            # Total E: Brim = 4.0, Support = 8.0 - 4.0 = 4.0, Top surface = 2.0 -> total 10.0
            # With fallback_mass_g = 100.0:
            # Brim = 40.0g, Support = 40.0g, Top surface = 20.0g
            roles = parse_gcode_filament_by_role(gcode_file, fallback_mass_g=100.0)
            self.assertIn("Brim", roles)
            self.assertIn("Support", roles)
            self.assertIn("Top surface", roles)
            self.assertAlmostEqual(roles["Brim"], 40.0, places=1)
            self.assertAlmostEqual(roles["Support"], 40.0, places=1)
            self.assertAlmostEqual(roles["Top surface"], 20.0, places=1)


class TestMatrixComparison(unittest.TestCase):
    def test_empty_variants(self):
        comp = compute_matrix_comparison([])
        self.assertIsNone(comp["baseline"])
        self.assertEqual(comp["summary_rows"], [])
        self.assertEqual(comp["summary_markdown"], "")
        self.assertEqual(comp["line_type_markdown"], "")

    def test_multi_variant_comparison_and_deltas(self):
        variants = [
            {
                "name": "baseline_var",
                "changes": {},
                "stats": {
                    "time_s": 3600,
                    "filament_g": 50.0,
                    "cost_usd": 1.00,
                    "filament_by_role": {"Inner wall": 20.0, "Outer wall": 10.0, "Sparse infill": 20.0},
                },
                "warnings": [],
                "error": None,
            },
            {
                "name": "speed_var",
                "changes": {"layer_height": "0.24"},
                "stats": {
                    "time_s": 2400,  # 40m (-20m)
                    "filament_g": 52.0,  # +2.0g
                    "cost_usd": 1.04,
                    "filament_by_role": {"Inner wall": 22.0, "Outer wall": 10.0, "Sparse infill": 20.0},
                },
                "warnings": [],
                "error": None,
            },
            {
                "name": "light_var",
                "changes": {"sparse_infill_density": "10%"},
                "stats": {
                    "time_s": 3900,  # 1h 05m (+5m)
                    "filament_g": 42.0,  # -8.0g
                    "cost_usd": 0.84,
                    "filament_by_role": {"Inner wall": 20.0, "Outer wall": 10.0, "Sparse infill": 12.0},
                },
                "warnings": [],
                "error": None,
            },
        ]

        comp = compute_matrix_comparison(variants, baseline_name="baseline_var")

        # Check baseline & extreme designations
        self.assertEqual(comp["baseline"], "baseline_var")
        self.assertEqual(comp["fastest"], "speed_var")
        self.assertEqual(comp["lightest"], "light_var")
        self.assertEqual(comp["recommended"], "speed_var")

        # Summary rows verification
        rows = comp["summary_rows"]
        self.assertEqual(len(rows), 3)

        # Baseline row
        r_base = rows[0]
        self.assertEqual(r_base["name"], "baseline_var")
        self.assertIn("(baseline)", r_base["display_name"])
        self.assertEqual(r_base["vs_baseline"], "-")
        self.assertEqual(r_base["print_time"], "1h 00m")

        # Speed row (fastest)
        r_speed = rows[1]
        self.assertEqual(r_speed["name"], "speed_var")
        self.assertIn("★ fastest", r_speed["display_name"])
        self.assertEqual(r_speed["vs_baseline"], "-20m, +2.0g")

        # Light row (lightest)
        r_light = rows[2]
        self.assertEqual(r_light["name"], "light_var")
        self.assertIn("★ lightest", r_light["display_name"])
        self.assertEqual(r_light["vs_baseline"], "+5m, -8.0g")

        # Line type matrix
        lt = comp["line_type_matrix"]
        self.assertIn("Inner wall", lt["columns"])
        self.assertIn("Outer wall", lt["columns"])
        self.assertIn("Sparse infill", lt["columns"])
        self.assertEqual(len(lt["rows"]), 3)

        # Markdown tables verification (Image 1 and Image 2 styles)
        sum_md = comp["summary_markdown"]
        self.assertIn("| Variant | Print Time | Filament | Cost | vs baseline |", sum_md)
        self.assertIn("baseline_var (baseline)", sum_md)
        self.assertIn("-20m, +2.0g", sum_md)

        lt_md = comp["line_type_markdown"]
        self.assertIn("### Filament by line type (grams)", lt_md)
        self.assertIn("| Variant | Inner wall | Outer wall | Sparse infill |", lt_md)
        self.assertIn("| baseline_var | 20.00 | 10.00 | 20.00 |", lt_md)


class TestHtmlReportGeneration(unittest.TestCase):
    def test_generate_html_report_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "report.html"
            manifest_data = {
                "source": {
                    "app": "OrcaSlicer",
                    "app_version": "2.4.2",
                    "printer_preset": "Bambu Lab P1S 0.4 nozzle",
                    "print_preset": "0.20mm Standard",
                    "filament_preset": "Generic PLA",
                    "plate_objects": ["Model.stl"],
                }
            }
            comparison = {
                "baseline": "v1",
                "recommended": "v1",
                "recommendation_reason": "Fastest and lightest.",
                "summary_rows": [
                    {
                        "name": "v1",
                        "display_name": "v1 (baseline)",
                        "print_time": "1h 00m",
                        "time_s": 3600,
                        "filament": "50.0 g",
                        "filament_g": 50.0,
                        "cost": "$1.00",
                        "cost_usd": 1.0,
                        "vs_baseline": "-",
                        "is_baseline": True,
                        "is_fastest": True,
                        "is_lightest": True,
                        "is_recommended": True,
                        "error": None,
                    }
                ],
                "line_type_matrix": {
                    "columns": ["Inner wall", "Outer wall"],
                    "rows": [
                        {
                            "name": "v1",
                            "display_name": "v1",
                            "roles": {"Inner wall": 30.0, "Outer wall": 20.0},
                            "total_g": 50.0,
                        }
                    ],
                },
            }

            path = generate_html_report(manifest_data, comparison, out_file)
            self.assertTrue(path.is_file())
            content = path.read_text(encoding="utf-8")
            self.assertIn("OrcaSlicer Matrix Comparison Report", content)
            self.assertIn("Bambu Lab P1S 0.4 nozzle", content)
            self.assertIn("Pareto Frontier: Print Time vs Filament Mass", content)
            self.assertIn("3D Matrix Lattice", content)
            self.assertIn("<svg", content)


class TestLattice3DVisualization(unittest.TestCase):
    def test_empty_rows(self):
        svg = _generate_3d_lattice_svg([], {})
        self.assertIn("No variants to plot in 3D", svg)

    def test_3d_lattice_svg_generation(self):
        summary_rows = [
            {
                "name": "layer_height=0.16, wall_loops=2, sparse_infill_density=15%",
                "display_name": "v1 (baseline)",
                "print_time": "1h 00m",
                "time_s": 3600,
                "filament": "45.0 g",
                "filament_g": 45.0,
                "cost": "$0.90",
                "cost_usd": 0.90,
                "vs_baseline": "-",
                "is_baseline": True,
                "is_fastest": False,
                "is_recommended": False,
                "changes": {"layer_height": "0.16", "wall_loops": "2", "sparse_infill_density": "15%"},
            },
            {
                "name": "layer_height=0.20, wall_loops=3, sparse_infill_density=20%",
                "display_name": "v2",
                "print_time": "45m",
                "time_s": 2700,
                "filament": "42.0 g",
                "filament_g": 42.0,
                "cost": "$0.84",
                "cost_usd": 0.84,
                "vs_baseline": "-15m, -3.0g",
                "is_baseline": False,
                "is_fastest": True,
                "is_recommended": True,
                "changes": {"layer_height": "0.20", "wall_loops": "3", "sparse_infill_density": "20%"},
            },
        ]
        matrix_dict = {
            "layer_height": ["0.16", "0.20"],
            "wall_loops": ["2", "3"],
            "sparse_infill_density": ["15%", "20%"],
        }
        svg = _generate_3d_lattice_svg(summary_rows, matrix_dict)
        self.assertIn("<svg", svg)
        self.assertIn("stroke-dasharray=\"3,3\"", svg)  # Bounding box wireframe
        self.assertIn("[X]", svg)
        self.assertIn("[Y]", svg)
        self.assertIn("[Z]", svg)
        self.assertIn("<circle", svg)
        self.assertIn("<title>", svg)
        self.assertIn("rec", svg)

    def test_single_value_axis_no_zero_division(self):
        summary_rows = [
            {
                "name": "layer_height=0.20, wall_loops=2",
                "time_s": 3000,
                "filament_g": 40.0,
                "changes": {"layer_height": "0.20", "wall_loops": "2"},
            }
        ]
        matrix_dict = {
            "layer_height": ["0.20"],  # Single value: len - 1 == 0
            "wall_loops": ["2"],        # Single value
        }
        # Must execute without ZeroDivisionError
        svg = _generate_3d_lattice_svg(summary_rows, matrix_dict)
        self.assertIn("<svg", svg)
        self.assertIn("[X]", svg)


if __name__ == "__main__":
    unittest.main()
