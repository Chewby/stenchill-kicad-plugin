"""
Stenchill Action Plugin for KiCad 8+.
Author: Thomas COTTARD - https://www.stenchill.com

Exports paste layers and edge cuts from the current PCB,
sends them to the Stenchill API, and saves the generated STL stencil.
"""

import os
import pcbnew


class StenchillPlugin(pcbnew.ActionPlugin):
    """KiCad Action Plugin that generates 3D-printable stencils via Stenchill."""

    def defaults(self):
        self.name = "Stenchill"
        self.category = "Fabrication"
        self.description = "Generate a 3D-printable solder paste stencil from this PCB"
        self.show_toolbar_button = True
        icon_path = os.path.join(os.path.dirname(__file__), "icon-96.png")
        if os.path.exists(icon_path):
            self.icon_file_name = icon_path

    def Run(self):
        board = pcbnew.GetBoard()
        if board is None:
            _show_error("No PCB is currently open.")
            return

        board_path = board.GetFileName()
        if not board_path:
            _show_error("Please save your PCB before generating a stencil.")
            return

        from .dialog import StenchillDialog

        # No parent on purpose. KiCad 10 runs as a single process with several
        # top-level frames, and wx.GetTopLevelWindows()[0] is the project
        # manager frame, not the PCB editor. Parenting a modal dialog to the
        # project manager and then dismissing it closes the whole KiCad window.
        # An app-modal dialog with no parent has no frame to cascade onto.
        dlg = StenchillDialog(None, board)
        dlg.ShowModal()
        dlg.Destroy()


def _show_error(message: str):
    """Show a simple error dialog."""
    import wx
    wx.MessageBox(message, "Stenchill", wx.OK | wx.ICON_ERROR)
