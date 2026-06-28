"""
Stenchill API client - sends Gerber ZIP to the public API and retrieves the STL result.
Author: Thomas COTTARD - https://www.stenchill.com
"""

# Defer annotation evaluation so PEP 604 unions (e.g. ``tuple | None``) don't run
# at definition time. KiCad bundles Python 3.9, which predates PEP 604, so an
# eagerly-evaluated ``X | None`` return annotation would raise TypeError at import.
from __future__ import annotations

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
    1. certifi (if installed - best cross-platform option)
    2. macOS: Homebrew / system OpenSSL cert bundles
    3. Default system certificates (works on Windows and most Linux)
    """
    # 1. certifi
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass

    # 2. macOS - Python shipped with KiCad often lacks root certs
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

# Public API base. Override with the STENCHILL_API_BASE env var to point the
# plugin at a local/staging backend (e.g. http://localhost:8080/api/v1) for
# testing; defaults to production. A trailing slash is tolerated.
API_BASE = os.environ.get(
    "STENCHILL_API_BASE", "https://www.stenchill.com/api/v1"
).rstrip("/")
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


def _parse_version(v) -> tuple | None:
    """Parse 'AA.BB.CC' into a tuple of ints, or None if unparseable."""
    try:
        return tuple(int(part) for part in v.strip().split("."))
    except (AttributeError, ValueError):
        return None


def is_newer(latest, current) -> bool:
    """True if `latest` is a strictly higher version than `current`.

    Any unparseable input returns False (never nag on a malformed version).
    """
    lv = _parse_version(latest)
    cv = _parse_version(current)
    if lv is None or cv is None:
        return False
    length = max(len(lv), len(cv))
    lv = lv + (0,) * (length - len(lv))
    cv = cv + (0,) * (length - len(cv))
    return lv > cv


def compose_progress_label(label, label_text, face_progress):
    """Build the displayed progress text, mirroring the website's per-face
    composition (`composeFaceProgressLabel`).

    - 0 or 1 face -> the macro ``label_text`` (single face == the macro phase).
    - multiple faces, none active -> ``label_text`` (macro already reflects
      packaging/done).
    - multiple faces with at least one active -> ``"Front: X · Back: Y"`` where a
      done face shows ``"✓"`` and an active face shows its per-face ``labelText``.

    Each ``face_progress`` entry is the SSE shape
    ``{"face", "label", "labelText", "done"}``.
    """
    if not face_progress or len(face_progress) <= 1:
        return label_text
    active = [f for f in face_progress if not f.get("done")]
    if not active:
        return label_text
    parts = []
    for f in face_progress:
        name = str(f.get("face", "")).capitalize() or "?"
        text = "✓" if f.get("done") else (f.get("labelText") or f.get("label", ""))
        parts.append(f"{name}: {text}")
    return " · ".join(parts)


def fetch_latest_version(timeout: int = 4) -> str | None:
    """GET /plugin/version and return the latest version string, or None on any
    network/parse error (the caller stays silent on failure)."""
    url = f"{API_BASE}/plugin/version"
    try:
        req = Request(url, headers={"User-Agent": _get_user_agent()})
        ctx = _ssl_context()
        with urlopen(req, timeout=timeout, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest = data.get("latest")
        return latest if isinstance(latest, str) else None
    except Exception:
        return None


class ApiError(Exception):
    """Raised when the Stenchill API returns an error."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def _build_multipart(zip_path, thickness, shrink, pcb_thickness, shoulder_length,
                     shoulder_width, enable_shoulders, shoulder_clearance, nozzle_diameter,
                     enable_slotify):
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
        "enableSlotify": str(enable_slotify).lower(),
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
    on_queued=None,
    thickness: float = 0.4,
    shrink: float = 0.0,
    pcb_thickness: float = 1.6,
    shoulder_length: float = 15.0,
    shoulder_width: float = 3.0,
    enable_shoulders: bool = True,
    shoulder_clearance: float = 0.3,
    nozzle_diameter: float = 0.4,
    enable_slotify: bool = True,
) -> str:
    """
    SSE streaming generation - calls on_progress(step, total, label, label_text) and returns path to result ZIP.

    Args:
        zip_path: Path to the Gerber ZIP file.
        on_progress: Callback(step: int, total: int, label: str, label_text: str) called for each progress event.
        on_queued: Callback(position: int, queue_depth: int, eta_seconds: int) called when request is queued.
        Other args: Generation parameters.

    Returns:
        Path to the downloaded result ZIP containing STL files.
    """
    body, headers = _build_multipart(zip_path, thickness, shrink, pcb_thickness,
                                     shoulder_length, shoulder_width, enable_shoulders,
                                     shoulder_clearance, nozzle_diameter, enable_slotify)

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
                            data.get("labelText", ""),
                            data.get("faceProgress", []),
                        )
                    elif event_type == "queued" and on_queued:
                        on_queued(
                            data.get("position", 1),
                            data.get("queueDepth", 1),
                            data.get("etaSeconds", 0),
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
