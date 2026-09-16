"""Typed HTTP client used by Matrix Studio's worker threads."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from .client import DEFAULT_BASE_URL, discover_api_token


class StudioApiError(RuntimeError):
    pass


class IncompatibleOrcaError(StudioApiError):
    pass


@dataclass(frozen=True)
class Capabilities:
    api_version: str
    app_version: str
    build_id: str
    features: frozenset[str] = field(default_factory=frozenset)
    max_matrix_variants: int = 32
    compare_bundle_versions: tuple[int, ...] = (1,)

    @property
    def supports_matrix_studio(self) -> bool:
        required = {"status", "config", "slice", "slice_cancel", "gcode"}
        return required.issubset(self.features)


class StudioClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.base_url = (base_url or os.getenv("ORCA_API_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.token = token or discover_api_token()
        if not self.token:
            raise StudioApiError("No OrcaSlicer Remote API token was found.")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"X-Api-Token": self.token, "User-Agent": "OrcaMatrixStudio/2.0"},
            timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "StudioClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise StudioApiError(f"Could not reach OrcaSlicer at {self.base_url}: {exc}") from exc
        if response.status_code in (401, 403):
            raise StudioApiError("OrcaSlicer rejected the Remote API token.")
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise StudioApiError(f"OrcaSlicer returned HTTP {response.status_code}: {detail}")
        return response

    def capabilities(self) -> Capabilities:
        response = self._request("GET", "/api/v1/capabilities")
        data = response.json()
        result = Capabilities(
            api_version=str(data.get("api_version", "0")),
            app_version=str(data.get("app_version", "unknown")),
            build_id=str(data.get("build_id", "unknown")),
            features=frozenset(str(item) for item in data.get("features", [])),
            max_matrix_variants=int(data.get("max_matrix_variants", 8)),
            compare_bundle_versions=tuple(int(item) for item in data.get("compare_bundle_versions", [1])),
        )
        if not result.supports_matrix_studio or 2 not in result.compare_bundle_versions:
            raise IncompatibleOrcaError(
                "This OrcaSlicer build does not provide the Matrix Studio v2 contract."
            )
        return result

    def status(self) -> Dict[str, Any]:
        return self._request("GET", "/api/v1/status").json()

    def objects(self) -> List[Dict[str, Any]]:
        data = self._request("GET", "/api/v1/objects").json()
        return list(data.get("objects", []))

    def config(self) -> Dict[str, str]:
        data = self._request("GET", "/api/v1/config").json()
        return {str(k): str(v) for k, v in data.get("config", {}).items()}

    def apply_config(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        normalized = {
            key: ("1" if value is True else "0" if value is False else str(value))
            for key, value in changes.items()
        }
        return self._request("PUT", "/api/v1/config", json=normalized).json()

    def start_slice(self) -> Dict[str, Any]:
        return self._request("POST", "/api/v1/slice").json()

    def slice_status(self) -> Dict[str, Any]:
        return self._request("GET", "/api/v1/slice/status").json()

    def cancel_slice(self) -> Dict[str, Any]:
        return self._request("POST", "/api/v1/slice/cancel").json()

    def gcode(self, timeout: float = 120.0) -> bytes:
        return self._request("GET", "/api/v1/gcode", timeout=timeout).content

    def plate_render(self) -> bytes:
        return self._request("GET", "/api/v1/plate/render").content
