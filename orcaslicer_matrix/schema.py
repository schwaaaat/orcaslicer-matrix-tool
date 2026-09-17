"""Schema loader and setting key resolver for OrcaSlicer settings.

Resolves human-readable labels (e.g. 'layer height', 'wall count') and raw keys
('layer_height', 'wall_loops') to canonical OrcaSlicer config keys using
`print_settings_schema.json`.
"""

from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional


class UnknownSettingError(ValueError):
    """Raised when a setting axis cannot be resolved to a known OrcaSlicer config key."""

    def __init__(self, key: str, suggestions: Optional[List[str]] = None):
        self.key = key
        self.suggestions = suggestions or []
        if self.suggestions:
            sugg_str = ", ".join(f"'{s}'" for s in self.suggestions)
            msg = f"Unknown OrcaSlicer setting '{key}'. Did you mean: {sugg_str}?"
        else:
            msg = f"Unknown OrcaSlicer setting '{key}'. Check print_settings_schema.json for valid keys."
        super().__init__(msg)


# Common synonyms and aliases from other slicers or human conventions
COMMON_ALIASES: Dict[str, str] = {
    "wall count": "wall_loops",
    "wall counts": "wall_loops",
    "wall loops": "wall_loops",
    "walls": "wall_loops",
    "perimeters": "wall_loops",
    "infill": "sparse_infill_density",
    "infill density": "sparse_infill_density",
    "sparse infill density": "sparse_infill_density",
    "infill pattern": "sparse_infill_pattern",
    "sparse infill pattern": "sparse_infill_pattern",
    "layer height": "layer_height",
    "initial layer height": "initial_layer_height",
    "first layer height": "initial_layer_height",
    "print speed": "outer_wall_speed",
    "speed": "outer_wall_speed",
    "outer wall speed": "outer_wall_speed",
    "inner wall speed": "inner_wall_speed",
    "infill speed": "sparse_infill_speed",
    "travel speed": "travel_speed",
    "top surface speed": "top_surface_speed",
    "nozzle temp": "nozzle_temperature",
    "nozzle temperature": "nozzle_temperature",
    "bed temp": "hot_plate_temp",
    "bed temperature": "hot_plate_temp",
    "hot plate temp": "hot_plate_temp",
    "top layers": "top_shell_layers",
    "bottom layers": "bottom_shell_layers",
    "top shell layers": "top_shell_layers",
    "bottom shell layers": "bottom_shell_layers",
    "support": "enable_support",
    "supports": "enable_support",
    "enable support": "enable_support",
    "tree support": "enable_support",
    "support type": "support_type",
    "brim type": "brim_type",
    "brim width": "brim_width",
    "seam position": "seam_position",
    "fan speed": "fan_max_speed",
    "ironing": "ironing_type",
    "elephant foot compensation": "elefant_foot_compensation",
    "elephants foot compensation": "elefant_foot_compensation",
}


def _normalize(name: str) -> str:
    """Normalize string for fuzzy comparison: lowercased, stripped, hyphens/spaces to underscores."""
    return name.strip().lower().replace("-", "_").replace(" ", "_")


class SettingsSchema:
    """Provides lookup and validation against OrcaSlicer's print_settings_schema.json."""

    def __init__(self, schema_path: Optional[str | Path] = None):
        self._schema_path = self._locate_schema(schema_path)
        self._raw_schema: Dict[str, Any] = {}
        self._settings: Dict[str, Dict[str, Any]] = {}
        self._normalized_keys: Dict[str, str] = {}
        self._label_map: Dict[str, str] = {}
        self._load()

    @staticmethod
    def _locate_schema(explicit_path: Optional[str | Path]) -> Path:
        if explicit_path:
            p = Path(explicit_path)
            if p.is_file():
                return p
            raise FileNotFoundError(f"Schema file not found at: {explicit_path}")

        candidates: List[Path] = []

        # 1. Package directory (adjacent to this file) and its parent
        here = Path(__file__).resolve().parent
        candidates.append(here / "print_settings_schema.json")
        candidates.append(here.parent / "print_settings_schema.json")

        # 2. PyInstaller MEIPASS if running bundled
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            m_path = Path(meipass)
            candidates.append(m_path / "print_settings_schema.json")
            candidates.append(m_path / "orcaslicer_matrix" / "print_settings_schema.json")

        # 3. Executable directory (for frozen or runner-launched binaries)
        try:
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / "print_settings_schema.json")
            candidates.append(exe_dir / "_internal" / "print_settings_schema.json")
            candidates.append(exe_dir / "_internal" / "orcaslicer_matrix" / "print_settings_schema.json")
            candidates.append(exe_dir.parent / "print_settings_schema.json")
        except Exception:
            pass

        # 4. importlib.resources fallback
        try:
            import importlib.resources as pkg_resources
            ref = pkg_resources.files("orcaslicer_matrix").joinpath("print_settings_schema.json")
            if hasattr(ref, "is_file") and ref.is_file():
                candidates.append(Path(str(ref)))
        except Exception:
            pass

        # 5. Current working directory and parent
        cwd = Path.cwd()
        candidates.append(cwd / "print_settings_schema.json")
        candidates.append(cwd.parent / "print_settings_schema.json")

        for c in candidates:
            try:
                if c.is_file():
                    return c.resolve()
            except OSError:
                continue

        raise FileNotFoundError(
            "Could not locate 'print_settings_schema.json'. "
            "Pass schema_path explicitly or ensure it exists in the workspace."
        )

    def _load(self) -> None:
        with open(self._schema_path, "r", encoding="utf-8") as f:
            self._raw_schema = json.load(f)

        for key, rec in self._raw_schema.items():
            if key.startswith("_") or not isinstance(rec, dict):
                continue
            self._settings[key] = rec
            self._normalized_keys[_normalize(key)] = key

            label = rec.get("label")
            if label and isinstance(label, str):
                self._label_map[label.strip().lower()] = key
                self._label_map[_normalize(label)] = key

    @property
    def schema_path(self) -> Path:
        return self._schema_path

    @property
    def setting_keys(self) -> List[str]:
        return list(self._settings.keys())

    def get_setting(self, canonical_key: str) -> Optional[Dict[str, Any]]:
        return self._settings.get(canonical_key)

    def resolve_key(self, name: str) -> str:
        """Resolve a key or label to a canonical OrcaSlicer setting key.

        Order of precedence:
        1. Exact match against schema keys
        2. Known human aliases (e.g. 'wall count' -> 'wall_loops')
        3. Normalized key match ('layer-height' -> 'layer_height')
        4. Human label match ('Layer height' -> 'layer_height')
        5. Raise UnknownSettingError with closest suggestions
        """
        raw = name.strip()
        if raw in self._settings:
            return raw

        lower_raw = raw.lower()
        if lower_raw in COMMON_ALIASES:
            alias_target = COMMON_ALIASES[lower_raw]
            if alias_target in self._settings:
                return alias_target

        norm = _normalize(raw)
        if norm in COMMON_ALIASES:
            alias_target = COMMON_ALIASES[norm]
            if alias_target in self._settings:
                return alias_target

        if norm in self._normalized_keys:
            return self._normalized_keys[norm]

        if lower_raw in self._label_map:
            return self._label_map[lower_raw]

        if norm in self._label_map:
            return self._label_map[norm]

        # Not found - compute close suggestions
        suggestions = self.suggest(raw)
        raise UnknownSettingError(name, suggestions)

    def suggest(self, query: str, limit: int = 5) -> List[str]:
        """Find closest matching keys or labels for an unrecognized input."""
        q = query.strip().lower()
        q_norm = _normalize(query)

        # Candidates pool: all keys + all labels
        candidates = list(self._settings.keys()) + list(self._label_map.keys())
        matches = difflib.get_close_matches(q, candidates, n=limit, cutoff=0.5)
        if not matches and q_norm != q:
            matches = difflib.get_close_matches(q_norm, candidates, n=limit, cutoff=0.5)

        # Map label matches back to canonical keys for user clarity
        results = []
        seen = set()
        for m in matches:
            canonical = self._settings.get(m)
            if canonical:
                key_name = m
            else:
                key_name = self._label_map.get(m, m)
            if key_name not in seen:
                seen.add(key_name)
                results.append(key_name)
        return results[:limit]


_DEFAULT_SCHEMA: Optional[SettingsSchema] = None


def get_default_schema() -> SettingsSchema:
    """Get or instantiate singleton default schema."""
    global _DEFAULT_SCHEMA
    if _DEFAULT_SCHEMA is None:
        _DEFAULT_SCHEMA = SettingsSchema()
    return _DEFAULT_SCHEMA


def resolve_setting(name: str) -> str:
    """Convenience helper to resolve setting key against default schema."""
    return get_default_schema().resolve_key(name)


def resolve_matrix_dict(matrix: Dict[str, Any]) -> Dict[str, List[str]]:
    """Validate and resolve matrix dictionary keys, ensuring all values are list of strings.

    Example input:
        {"layer height": [0.16, 0.20], "wall_loops": ["2", 3]}
    Returns:
        {"layer_height": ["0.16", "0.2"], "wall_loops": ["2", "3"]}
    """
    schema = get_default_schema()
    resolved: Dict[str, List[str]] = {}

    for axis_name, values in matrix.items():
        canonical = schema.resolve_key(axis_name)
        if not isinstance(values, list):
            values = [values]
        if not values:
            raise ValueError(f"Axis '{axis_name}' (resolved to '{canonical}') has no values specified.")
        # Ensure all values are converted to string format
        resolved[canonical] = [str(v) for v in values]

    return resolved
