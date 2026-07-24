"""Pure window-sizing helpers for the Stenchill dialog.

Kept free of wx/pcbnew imports so the arithmetic can be unit-tested outside
KiCad. The dialog measures its content at the current DPI (which is what makes
it grow correctly under Windows display scaling) and then clamps the result to
the usable screen area with :func:`clamp_window_size`.
"""


def clamp_window_size(content_w, content_h, work_w, work_h, margin=40):
    """Clamp a fitted content size to the usable screen area.

    ``content_*`` is the size the dialog wants at the current DPI; ``work_*``
    is the display's work area (screen minus taskbar/dock). The result never
    exceeds the work area minus ``margin`` on each axis, so a window taller
    than the screen scrolls instead of running its buttons off-screen. It also
    never grows the content (only shrinks) and never goes negative.
    """
    width = min(content_w, max(0, work_w - margin))
    height = min(content_h, max(0, work_h - margin))
    return (width, height)


def focus_is_within(focus, ctrl, get_parent):
    """True if ``focus`` is ``ctrl`` or one of its descendants.

    A ``wx.SpinCtrlDouble`` is a composite control: clicking into it focuses an
    internal text child, not the SpinCtrlDouble itself, so ``FindFocus() is
    ctrl`` never matches. This walks the focused window up its parent chain
    (via ``get_parent``, e.g. ``wx.Window.GetParent``) so a clicked field still
    counts as focused. ``focus`` of ``None`` (nothing focused) returns False.
    """
    node = focus
    while node is not None:
        if node is ctrl:
            return True
        node = get_parent(node)
    return False


def wheel_scroll_lines(rotation, delta, lines_per_action=3):
    """Number of scroll lines for a mouse-wheel event, for ScrolledWindow.ScrollLines.

    ``rotation`` and ``delta`` are the wx wheel event values; a positive
    rotation is the wheel turned away from the user (conventionally "scroll
    up"). ScrollLines uses positive = down, so this returns a NEGATIVE value
    for a scroll-up rotation. ``delta`` of 0 is treated as the usual 120 to
    avoid a division by zero. The result is rounded to a whole number of lines.
    """
    step = delta or 120
    notches = rotation / step
    return int(round(-notches * lines_per_action))
