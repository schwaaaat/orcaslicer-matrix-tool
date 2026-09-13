"""Setting Catalog for OrcaSlicer Matrix Exploration.

Provides comprehensive coverage of all OrcaSlicer Process Tab settings:
  - Process: Quality (Layers, seams, ironing, wall generator, precision, elephant foot)
  - Process: Strength (Walls, shells, infill patterns, infill density, combine infill)
  - Process: Speed (Perimeter speeds, infill speeds, overhangs, accelerations, jerks)
  - Process: Support (Normal/tree supports, styles, overhang angles, interface, Z-gaps)
  - Process: Others (Brim, fuzzy skin, prime tower, scarf seams, flush options)
  - Process: Advanced (Flow ratios, bridge anchors, interlocking beams)
  - Extrusion & Flow (Line widths, flow multipliers, pressure advance, retraction)
  - Filament & Cooling (Nozzle/bed temperatures, fan cooling speeds)
  - All Settings (Full access to all 800+ settings in print_settings_schema.json)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .schema import SettingsSchema, get_default_schema


@dataclass(frozen=True)
class PresetValue:
    """A preset/suggested value for a matrix dimension."""
    value: str
    label: str = ""
    description: str = ""

    def display_name(self) -> str:
        if self.label:
            return self.label
        return self.value


@dataclass
class DimensionDefinition:
    """Definition of a configurable matrix dimension."""
    key: str
    label: str
    category: str
    tooltip: str = ""
    unit: Optional[str] = None
    type: str = "coFloat"
    presets: List[PresetValue] = field(default_factory=list)
    enum_values: Optional[List[str]] = None
    enum_labels: Optional[List[str]] = None
    default_val: Optional[str] = None

    @property
    def full_display_name(self) -> str:
        unit_str = f" [{self.unit}]" if self.unit else ""
        return f"{self.label} ({self.key}){unit_str}"


# Standard Process Tab Category Names
CAT_QUALITY = "Process: Quality"
CAT_STRENGTH = "Process: Strength"
CAT_SPEED = "Process: Speed"
CAT_SUPPORT = "Process: Support"
CAT_OTHERS = "Process: Others"
CAT_ADVANCED = "Process: Advanced"
CAT_EXTRUSION = "Extrusion & Flow"
CAT_FILAMENT = "Filament & Cooling"
CAT_ALL = "All Settings (800+)"

PROCESS_CATEGORIES = [
    CAT_QUALITY,
    CAT_STRENGTH,
    CAT_SPEED,
    CAT_SUPPORT,
    CAT_OTHERS,
    CAT_ADVANCED,
    CAT_EXTRUSION,
    CAT_FILAMENT,
    CAT_ALL,
]

# Aliases for compatibility
CURATED_DIMENSIONS = list(PROCESS_CATEGORIES)


# Hand-curated rich preset overrides for top settings
CURATED_OVERRIDES: Dict[str, Dict[str, Any]] = {
    # --- Quality ---
    "layer_height": {
        "category": CAT_QUALITY,
        "presets": [
            PresetValue("0.08", "0.08 mm"),
            PresetValue("0.12", "0.12 mm"),
            PresetValue("0.16", "0.16 mm"),
            PresetValue("0.20", "0.20 mm"),
            PresetValue("0.24", "0.24 mm"),
            PresetValue("0.28", "0.28 mm"),
            PresetValue("0.32", "0.32 mm"),
        ],
    },
    "initial_layer_height": {
        "category": CAT_QUALITY,
        "presets": [
            PresetValue("0.16", "0.16 mm"),
            PresetValue("0.20", "0.20 mm"),
            PresetValue("0.24", "0.24 mm"),
            PresetValue("0.28", "0.28 mm"),
        ],
    },
    "wall_generator": {
        "category": CAT_QUALITY,
        "presets": [
            PresetValue("classic", "Classic"),
            PresetValue("arachne", "Arachne"),
        ],
    },
    "seam_position": {
        "category": CAT_QUALITY,
        "presets": [
            PresetValue("aligned", "Aligned"),
            PresetValue("rear", "Rear"),
            PresetValue("nearest", "Nearest"),
            PresetValue("random", "Random"),
        ],
    },
    "precise_outer_wall": {
        "category": CAT_QUALITY,
        "presets": [
            PresetValue("1", "1 (Enabled)"),
            PresetValue("0", "0 (Disabled)"),
        ],
    },
    "enable_arc_fitting": {
        "category": CAT_QUALITY,
        "presets": [
            PresetValue("1", "1 (Enabled)"),
            PresetValue("0", "0 (Disabled)"),
        ],
    },
    "only_one_wall_first_layer": {
        "category": CAT_QUALITY,
        "presets": [
            PresetValue("1", "1 (Enabled)"),
            PresetValue("0", "0 (Disabled)"),
        ],
    },
    "only_one_wall_top": {
        "category": CAT_QUALITY,
        "presets": [
            PresetValue("1", "1 (Enabled)"),
            PresetValue("0", "0 (Disabled)"),
        ],
    },
    "elefant_foot_compensation": {
        "category": CAT_QUALITY,
        "presets": [
            PresetValue("0.0", "0.0 mm (Off)"),
            PresetValue("0.10", "0.10 mm"),
            PresetValue("0.15", "0.15 mm"),
            PresetValue("0.20", "0.20 mm"),
            PresetValue("0.25", "0.25 mm"),
        ],
    },
    "ironing_type": {
        "category": CAT_QUALITY,
        "presets": [
            PresetValue("no ironing", "No Ironing"),
            PresetValue("top", "Top Surfaces"),
            PresetValue("topmost", "Topmost Surface"),
            PresetValue("solid", "All Solid Layers"),
        ],
    },
    "ironing_speed": {
        "category": CAT_QUALITY,
        "presets": [
            PresetValue("15", "15 mm/s"),
            PresetValue("30", "30 mm/s"),
            PresetValue("50", "50 mm/s"),
        ],
    },
    "ironing_flow": {
        "category": CAT_QUALITY,
        "presets": [
            PresetValue("10%", "10%"),
            PresetValue("15%", "15%"),
            PresetValue("20%", "20%"),
            PresetValue("25%", "25%"),
        ],
    },

    # --- Strength ---
    "wall_loops": {
        "category": CAT_STRENGTH,
        "presets": [
            PresetValue("1", "1 Wall"),
            PresetValue("2", "2 Walls"),
            PresetValue("3", "3 Walls"),
            PresetValue("4", "4 Walls"),
            PresetValue("5", "5 Walls"),
            PresetValue("6", "6 Walls"),
        ],
    },
    "sparse_infill_density": {
        "category": CAT_STRENGTH,
        "presets": [
            PresetValue("10%", "10% (Draft / Light)"),
            PresetValue("15%", "15% (Standard)"),
            PresetValue("20%", "20% (Sturdy)"),
            PresetValue("25%", "25% (High Strength)"),
            PresetValue("40%", "40% (Heavy Duty)"),
            PresetValue("60%", "60% (Solid Structural)"),
        ],
    },
    "sparse_infill_pattern": {
        "category": CAT_STRENGTH,
        "presets": [
            PresetValue("gyroid", "Gyroid (Isotropic)"),
            PresetValue("grid", "Grid (Fast)"),
            PresetValue("rectilinear", "Rectilinear (Clean)"),
            PresetValue("cubic", "Cubic (3D Rigid)"),
            PresetValue("crosshatch", "Cross Hatch (Modern Orca)"),
            PresetValue("honeycomb", "Honeycomb (Stiff)"),
            PresetValue("adaptivecubic", "Adaptive Cubic (Gradient)"),
        ],
    },
    "top_shell_layers": {
        "category": CAT_STRENGTH,
        "presets": [
            PresetValue("3", "3 Layers (Draft)"),
            PresetValue("4", "4 Layers (Standard)"),
            PresetValue("5", "5 Layers (Clean Top)"),
            PresetValue("6", "6 Layers (Perfect Seal)"),
            PresetValue("8", "8 Layers (Machined)"),
        ],
    },
    "bottom_shell_layers": {
        "category": CAT_STRENGTH,
        "presets": [
            PresetValue("2", "2 Layers"),
            PresetValue("3", "3 Layers (Standard)"),
            PresetValue("4", "4 Layers (Strong)"),
            PresetValue("5", "5 Layers"),
        ],
    },
    "alternate_extra_wall": {
        "category": CAT_STRENGTH,
        "presets": [
            PresetValue("1", "1 (Enabled)"),
            PresetValue("0", "0 (Disabled)"),
        ],
    },
    "infill_combination": {
        "category": CAT_STRENGTH,
        "presets": [
            PresetValue("1", "1 (Enabled - Thicker Infill)"),
            PresetValue("0", "0 (Disabled - Sync with Walls)"),
        ],
    },

    # --- Speed ---
    "outer_wall_speed": {
        "category": CAT_SPEED,
        "presets": [
            PresetValue("30", "30 mm/s (Show Quality)"),
            PresetValue("50", "50 mm/s (Fine)"),
            PresetValue("80", "80 mm/s (Standard)"),
            PresetValue("120", "120 mm/s (Fast)"),
            PresetValue("160", "160 mm/s (High Speed)"),
            PresetValue("200", "200 mm/s (Extreme)"),
        ],
    },
    "inner_wall_speed": {
        "category": CAT_SPEED,
        "presets": [
            PresetValue("80", "80 mm/s"),
            PresetValue("120", "120 mm/s (Standard)"),
            PresetValue("180", "180 mm/s (Fast)"),
            PresetValue("250", "250 mm/s (High Speed)"),
            PresetValue("300", "300 mm/s (Max)"),
        ],
    },
    "sparse_infill_speed": {
        "category": CAT_SPEED,
        "presets": [
            PresetValue("100", "100 mm/s"),
            PresetValue("150", "150 mm/s"),
            PresetValue("200", "200 mm/s (Standard)"),
            PresetValue("270", "270 mm/s (Fast)"),
            PresetValue("350", "350 mm/s (High Speed)"),
        ],
    },
    "top_surface_speed": {
        "category": CAT_SPEED,
        "presets": [
            PresetValue("30", "30 mm/s (Smooth)"),
            PresetValue("50", "50 mm/s (Standard)"),
            PresetValue("80", "80 mm/s (Fast)"),
            PresetValue("120", "120 mm/s (Draft)"),
        ],
    },
    "travel_speed": {
        "category": CAT_SPEED,
        "presets": [
            PresetValue("200", "200 mm/s (Conservative)"),
            PresetValue("300", "300 mm/s (Standard)"),
            PresetValue("400", "400 mm/s (High Speed)"),
            PresetValue("500", "500 mm/s (Rapid)"),
        ],
    },
    "outer_wall_acceleration": {
        "category": CAT_SPEED,
        "presets": [
            PresetValue("1000", "1000 mm/s² (No Ringing)"),
            PresetValue("2000", "2000 mm/s²"),
            PresetValue("3000", "3000 mm/s² (Standard)"),
            PresetValue("5000", "5000 mm/s² (High Accel)"),
            PresetValue("7000", "7000 mm/s² (Extreme)"),
        ],
    },

    # --- Support ---
    "enable_support": {
        "category": CAT_SUPPORT,
        "presets": [
            PresetValue("1", "1 (Enabled)"),
            PresetValue("0", "0 (Disabled)"),
        ],
    },
    "support_type": {
        "category": CAT_SUPPORT,
        "presets": [
            PresetValue("normal(auto)", "Normal (Auto Columns)"),
            PresetValue("tree(auto)", "Tree (Auto Branching)"),
            PresetValue("normal(manual)", "Normal (Manual Enforcers)"),
            PresetValue("tree(manual)", "Tree (Manual Enforcers)"),
        ],
    },
    "support_style": {
        "category": CAT_SUPPORT,
        "presets": [
            PresetValue("default", "Default"),
            PresetValue("organic", "Organic (Smooth Curves)"),
            PresetValue("snug", "Snug (Tight Fit)"),
            PresetValue("tree_slim", "Tree Slim (Material Saver)"),
            PresetValue("tree_strong", "Tree Strong (Heavy Parts)"),
            PresetValue("tree_hybrid", "Tree Hybrid (Balanced)"),
        ],
    },
    "support_threshold_angle": {
        "category": CAT_SUPPORT,
        "presets": [
            PresetValue("25", "25° (Steep overhangs only)"),
            PresetValue("30", "30° (Aggressive)"),
            PresetValue("45", "45° (Standard)"),
            PresetValue("55", "55° (Conservative)"),
            PresetValue("60", "60° (Maximum Support)"),
        ],
    },
    "support_top_z_distance": {
        "category": CAT_SUPPORT,
        "presets": [
            PresetValue("0.10", "0.10mm (Very Tight)"),
            PresetValue("0.16", "0.16mm (Clean Overhang)"),
            PresetValue("0.20", "0.20mm (Easy Removal)"),
            PresetValue("0.25", "0.25mm (Breakaway)"),
        ],
    },

    # --- Others ---
    "brim_type": {
        "category": CAT_OTHERS,
        "presets": [
            PresetValue("no_brim", "No Brim"),
            PresetValue("auto_brim", "Auto Brim"),
            PresetValue("outer_only", "Outer Brim Only"),
            PresetValue("inner_only", "Inner Brim Only"),
            PresetValue("outer_and_inner", "Outer and Inner Brim"),
            PresetValue("brim_ears", "Mouse Ears (Corners Only)"),
        ],
    },
    "brim_width": {
        "category": CAT_OTHERS,
        "presets": [
            PresetValue("0", "0 mm (Off)"),
            PresetValue("3", "3 mm (Light)"),
            PresetValue("5", "5 mm (Standard)"),
            PresetValue("8", "8 mm (Heavy Anti-Warp)"),
            PresetValue("12", "12 mm (Maximum)"),
        ],
    },
    "fuzzy_skin": {
        "category": CAT_OTHERS,
        "presets": [
            PresetValue("disabled_fuzzy", "Disabled"),
            PresetValue("external", "Contour Only (Outside)"),
            PresetValue("all", "Contour and Holes"),
            PresetValue("allwalls", "All Walls"),
        ],
    },

    # --- Extrusion & Flow ---
    "line_width": {
        "category": CAT_EXTRUSION,
        "presets": [
            PresetValue("0.36", "0.36mm (Fine Line)"),
            PresetValue("0.40", "0.40mm (Exact Nozzle)"),
            PresetValue("0.42", "0.42mm (Orca Standard)"),
            PresetValue("0.45", "0.45mm (Strong Bond)"),
            PresetValue("0.50", "0.50mm (High Flow)"),
        ],
    },
    "outer_wall_line_width": {
        "category": CAT_EXTRUSION,
        "presets": [
            PresetValue("0.35", "0.35mm (Sharp Detail)"),
            PresetValue("0.40", "0.40mm"),
            PresetValue("0.42", "0.42mm (Standard)"),
            PresetValue("0.45", "0.45mm (Thick Outer)"),
        ],
    },
    "pressure_advance": {
        "category": CAT_EXTRUSION,
        "presets": [
            PresetValue("0.015", "0.015 (Direct Drive PLA)"),
            PresetValue("0.025", "0.025 (Standard Direct Drive)"),
            PresetValue("0.035", "0.035 (PETG Direct Drive)"),
            PresetValue("0.050", "0.050 (High Elasticity)"),
            PresetValue("0.075", "0.075 (Long Bowden)"),
        ],
    },
    "retraction_length": {
        "category": CAT_EXTRUSION,
        "presets": [
            PresetValue("0.2", "0.2mm (All-Metal Direct Drive)"),
            PresetValue("0.4", "0.4mm"),
            PresetValue("0.8", "0.8mm (Standard Direct Drive)"),
            PresetValue("1.2", "1.2mm"),
            PresetValue("2.0", "2.0mm (Short Bowden)"),
            PresetValue("4.0", "4.0mm (Long Bowden)"),
        ],
    },

    # --- Filament & Cooling ---
    "nozzle_temperature": {
        "category": CAT_FILAMENT,
        "presets": [
            PresetValue("195", "195°C (Cool PLA)"),
            PresetValue("205", "205°C (Standard PLA)"),
            PresetValue("215", "215°C (High Speed PLA)"),
            PresetValue("225", "225°C (PLA+ / Matte)"),
            PresetValue("235", "235°C (Cool PETG/ABS)"),
            PresetValue("245", "245°C (Standard PETG)"),
            PresetValue("255", "255°C (High Speed PETG)"),
            PresetValue("270", "270°C (Nylon/ASA)"),
        ],
    },
    "hot_plate_temp": {
        "category": CAT_FILAMENT,
        "presets": [
            PresetValue("50", "50°C (Smooth PEI)"),
            PresetValue("55", "55°C (Standard PLA)"),
            PresetValue("60", "60°C (Textured PEI)"),
            PresetValue("70", "70°C (PETG Low)"),
            PresetValue("80", "80°C (Standard PETG)"),
            PresetValue("90", "90°C (ABS Base)"),
            PresetValue("100", "100°C (ABS High)"),
        ],
    },
    "fan_max_speed": {
        "category": CAT_FILAMENT,
        "presets": [
            PresetValue("20%", "20% (PETG Minimal)"),
            PresetValue("40%", "40% (Mild)"),
            PresetValue("60%", "60% (Moderate)"),
            PresetValue("80%", "80% (High Cooling)"),
            PresetValue("100%", "100% (Maximum Blast)"),
        ],
    },
    "fan_min_speed": {
        "category": CAT_FILAMENT,
        "presets": [
            PresetValue("0%", "0% (ABS No Fan)"),
            PresetValue("20%", "20% (PETG Base)"),
            PresetValue("40%", "40%"),
            PresetValue("60%", "60%"),
            PresetValue("100%", "100% (Continuous PLA)"),
        ],
    },
}


def classify_setting_category(key: str, schema_rec: Dict[str, Any]) -> str:
    """Classify a schema setting into its proper OrcaSlicer Process tab."""
    # 1. Check curated overrides
    if key in CURATED_OVERRIDES and "category" in CURATED_OVERRIDES[key]:
        return CURATED_OVERRIDES[key]["category"]

    cat = schema_rec.get("category")
    if cat == "Quality" or cat == "Layers and Perimeters":
        return CAT_QUALITY
    elif cat == "Strength":
        return CAT_STRENGTH
    elif cat == "Speed" or cat == "Machine limits":
        return CAT_SPEED
    elif cat == "Support":
        return CAT_SUPPORT
    elif cat in ("Others", "Other", "Flush options"):
        return CAT_OTHERS
    elif cat == "Advanced":
        return CAT_ADVANCED

    # Heuristic classification for un-categorized settings in schema
    k_lower = key.lower()
    lbl_lower = (schema_rec.get("label") or "").lower()

    if any(w in k_lower for w in ("temp", "temperature", "fan_", "cooling", "chamber")):
        return CAT_FILAMENT
    if any(w in k_lower for w in ("line_width", "flow_ratio", "retract", "pressure_advance", "extrusion")):
        return CAT_EXTRUSION
    if any(w in k_lower for w in ("speed", "accel", "jerk", "travel")):
        return CAT_SPEED
    if any(w in k_lower for w in ("height", "seam", "iron", "perimeter", "elephant", "precision", "resolution", "scarf", "arc_fitting")):
        return CAT_QUALITY
    if any(w in k_lower for w in ("infill", "shell", "wall", "density", "pattern")):
        return CAT_STRENGTH
    if any(w in k_lower for w in ("support", "raft", "overhang")):
        return CAT_SUPPORT
    if any(w in k_lower for w in ("brim", "fuzzy", "tower", "wipe", "flush", "purge", "prime")):
        return CAT_OTHERS

    return CAT_QUALITY if "layer" in k_lower else CAT_OTHERS


class DimensionCatalog:
    """Catalog managing both curated high-value dimensions and full schema settings."""

    def __init__(self, schema: Optional[SettingsSchema] = None):
        self.schema = schema or get_default_schema()
        self._dimensions_by_key: Dict[str, DimensionDefinition] = {}
        self._dimensions_by_category: Dict[str, List[DimensionDefinition]] = {
            cat: [] for cat in PROCESS_CATEGORIES
        }
        self._build_catalog()

    def _build_catalog(self) -> None:
        """Process all 800+ settings from schema into rich DimensionDefinitions."""
        all_keys = sorted(self.schema.setting_keys)

        for key in all_keys:
            rec = self.schema.get_setting(key)
            if not rec or not isinstance(rec, dict):
                continue

            category = classify_setting_category(key, rec)
            label = rec.get("label") or key.replace("_", " ").title()
            tooltip = rec.get("tooltip") or ""
            unit = rec.get("unit")
            stype = rec.get("type") or "coString"
            enum_vals = rec.get("enum_values")
            enum_labels = rec.get("enum_labels")
            default_val = rec.get("default")

            presets: List[PresetValue] = []

            # 1. Use curated override presets if available
            if key in CURATED_OVERRIDES and "presets" in CURATED_OVERRIDES[key]:
                presets = list(CURATED_OVERRIDES[key]["presets"])
            # 2. Otherwise auto-derive from schema enums/bools/defaults
            elif enum_vals and isinstance(enum_vals, list):
                for i, ev in enumerate(enum_vals):
                    lbl = enum_labels[i] if enum_labels and i < len(enum_labels) else ev
                    presets.append(PresetValue(value=str(ev), label=str(lbl)))
            elif stype in ("coBool", "coBools"):
                presets = [
                    PresetValue("1", "1 (Enabled)"),
                    PresetValue("0", "0 (Disabled)"),
                ]
            elif default_val is not None and str(default_val).strip() != "":
                presets.append(PresetValue(value=str(default_val), label=f"Default: {default_val}"))

            dim = DimensionDefinition(
                key=key,
                label=label,
                category=category,
                tooltip=tooltip,
                unit=unit,
                type=stype,
                presets=presets,
                enum_values=enum_vals,
                enum_labels=enum_labels,
                default_val=str(default_val) if default_val is not None else None,
            )

            self._dimensions_by_key[key] = dim
            if category in self._dimensions_by_category:
                self._dimensions_by_category[category].append(dim)
            self._dimensions_by_category[CAT_ALL].append(dim)

        # Sort dimensions in each category alphabetically by human label
        for cat in self._dimensions_by_category:
            self._dimensions_by_category[cat].sort(key=lambda d: d.label.lower())

    def get_categories(self) -> List[str]:
        """Return the available categories corresponding to Process tabs."""
        return list(PROCESS_CATEGORIES)

    def get_dimensions_for_category(self, category: str) -> List[DimensionDefinition]:
        """Return dimensions belonging to a specific Process category."""
        return list(self._dimensions_by_category.get(category, self._dimensions_by_category[CAT_ALL]))

    def get_all_available_dimensions(self) -> List[DimensionDefinition]:
        """Return all available dimensions across the entire schema."""
        return list(self._dimensions_by_category[CAT_ALL])

    def get_curated_dimensions(self) -> List[DimensionDefinition]:
        """Return curated high-priority dimensions."""
        result = []
        for k in CURATED_OVERRIDES:
            if k in self._dimensions_by_key:
                result.append(self._dimensions_by_key[k])
        return result

    def get_dimension(self, key_or_label: str) -> Optional[DimensionDefinition]:
        """Look up dimension definition by key or human label."""
        try:
            canonical = self.schema.resolve_key(key_or_label)
        except Exception:
            canonical = key_or_label

        if canonical in self._dimensions_by_key:
            return self._dimensions_by_key[canonical]

        rec = self.schema.get_setting(canonical)
        if rec:
            category = classify_setting_category(canonical, rec)
            return DimensionDefinition(
                key=canonical,
                label=rec.get("label") or canonical.replace("_", " ").title(),
                category=category,
                tooltip=rec.get("tooltip") or "",
                unit=rec.get("unit"),
                type=rec.get("type") or "coString",
            )

        return None


_DEFAULT_CATALOG: Optional[DimensionCatalog] = None


def get_default_catalog() -> DimensionCatalog:
    global _DEFAULT_CATALOG
    if _DEFAULT_CATALOG is None:
        _DEFAULT_CATALOG = DimensionCatalog()
    return _DEFAULT_CATALOG
