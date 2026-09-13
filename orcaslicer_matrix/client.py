"""Standard-library REST client for OrcaSlicer Remote API.

Zero runtime third-party dependencies (uses urllib.request).
Implements direct HTTP communication with OrcaSlicer's embedded Boost.Beast server.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_BASE_URL = "http://127.0.0.1:13130"
DEFAULT_TIMEOUT = 30.0


class OrcaError(Exception):
    """Base exception for all OrcaSlicer API errors."""
    pass


class OrcaConnectionError(OrcaError):
    """Raised when the client cannot connect to OrcaSlicer."""
    pass


class OrcaAuthError(OrcaError):
    """Raised when authentication fails (missing or rejected API token)."""
    pass


class OrcaApiError(OrcaError):
    """Raised when OrcaSlicer returns an HTTP 4xx or 5xx response."""

    def __init__(self, status_code: int, body: Any, message: str = ""):
        self.status_code = status_code
        self.body = body
        msg = message or f"OrcaSlicer API returned HTTP {status_code}: {body}"
        super().__init__(msg)


def discover_api_token() -> Optional[str]:
    """Attempt to discover the OrcaSlicer Remote API token from the environment or configuration.

    Search sequence:
    1. ORCA_API_TOKEN environment variable.
    2. %APPDATA%/OrcaSlicer/OrcaSlicer.conf (Windows) or ~/.config/OrcaSlicer/OrcaSlicer.conf (Linux/macOS).
    3. Local .mcp.json files in parent directories.
    """
    # 1. Env var
    env_token = os.environ.get("ORCA_API_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()

    # 2. OrcaSlicer.conf
    conf_candidates: List[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        conf_candidates.append(Path(appdata) / "OrcaSlicer" / "OrcaSlicer.conf")
    user_home = Path.home()
    conf_candidates.append(user_home / ".config" / "OrcaSlicer" / "OrcaSlicer.conf")
    conf_candidates.append(user_home / "AppData" / "Roaming" / "OrcaSlicer" / "OrcaSlicer.conf")

    for conf_path in conf_candidates:
        if conf_path.is_file():
            try:
                content = conf_path.read_text(encoding="utf-8", errors="ignore")
                match = re.search(r'"remote_api_token"\s*:\s*"([^"]+)"', content)
                if match and match.group(1).strip():
                    return match.group(1).strip()
            except Exception:
                pass

    # 3. .mcp.json
    mcp_candidates = [
        Path.cwd() / ".mcp.json",
        Path.cwd().parent / ".mcp.json",
        Path("G:/Claude/orcaslicer-mcp/.mcp.json"),
    ]
    for mcp_path in mcp_candidates:
        if mcp_path.is_file():
            try:
                data = json.loads(mcp_path.read_text(encoding="utf-8", errors="ignore"))
                # search for token or headers with X-Api-Token
                content_str = json.dumps(data)
                match = re.search(r'"X-Api-Token":\s*"([^"]+)"', content_str)
                if match:
                    return match.group(1).strip()
                match = re.search(r'"token":\s*"([^"]+)"', content_str)
                if match:
                    return match.group(1).strip()
            except Exception:
                pass

    return None


class OrcaClient:
    """Synchronous REST client for OrcaSlicer's Remote API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = (base_url or os.environ.get("ORCA_API_URL") or DEFAULT_BASE_URL).rstrip("/")
        discovered_token = token or discover_api_token()
        if not discovered_token:
            raise OrcaAuthError(
                "No OrcaSlicer Remote API token found. "
                "Specify --token, set ORCA_API_TOKEN env var, or configure Remote API in OrcaSlicer Preferences."
            )
        self.token = discovered_token
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Optional[Any] = None,
        timeout: Optional[float] = None,
        expect_raw: bool = False,
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = {
            "X-Api-Token": self.token,
            "User-Agent": "OrcaSlicerMatrixTool/1.0",
        }
        data_bytes: Optional[bytes] = None

        if body is not None:
            if isinstance(body, (dict, list)):
                data_bytes = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            elif isinstance(body, bytes):
                data_bytes = body
            elif isinstance(body, str):
                data_bytes = body.encode("utf-8")

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        req_timeout = timeout if timeout is not None else self.timeout

        try:
            with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                resp_bytes = resp.read()
                if expect_raw:
                    return resp_bytes
                if not resp_bytes:
                    return {}
                try:
                    return json.loads(resp_bytes.decode("utf-8"))
                except UnicodeDecodeError:
                    return resp_bytes
                except json.JSONDecodeError:
                    return resp_bytes.decode("utf-8", errors="replace")

        except urllib.error.HTTPError as e:
            err_body: Any = None
            try:
                raw_err = e.read()
                err_body = json.loads(raw_err.decode("utf-8"))
            except Exception:
                err_body = raw_err.decode("utf-8", errors="replace") if "raw_err" in locals() else ""

            if e.code in (401, 403):
                raise OrcaAuthError(
                    f"OrcaSlicer Remote API authentication failed (HTTP {e.code}). Check your API token."
                ) from e

            raise OrcaApiError(e.code, err_body) from e

        except (urllib.error.URLError, TimeoutError, ConnectionRefusedError, OSError) as e:
            raise OrcaConnectionError(
                f"Could not connect to OrcaSlicer at {self.base_url}: {e}. "
                "Ensure OrcaSlicer is running and Remote API is enabled in Preferences > Remote API."
            ) from e

    def get_status(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Fetch current app/plate status: presets, objects, and slice result validity."""
        return self._request("GET", "/api/v1/status", timeout=timeout)

    def get_objects(self, timeout: Optional[float] = None) -> List[Dict[str, Any]]:
        """Fetch list of objects currently on the plater."""
        res = self._request("GET", "/api/v1/objects", timeout=timeout)
        if isinstance(res, dict) and "objects" in res:
            return res["objects"]
        return []

    def get_config(self, keys: Optional[List[str]] = None) -> Dict[str, str]:
        """Read current merged config values.

        IMPORTANT: Always fetches full config and filters client-side, avoiding the
        OrcaSlicer server's known comma-splitting query bug on `?keys=`.
        """
        data = self._request("GET", "/api/v1/config")
        cfg: Dict[str, str] = data.get("config", {}) if isinstance(data, dict) else {}
        if keys:
            return {k: cfg[k] for k in keys if k in cfg}
        return cfg

    def put_config(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """Apply config overrides.

        Args:
            changes: Map of setting keys to new values.

        Returns:
            Dict containing 'applied' list and optional 'errors' dict.
        """
        # Ensure all values are sent as strings
        str_changes = {k: str(v) for k, v in changes.items()}
        return self._request("PUT", "/api/v1/config", body=str_changes)

    def slice(self, retry_on_not_started: bool = True) -> Dict[str, Any]:
        """Trigger an asynchronous slice.

        Handles transient HTTP 422 'slice_not_started' by pausing 1.5s and retrying once.
        """
        try:
            return self._request("POST", "/api/v1/slice")
        except OrcaApiError as e:
            is_not_started = False
            if e.status_code == 422:
                body_str = json.dumps(e.body) if isinstance(e.body, dict) else str(e.body)
                if "slice_not_started" in body_str:
                    is_not_started = True

            if is_not_started and retry_on_not_started:
                time.sleep(1.5)
                return self._request("POST", "/api/v1/slice")
            raise

    def slice_status(self) -> Dict[str, Any]:
        """Poll the current slice status and stats."""
        return self._request("GET", "/api/v1/slice/status")

    def cancel_slice(self) -> Dict[str, Any]:
        """Cancel an ongoing slice."""
        return self._request("POST", "/api/v1/slice/cancel")

    def get_gcode(self, timeout: float = 60.0) -> bytes:
        """Download raw G-code bytes from the last completed slice."""
        return self._request("GET", "/api/v1/gcode", timeout=timeout, expect_raw=True)
