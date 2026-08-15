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
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# Only stdlib used - no external dependencies required.


_ssl_ctx_cache = None


def _ssl_context() -> ssl.SSLContext:
    """Return the shared SSL context, building it on first use. The resolution
    (certifi import, cert-path probing, CA-bundle parse) never changes within a
    session, so it runs once instead of on every request."""
    global _ssl_ctx_cache
    if _ssl_ctx_cache is None:
        _ssl_ctx_cache = _build_ssl_context()
    return _ssl_ctx_cache


def _build_ssl_context() -> ssl.SSLContext:
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
SHARE_URL = f"{API_BASE}/plugin/share"
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


def compose_progress_label(label_text, face_progress):
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


class GenerationCancelled(Exception):
    """Raised inside generate_stencil_stream when the caller's cancel_event is
    set: the stream is abandoned and the result is never downloaded."""


def _as_int(value, default=0):
    """Coerce an SSE payload field to int, tolerating null/strings/garbage.
    The server contract says int, but a proxy or server change must degrade to
    the default rather than kill the generation with a TypeError."""
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _dispatch_sse_event(event_type, data_str, on_progress, on_queued):
    """Handle one complete SSE event. Returns the stlPath for a 'complete'
    event, None otherwise. Raises ApiError for an 'error' event. Malformed
    payloads are skipped silently (the stream must survive them).

    Per the SSE spec, an event with no ``event:`` field has type "message"."""
    if event_type is None:
        event_type = "message"
    try:
        data = json.loads(data_str)
    except ValueError:  # JSONDecodeError is a subclass of ValueError
        return None
    if not isinstance(data, dict):
        return None

    if event_type == "progress" and on_progress:
        face_progress = data.get("faceProgress")
        on_progress(
            _as_int(data.get("step"), 0),
            _as_int(data.get("total"), 5),
            str(data.get("label") or ""),
            str(data.get("labelText") or ""),
            face_progress if isinstance(face_progress, list) else [],
        )
    elif event_type == "queued" and on_queued:
        on_queued(
            _as_int(data.get("position"), 1),
            _as_int(data.get("queueDepth"), 1),
            _as_int(data.get("etaSeconds"), 0),
        )
    elif event_type == "complete":
        return data.get("stlPath", "")
    elif event_type == "error":
        raise ApiError(f"Generation failed: {data.get('error', 'unknown')}")
    return None


# Defaults matching the web UI (see dialog.py's own _DEFAULTS, which the
# dialog's params dict is built from). generate_stencil_stream merges its
# caller-supplied params dict onto this, so a call without ``params`` (or one
# that omits a key) behaves exactly as it did when these were 10 keyword
# arguments with these same defaults.
_DEFAULT_PARAMS = {
    "thickness": 0.4,
    "shrink": 0.0,
    "pcb_thickness": 1.6,
    "shoulder_length": 15.0,
    "shoulder_width": 3.0,
    "enable_shoulders": True,
    "shoulder_clearance": 0.3,
    "nozzle_diameter": 0.4,
    "enable_slotify": True,
    "drop_unprintable_grids": True,
}


def _build_multipart(zip_path, thickness, shrink, pcb_thickness, shoulder_length,
                     shoulder_width, enable_shoulders, shoulder_clearance, nozzle_diameter,
                     enable_slotify, drop_unprintable_grids):
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
        "dropUnprintableGrids": str(drop_unprintable_grids).lower(),
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


def _build_file_multipart(zip_path: str):
    """Multipart body + headers carrying only the gerber ZIP under field 'file'.

    The share endpoint needs the file alone (no generation params), so this is a
    trimmed sibling of ``_build_multipart``.
    """
    boundary = f"----StenchillBoundary{uuid.uuid4().hex}"

    with open(zip_path, "rb") as f:
        file_data = f.read()

    file_part = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="gerbers.zip"\r\n'
        f'Content-Type: application/zip\r\n\r\n'
    )

    body = file_part.encode("utf-8") + file_data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": _get_user_agent(),
        "X-API-Key": API_KEY,
    }
    return body, headers


def share_stencil(zip_path: str, params: dict | None = None) -> str:
    """Upload the gerber ZIP to the share endpoint and return the /view URL.

    When ``params`` (the snake_case dialog dict) is provided, a
    stenchill-params.json is embedded in the ZIP so /view reproduces the
    plugin's exact stencil. NOTE: this MUTATES the file at ``zip_path`` in
    place (fine for the dialog's throwaway export, surprising otherwise).
    Raises ApiError on any HTTP/network failure.
    """
    if params is not None:
        from .share_params import inject_params_into_zip
        inject_params_into_zip(zip_path, params)
    body, headers = _build_file_multipart(zip_path)
    req = Request(SHARE_URL, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, context=_ssl_context(), timeout=TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        url = payload.get("url")
        if not url:
            raise ApiError("Share response did not include a URL.")
        return url
    except HTTPError as e:
        detail = e.read().decode("utf-8", "replace") if e.fp else ""
        raise ApiError(f"Share failed (HTTP {e.code}): {detail}", status_code=e.code)
    except URLError as e:
        raise ApiError(f"Could not reach the server: {e.reason}")


def is_trusted_view_url(url) -> bool:
    """The /view URL comes from the share response; only hand trusted links to
    the browser. Anything else is shown as plain text instead of opened, so a
    misbehaving backend can't redirect the user off-site. Trusted:
    https://stenchill.com (production) or a localhost / 127.0.0.1 URL on any
    port (local development against a dev backend).

    Vit ici et non dans dialog.py depuis le 2026-08-09 : c'est la sortie de
    ``share_stencil`` que cette fonction filtre, et dialog.py importe wx, ce qui
    la rendait intestable hors KiCad.
    """
    # Refus de tout antislash AVANT le parse : urlparse et les navigateurs
    # WHATWG ne s'accordent pas sur la fin de l'autorite. Sur
    # « https://evil.com\\@stenchill.com/x », urlparse lit stenchill.com comme
    # hote, mais Chrome et Firefox coupent l'autorite au « \\ » et naviguent
    # vers evil.com — exactement le detournement que ce filtre existe pour
    # empecher. Aucune URL legitime du backend n'en contient.
    if not isinstance(url, str) or "\\" in url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.hostname in ("localhost", "127.0.0.1"):
        return parsed.scheme in ("http", "https")
    return parsed.scheme == "https" and parsed.hostname in ("stenchill.com", "www.stenchill.com")


def _flush_sse_event(event_type, data_lines, on_progress, on_queued):
    """Dispatch an assembled SSE event if it carried data lines, else None."""
    if not data_lines:
        return None
    return _dispatch_sse_event(event_type, "\n".join(data_lines), on_progress, on_queued)


def _read_sse_stream(resp, cancel_event, on_progress, on_queued):
    """Consume an SSE response and return the final stlPath (from the
    'complete' event) or None.

    Spec-conformant assembly: data lines accumulate until a blank line ends the
    event (multi-line data joined with "\\n"); comment lines (": ping"
    keep-alives) and unknown fields (id:, retry:) are ignored. Honours
    cancel_event between lines; propagates ApiError from an 'error' event.
    """
    stl_path = None
    event_type = None
    data_lines = []
    for raw_line in resp:
        if cancel_event is not None and cancel_event.is_set():
            raise GenerationCancelled()
        line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
        if not line:
            result = _flush_sse_event(event_type, data_lines, on_progress, on_queued)
            if result is not None:
                stl_path = result
            event_type = None
            data_lines = []
        elif line.startswith(":"):
            pass  # comment / keep-alive
        elif line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))

    # Dispatch a final event not terminated by a blank line.
    result = _flush_sse_event(event_type, data_lines, on_progress, on_queued)
    if result is not None:
        stl_path = result
    return stl_path


def _download_result(download_url, ctx, cancel_event):
    """Stream the result ZIP to a temp file, honouring cancel_event mid-download.
    Returns the temp file path; removes the temp file on any failure."""
    dl_req = Request(download_url, headers={"User-Agent": _get_user_agent(), "X-API-Key": API_KEY})
    with urlopen(dl_req, timeout=TIMEOUT_SECONDS, context=ctx) as dl_resp:
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", prefix="stenchill_result_", delete=False)
        try:
            # Stream in chunks: constant memory for multi-MB results, and
            # cancellation is honoured mid-download.
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise GenerationCancelled()
                chunk = dl_resp.read(64 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)
            tmp.close()
            return tmp.name
        except Exception:
            tmp.close()
            os.unlink(tmp.name)
            raise


def generate_stencil_stream(
    zip_path: str,
    params: dict | None = None,
    on_progress=None,
    on_queued=None,
    cancel_event=None,
) -> str:
    """
    SSE streaming generation - returns path to the result ZIP.

    Args:
        zip_path: Path to the Gerber ZIP file.
        params: Generation parameters (thickness, shrink, pcb_thickness,
            shoulder_length, shoulder_width, enable_shoulders,
            shoulder_clearance, nozzle_diameter, enable_slotify,
            drop_unprintable_grids). Any key omitted falls back to
            _DEFAULT_PARAMS, so a call without ``params`` behaves exactly like
            the pre-refactor defaults.
        on_progress: Callback(step: int, total: int, label: str, label_text: str,
            face_progress: list) called for each progress event.
        on_queued: Callback(position: int, queue_depth: int, eta_seconds: int) called when request is queued.
        cancel_event: Optional threading.Event; when set, the stream is
            abandoned (GenerationCancelled) and the result is never downloaded.

    Returns:
        Path to the downloaded result ZIP containing STL files.

    Raises:
        GenerationCancelled: cancel_event was set during the stream.
        ApiError: server or network error.
    """
    merged = {**_DEFAULT_PARAMS, **(params or {})}
    body, headers = _build_multipart(zip_path, merged["thickness"], merged["shrink"],
                                     merged["pcb_thickness"], merged["shoulder_length"],
                                     merged["shoulder_width"], merged["enable_shoulders"],
                                     merged["shoulder_clearance"], merged["nozzle_diameter"],
                                     merged["enable_slotify"], merged["drop_unprintable_grids"])

    req = Request(STREAM_URL, data=body, headers=headers, method="POST")
    ctx = _ssl_context()

    try:
        with urlopen(req, timeout=TIMEOUT_SECONDS, context=ctx) as resp:
            stl_path = _read_sse_stream(resp, cancel_event, on_progress, on_queued)

        if cancel_event is not None and cancel_event.is_set():
            raise GenerationCancelled()

        if not stl_path:
            raise ApiError("No result received from server")

        # Validate download path (whitelist matching server-side regex).
        # \Z, not $, so a trailing newline can't slip through the whitelist.
        if not re.match(r'^[a-zA-Z0-9._-]+\.zip\Z', stl_path):
            raise ApiError("Invalid download path received from server")

        download_url = f"{API_BASE}/download/{stl_path}"
        return _download_result(download_url, ctx, cancel_event)

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
