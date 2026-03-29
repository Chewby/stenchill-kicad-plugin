"""
Stenchill parameter dialog - wxPython UI for configuring stencil generation.
Author: Thomas COTTARD - https://www.stenchill.com
"""

import json
import os
import threading
import zipfile
from datetime import datetime

import wx
import wx.adv
import pcbnew


# Default parameter values matching the Stenchill web UI
_DEFAULTS = {
    "thickness": 0.4,
    "shrink": 0.0,
    "nozzle_diameter": 0.4,
    "enable_shoulders": True,
    "pcb_thickness": 1.6,
    "shoulder_length": 15.0,
    "shoulder_width": 3.0,
    "shoulder_clearance": 0.3,
}


from . import VERSION
_SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".config", "stenchill")
_SETTINGS_FILE = os.path.join(_SETTINGS_DIR, "settings.json")


def _load_settings() -> dict:
    """Load saved parameters, falling back to defaults."""
    try:
        with open(_SETTINGS_FILE, "r") as f:
            saved = json.load(f)
            return {k: saved.get(k, v) for k, v in _DEFAULTS.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULTS)


def _save_settings(params: dict) -> None:
    """Persist parameters for next session."""
    try:
        os.makedirs(_SETTINGS_DIR, exist_ok=True)
        with open(_SETTINGS_FILE, "w") as f:
            json.dump(params, f, indent=2)
    except OSError:
        pass


class StenchillDialog(wx.Dialog):
    """Main dialog for Stenchill stencil generation."""

    def __init__(self, parent, board):
        super().__init__(parent, title=f"Stenchill - Stencil Generator v{VERSION}", size=(480, 680))
        self.board = board
        self.result_path = None
        self._settings = _load_settings()
        self._build_ui()
        self.CenterOnParent()

    def _build_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # ── Logo ──
        logo_path = os.path.join(os.path.dirname(__file__), "icon-96.png")
        if os.path.exists(logo_path):
            logo_img = wx.Image(logo_path, wx.BITMAP_TYPE_PNG)
            logo_img = logo_img.Scale(48, 48, wx.IMAGE_QUALITY_BICUBIC)
            logo_bmp = wx.StaticBitmap(panel, bitmap=wx.Bitmap(logo_img))
            main_sizer.Add(logo_bmp, 0, wx.TOP | wx.ALIGN_CENTER, 10)

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

        main_sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 5)

        # ── Stencil Parameters ──
        stencil_box = wx.StaticBoxSizer(wx.VERTICAL, panel, "Stencil Parameters")
        grid = wx.FlexGridSizer(3, 2, 8, 16)
        grid.AddGrowableCol(1, 1)

        self.thickness_ctrl = self._add_param(
            panel, grid, "Thickness (mm):", self._settings["thickness"], 0.05, 10.0,
            "Stencil plate thickness - typical: 0.3-0.4 mm"
        )
        self.shrink_ctrl = self._add_param(
            panel, grid, "Shrink (mm):", self._settings["shrink"], -1.0, 5.0,
            "Pad reduction - negative values enlarge pads"
        )
        self.nozzle_ctrl = self._add_param(
            panel, grid, "Nozzle (mm), 0.2 rec.:", self._settings["nozzle_diameter"], 0.1, 2.0,
            "Your 3D printer nozzle size - 0.2 mm recommended for best results"
        )

        stencil_box.Add(grid, 0, wx.EXPAND | wx.ALL, 8)
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
            panel, self.shoulder_grid, "PCB thickness (mm):", self._settings["pcb_thickness"], 0.1, 10.0,
            "Your PCB board thickness"
        )
        self.shoulder_length_ctrl = self._add_param(
            panel, self.shoulder_grid, "Shoulder length (mm):", self._settings["shoulder_length"], 1.0, 500.0,
            "L-bracket length along PCB edge"
        )
        self.shoulder_width_ctrl = self._add_param(
            panel, self.shoulder_grid, "Shoulder width (mm):", self._settings["shoulder_width"], 0.5, 50.0,
            "L-bracket wall thickness"
        )
        self.shoulder_clearance_ctrl = self._add_param(
            panel, self.shoulder_grid, "Clearance (mm):", self._settings["shoulder_clearance"], 0.0, 5.0,
            "Gap between PCB edge and shoulder walls"
        )

        shoulder_box.Add(self.shoulder_grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        main_sizer.Add(shoulder_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

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

        # Initially hide all status widgets
        main_sizer.Show(self.progress, False)
        main_sizer.Show(self.status_text, False)
        main_sizer.Show(self.result_text, False)

        # ── Spacer to push buttons to bottom ──
        main_sizer.AddStretchSpacer()

        # ── Bottom bar: support link + buttons ──
        bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)

        support_link = wx.adv.HyperlinkCtrl(
            panel, label="\u2615  Support this project",
            url="https://paypal.me/thomascottard"
        )
        support_link.SetVisitedColour(support_link.GetNormalColour())
        support_font = support_link.GetFont()
        support_font.SetPointSize(support_font.GetPointSize() - 1)
        support_link.SetFont(support_font)
        bottom_sizer.Add(support_link, 0, wx.ALIGN_CENTER_VERTICAL)

        bottom_sizer.AddStretchSpacer()

        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "Cancel")
        bottom_sizer.Add(cancel_btn, 0, wx.RIGHT, 8)

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

        ctrl = wx.SpinCtrlDouble(panel, value=str(default), min=min_val, max=max_val, inc=0.05)
        ctrl.SetDigits(2)
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
        self.main_sizer.Show(self.progress, True)
        self.main_sizer.Show(self.status_text, True)
        self.main_sizer.Show(self.result_text, False)
        self.status_text.SetForegroundColour(wx.Colour(100, 100, 100))
        self.status_text.SetLabel("Exporting Gerber layers...")
        self.progress.SetRange(100)
        self.progress.SetValue(0)
        self.panel.Layout()

        # Collect parameters
        params = {
            "thickness": self.thickness_ctrl.GetValue(),
            "shrink": self.shrink_ctrl.GetValue(),
            "nozzle_diameter": self.nozzle_ctrl.GetValue(),
            "enable_shoulders": self.shoulders_cb.GetValue(),
            "pcb_thickness": self.pcb_thickness_ctrl.GetValue(),
            "shoulder_length": self.shoulder_length_ctrl.GetValue(),
            "shoulder_width": self.shoulder_width_ctrl.GetValue(),
            "shoulder_clearance": self.shoulder_clearance_ctrl.GetValue(),
        }
        output_dir = self.output_dir.GetPath()
        board_name = os.path.splitext(os.path.basename(self.board.GetFileName()))[0]

        # Save params for next session
        _save_settings(params)

        # Export Gerbers on main thread (pcbnew.BOARD is not thread-safe)
        try:
            from .exporter import export_gerber_zip
            zip_path = export_gerber_zip(self.board)
        except Exception as e:
            self._on_error(str(e))
            return

        thread = threading.Thread(
            target=self._generate_worker,
            args=(zip_path, params, output_dir, board_name),
            daemon=True,
        )
        thread.start()

    def _generate_worker(self, zip_path, params, output_dir, board_name):
        """Background worker: call API with SSE streaming, save results."""
        result_zip = None
        try:
            wx.CallAfter(self._set_status, "Connecting to Stenchill...")

            progress_labels = {
                "PROGRESS.EXTRACTING_PADS": "Extracting pads...",
                "PROGRESS.MORPHOLOGICAL_CLOSE": "Merging split pads...",
                "PROGRESS.NOZZLE_COMPENSATION": "Nozzle compensation...",
                "PROGRESS.EXTRUSION_3D": "3D extrusion...",
                "PROGRESS.EXPORTING": "Exporting STL/3MF...",
            }

            def on_progress(step, total, label):
                percent = int((step / total) * 100) if total > 0 else 0
                text = progress_labels.get(label, label)
                wx.CallAfter(self._set_progress, percent, text)

            # Step 1: Call streaming API
            from .api_client import generate_stencil_stream, ApiError
            try:
                result_zip = generate_stencil_stream(
                    zip_path=zip_path,
                    on_progress=on_progress,
                    thickness=params["thickness"],
                    shrink=params["shrink"],
                    pcb_thickness=params["pcb_thickness"],
                    shoulder_length=params["shoulder_length"],
                    shoulder_width=params["shoulder_width"],
                    enable_shoulders=params["enable_shoulders"],
                    shoulder_clearance=params["shoulder_clearance"],
                    nozzle_diameter=params["nozzle_diameter"],
                )
            finally:
                # Clean up temp Gerber ZIP
                if os.path.exists(zip_path):
                    os.unlink(zip_path)

            wx.CallAfter(self._set_status, "Saving STL files...")

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
                    if safe_name.lower().endswith((".stl", ".3mf")):
                        dest = os.path.join(gen_dir, safe_name)
                        with zf.open(name) as src, open(dest, "wb") as dst:
                            dst.write(src.read())
                        saved_files.append(safe_name)

            if saved_files:
                files_str = ", ".join(saved_files)
                folder_name = os.path.basename(gen_dir)
                wx.CallAfter(self._on_success, f"Saved: {files_str}\nFolder: {folder_name}")
            else:
                wx.CallAfter(self._on_error, "No STL files found in the API response.")

        except Exception as e:
            wx.CallAfter(self._on_error, str(e))
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

    def _on_success(self, message):
        self.main_sizer.Show(self.progress, False)
        self.main_sizer.Show(self.status_text, False)
        self.main_sizer.Show(self.result_text, True)
        self.generate_btn.Enable()
        self.result_text.SetForegroundColour(wx.Colour(0, 128, 0))
        self.result_text.SetLabel(f"\u2705  {message}")
        self.panel.Layout()

    def _on_error(self, message):
        self.main_sizer.Show(self.progress, False)
        self.main_sizer.Show(self.status_text, False)
        self.main_sizer.Show(self.result_text, True)
        self.generate_btn.Enable()
        self.result_text.SetForegroundColour(wx.Colour(200, 0, 0))
        self.result_text.SetLabel(f"\u274c  Error: {message}")
        self.panel.Layout()
