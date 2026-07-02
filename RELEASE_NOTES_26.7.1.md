# Stenchill for KiCad — v26.7.1

Big quality-of-life release. The plugin now mirrors more of what the website does,
and several rough edges (especially on macOS and outside the US) are fixed.

## ✨ New
- **Live progress labels** during generation now read in plain English (e.g. "Nozzle
  compensation…", "Writing STL/3MF…") instead of internal codes — and show
  **per-face detail** for two-sided boards (e.g. `Front: ✓ · Back: 3D extrusion…`).
- **"Merge close pads"** toggle — fuse fine-pitch pad rows into a single slot,
  avoiding sub-nozzle walls (on by default).
- **Queue status** — when the server is busy you now see your position in line
  instead of a frozen "Connecting…".
- **"New version available"** notice with a one-click link, so you know when to
  update via KiCad's Plugin Manager.
- **"Reset params"** button to restore every parameter to its defaults (with
  confirmation).
- **"Open folder"** button after a successful generation — jump straight to your
  STL files (macOS / Windows / Linux).
- **CREDITS.txt** is now saved next to the STL files.
- **Ko-fi** support link added next to PayPal.

## 🔧 Improved
- Tighter, more realistic parameter limits in the dialog (thickness, nozzle,
  shoulders…) to steer toward printable values. (Server stays compatible with
  older plugin versions.)
- Stenchill-branded confirmation dialog.

## 🐞 Fixed
- **Quit no longer closes the whole KiCad window** on macOS (the dialog was
  attached to the wrong window).
- **Decimal-separator bug**: on systems using a comma decimal separator (FR, DE,
  …), parameter fields could land on absurd values (e.g. a 4 mm nozzle). Values are
  now read locale-safely.
- **Cancel** during a generation no longer leaves a folder of STL files behind.
- Correct version shown in the title / update check (was "unknown" in PCM installs).
- Compatibility with the Python bundled in KiCad (3.9).

---
*Requires an internet connection. Files are processed on stenchill.com and not
stored on the server.*
