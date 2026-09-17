"""Unit tests for dimension catalog, Process tab categories, presets, and schema integration."""

import unittest

from orcaslicer_matrix.catalog import (
    CAT_ADVANCED,
    CAT_ALL,
    CAT_COMMON,
    CAT_EXTRUSION,
    CAT_FAVORITES,
    CAT_FILAMENT,
    CAT_OTHERS,
    CAT_QUALITY,
    CAT_SPEED,
    CAT_STRENGTH,
    CAT_SUPPORT,
    CURATED_OVERRIDES,
    DimensionCatalog,
    DimensionDefinition,
    PresetValue,
    get_default_catalog,
)


class TestCatalog(unittest.TestCase):
    def setUp(self):
        self.catalog = get_default_catalog()

    def test_curated_dimensions_loaded(self):
        curated = self.catalog.get_curated_dimensions()
        self.assertGreaterEqual(len(curated), 25)

        # Verify key process dimensions exist
        keys = [d.key for d in curated]
        self.assertIn("layer_height", keys)
        self.assertIn("wall_loops", keys)
        self.assertIn("sparse_infill_density", keys)
        self.assertIn("outer_wall_speed", keys)
        self.assertIn("nozzle_temperature", keys)
        self.assertIn("enable_support", keys)
        self.assertIn("line_width", keys)

    def test_presets_exist_for_curated(self):
        lh = self.catalog.get_dimension("layer_height")
        self.assertIsNotNone(lh)
        self.assertEqual(lh.unit, "mm")
        self.assertGreater(len(lh.presets), 3)

        preset_vals = [p.value for p in lh.presets]
        self.assertIn("0.16", preset_vals)
        self.assertIn("0.20", preset_vals)
        self.assertIn("0.24", preset_vals)

    def test_process_categories(self):
        cats = self.catalog.get_categories()
        self.assertIn(CAT_COMMON, cats)
        self.assertIn(CAT_FAVORITES, cats)
        self.assertIn(CAT_QUALITY, cats)
        self.assertIn(CAT_STRENGTH, cats)
        self.assertIn(CAT_SPEED, cats)
        self.assertIn(CAT_SUPPORT, cats)
        self.assertIn(CAT_OTHERS, cats)
        self.assertIn(CAT_ADVANCED, cats)
        self.assertIn(CAT_EXTRUSION, cats)
        self.assertIn(CAT_FILAMENT, cats)
        self.assertIn(CAT_ALL, cats)

    def test_common_settings_category(self):
        common_dims = self.catalog.get_dimensions_for_category(CAT_COMMON)
        self.assertEqual(len(common_dims), len(CURATED_OVERRIDES))
        self.assertTrue(any(d.key == "layer_height" for d in common_dims))
        self.assertTrue(any(d.key == "wall_loops" for d in common_dims))

    def test_favorites_category_dynamic(self):
        # Empty favorites returns empty list
        empty_favs = self.catalog.get_dimensions_for_category(CAT_FAVORITES)
        self.assertEqual(empty_favs, [])

        # Non-empty favorites resolves definitions and sorts by label
        fav_dims = self.catalog.get_dimensions_for_category(
            CAT_FAVORITES,
            favorite_keys=["wall_loops", "layer_height", "non_existent_key"]
        )
        self.assertEqual(len(fav_dims), 2)
        fav_keys = [d.key for d in fav_dims]
        self.assertIn("layer_height", fav_keys)
        self.assertIn("wall_loops", fav_keys)
        self.assertEqual(fav_dims, sorted(fav_dims, key=lambda d: d.label.lower()))

    def test_dimensions_by_process_category(self):
        quality_dims = self.catalog.get_dimensions_for_category(CAT_QUALITY)
        self.assertGreater(len(quality_dims), 80)
        self.assertTrue(any(d.key == "layer_height" for d in quality_dims))
        self.assertTrue(all(d.category == CAT_QUALITY for d in quality_dims))

        speed_dims = self.catalog.get_dimensions_for_category(CAT_SPEED)
        self.assertGreater(len(speed_dims), 40)
        self.assertTrue(any(d.key == "outer_wall_speed" for d in speed_dims))

        strength_dims = self.catalog.get_dimensions_for_category(CAT_STRENGTH)
        self.assertGreater(len(strength_dims), 40)
        self.assertTrue(any(d.key == "wall_loops" for d in strength_dims))

        support_dims = self.catalog.get_dimensions_for_category(CAT_SUPPORT)
        self.assertGreater(len(support_dims), 50)
        self.assertTrue(any(d.key == "enable_support" for d in support_dims))

    def test_resolve_by_alias(self):
        # 'wall count' should resolve to wall_loops dimension
        dim = self.catalog.get_dimension("wall count")
        self.assertIsNotNone(dim)
        self.assertEqual(dim.key, "wall_loops")

    def test_fallback_to_schema_for_arbitrary_setting(self):
        dim = self.catalog.get_dimension("accel_to_decel_enable")
        self.assertIsNotNone(dim)
        self.assertEqual(dim.key, "accel_to_decel_enable")
        self.assertEqual(dim.type, "coBool")
        # Should have auto-generated boolean presets as '1' and '0'
        p_vals = [p.value for p in dim.presets]
        self.assertIn("1", p_vals)
        self.assertIn("0", p_vals)

    def test_boolean_presets_are_one_and_zero(self):
        # Arc fitting and first layer walls must use '1' and '0' for OrcaSlicer compatibility
        arc_dim = self.catalog.get_dimension("enable_arc_fitting")
        self.assertIsNotNone(arc_dim)
        arc_vals = [p.value for p in arc_dim.presets]
        self.assertEqual(arc_vals, ["1", "0"])

        wall1_dim = self.catalog.get_dimension("only_one_wall_first_layer")
        self.assertIsNotNone(wall1_dim)
        wall1_vals = [p.value for p in wall1_dim.presets]
        self.assertEqual(wall1_vals, ["1", "0"])

        supp_dim = self.catalog.get_dimension("enable_support")
        self.assertIsNotNone(supp_dim)
        supp_vals = [p.value for p in supp_dim.presets]
        self.assertEqual(supp_vals, ["1", "0"])

    def test_total_available_dimensions(self):
        all_dims = self.catalog.get_all_available_dimensions()
        # Should include all 807 schema settings
        self.assertGreaterEqual(len(all_dims), 800)


if __name__ == "__main__":
    unittest.main()
