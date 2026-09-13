"""OrcaSlicer Matrix Tool: Standalone, token-free matrix slicer and compare manifest generator."""

from .client import OrcaApiError, OrcaAuthError, OrcaClient, OrcaConnectionError, OrcaError
from .matrix import Variant, VariantLimitExceededError, build_variants, parse_matrix_input
from .runner import MatrixRunner
from .schema import SettingsSchema, UnknownSettingError, resolve_matrix_dict, resolve_setting

__version__ = "1.0.0"
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
    "VariantLimitExceededError",
    "build_variants",
    "parse_matrix_input",
    "MatrixRunner",
]
