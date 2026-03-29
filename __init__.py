"""
Stenchill KiCad Plugin - Generate 3D-printable solder paste stencils.
Author: Thomas COTTARD - https://www.stenchill.com
"""

import json
import os


def _read_version() -> str:
    try:
        with open(os.path.join(os.path.dirname(__file__), "metadata.json"), "r") as f:
            return json.load(f)["versions"][0]["version"]
    except Exception:
        return "unknown"


VERSION = _read_version()

from .plugin import StenchillPlugin  # noqa: F401, E402

# Register the plugin with KiCad
StenchillPlugin().register()
