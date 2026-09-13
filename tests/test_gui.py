"""Unit tests for the OrcaSlicer Matrix Tool Graphical User Interface (GUI)."""

import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
