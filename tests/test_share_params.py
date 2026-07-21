import importlib.util
import json
import os
import zipfile
from pathlib import Path

# Load the pure module by path; importing `plugin.share_params` would run
# plugin/__init__.py which pulls in pcbnew (unavailable outside KiCad).
_MOD_PATH = Path(__file__).resolve().parents[1] / "share_params.py"
_spec = importlib.util.spec_from_file_location("share_params", _MOD_PATH)
share_params = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(share_params)

_SNAKE = {
    "thickness": 0.4, "shrink": 0.0, "nozzle_diameter": 0.2,
    "enable_slotify": False, "enable_shoulders": True, "pcb_thickness": 1.6,
    "shoulder_length": 15.0, "shoulder_width": 3.0, "shoulder_clearance": 0.2,
}


def test_build_params_dict_maps_camelcase_and_version():
    d = share_params.build_params_dict(_SNAKE)
    assert d["v"] == 1
    assert d["nozzleDiameter"] == 0.2
    assert d["enableSlotify"] is False
    assert d["pcbThickness"] == 1.6
    assert d["thickness"] == 0.4
    assert "nozzle_diameter" not in d  # snake keys dropped


def test_build_params_dict_drops_unknown_keys():
    d = share_params.build_params_dict({**_SNAKE, "bogus": 1})
    assert "bogus" not in d


def test_inject_params_into_zip_adds_entry_preserving_originals(tmp_path):
    zpath = tmp_path / "g.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("board-F_Paste.gbr", "G04 test*")
    share_params.inject_params_into_zip(str(zpath), _SNAKE)
    with zipfile.ZipFile(zpath) as zf:
        names = zf.namelist()
        assert "stenchill-params.json" in names
        assert "board-F_Paste.gbr" in names  # original untouched
        data = json.loads(zf.read("stenchill-params.json"))
    assert data["enableSlotify"] is False
    assert data["v"] == 1


def test_write_params_json_creates_file(tmp_path):
    p = share_params.write_params_json(str(tmp_path), _SNAKE)
    assert os.path.basename(p) == "stenchill-params.json"
    data = json.loads(Path(p).read_text())
    assert data["v"] == 1
    assert data["thickness"] == 0.4
