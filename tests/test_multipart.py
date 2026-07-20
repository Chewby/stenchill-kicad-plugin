import importlib.util
from pathlib import Path

_MOD = Path(__file__).resolve().parents[1] / "api_client.py"
_spec = importlib.util.spec_from_file_location("api_client", _MOD)
api_client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api_client)

# api_client._get_user_agent() does a lazy `from . import VERSION`, which
# requires package context that this by-path import doesn't have (see
# test_share_params.py for the same constraint on share_params). Pre-seed
# the module-level cache so header building doesn't need the relative import.
api_client._user_agent = "StenchillKiCadPlugin/test"


def _write_zip(tmp_path):
    p = tmp_path / "g.zip"
    p.write_bytes(b"PK\x05\x06" + b"\x00" * 18)  # minimal empty-zip-ish bytes
    return str(p)


def test_file_multipart_has_file_part_and_boundary(tmp_path):
    body, headers = api_client._build_file_multipart(_write_zip(tmp_path))
    boundary = headers["Content-Type"].split("boundary=")[1]
    assert isinstance(body, bytes)
    assert boundary.encode() in body
    assert b'name="file"; filename="gerbers.zip"' in body
    assert headers["X-API-Key"]
    assert body.rstrip().endswith(b"--" + boundary.encode() + b"--")


def test_full_multipart_includes_params(tmp_path):
    body, headers = api_client._build_multipart(
        _write_zip(tmp_path), 0.4, 0.0, 1.6, 15.0, 3.0, True, 0.3, 0.2, False
    )
    assert b'name="file"' in body
    assert b'name="thickness"' in body
    assert b'name="enableSlotify"' in body
    assert b"0.4" in body
