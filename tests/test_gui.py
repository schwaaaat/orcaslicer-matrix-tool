"""Unit tests for the OrcaSlicer Matrix Tool Graphical User Interface (GUI)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from orcaslicer_matrix.gui import DimensionCard, OrcaMatrixApp
from orcaslicer_matrix.matrix import MAX_DIMENSIONS, MAX_VARIANTS


class TestOrcaMatrixApp(unittest.TestCase):
    def setUp(self):
        try:
            self.app = OrcaMatrixApp(client=None, auto_connect=False)
            self.app.withdraw()  # Hide window during test execution
        except Exception as e:
            self.skipTest(f"Tkinter display not available in environment: {e}")

    def tearDown(self):
        if hasattr(self, "app") and self.app:
            self.app.destroy()

    def test_initial_state_and_dimensions(self):
        # Default loads with 2 dimensions
        self.assertEqual(len(self.app.active_dimension_cards), 2)
        self.assertIn("2 / 3 active", self.app.dim_count_badge.cget("text"))
        self.assertEqual(str(self.app.add_dim_btn.cget("state")), "normal")

        # Check default keys
        card0 = self.app.active_dimension_cards[0]
        card1 = self.app.active_dimension_cards[1]
        self.assertEqual(card0.current_dim.key, "layer_height")
        self.assertEqual(card1.current_dim.key, "wall_loops")

    def test_max_dimensions_enforcement_at_three(self):
        # Starts with 2 -> add 1 more -> becomes 3
        self.app._add_dimension(default_key="sparse_infill_density", default_values=["15%", "20%"])
        self.assertEqual(len(self.app.active_dimension_cards), MAX_DIMENSIONS)
        self.assertIn("3 / 3 active", self.app.dim_count_badge.cget("text"))

        # Add Dimension button must be disabled
        self.assertEqual(str(self.app.add_dim_btn.cget("state")), "disabled")
        self.assertEqual(str(self.app.add_dim_btn.cget("text")), "Max 3 Dimensions Reached")

        # Attempting to add a 4th dimension should be blocked
        self.app._add_dimension(silent=True)
        self.assertEqual(len(self.app.active_dimension_cards), MAX_DIMENSIONS)

    def test_remove_dimension_reenables_add_button(self):
        # Add 3rd dimension
        self.app._add_dimension(default_key="sparse_infill_density", default_values=["20%"])
        self.assertEqual(len(self.app.active_dimension_cards), 3)

        # Remove the 3rd dimension
        card_to_remove = self.app.active_dimension_cards[-1]
        self.app._remove_dimension(card_to_remove)

        # Should now be 2 dimensions and button re-enabled
        self.assertEqual(len(self.app.active_dimension_cards), 2)
        self.assertEqual(str(self.app.add_dim_btn.cget("state")), "normal")
        self.assertEqual(str(self.app.add_dim_btn.cget("text")), "+ Add Dimension")

    def test_permutations_formula_and_validation(self):
        # Card 0: 2 values ['0.16', '0.20']
        # Card 1: 2 values ['2', '3']
        # 2 * 2 = 4 variants <= 8
        self.app._on_dimensions_changed()
        formula = self.app.perm_formula_lbl.cget("text")
        self.assertIn("4 Variants", formula)
        self.assertIn("✓ 4 of 8 variants [Ready to slice]", self.app.perm_status_lbl.cget("text"))
        self.assertEqual(str(self.app.run_btn.cget("state")), "normal")

        # Check treeview has 4 entries
        items = self.app.perm_tree.get_children()
        self.assertEqual(len(items), 4)

    def test_limit_exceeded_disables_run_button(self):
        # Add 3rd dimension with 3 values
        # 2 * 2 * 3 = 12 variants > 8 limit!
        self.app._add_dimension(
            default_key="sparse_infill_density",
            default_values=["10%", "20%", "30%"],
        )
        self.app._on_dimensions_changed()

        formula = self.app.perm_formula_lbl.cget("text")
        self.assertIn("12 Variants", formula)
        self.assertIn("Exceeds Hard Cap of 8 Variants", self.app.perm_status_lbl.cget("text"))
        self.assertEqual(str(self.app.run_btn.cget("state")), "disabled")

        # Suggestions should be displayed
        suggestions = self.app.perm_suggestions_lbl.cget("text")
        self.assertIn("Suggestions to stay within 8", suggestions)

    def test_switching_dimension_resets_stale_values(self):
        # Card 1 starts as wall_loops with ['2', '3']
        card1 = self.app.active_dimension_cards[1]
        self.assertEqual(card1.current_dim.key, "wall_loops")
        self.assertEqual(card1.selected_values, ["2", "3"])

        # Switch to wall_generator via set_dimension_by_key
        card1.set_dimension_by_key("wall_generator", ["classic", "arachne"])
        self.assertEqual(card1.current_dim.key, "wall_generator")
        self.assertNotIn("2", card1.selected_values)
        self.assertNotIn("3", card1.selected_values)
        self.assertEqual(card1.selected_values, ["classic", "arachne"])

        # Switch interactively by combobox to seam_position
        for i, val_text in enumerate(card1.dim_combo["values"]):
            if "seam_position" in val_text:
                card1.dim_combo.current(i)
                card1._on_dimension_changed()
                break

        self.assertEqual(card1.current_dim.key, "seam_position")
        self.assertNotIn("classic", card1.selected_values)
        self.assertNotIn("arachne", card1.selected_values)
        # Should now have the first 2 presets for seam_position (aligned, rear)
        self.assertEqual(card1.selected_values, ["aligned", "rear"])

    def test_canvas_resize_updates_card_container_width(self):
        self.app.dim_scroll_canvas.event_generate("<Configure>", width=780)
        item_w = self.app.dim_scroll_canvas.itemcget(self.app.dim_cards_window, "width")
        self.assertEqual(int(float(item_w)), 780)

    def test_eta_approval_controls_toggle(self):
        # Defaults
        self.assertTrue(self.app.require_approval_var.get())
        self.assertTrue(self.app.auto_skip_var.get())
        self.assertEqual(self.app.auto_skip_threshold_var.get(), "30")
        self.assertEqual(str(self.app.auto_skip_chk.cget("state")), "normal")
        self.assertEqual(str(self.app.auto_skip_entry.cget("state")), "normal")

        # Disable auto-skip: threshold entry should disable
        self.app.auto_skip_var.set(False)
        self.app._on_auto_skip_toggle()
        self.assertEqual(str(self.app.auto_skip_entry.cget("state")), "disabled")

        # Re-enable auto-skip
        self.app.auto_skip_var.set(True)
        self.app._on_auto_skip_toggle()
        self.assertEqual(str(self.app.auto_skip_entry.cget("state")), "normal")

        # Uncheck require approval: both auto-skip checkbox and entry should disable
        self.app.require_approval_var.set(False)
        self.app._on_approval_toggle()
        self.assertEqual(str(self.app.auto_skip_chk.cget("state")), "disabled")
        self.assertEqual(str(self.app.auto_skip_entry.cget("state")), "disabled")

        # Check require approval back on: sub-controls re-enable
        self.app.require_approval_var.set(True)
        self.app._on_approval_toggle()
        self.assertEqual(str(self.app.auto_skip_chk.cget("state")), "normal")
        self.assertEqual(str(self.app.auto_skip_entry.cget("state")), "normal")


    def test_results_notebook_tabs_exist(self):
        tabs = self.app.results_notebook.tabs()
        self.assertEqual(len(tabs), 4)
        tab_titles = [self.app.results_notebook.tab(t, "text") for t in tabs]
        self.assertIn("Variants Preview", tab_titles)
        self.assertIn("Summary & Deltas", tab_titles)
        self.assertIn("Filament by Line Type", tab_titles)
        self.assertIn("Visual Charts", tab_titles)

    def test_populate_results_dashboard(self):
        comparison = {
            "baseline": "v1",
            "recommended": "v2",
            "recommendation_reason": "Fastest slice time.",
            "summary_rows": [
                {
                    "name": "v1",
                    "display_name": "v1 (baseline)",
                    "print_time": "1h 00m",
                    "filament": "50.0 g",
                    "cost": "$1.00",
                    "vs_baseline": "-",
                    "time_s": 3600,
                    "filament_g": 50.0,
                    "is_baseline": True,
                    "is_fastest": False,
                    "is_lightest": False,
                    "is_recommended": False,
                    "error": None,
                },
                {
                    "name": "v2",
                    "display_name": "v2 ★ fastest",
                    "print_time": "45m",
                    "filament": "51.0 g",
                    "cost": "$1.02",
                    "vs_baseline": "-15m, +1.0g",
                    "time_s": 2700,
                    "filament_g": 51.0,
                    "is_baseline": False,
                    "is_fastest": True,
                    "is_lightest": False,
                    "is_recommended": True,
                    "error": None,
                },
            ],
            "line_type_matrix": {
                "columns": ["Inner wall", "Outer wall"],
                "rows": [
                    {"name": "v1", "roles": {"Inner wall": 30.0, "Outer wall": 20.0}, "total_g": 50.0},
                    {"name": "v2", "roles": {"Inner wall": 31.0, "Outer wall": 20.0}, "total_g": 51.0},
                ],
            },
            "summary_markdown": "# Summary\n...",
            "line_type_markdown": "# Line Types\n...",
        }

        self.app._populate_results_dashboard(comparison, Path("test_dir/manifest.json"))

        # Check banner
        self.assertIn("v2", self.app.rec_banner_title.cget("text"))
        self.assertEqual(self.app.rec_banner_desc.cget("text"), "Fastest slice time.")

        # Check summary treeview
        summary_items = self.app.summary_tree.get_children()
        self.assertEqual(len(summary_items), 2)
        v1_row = self.app.summary_tree.item(summary_items[0])["values"]
        self.assertEqual(v1_row[0], "v1 (baseline)")
        self.assertEqual(v1_row[1], "1h 00m")

        # Check line type treeview
        lt_items = self.app.line_type_tree.get_children()
        self.assertEqual(len(lt_items), 2)

        # Check notebook tab switched to summary
        current_tab = self.app.results_notebook.select()
        self.assertEqual(self.app.results_notebook.tab(current_tab, "text"), "Summary & Deltas")

    def test_charts_canvas_rendering(self):
        comparison = {
            "summary_rows": [
                {"name": "v1", "time_s": 3600, "filament_g": 50.0, "is_baseline": True, "is_fastest": False, "is_recommended": False, "error": None},
                {"name": "v2", "time_s": 2700, "filament_g": 51.0, "is_baseline": False, "is_fastest": True, "is_recommended": True, "error": None},
            ],
            "line_type_matrix": {
                "columns": ["Inner wall", "Outer wall"],
                "rows": [
                    {"name": "v1", "roles": {"Inner wall": 30.0, "Outer wall": 20.0}, "total_g": 50.0},
                    {"name": "v2", "roles": {"Inner wall": 31.0, "Outer wall": 20.0}, "total_g": 51.0},
                ],
            },
        }
        self.app._last_comparison = comparison

        # Test stacked mode
        self.app.chart_type_var.set("stacked")
        self.app.compact_labels_var.set(True)
        self.app._redraw_charts()
        items_stacked = self.app.charts_canvas.find_all()
        self.assertGreater(len(items_stacked), 0)

        # Toggle compact labels off and redraw
        self.app.compact_labels_var.set(False)
        self.app._redraw_charts()
        self.assertGreater(len(self.app.charts_canvas.find_all()), 0)

        # Test hover motion on stacked chart
        class MockEvent:
            x = 150
            y = 50
        self.app._on_chart_motion(MockEvent())

        # Test pareto mode
        self.app.chart_type_var.set("pareto")
        self.app._redraw_charts()
        items_pareto = self.app.charts_canvas.find_all()
        self.assertGreater(len(items_pareto), 0)

        # Test 3D lattice mode
        self.app.chart_type_var.set("3d_lattice")
        self.app._redraw_charts()
        items_3d = self.app.charts_canvas.find_all()
        self.assertGreater(len(items_3d), 0)

        # Verify mouse rotation drag on 3D canvas
        init_yaw = self.app._rot_yaw
        init_pitch = self.app._rot_pitch
        ev_press = MockEvent()
        ev_press.x = 200
        ev_press.y = 200
        self.app._on_chart_press(ev_press)
        self.assertTrue(self.app._is_dragging_3d)

        ev_drag = MockEvent()
        ev_drag.x = 230
        ev_drag.y = 180
        self.app._on_chart_drag(ev_drag)
        self.assertNotEqual(self.app._rot_yaw, init_yaw)
        self.assertNotEqual(self.app._rot_pitch, init_pitch)

        ev_release = MockEvent()
        self.app._on_chart_release(ev_release)
        self.assertFalse(self.app._is_dragging_3d)

        # Test 3D hover tracking
        hover_nodes = [item for item in self.app._chart_hover_items if item.get("type") == "3d_node"]
        self.assertGreater(len(hover_nodes), 0)
        target_node = hover_nodes[0]
        ev_node_hover = MockEvent()
        ev_node_hover.x = int(target_node["cx"])
        ev_node_hover.y = int(target_node["cy"])
        self.app._on_chart_motion(ev_node_hover)
        self.assertIn("3D Node", self.app.chart_hover_lbl.cget("text"))

        # Test leave event
        self.app._on_chart_leave(MockEvent())
        self.assertIn("Hover over", self.app.chart_hover_lbl.cget("text"))

    @patch("tkinter.messagebox.showinfo")
    def test_on_run_complete_loads_manifest_and_populates_dashboard(self, mock_showinfo):
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = Path(tmp_dir) / "manifest.json"
            manifest_data = {
                "schema_version": 1,
                "variants": [],
                "comparison": {
                    "recommended": "test_variant",
                    "recommendation_reason": "Optimal speed.",
                    "summary_rows": [
                        {
                            "name": "test_variant",
                            "display_name": "test_variant (baseline)",
                            "print_time": "1h 10m",
                            "filament": "45.0 g",
                            "cost": "$0.90",
                            "vs_baseline": "-",
                        }
                    ],
                    "line_type_matrix": {
                        "columns": ["Inner wall"],
                        "rows": [{"name": "test_variant", "roles": {"Inner wall": 45.0}, "total_g": 45.0}],
                    },
                },
            }
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f)

            # Disable viewer launch for test
            self.app.launch_viewer_var.set(False)

            # Invoke _on_run_finished
            self.app._on_run_finished(manifest_path, dry_run=False)

            # Verify no exceptions and dashboard populated
            self.assertIn("test_variant", self.app.rec_banner_title.cget("text"))
            self.assertEqual(len(self.app.summary_tree.get_children()), 1)
            self.assertEqual(len(self.app.line_type_tree.get_children()), 1)

    def test_parse_sort_key(self):
        self.assertEqual(self.app._parse_sort_key("0.84g"), (1, 0.84, ""))
        self.assertEqual(self.app._parse_sort_key("5.4g"), (1, 5.4, ""))
        self.assertEqual(self.app._parse_sort_key("$1.08"), (1, 1.08, ""))
        self.assertEqual(self.app._parse_sort_key("1h 00m"), (1, 3600.0, ""))
        self.assertEqual(self.app._parse_sort_key("45s"), (1, 45.0, ""))
        self.assertEqual(self.app._parse_sort_key("15%"), (1, 15.0, ""))
        self.assertEqual(self.app._parse_sort_key("-"), (3, 0.0, ""))
        self.assertEqual(self.app._parse_sort_key("0.16mm / 2 walls"), (2, 0.0, "0.16mm / 2 walls"))

    def test_treeview_column_sorting_and_clean_names(self):
        comparison = {
            "summary_rows": [
                {
                    "name": "layer_height=0.16, wall_loops=2",
                    "display_name": "0.16mm / 2 walls (baseline)",
                    "print_time": "1h 00m",
                    "time_s": 3600,
                    "filament": "50.0 g",
                    "cost": "$1.00",
                    "vs_baseline": "-",
                },
                {
                    "name": "layer_height=0.20, wall_loops=3",
                    "display_name": "0.20mm / 3 walls ★ fastest",
                    "print_time": "45m",
                    "time_s": 2700,
                    "filament": "42.0 g",
                    "cost": "$0.84",
                    "vs_baseline": "-15m, -8.0g",
                },
            ],
            "line_type_matrix": {
                "columns": ["Inner wall", "Outer wall"],
                "rows": [
                    {
                        "name": "layer_height=0.16, wall_loops=2",
                        "clean_name": "0.16mm / 2 walls",
                        "roles": {"Inner wall": 0.02, "Outer wall": 0.84},
                        "total_g": 5.4,
                    },
                    {
                        "name": "layer_height=0.16, wall_loops=3",
                        "clean_name": "0.16mm / 3 walls",
                        "roles": {"Inner wall": 0.04, "Outer wall": 1.01},
                        "total_g": 6.2,
                    },
                    {
                        "name": "layer_height=0.20, wall_loops=2",
                        "clean_name": "0.20mm / 2 walls",
                        "roles": {"Inner wall": 0.02, "Outer wall": 0.73},
                        "total_g": 5.3,
                    },
                ],
            },
        }

        self.app._populate_results_dashboard(comparison, Path("test/manifest.json"))

        # 1. Verify clean text in line_type_tree first column (not layer_height=0.16...)
        lt_items = self.app.line_type_tree.get_children()
        self.assertEqual(len(lt_items), 3)
        first_row_vals = self.app.line_type_tree.item(lt_items[0])["values"]
        self.assertEqual(first_row_vals[0], "0.16mm / 2 walls")
        self.assertNotIn("layer_height=", first_row_vals[0])

        # 2. Test click-to-sort on "total" column
        # Click 1: Ascending sort (5.3g, 5.4g, 6.2g)
        self.app.tk.call(self.app.line_type_tree.heading("total", "command"))

        items_asc = self.app.line_type_tree.get_children()
        asc_totals = [self.app.line_type_tree.item(i)["values"][-1] for i in items_asc]
        self.assertEqual(asc_totals, ["5.3g", "5.4g", "6.2g"])
        self.assertIn("▲", self.app.line_type_tree.heading("total", "text"))

        # Click 2: Descending sort (6.2g, 5.4g, 5.3g)
        self.app.tk.call(self.app.line_type_tree.heading("total", "command"))
        items_desc = self.app.line_type_tree.get_children()
        desc_totals = [self.app.line_type_tree.item(i)["values"][-1] for i in items_desc]
        self.assertEqual(desc_totals, ["6.2g", "5.4g", "5.3g"])
        self.assertIn("▼", self.app.line_type_tree.heading("total", "text"))

        # 3. Test click-to-sort on "variant" column (alphabetical)
        self.app.tk.call(self.app.line_type_tree.heading("variant", "command"))
        items_var_asc = self.app.line_type_tree.get_children()
        var_names = [self.app.line_type_tree.item(i)["values"][0] for i in items_var_asc]
        self.assertEqual(var_names, sorted(var_names))
        self.assertIn("▲", self.app.line_type_tree.heading("variant", "text"))
        self.assertNotIn("▼", self.app.line_type_tree.heading("total", "text"))
        self.assertNotIn("▲", self.app.line_type_tree.heading("total", "text"))

        # 4. Test summary_tree sorting by time
        sum_items = self.app.summary_tree.get_children()
        self.assertEqual(len(sum_items), 2)
        self.app.tk.call(self.app.summary_tree.heading("time", "command"))
        items_time_asc = self.app.summary_tree.get_children()
        time_vals = [self.app.summary_tree.item(i)["values"][1] for i in items_time_asc]
        self.assertEqual(time_vals, ["45m", "1h 00m"])


if __name__ == "__main__":
    unittest.main()
