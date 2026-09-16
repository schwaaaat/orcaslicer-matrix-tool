"""OrcaSlicer Matrix Studio."""

from .catalog import DimensionCatalog, DimensionDefinition, PresetValue, get_default_catalog
from .client import OrcaApiError, OrcaAuthError, OrcaClient, OrcaConnectionError, OrcaError
from .matrix import (
    MAX_DIMENSIONS,
    MAX_VARIANTS,
    DimensionLimitExceededError,
    Variant,
    VariantLimitExceededError,
    build_variants,
    parse_matrix_input,
)
from .runner import MatrixRunner
from .run_bundle import AxisDefinition, RunBundle, RunBundleStore, RunLibrary, VariantRecord
from .schema import SettingsSchema, UnknownSettingError, resolve_matrix_dict, resolve_setting

__version__ = "2.0.0"
__all__ = [
    "OrcaClient",
    "OrcaError",
    "OrcaConnectionError",
    "OrcaAuthError",
    "OrcaApiError",
    "SettingsSchema",
    "UnknownSettingError",
    "resolve_setting",
    "resolve_matrix_dict",
    "Variant",
    "MAX_DIMENSIONS",
    "MAX_VARIANTS",
    "DimensionLimitExceededError",
    "VariantLimitExceededError",
    "build_variants",
    "parse_matrix_input",
    "MatrixRunner",
    "DimensionCatalog",
    "DimensionDefinition",
    "PresetValue",
    "get_default_catalog",
    "AxisDefinition",
    "VariantRecord",
    "RunBundle",
    "RunBundleStore",
    "RunLibrary",
]
