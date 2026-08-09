"""
Gerber exporter - exports paste layers and edge cuts from a KiCad board.
Creates a ZIP archive ready to send to the Stenchill API.
Author: Thomas COTTARD - https://www.stenchill.com
"""

import glob
import os
import tempfile
import zipfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # jamais evalue a l'execution : sert l'annotation de export_gerber_zip
    import pcbnew

# `pcbnew` n'est importe qu'a l'appel, et non en tete de module. Il n'existe que
# dans l'interpreteur embarque de KiCad, or les quatre fonctions ci-dessous sont
# pures : les charger ne doit pas exiger KiCad, sinon elles restent hors de
# portee des tests. A l'interieur de KiCad le module est toujours la, donc le
# seul effet observable est le moment de l'echec en son absence, passe de
# l'import du plugin a l'export lui-meme.


def _layers_to_export() -> list:
    """Layers to export: paste layers + board outline."""
    import pcbnew
    return [
        (pcbnew.F_Paste, "F_Paste", "Front paste"),
        (pcbnew.B_Paste, "B_Paste", "Back paste"),
        (pcbnew.Edge_Cuts, "Edge_Cuts", "Board outline"),
    ]


def _configure_plot_options(po, gerber_dir: str) -> None:
    """Configure the plot controller for X2 Gerber output (paste + edge cuts)."""
    po.SetOutputDirectory(gerber_dir)
    po.SetPlotFrameRef(False)
    po.SetSketchPadsOnFabLayers(False)
    po.SetUseGerberProtelExtensions(False)
    po.SetUseGerberX2format(True)
    po.SetIncludeGerberNetlistInfo(False)
    po.SetSubtractMaskFromSilk(False)
    po.SetDrillMarksType(0)  # NO_DRILL_SHAPE - exclude through-hole drill marks


def _plot_export_layers(pc, board_name: str) -> list:
    """Plot each export layer; return the deduped list of written file paths."""
    import pcbnew
    plot_files = []
    for layer_id, layer_suffix, _desc in _layers_to_export():
        filename = f"{board_name}-{layer_suffix}"
        pc.SetLayer(layer_id)
        if not pc.OpenPlotfile(filename, pcbnew.PLOT_FORMAT_GERBER, layer_suffix):
            pc.ClosePlot()
            raise RuntimeError(f"KiCad could not open the plot file for {layer_suffix}.")
        pc.PlotLayer()
        plot_file = pc.GetPlotFileName()
        pc.ClosePlot()
        if plot_file:
            plot_files.append(plot_file)
    # A failed/blank GetPlotFileName can repeat the previous layer's path;
    # dedupe so no file is zipped twice under one arcname.
    return list(dict.fromkeys(plot_files))


def _resolve_gerber_files(plot_files: list, tmpdir: str,
                          expected_board_paths: list, preexisting: set) -> list:
    """Existing plotted files, with a glob fallback for KiCad versions where
    GetPlotFileName is empty: search the temp dir plus board-dir files that did
    not exist before this plot (freshly written by KiCad, not the user's)."""
    found_gerbers = [f for f in plot_files if os.path.exists(f)]
    if not found_gerbers:
        found_gerbers = glob.glob(os.path.join(tmpdir, "**", "*.gbr"), recursive=True)
        found_gerbers.extend(
            p for p in expected_board_paths
            if p not in preexisting and os.path.exists(p)
        )
    return found_gerbers


def _board_dir_strays(found_gerbers: list, board_dir: str) -> list:
    """Files KiCad wrote next to the board (it sometimes resolves the output
    dir relative to the board): ours to clean up afterwards."""
    if not board_dir:
        return []
    board_dir_abs = os.path.abspath(board_dir)
    return [
        f for f in found_gerbers
        if os.path.dirname(os.path.abspath(f)) == board_dir_abs
    ]


def _select_exportable_gerbers(found_gerbers: list, tmpdir: str,
                               gerber_dir: str, board_dir: str) -> list:
    """Return the non-empty gerbers to zip; raise if none were found, all are
    empty, or no paste layer is present."""
    if not found_gerbers:
        # Diagnostic: list what IS in the temp dir
        all_files = []
        for root, _dirs, files in os.walk(tmpdir):
            for f in files:
                all_files.append(os.path.join(root, f))
        raise RuntimeError(
            f"No .gbr files found.\n"
            f"Temp dir: {gerber_dir}\n"
            f"Board dir: {board_dir}\n"
            f"Files in temp: {all_files}"
        )

    exported_files = [f for f in found_gerbers if os.path.getsize(f) > 0]
    if not exported_files:
        raise RuntimeError("Gerber files were generated but are all empty.")

    # Check that at least one paste layer was exported
    has_paste = any("Paste" in os.path.basename(f) for f in exported_files)
    if not has_paste:
        raise RuntimeError(
            "No paste layer found. Make sure your PCB has pads with "
            "solder paste enabled (check pad properties)."
        )
    return exported_files


def export_gerber_zip(board: "pcbnew.BOARD") -> str:
    """
    Export paste layers and edge cuts as Gerber files, packaged in a ZIP.

    Returns the path to the temporary ZIP file.
    The caller is responsible for deleting it.
    """
    import pcbnew
    zip_tmp = tempfile.NamedTemporaryFile(suffix=".zip", prefix="stenchill_gerbers_", delete=False)
    zip_path = zip_tmp.name
    zip_tmp.close()

    try:
        with tempfile.TemporaryDirectory(prefix="stenchill_") as tmpdir:
            gerber_dir = os.path.join(tmpdir, "gerbers")
            os.makedirs(gerber_dir)

            pc = pcbnew.PLOT_CONTROLLER(board)
            _configure_plot_options(pc.GetPlotOptions(), gerber_dir)

            board_name = os.path.splitext(os.path.basename(board.GetFileName()))[0]
            board_dir = os.path.dirname(board.GetFileName())

            # Snapshot the expected board-dir paths that exist BEFORE plotting:
            # anything in this set was NOT written by us and must be neither
            # zipped (stale layer) nor deleted (it belongs to the user).
            expected_board_paths = [
                os.path.join(board_dir, f"{board_name}-{suffix}.gbr")
                for _, suffix, _ in _layers_to_export()
            ] if board_dir else []
            preexisting = {p for p in expected_board_paths if os.path.exists(p)}

            plot_files = _plot_export_layers(pc, board_name)
            found_gerbers = _resolve_gerber_files(
                plot_files, tmpdir, expected_board_paths, preexisting
            )
            board_gerbers = _board_dir_strays(found_gerbers, board_dir)

            try:
                exported_files = _select_exportable_gerbers(
                    found_gerbers, tmpdir, gerber_dir, board_dir
                )
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for filepath in exported_files:
                        zf.write(filepath, os.path.basename(filepath))
            finally:
                # Remove strays KiCad wrote to the board directory, even when
                # zipping or validation failed.
                for f in board_gerbers:
                    if os.path.exists(f):
                        os.unlink(f)

    except Exception:
        if os.path.exists(zip_path):
            os.unlink(zip_path)
        raise

    return zip_path
