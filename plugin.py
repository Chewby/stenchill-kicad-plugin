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
        import wx

        parent = wx.GetTopLevelWindows()[0] if wx.GetTopLevelWindows() else None
        dlg = StenchillDialog(parent, board)
        dlg.ShowModal()
        dlg.Destroy()


def _show_error(message: str):
    """Show a simple error dialog."""
    import wx
    wx.MessageBox(message, "Stenchill", wx.OK | wx.ICON_ERROR)
