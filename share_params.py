"""Build and persist the Stenchill generation parameters as JSON.

Shared by the share flow (embeds the JSON inside the upload ZIP so /view can
reproduce the plugin's exact stencil) and the normal generation flow (drops the
JSON in the output folder as a record of the settings used).

Pure stdlib, no pcbnew; importable and unit-testable outside KiCad.
"""
from __future__ import annotations

import json
import os
import zipfile

PARAMS_FILENAME = "stenchill-params.json"
SCHEMA_VERSION = 1

# snake_case dialog key -> camelCase key matching the site's StencilOptions.
_KEY_MAP = {
    "thickness": "thickness",
    "shrink": "shrink",
    "nozzle_diameter": "nozzleDiameter",
    "enable_slotify": "enableSlotify",
    "enable_shoulders": "enableShoulders",
    "pcb_thickness": "pcbThickness",
    "shoulder_length": "shoulderLength",
    "shoulder_width": "shoulderWidth",
    "shoulder_clearance": "shoulderClearance",
}


def build_params_dict(params_snake: dict) -> dict:
    """camelCase params (matching StencilOptions) + schema version.

    Native value types (float/bool) are preserved. Unknown keys are dropped.
    """
    out: dict = {"v": SCHEMA_VERSION}
    for snake, camel in _KEY_MAP.items():
        if snake in params_snake:
            out[camel] = params_snake[snake]
    return out


def params_json_bytes(params_snake: dict) -> bytes:
    return (json.dumps(build_params_dict(params_snake), indent=2) + "\n").encode("utf-8")


def inject_params_into_zip(zip_path: str, params_snake: dict) -> None:
    """Append stenchill-params.json to an existing ZIP, in place."""
    with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(PARAMS_FILENAME, params_json_bytes(params_snake))


def write_params_json(dir_path: str, params_snake: dict) -> str:
    """Write stenchill-params.json into dir_path; return the file path."""
    dest = os.path.join(dir_path, PARAMS_FILENAME)
    with open(dest, "wb") as f:
        f.write(params_json_bytes(params_snake))
    return dest
