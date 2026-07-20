import importlib.util
from pathlib import Path

import pytest

_MOD = Path(__file__).resolve().parents[1] / "api_client.py"
_spec = importlib.util.spec_from_file_location("api_client", _MOD)
api_client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api_client)


# ── is_newer ──

@pytest.mark.parametrize("latest,current,expected", [
    ("26.7.2", "26.7.1", True),
    ("26.8", "26.7.1", True),
    ("27.0.0", "26.7.1", True),
    ("26.7.1", "26.7.1", False),
    ("26.7.0", "26.7.1", False),
    # short vs long: padding with zeros, not lexicographic tuple compare
    ("26.7", "26.7.0", False),
    ("26.7.1", "26.7", True),
])
def test_is_newer(latest, current, expected):
    assert api_client.is_newer(latest, current) is expected


@pytest.mark.parametrize("latest,current", [
    ("garbage", "26.7.1"),
    ("26.7.1", "garbage"),
    (None, "26.7.1"),
    ("26.7.1", None),
    ("", ""),
    ("26.7.x", "26.7.1"),
])
def test_is_newer_never_nags_on_malformed_versions(latest, current):
    assert api_client.is_newer(latest, current) is False


# ── compose_progress_label ──

def _face(name, done=False, label_text="Extruding"):
    return {"face": name, "label": "extrude", "labelText": label_text, "done": done}


def test_compose_label_no_faces_uses_macro_text():
    assert api_client.compose_progress_label("Packaging...", []) == "Packaging..."
    assert api_client.compose_progress_label("Packaging...", None) == "Packaging..."


def test_compose_label_single_face_uses_macro_text():
    assert api_client.compose_progress_label("Extruding...", [_face("front")]) == "Extruding..."


def test_compose_label_all_faces_done_uses_macro_text():
    faces = [_face("front", done=True), _face("back", done=True)]
    assert api_client.compose_progress_label("Packaging...", faces) == "Packaging..."


def test_compose_label_multi_face_composes_per_face():
    faces = [_face("front", done=True), _face("back", label_text="Compensating")]
    assert api_client.compose_progress_label("...", faces) == "Front: ✓ · Back: Compensating"


def test_compose_label_falls_back_to_label_when_no_label_text():
    faces = [
        {"face": "front", "label": "extrude", "labelText": "", "done": False},
        _face("back"),
    ]
    assert api_client.compose_progress_label("...", faces) == "Front: extrude · Back: Extruding"


# ── _as_int ──

@pytest.mark.parametrize("value,default,expected", [
    (3, 0, 3),
    ("4", 0, 4),
    (2.9, 0, 2),
    (None, 5, 5),
    ("garbage", 5, 5),
    (True, 5, 5),  # bool is not an int for the SSE contract
    ([], 5, 5),
])
def test_as_int(value, default, expected):
    assert api_client._as_int(value, default) == expected


# ── _dispatch_sse_event ──

def _dispatch(event_type, data_str, on_progress=None, on_queued=None):
    return api_client._dispatch_sse_event(event_type, data_str, on_progress, on_queued)


def test_dispatch_progress_calls_callback_with_coerced_fields():
    calls = []
    _dispatch(
        "progress",
        '{"step": "3", "total": null, "label": "extrude", "labelText": "Extruding",'
        ' "faceProgress": "not-a-list"}',
        on_progress=lambda *a: calls.append(a),
    )
    assert calls == [(3, 5, "extrude", "Extruding", [])]


def test_dispatch_queued_calls_callback():
    calls = []
    _dispatch("queued", '{"position": 2, "queueDepth": 4, "etaSeconds": 30}',
              on_queued=lambda *a: calls.append(a))
    assert calls == [(2, 4, 30)]


def test_dispatch_complete_returns_stl_path():
    assert _dispatch("complete", '{"stlPath": "abc.zip"}') == "abc.zip"


def test_dispatch_error_raises_api_error():
    with pytest.raises(api_client.ApiError, match="boom"):
        _dispatch("error", '{"error": "boom"}')


@pytest.mark.parametrize("payload", ["not json", "[1, 2]", '"just a string"', ""])
def test_dispatch_survives_malformed_payloads(payload):
    assert _dispatch("progress", payload, on_progress=lambda *a: pytest.fail()) is None


def test_dispatch_none_event_type_defaults_to_message():
    # SSE spec: no `event:` field means type "message" — must not be treated
    # as any known event.
    assert _dispatch(None, '{"stlPath": "abc.zip"}') is None
