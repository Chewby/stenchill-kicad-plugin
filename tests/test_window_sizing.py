"""Tests for the pure window-sizing arithmetic.

The dialog's DPI-driven growth is wxWidgets/OS behavior and is validated
visually inside KiCad. What IS unit-testable is the clamp that keeps the
fitted window from opening larger than the usable screen -- extracted into
``window_sizing`` precisely so it can be exercised without wx or pcbnew.
"""

import importlib.util
from pathlib import Path

# Load the pure module by path; importing `plugin.window_sizing` would run
# plugin/__init__.py which pulls in pcbnew (unavailable outside KiCad).
_MOD_PATH = Path(__file__).resolve().parents[1] / "window_sizing.py"
_spec = importlib.util.spec_from_file_location("window_sizing", _MOD_PATH)
window_sizing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(window_sizing)

clamp_window_size = window_sizing.clamp_window_size


def test_content_smaller_than_screen_is_unchanged():
    # Fits comfortably: only shrinks, never grows -> returned as-is.
    assert clamp_window_size(560, 680, 1920, 1080) == (560, 680)


def test_taller_than_screen_clamps_height_only():
    # 150% scaling on a 1080p screen: content overflows vertically.
    assert clamp_window_size(560, 1400, 1920, 1080) == (560, 1080 - 40)


def test_larger_on_both_axes_clamps_both():
    assert clamp_window_size(2200, 1400, 1920, 1080) == (1920 - 40, 1080 - 40)


def test_custom_margin_is_respected():
    assert clamp_window_size(560, 1400, 1920, 1080, margin=60) == (560, 1080 - 60)


def test_content_exactly_screen_size_clamps_down_by_margin():
    # Equal to the work area still leaves room for the margin.
    assert clamp_window_size(1920, 1080, 1920, 1080) == (1920 - 40, 1080 - 40)


def test_never_returns_negative_on_tiny_work_area():
    # Degenerate screen smaller than the margin: floor at 0, never negative.
    assert clamp_window_size(560, 680, 20, 20) == (0, 0)


# ── wheel_scroll_lines (mouse-wheel → ScrollLines amount) ──

def test_wheel_up_scrolls_up_negative():
    # Positive rotation (wheel away from user) -> scroll up -> negative lines.
    assert window_sizing.wheel_scroll_lines(120, 120, 3) == -3


def test_wheel_down_scrolls_down_positive():
    assert window_sizing.wheel_scroll_lines(-120, 120, 3) == 3


def test_wheel_multiple_notches_scale():
    assert window_sizing.wheel_scroll_lines(240, 120, 3) == -6


def test_wheel_default_lines_per_action_is_three():
    assert window_sizing.wheel_scroll_lines(120, 120) == -3


def test_wheel_zero_delta_does_not_divide_by_zero():
    # Degenerate delta falls back to 120; one notch, default 3 lines.
    assert window_sizing.wheel_scroll_lines(120, 0, 3) == -3


# ── focus_is_within (clicked-field detection through composite controls) ──

class _FakeWin:
    """Minimal stand-in for a wx.Window with a parent chain."""

    def __init__(self, parent=None):
        self.parent = parent


def _get_parent(win):
    return win.parent


def test_focus_directly_on_ctrl_is_within():
    ctrl = _FakeWin()
    assert window_sizing.focus_is_within(ctrl, ctrl, _get_parent) is True


def test_focus_on_internal_child_is_within():
    # SpinCtrlDouble case: focus lands on the inner text child of the ctrl.
    ctrl = _FakeWin()
    inner = _FakeWin(parent=ctrl)
    assert window_sizing.focus_is_within(inner, ctrl, _get_parent) is True


def test_focus_on_deeper_descendant_is_within():
    ctrl = _FakeWin()
    inner = _FakeWin(parent=ctrl)
    deeper = _FakeWin(parent=inner)
    assert window_sizing.focus_is_within(deeper, ctrl, _get_parent) is True


def test_focus_elsewhere_is_not_within():
    ctrl = _FakeWin()
    other = _FakeWin(parent=_FakeWin())
    assert window_sizing.focus_is_within(other, ctrl, _get_parent) is False


def test_no_focus_is_not_within():
    ctrl = _FakeWin()
    assert window_sizing.focus_is_within(None, ctrl, _get_parent) is False
