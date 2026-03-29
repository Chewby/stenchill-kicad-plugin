"""
Stenchill API client - sends Gerber ZIP to the public API and retrieves the STL result.
Author: Thomas COTTARD - https://www.stenchill.com
"""

import json
import os
import re
import ssl
import tempfile
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# Only stdlib used - no external dependencies required.


def _ssl_context() -> ssl.SSLContext:
    """Build an SSL context with broad OS compatibility.

    Resolution order:
    1. certifi (if installed — best cross-platform option)
    2. macOS: Homebrew / system OpenSSL cert bundles
    3. Default system certificates (works on Windows and most Linux)
    """
    # 1. certifi
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass

    # 2. macOS — Python shipped with KiCad often lacks root certs
    import sys
    if sys.platform == "darwin":
        mac_cert_paths = [
            "/opt/homebrew/etc/openssl@3/cert.pem",
            "/opt/homebrew/etc/openssl/cert.pem",
            "/usr/local/etc/openssl@3/cert.pem",
            "/usr/local/etc/openssl/cert.pem",
            "/etc/ssl/cert.pem",
        ]
        for path in mac_cert_paths:
            if os.path.isfile(path):
                return ssl.create_default_context(cafile=path)

    # 3. Default (Windows / Linux)
    return ssl.create_default_context()

API_BASE = "https://www.stenchill.com/api/v1"
STREAM_URL = f"{API_BASE}/generate/stream"
# Client identification key (not a secret - used for rate limiting and source tracking)
API_KEY = "stenchill-kicad-2026-xK9mP4wQ7rT2"
TIMEOUT_SECONDS = 300
# Lazy import to avoid circular dependency at module load time
_user_agent = None

def _get_user_agent() -> str:
    global _user_agent
    if _user_agent is None:
        from . import VERSION
        _user_agent = f"StenchillKiCadPlugin/{VERSION}"
    return _user_agent


class ApiError(Exception):
    """Raised when the Stenchill API returns an error."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def _build_multipart(zip_path, thickness, shrink, pcb_thickness, shoulder_length,
                     shoulder_width, enable_shoulders, shoulder_clearance, nozzle_diameter):
    """Build multipart body and headers for the API request."""
    boundary = f"----StenchillBoundary{uuid.uuid4().hex}"

    with open(zip_path, "rb") as f:
        file_data = f.read()

    file_part = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="gerbers.zip"\r\n'
        f'Content-Type: application/zip\r\n\r\n'
    )

    params = {
        "thickness": str(thickness),
        "shrink": str(shrink),
        "pcbThickness": str(pcb_thickness),
        "shoulderLength": str(shoulder_length),
        "shoulderWidth": str(shoulder_width),
        "enableShoulders": str(enable_shoulders).lower(),
        "shoulderClearance": str(shoulder_clearance),
        "nozzleDiameter": str(nozzle_diameter),
    }

    param_parts = b""
    for name, value in params.items():
        param_parts += (
            f'\r\n--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f'{value}'
        ).encode("utf-8")

    body = file_part.encode("utf-8") + file_data + param_parts + f"\r\n--{boundary}--\r\n".encode("utf-8")
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": _get_user_agent(),
        "X-API-Key": API_KEY,
    }
    return body, headers


def generate_stencil_stream(
    zip_path: str,
    on_progress=None,
    thickness: float = 0.4,
    shrink: float = 0.0,
    pcb_thickness: float = 1.6,
    shoulder_length: float = 15.0,
    shoulder_width: float = 3.0,
    enable_shoulders: bool = True,
    shoulder_clearance: float = 0.3,
    nozzle_diameter: float = 0.4,
) -> str:
    """
    SSE streaming generation - calls on_progress(step, total, label) and returns path to result ZIP.

    Args:
        zip_path: Path to the Gerber ZIP file.
        on_progress: Callback(step: int, total: int, label: str) called for each progress event.
        Other args: Generation parameters.

    Returns:
        Path to the downloaded result ZIP containing STL files.
    """
    body, headers = _build_multipart(zip_path, thickness, shrink, pcb_thickness,
                                     shoulder_length, shoulder_width, enable_shoulders,
                                     shoulder_clearance, nozzle_diameter)

    req = Request(STREAM_URL, data=body, headers=headers, method="POST")
    ctx = _ssl_context()

    try:
        with urlopen(req, timeout=TIMEOUT_SECONDS, context=ctx) as resp:
            stl_path = None
            event_type = None

            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip("\n\r")

                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_str = line[5:].strip()
                    try:
                        data = json.loads(data_str)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    if event_type == "progress" and on_progress:
                        on_progress(
                            data.get("step", 0),
                            data.get("total", 5),
                            data.get("label", ""),
                        )
                    elif event_type == "complete":
                        stl_path = data.get("stlPath", "")
                    elif event_type == "error":
                        raise ApiError(
                            f"Generation failed: {data.get('error', 'unknown')}",
                        )

                    event_type = None

            if not stl_path:
                raise ApiError("No result received from server")

            # Validate download path (whitelist matching server-side regex)
            if not re.match(r'^[a-zA-Z0-9._-]+\.zip$', stl_path):
                raise ApiError("Invalid download path received from server")

            # Download the result ZIP
            download_url = f"{API_BASE}/download/{stl_path}"
            dl_req = Request(download_url, headers={"User-Agent": _get_user_agent(), "X-API-Key": API_KEY})
            with urlopen(dl_req, timeout=TIMEOUT_SECONDS, context=ctx) as dl_resp:
                result_data = dl_resp.read()
                tmp = tempfile.NamedTemporaryFile(suffix=".zip", prefix="stenchill_result_", delete=False)
                try:
                    tmp.write(result_data)
                    tmp.close()
                    return tmp.name
                except Exception:
                    tmp.close()
                    os.unlink(tmp.name)
                    raise

    except HTTPError as e:
        detail = "Unknown error"
        try:
            error_body = e.read().decode("utf-8")
            error_json = json.loads(error_body)
            detail = error_json.get("detail", detail)
        except Exception:
            pass
        raise ApiError(f"API error ({e.code}): {detail}", status_code=e.code)

    except URLError as e:
        raise ApiError(
            f"Cannot reach Stenchill server.\n"
            f"Check your internet connection.\n\n"
            f"Details: {e.reason}"
        )
