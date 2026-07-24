# Stenchill for KiCad, v26.7.3

A bug-fix release. The headline is a fix for the plugin window getting cut off
on high-scaling Windows displays, plus a round of hardening and internal
cleanup.

## Fixed
- **Window no longer clips its buttons at high display scaling.** On Windows
  with display scaling above 100% (150% is the default on many 4K screens),
  the dialog opened at a fixed height that ignored the scaling, so the
  Generate button and others were pushed off-screen with no way to scroll or
  resize. The window now sizes itself to its content at the current DPI, can be
  resized, and scrolls if it ever exceeds the screen. Thanks to the user who
  reported this with a clear description.
- The progress and result areas that appear during generation now grow the
  window (or scroll) instead of risking the same clipping mid-run.
- On a multi-monitor setup, the window is sized against the screen KiCad is
  actually on, not the primary one.
- When the window does scroll, the mouse wheel now scrolls it even when the
  cursor is over a number field; the wheel only changes a field's value once
  you click into it.

## Hardening
- The "View in 3D" link is only opened in your browser when it is an https
  link on stenchill.com; anything else is shown as text instead of opened.
- The logo and progress bar now scale with the display, matching the rest of
  the UI at 150/200%.

## Under the hood
- Refactored the SSE streaming, gerber export, and generation worker into
  smaller, focused pieces (no behavior change), and added unit tests for the
  stream assembly. 55 pure-stdlib tests now ship with the source.
- The plugin is now covered by static analysis (SonarQube), clean at zero
  issues.

---
Requires an internet connection. Files are processed on stenchill.com and not
stored on the server (shared previews auto-expire after 30 minutes).
