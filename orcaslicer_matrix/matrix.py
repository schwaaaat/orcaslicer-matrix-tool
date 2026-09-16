"""Matrix permutation generation, variant naming, and configurable limit enforcement.

Enforces the hard cap of 8 total variants required by COMPARE_MANIFEST_SCHEMA.md.
Provides actionable suggestions if the limit is exceeded.
"""

from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema import resolve_matrix_dict


MAX_DIMENSIONS = 3
MAX_VARIANTS = 8


class DimensionLimitExceededError(ValueError):
    """Raised when the matrix defines more than MAX_DIMENSIONS (3) simultaneous dimensions."""

    def __init__(self, count: int, axes: List[str], max_limit: int = MAX_DIMENSIONS):
        self.count = count
        self.axes = axes
        self.max_limit = max_limit
        msg = (
            f"Matrix defines {count} simultaneous dimensions ({', '.join(axes)}), "
            f"which exceeds the maximum limit of {max_limit} simultaneous dimensions.\n"
            f"A maximum of {max_limit} simultaneous dimensions is supported because any more "
            f"becomes unmanageable and leads to combinatorial explosion.\n"
            f"Please reduce your matrix to {max_limit} or fewer dimensions."
        )
        super().__init__(msg)


class VariantLimitExceededError(ValueError):
    """Raised when the Cartesian product exceeds the configured hard cap."""

    def __init__(self, count: int, axes: Dict[str, List[str]], max_limit: int = MAX_VARIANTS):
        self.count = count
        self.axes = axes
        self.max_limit = max_limit

        lines = [
            f"Matrix permutation produces {count} variants, which exceeds the hard cap of {max_limit} variants.",
            f"This run is configured for at most {max_limit} variants to bound slicing and storage resources.",
            "",
            "Current axes configuration:",
        ]
        for axis, values in axes.items():
            lines.append(f"  - {axis}: {len(values)} values ({values})")

        lines.append("")
        lines.append("Suggestions to stay within the limit:")
        suggestions = self._calculate_reduction_suggestions(axes, max_limit)
        for s in suggestions:
            lines.append(f"  * {s}")

        super().__init__("\n".join(lines))

    @staticmethod
    def _calculate_reduction_suggestions(axes: Dict[str, List[str]], max_limit: int) -> List[str]:
        suggestions: List[str] = []
        axis_names = list(axes.keys())
        counts = {k: len(v) for k, v in axes.items()}

        # 1. Suggest dropping an axis
        if len(axis_names) > 1:
            for name in axis_names:
                remaining_product = 1
                for other in axis_names:
                    if other != name:
                        remaining_product *= counts[other]
                if remaining_product <= max_limit:
                    suggestions.append(
                        f"Drop axis '{name}' -> remaining axes produce {remaining_product} variants."
                    )

        # 2. Suggest trimming values on largest axes
        sorted_axes = sorted(axis_names, key=lambda a: counts[a], reverse=True)
        for name in sorted_axes:
            curr_c = counts[name]
            other_prod = 1
            for other in axis_names:
                if other != name:
                    other_prod *= counts[other]
            for target_c in range(curr_c - 1, 0, -1):
                if target_c * other_prod <= max_limit:
                    suggestions.append(
                        f"Reduce '{name}' from {curr_c} to {target_c} values -> produces {target_c * other_prod} variants."
                    )
                    break

        if not suggestions:
            suggestions.append(f"Reduce number of values across axes until product <= {max_limit}.")

        return suggestions[:4]


def slugify_name(name: str) -> str:
    """Create a clean, filesystem-safe filename slug from a variant name.

    Example:
        'layer_height=0.16, wall_loops=2' -> 'layer_height_0.16_wall_loops_2'
    """
    # Replace '=' and ',' with '_'
    s = name.replace("=", "_").replace(",", "_")
    # Replace non-alphanumeric, dot, dash with underscore
    s = re.sub(r"[^\w\.\-]+", "_", s)
    # Collapse multiple underscores
    s = re.sub(r"_+", "_", s)
    return s.strip("._")


@dataclass(frozen=True)
class Variant:
    """Represents a single permutation in the matrix."""
    name: str
    changes: Dict[str, str]
    slug: str
    gcode_filename: str

    @classmethod
    def from_changes(cls, changes: Dict[str, str], custom_name: Optional[str] = None) -> "Variant":
        if custom_name:
            name = custom_name
        else:
            # Format: "layer_height=0.16, wall_loops=2"
            name = ", ".join(f"{k}={v}" for k, v in sorted(changes.items()))
        slug = slugify_name(name)
        return cls(
            name=name,
            changes=changes,
            slug=slug,
            gcode_filename=f"{slug}.gcode",
        )


def build_variants(
    resolved_matrix: Dict[str, List[str]],
    max_variants: int = MAX_VARIANTS,
    max_dimensions: int = MAX_DIMENSIONS,
) -> List[Variant]:
    """Generate the Cartesian product of the resolved matrix.

    Validates that:
      1. Dimension count does not exceed max_dimensions (default 3).
      2. Total permutation count does not exceed max_variants (default 8).
    """
    if not resolved_matrix:
        raise ValueError("Matrix is empty: at least one axis must be specified.")

    keys = list(resolved_matrix.keys())
    if len(keys) > max_dimensions:
        raise DimensionLimitExceededError(len(keys), keys, max_limit=max_dimensions)

    value_lists = [resolved_matrix[k] for k in keys]

    total_permutations = 1
    for vl in value_lists:
        total_permutations *= len(vl)

    if total_permutations > max_variants:
        raise VariantLimitExceededError(total_permutations, resolved_matrix, max_limit=max_variants)

    variants: List[Variant] = []
    for combination in itertools.product(*value_lists):
        changes = {keys[i]: combination[i] for i in range(len(keys))}
        variants.append(Variant.from_changes(changes))

    return variants


def parse_axis_string(axis_arg: str) -> tuple[str, List[str]]:
    """Parse an individual CLI axis argument like 'layer_height=0.16,0.2,0.24'."""
    if "=" not in axis_arg:
        raise ValueError(f"Invalid axis format '{axis_arg}'. Expected 'axis_name=val1,val2,...'")
    key, val_str = axis_arg.split("=", 1)
    key = key.strip()
    values = [v.strip() for v in val_str.split(",") if v.strip()]
    if not key:
        raise ValueError(f"Empty axis name in '{axis_arg}'")
    if not values:
        raise ValueError(f"No values specified for axis '{key}' in '{axis_arg}'")
    return key, values


def parse_matrix_input(
    config_file: Optional[str | Path] = None,
    matrix_json: Optional[str] = None,
    axis_args: Optional[List[str]] = None,
) -> Dict[str, List[str]]:
    """Parse matrix configuration from JSON file, JSON string, or CLI axis arguments.

    Returns the validated, resolved canonical matrix.
    """
    raw_dict: Dict[str, Any] = {}

    if config_file:
        path = Path(config_file)
        if not path.is_file():
            raise FileNotFoundError(f"Matrix config file not found: {config_file}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Config file '{config_file}' must contain a JSON object mapping axes to values.")
        # If wrapped under a 'matrix' key, unwrap
        if "matrix" in data and isinstance(data["matrix"], dict):
            raw_dict = data["matrix"]
        else:
            raw_dict = data

    elif matrix_json:
        data = json.loads(matrix_json)
        if not isinstance(data, dict):
            raise ValueError("Matrix JSON string must be a JSON object.")
        if "matrix" in data and isinstance(data["matrix"], dict):
            raw_dict = data["matrix"]
        else:
            raw_dict = data

    elif axis_args:
        for arg in axis_args:
            k, vals = parse_axis_string(arg)
            raw_dict[k] = vals

    else:
        raise ValueError(
            "No matrix specification provided. Use --config <file>, --matrix <json>, or --axis <key=v1,v2>"
        )

    return resolve_matrix_dict(raw_dict)
