"""
Stenchill parameter dialog - wxPython UI for configuring stencil generation.
Author: Thomas COTTARD - https://www.stenchill.com
"""

import json
import math
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
import zipfile
from datetime import datetime

import wx
import wx.adv
import pcbnew


def _add_logo(panel, sizer, top_margin: int) -> None:
    """Add the 48x48 Stenchill logo to the sizer, if the icon file exists."""
    logo_path = os.path.join(os.path.dirname(__file__), "icon-96.png")
    if not os.path.exists(logo_path):
        return
    img = wx.Image(logo_path, wx.BITMAP_TYPE_PNG).Scale(48, 48, wx.IMAGE_QUALITY_BICUBIC)
    sizer.Add(wx.StaticBitmap(panel, bitmap=wx.Bitmap(img)), 0, wx.TOP | wx.ALIGN_CENTER, top_margin)


def _open_in_file_manager(path: str) -> None:
    """Open a folder in the OS file manager. Best-effort; never raises."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        elif sys.platform == "win32":
            os.startfile(path)  # noqa: only exists on Windows; reached only here
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass


# Default parameter values matching the Stenchill web UI
_DEFAULTS = {
    "thickness": 0.4,
    "shrink": 0.0,
    "nozzle_diameter": 0.4,
    "enable_slotify": True,
    "enable_shoulders": True,
    "pcb_thickness": 1.6,
    "shoulder_length": 15.0,
    "shoulder_width": 3.0,
    "shoulder_clearance": 0.3,
}


from . import VERSION
_SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".config", "stenchill")
_SETTINGS_FILE = os.path.join(_SETTINGS_DIR, "settings.json")


def _read_raw_settings() -> dict:
    """Best-effort raw read of the settings file; {} on any problem."""
    try:
        with open(_SETTINGS_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_settings() -> dict:
    """Load saved parameters, falling back to defaults. Never raises and never
    returns an ill-typed value: a corrupt or unreadable settings file must not
    prevent the dialog from opening (the values feed SpinCtrlDouble.SetValue)."""
    saved = _read_raw_settings()
    settings = {}
    for key, default in _DEFAULTS.items():
        value = saved.get(key, default)
        if isinstance(default, bool):
            settings[key] = value if isinstance(value, bool) else default
        else:
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = default
            # json.load accepts bare NaN/Infinity tokens; those would reach
            # SpinCtrlDouble.SetValue unclamped and leak "nan" to the API.
            settings[key] = value if math.isfinite(value) else default
    return settings


def _save_settings(params: dict) -> None:
    """Persist parameters for next session. Read-merge-write, so keys other
    than the generation parameters (e.g. a future export path) survive both
    Generate and Reset."""
    try:
        data = _read_raw_settings()
        data.update(params)
        os.makedirs(_SETTINGS_DIR, exist_ok=True)
        with open(_SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


class _ConfirmDialog(wx.Dialog):
    """Small Stenchill-branded Yes/No confirmation (the native wx.MessageBox
    shows the host app icon — KiCad — on macOS, which we can't replace)."""

    def __init__(self, parent, title, message):
        super().__init__(parent, title=title)
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        _add_logo(panel, sizer, 16)

        heading = wx.StaticText(panel, label=title)
        heading_font = heading.GetFont()
        heading_font.SetWeight(wx.FONTWEIGHT_BOLD)
        heading.SetFont(heading_font)
        sizer.Add(heading, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.ALIGN_CENTER, 16)

        text = wx.StaticText(panel, label=message, style=wx.ALIGN_CENTER)
        sizer.Add(text, 0, wx.ALL | wx.ALIGN_CENTER, 16)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        no_btn = wx.Button(panel, wx.ID_NO, "No")
        no_btn.SetDefault()  # safe default: Enter does not confirm a destructive action
        no_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_NO))
        btns.Add(no_btn, 0, wx.RIGHT, 8)
        yes_btn = wx.Button(panel, wx.ID_YES, "Yes")
        yes_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_YES))
        btns.Add(yes_btn, 0)
        sizer.Add(btns, 0, wx.ALL | wx.ALIGN_CENTER, 12)

        panel.SetSizerAndFit(sizer)
        self.Fit()
        self.CenterOnParent()


def _confirm(parent, title, message) -> bool:
    """Show the Stenchill confirmation dialog; return True if the user chose Yes."""
    dlg = _ConfirmDialog(parent, title, message)
    result = dlg.ShowModal()
    dlg.Destroy()
    return result == wx.ID_YES


class StenchillDialog(wx.Dialog):
    """Main dialog for Stenchill stencil generation."""

    def __init__(self, parent, board):
        super().__init__(parent, title=f"Stenchill - Stencil Generator v{VERSION}", size=(560, 680))
        self.board = board
        self.result_path = None
        # Generation state: _generating drives the dismiss button label
        # (Quit/Cancel); _gen_token invalidates a cancelled worker's late
        # wx.CallAfter callbacks so they don't rewrite the UI.
        self._generating = False
        self._gen_token = 0
        self._cancel_event = None
        self._last_gen_dir = None
        self._settings = _load_settings()
        self._build_ui()
        self.CenterOnParent()
        # Route the window [X] / Escape through our own handler so it only
        # closes this dialog, never the parent PCB view.
        self.Bind(wx.EVT_CLOSE, self._on_close)
        threading.Thread(target=self._check_for_update, daemon=True).start()

    def _build_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # ── Logo ──
        _add_logo(panel, main_sizer, 10)

        # ── Header ──
        header = wx.StaticText(panel, label="Generate 3D-Printable Stencil")
        header_font = header.GetFont()
        header_font.SetPointSize(14)
        header_font.SetWeight(wx.FONTWEIGHT_BOLD)
        header.SetFont(header_font)
        main_sizer.Add(header, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER, 10)

        subtitle = wx.StaticText(
            panel,
            label="Export paste layers from your PCB and generate STL files",
            style=wx.ALIGN_CENTER
        )
        subtitle.SetForegroundColour(wx.Colour(100, 100, 100))
        main_sizer.Add(subtitle, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)

        link = wx.adv.HyperlinkCtrl(panel, label="stenchill.com", url="https://www.stenchill.com")
        link.SetVisitedColour(link.GetNormalColour())
        main_sizer.Add(link, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        self.update_text = wx.StaticText(panel, label="")
        self.update_text.SetForegroundColour(wx.Colour(180, 95, 0))
        main_sizer.Add(self.update_text, 0, wx.ALIGN_CENTER | wx.BOTTOM, 4)
        self.update_link = wx.adv.HyperlinkCtrl(
            panel, label="Update via KiCad's Plugin Manager",
            url="https://www.stenchill.com/en/kicad-plugin",
        )
        self.update_link.SetVisitedColour(self.update_link.GetNormalColour())
        main_sizer.Add(self.update_link, 0, wx.ALIGN_CENTER | wx.BOTTOM, 6)
        main_sizer.Show(self.update_text, False)
        main_sizer.Show(self.update_link, False)

        main_sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 5)

        # Stencil parameters — bounds aligned with the web frontend and server.
        stencil_box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Stencil Parameters")
        grid = wx.FlexGridSizer(3, 2, 8, 16)
        grid.AddGrowableCol(1, 1)

        self.thickness_ctrl = self._add_param(
            panel, grid, "Thickness (mm):", self._settings["thickness"], 0.05, 1.0,
            "Stencil plate thickness - typical: 0.3-0.4 mm"
        )
        self.shrink_ctrl = self._add_param(
            panel, grid, "Shrink (mm):", self._settings["shrink"], -1.0, 5.0,
            "Pad reduction - negative values enlarge pads"
        )
        self.nozzle_ctrl = self._add_param(
            panel, grid, "Nozzle (mm), 0.2 rec.:", self._settings["nozzle_diameter"], 0.1, 1.5,
            "Your 3D printer nozzle size - 0.2 mm recommended for best results"
        )

        stencil_box.Add(grid, 0, wx.EXPAND | wx.ALL, 8)

        self.slotify_cb = wx.CheckBox(panel, label="Merge close pads")
        self.slotify_cb.SetValue(self._settings["enable_slotify"])
        self.slotify_cb.SetToolTip(
            "Fuse fine-pitch pad rows into a single slot when the gap between "
            "pads is narrower than the nozzle, avoiding sub-nozzle walls."
        )
        stencil_box.Add(self.slotify_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        main_sizer.Add(stencil_box, 0, wx.EXPAND | wx.ALL, 10)

        # ── Shoulder Parameters ──
        shoulder_box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Registration Shoulders")

        self.shoulders_cb = wx.CheckBox(panel, label="Enable shoulders (alignment supports)")
        self.shoulders_cb.SetValue(self._settings["enable_shoulders"])
        self.shoulders_cb.Bind(wx.EVT_CHECKBOX, self._on_shoulder_toggle)
        shoulder_box.Add(self.shoulders_cb, 0, wx.ALL, 8)

        self.shoulder_grid = wx.FlexGridSizer(4, 2, 8, 16)
        self.shoulder_grid.AddGrowableCol(1, 1)

        self.pcb_thickness_ctrl = self._add_param(
            panel, self.shoulder_grid, "PCB thickness (mm):", self._settings["pcb_thickness"], 0.1, 5.0,
            "Your PCB board thickness"
        )
        self.shoulder_length_ctrl = self._add_param(
            panel, self.shoulder_grid, "Shoulder length (mm):", self._settings["shoulder_length"], 1.0, 200.0,
            "L-bracket length along PCB edge"
        )
        self.shoulder_width_ctrl = self._add_param(
            panel, self.shoulder_grid, "Shoulder width (mm):", self._settings["shoulder_width"], 0.5, 15.0,
            "L-bracket wall thickness"
        )
        self.shoulder_clearance_ctrl = self._add_param(
            panel, self.shoulder_grid, "Clearance (mm):", self._settings["shoulder_clearance"], 0.0, 2.0,
            "Gap between PCB edge and shoulder walls"
        )

        shoulder_box.Add(self.shoulder_grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        main_sizer.Add(shoulder_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Single key -> control registry. _on_generate (collect) and _on_reset
        # (restore defaults) iterate this instead of maintaining parallel
        # hand-written lists that silently drift when a parameter is added.
        self._param_ctrls = {
            "thickness": self.thickness_ctrl,
            "shrink": self.shrink_ctrl,
            "nozzle_diameter": self.nozzle_ctrl,
            "enable_slotify": self.slotify_cb,
            "enable_shoulders": self.shoulders_cb,
            "pcb_thickness": self.pcb_thickness_ctrl,
            "shoulder_length": self.shoulder_length_ctrl,
            "shoulder_width": self.shoulder_width_ctrl,
            "shoulder_clearance": self.shoulder_clearance_ctrl,
        }

        # ── Output directory ──
        dir_sizer = wx.BoxSizer(wx.HORIZONTAL)
        dir_sizer.Add(wx.StaticText(panel, label="Output folder:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        board_dir = os.path.dirname(self.board.GetFileName())
        self.output_dir = wx.DirPickerCtrl(panel, path=board_dir, message="Choose output folder")
        self.output_dir.SetTextCtrlGrowable(True)
        # Override the localized button label
        picker_btn = self.output_dir.GetPickerCtrl()
        if picker_btn:
            picker_btn.SetLabel("Browse...")
        dir_sizer.Add(self.output_dir, 1, wx.EXPAND)

        main_sizer.Add(dir_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # ── Status / Result (share the same space below output folder) ──
        self.progress = wx.Gauge(panel, range=100, size=(-1, 8))
        main_sizer.Add(self.progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.status_text = wx.StaticText(panel, label="")
        self.status_text.SetForegroundColour(wx.Colour(100, 100, 100))
        main_sizer.Add(self.status_text, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)

        self.result_text = wx.StaticText(panel, label="")
        main_sizer.Add(self.result_text, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        self.open_folder_btn = wx.Button(panel, wx.ID_ANY, "\U0001F4C1  Open folder")
        self.open_folder_btn.SetToolTip("Open the output folder in your file manager")
        self.open_folder_btn.Bind(wx.EVT_BUTTON, self._on_open_folder)

        self.view_3d_btn = wx.Button(panel, wx.ID_ANY, "\U0001F310  View in 3D")
        self.view_3d_btn.SetToolTip("Upload the gerbers and open an interactive 3D preview on stenchill.com")
        self.view_3d_btn.Bind(wx.EVT_BUTTON, self._on_view_3d)

        # Post-generation actions on one row: review first (View in 3D), then
        # grab the files (Open folder). Shown/hidden together via this sizer.
        self.result_btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.result_btn_sizer.Add(self.view_3d_btn, 0, wx.RIGHT, 8)
        self.result_btn_sizer.Add(self.open_folder_btn, 0)
        main_sizer.Add(self.result_btn_sizer, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # Initially hide all status widgets
        main_sizer.Show(self.progress, False)
        main_sizer.Show(self.status_text, False)
        main_sizer.Show(self.result_text, False)
        main_sizer.Show(self.result_btn_sizer, False)

        # ── Spacer to push buttons to bottom ──
        main_sizer.AddStretchSpacer()

        # ── Bottom bar: support link + buttons ──
        bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # \u2500\u2500 Support links (Ko-fi + PayPal) \u2500\u2500
        def _small_font(ctrl):
            f = ctrl.GetFont()
            f.SetPointSize(f.GetPointSize() - 1)
            ctrl.SetFont(f)

        support_label = wx.StaticText(panel, label="Like it?  ")
        support_label.SetForegroundColour(wx.Colour(120, 120, 120))
        _small_font(support_label)
        bottom_sizer.Add(support_label, 0, wx.ALIGN_CENTER_VERTICAL)

        kofi_link = wx.adv.HyperlinkCtrl(
            panel, label="\u2615  Ko-fi", url="https://ko-fi.com/thomascottard"
        )
        kofi_link.SetVisitedColour(kofi_link.GetNormalColour())
        _small_font(kofi_link)
        bottom_sizer.Add(kofi_link, 0, wx.ALIGN_CENTER_VERTICAL)

        sep = wx.StaticText(panel, label="  \u00b7  ")
        sep.SetForegroundColour(wx.Colour(120, 120, 120))
        _small_font(sep)
        bottom_sizer.Add(sep, 0, wx.ALIGN_CENTER_VERTICAL)

        paypal_link = wx.adv.HyperlinkCtrl(
            panel, label="PayPal", url="https://paypal.me/thomascottard"
        )
        paypal_link.SetVisitedColour(paypal_link.GetNormalColour())
        _small_font(paypal_link)
        bottom_sizer.Add(paypal_link, 0, wx.ALIGN_CENTER_VERTICAL)

        bottom_sizer.AddStretchSpacer()

        # Dynamic dismiss button: "Quit" when idle (closes only this dialog),
        # "Cancel" during a generation (returns to the form). Custom ID + explicit
        # handler avoid the standard wx.ID_CANCEL default dismissal, which on
        # macOS/KiCad could propagate and close the parent PCB view.
        self.reset_btn = wx.Button(panel, wx.ID_ANY, "Reset params")
        self.reset_btn.SetToolTip("Reset all parameters to their default values")
        self.reset_btn.Bind(wx.EVT_BUTTON, self._on_reset)
        bottom_sizer.Add(self.reset_btn, 0, wx.RIGHT, 8)

        self.dismiss_btn = wx.Button(panel, wx.ID_ANY, "Quit")
        self.dismiss_btn.Bind(wx.EVT_BUTTON, self._on_dismiss)
        bottom_sizer.Add(self.dismiss_btn, 0, wx.RIGHT, 8)

        self.generate_btn = wx.Button(panel, wx.ID_OK, "Generate Stencil")
        self.generate_btn.SetDefault()
        self.generate_btn.Bind(wx.EVT_BUTTON, self._on_generate)
        bottom_sizer.Add(self.generate_btn, 0)

        main_sizer.Add(bottom_sizer, 0, wx.EXPAND | wx.ALL, 10)

        self.main_sizer = main_sizer
        self.panel = panel
        panel.SetSizer(main_sizer)

        # Sync shoulder controls with saved setting
        self._on_shoulder_toggle(None)

    def _add_param(self, panel, grid, label, default, min_val, max_val, tooltip):
        """Add a labeled SpinCtrlDouble to the grid."""
        lbl = wx.StaticText(panel, label=label)
        lbl.SetToolTip(tooltip)
        grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)

        # Set the value as a float via SetValue, NOT via the constructor's string
        # `value`. str(default) is always "."-formatted ("0.4"), which a
        # SpinCtrlDouble on a comma-decimal locale (FR, DE, ...) misparses (e.g.
        # 0.4 -> 4). SetValue(float) formats per the system locale; GetValue()
        # returns a locale-independent float.
        ctrl = wx.SpinCtrlDouble(panel, min=min_val, max=max_val, inc=0.05)
        ctrl.SetDigits(2)
        ctrl.SetValue(float(default))
        ctrl.SetToolTip(tooltip)
        grid.Add(ctrl, 1, wx.EXPAND)

        return ctrl

    def _on_shoulder_toggle(self, event):
        """Enable/disable shoulder parameters based on checkbox."""
        enabled = self.shoulders_cb.GetValue()
        for child in self.shoulder_grid.GetChildren():
            window = child.GetWindow()
            if window:
                window.Enable(enabled)

    def _on_generate(self, event):
        """Start the generation process in a background thread."""
        self.generate_btn.Disable()
        self.reset_btn.Disable()
        self._generating = True
        self._gen_token += 1
        self.dismiss_btn.SetLabel("Cancel")
        self.main_sizer.Show(self.progress, True)
        self.main_sizer.Show(self.status_text, True)
        self.main_sizer.Show(self.result_text, False)
        self.main_sizer.Show(self.result_btn_sizer, False)
        self.status_text.SetForegroundColour(wx.Colour(100, 100, 100))
        self.status_text.SetLabel("Exporting Gerber layers...")
        self.progress.SetRange(100)
        self.progress.SetValue(0)
        self.panel.Layout()
        # Flush the repaint now: the Gerber export below blocks the UI thread
        # (pcbnew.BOARD is main-thread-only), so without this the busy state
        # would never be painted and KiCad would look hung.
        self.panel.Refresh()
        self.panel.Update()

        params = {key: ctrl.GetValue() for key, ctrl in self._param_ctrls.items()}
        output_dir = self.output_dir.GetPath()
        board_name = os.path.splitext(os.path.basename(self.board.GetFileName()))[0]

        # Save params for next session
        _save_settings(params)

        # Lets the worker abort the SSE stream promptly instead of consuming
        # the connection to completion after a cancel.
        self._cancel_event = threading.Event()

        # Defer the blocking export one event-loop iteration so any pending
        # paint events run first.
        wx.CallAfter(self._start_generation, params, output_dir, board_name, self._gen_token)

    def _start_generation(self, params, output_dir, board_name, token):
        if token != self._gen_token:
            return  # cancelled before the export even started

        # Export Gerbers on main thread (pcbnew.BOARD is not thread-safe)
        try:
            from .exporter import export_gerber_zip
            zip_path = export_gerber_zip(self.board)
        except Exception as e:
            self._on_error(str(e))
            return

        thread = threading.Thread(
            target=self._generate_worker,
            args=(zip_path, params, output_dir, board_name, token, self._cancel_event),
            daemon=True,
        )
        thread.start()

    def _generate_worker(self, zip_path, params, output_dir, board_name, token, cancel_event):
        """Background worker: call API with SSE streaming, save results.

        ``token`` is the generation id captured at launch. Every UI update goes
        through ``ui()``, which drops the update if the user has cancelled or
        started another generation (token no longer current) — so a cancelled
        run can never rewrite the form or a freshly destroyed dialog.
        ``cancel_event`` is set on cancel so the SSE stream aborts promptly
        instead of running to completion just to be discarded.
        """
        def ui(fn, *fargs):
            def _apply():
                if token == self._gen_token:
                    fn(*fargs)
            wx.CallAfter(_apply)

        result_zip = None
        from .api_client import (
            generate_stencil_stream, compose_progress_label, GenerationCancelled,
        )
        try:
            ui(self._set_status, "Connecting to Stenchill...")

            def on_progress(step, total, label, label_text, face_progress):
                percent = int((step / total) * 100) if total > 0 else 0
                percent = max(0, min(100, percent))  # gauge range is fixed at 100
                text = compose_progress_label(label, label_text, face_progress)
                ui(self._set_progress, percent, text)

            def on_queued(position, queue_depth, eta_seconds):
                eta_str = f" · ETA ~{eta_seconds}s" if eta_seconds > 0 else ""
                ui(self._set_status, f"Position {position} of {queue_depth}{eta_str}")

            # Step 1: Call streaming API
            try:
                result_zip = generate_stencil_stream(
                    zip_path=zip_path,
                    on_progress=on_progress,
                    on_queued=on_queued,
                    cancel_event=cancel_event,
                    thickness=params["thickness"],
                    shrink=params["shrink"],
                    pcb_thickness=params["pcb_thickness"],
                    shoulder_length=params["shoulder_length"],
                    shoulder_width=params["shoulder_width"],
                    enable_shoulders=params["enable_shoulders"],
                    shoulder_clearance=params["shoulder_clearance"],
                    nozzle_diameter=params["nozzle_diameter"],
                    enable_slotify=params["enable_slotify"],
                )
            finally:
                # Clean up temp Gerber ZIP
                if os.path.exists(zip_path):
                    os.unlink(zip_path)

            # Cancelled (or the dialog was closed) while generating: drop the
            # result instead of writing STL files to the output folder. The
            # outer finally still cleans up the downloaded result_zip.
            if token != self._gen_token:
                return

            ui(self._set_status, "Saving STL files...")

            # Step 2: Create subfolder and extract STL files
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            gen_dir = os.path.join(output_dir, f"{board_name}_{timestamp}")
            os.makedirs(gen_dir, exist_ok=True)

            saved_files = []
            with zipfile.ZipFile(result_zip, "r") as zf:
                for name in zf.namelist():
                    safe_name = os.path.basename(name)
                    if not safe_name or safe_name.startswith('.'):
                        continue
                    is_mesh = safe_name.lower().endswith((".stl", ".3mf"))
                    is_credits = safe_name == "CREDITS.txt"
                    if not (is_mesh or is_credits):
                        continue
                    dest = os.path.join(gen_dir, safe_name)
                    with zf.open(name) as src, open(dest, "wb") as dst:
                        dst.write(src.read())
                    if is_mesh:
                        saved_files.append(safe_name)

            # Cancelled while the files were being written: remove the partial
            # output so no orphan folder silently appears in the project dir.
            if token != self._gen_token:
                shutil.rmtree(gen_dir, ignore_errors=True)
                return

            if saved_files:
                files_str = ", ".join(saved_files)
                folder_name = os.path.basename(gen_dir)
                ui(self._on_success, f"Saved: {files_str}\nFolder: {folder_name}", gen_dir)
            else:
                ui(self._on_error, "No STL files found in the API response.")

        except GenerationCancelled:
            pass  # user cancelled; the finally below cleans up the temp ZIP
        except Exception as e:
            ui(self._on_error, str(e))
        finally:
            if result_zip and os.path.exists(result_zip):
                os.unlink(result_zip)

    def _set_status(self, text):
        self.status_text.SetLabel(text)
        self.progress.Pulse()

    def _set_progress(self, percent, label):
        self.progress.SetValue(percent)
        if label:
            self.status_text.SetLabel(label)

    def _set_idle(self, show_result=False, show_open_folder=False):
        """Return the dialog to its idle state. Single owner of the busy/idle
        widget toggles: success, error and cancel all funnel through here, so
        a new widget in the status area only needs wiring in one place."""
        self._generating = False
        self.dismiss_btn.SetLabel("Quit")
        self.main_sizer.Show(self.progress, False)
        self.main_sizer.Show(self.status_text, False)
        self.main_sizer.Show(self.result_text, show_result)
        self.main_sizer.Show(self.result_btn_sizer, show_open_folder)
        self.generate_btn.Enable()
        self.reset_btn.Enable()
        self.panel.Layout()

    def _on_success(self, message, gen_dir):
        self._last_gen_dir = gen_dir
        self.result_text.SetForegroundColour(wx.Colour(0, 128, 0))
        self.result_text.SetLabel(f"\u2705  {message}")
        self._set_idle(show_result=True, show_open_folder=True)

    def _on_error(self, message):
        self.result_text.SetForegroundColour(wx.Colour(200, 0, 0))
        self.result_text.SetLabel(f"\u274c  Error: {message}")
        self._set_idle(show_result=True)

    def _on_dismiss(self, event):
        """Bottom button: cancel the running generation, or close the dialog."""
        if self._generating:
            self._cancel_generation()
        else:
            self._close_dialog()

    def _cancel_generation(self):
        """Abandon the UI wait and return to the idle form. Invalidates the
        running worker's callbacks (via _gen_token) and signals the worker to
        abort the SSE stream (via the cancel event) instead of consuming the
        connection to completion."""
        self._gen_token += 1
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._set_idle()

    def _on_view_3d(self, event):
        """Re-export the gerbers, upload them to the share endpoint, and open the
        result on the website. The gerber ZIP is re-exported fresh because the
        generation ZIP was already cleaned up. The current form params are
        embedded (stenchill-params.json) so /view reproduces this exact stencil.

        Feedback goes through ``result_text`` because ``status_text`` is hidden in
        the post-success state (the result widget is the visible one)."""
        self.view_3d_btn.Enable(False)
        self.result_text.SetForegroundColour(wx.Colour(100, 100, 100))
        self.result_text.SetLabel("Opening 3D view on stenchill.com...")
        self.panel.Layout()

        params = {key: ctrl.GetValue() for key, ctrl in self._param_ctrls.items()}

        # Export Gerbers on the main thread (pcbnew.BOARD is not thread-safe).
        try:
            from .exporter import export_gerber_zip
            zip_path = export_gerber_zip(self.board)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            self._on_view_3d_done(None, str(exc))
            return

        def worker():
            try:
                from .api_client import share_stencil
                url = share_stencil(zip_path, params)
                wx.CallAfter(self._on_view_3d_done, url, None)
            except Exception as exc:  # noqa: BLE001 - surface any failure to the user
                wx.CallAfter(self._on_view_3d_done, None, str(exc))
            finally:
                if zip_path and os.path.exists(zip_path):
                    try:
                        os.remove(zip_path)
                    except OSError:
                        pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_view_3d_done(self, url, error):
        """Back on the UI thread: open the browser or show the error."""
        self.view_3d_btn.Enable(True)
        if error:
            self.result_text.SetForegroundColour(wx.Colour(200, 0, 0))
            self.result_text.SetLabel(f"❌  Could not open 3D view: {error}")
            self.panel.Layout()
            return
        try:
            opened = webbrowser.open(url)
        except Exception:  # noqa: BLE001
            opened = False
        if opened:
            self.result_text.SetForegroundColour(wx.Colour(0, 128, 0))
            self.result_text.SetLabel("✅  Opened 3D view in your browser.")
        else:
            self.result_text.SetForegroundColour(wx.Colour(100, 100, 100))
            self.result_text.SetLabel(f"\U0001F517  Open this link in your browser:\n{url}")
        self.panel.Layout()

    def _on_open_folder(self, event):
        """Open the last generation's output folder in the OS file manager."""
        if self._last_gen_dir and os.path.isdir(self._last_gen_dir):
            _open_in_file_manager(self._last_gen_dir)

    def _on_reset(self, event):
        """Reset all generation parameters to their defaults, after confirmation.
        Leaves the output folder untouched."""
        if not _confirm(self, "Reset params",
                        "Reset all parameters to their default values?"):
            return
        for key, ctrl in self._param_ctrls.items():
            ctrl.SetValue(_DEFAULTS[key])
        self._on_shoulder_toggle(None)
        self._settings = dict(_DEFAULTS)
        _save_settings(dict(_DEFAULTS))

    def _on_close(self, event):
        """Window [X] / Escape: invalidate any in-flight worker callbacks, then
        close ONLY this dialog (never the parent PCB view)."""
        self._gen_token += 1
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._generating = False
        self._close_dialog()

    def _close_dialog(self):
        """Dismiss this dialog alone: EndModal when shown via ShowModal,
        otherwise Destroy. Never touches the parent frame."""
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()

    def _check_for_update(self):
        """Background: poll the API for the latest plugin version; reveal the
        update notice if newer. Silent on any failure."""
        from .api_client import fetch_latest_version, is_newer
        latest = fetch_latest_version()
        if latest and is_newer(latest, VERSION):
            wx.CallAfter(self._show_update_notice, latest)

    def _show_update_notice(self, latest):
        try:
            self.update_text.SetLabel(f"New version v{latest} available")
            self.main_sizer.Show(self.update_text, True)
            self.main_sizer.Show(self.update_link, True)
            self.panel.Layout()
        except RuntimeError:
            pass  # dialog was closed before the version check returned
