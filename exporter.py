"""
Gerber exporter - exports paste layers and edge cuts from a KiCad board.
Creates a ZIP archive ready to send to the Stenchill API.
Author: Thomas COTTARD - https://www.stenchill.com
"""

import glob
import os
import tempfile
import zipfile

import pcbnew


# Layers to export: paste layers + board outline
_LAYERS_TO_EXPORT = [
    (pcbnew.F_Paste, "F_Paste", "Front paste"),
    (pcbnew.B_Paste, "B_Paste", "Back paste"),
    (pcbnew.Edge_Cuts, "Edge_Cuts", "Board outline"),
]


def export_gerber_zip(board: "pcbnew.BOARD") -> str:
    """
    Export paste layers and edge cuts as Gerber files, packaged in a ZIP.

    Returns the path to the temporary ZIP file.
    The caller is responsible for deleting it.
    """
    zip_tmp = tempfile.NamedTemporaryFile(suffix=".zip", prefix="stenchill_gerbers_", delete=False)
    zip_path = zip_tmp.name
    zip_tmp.close()

    try:
        with tempfile.TemporaryDirectory(prefix="stenchill_") as tmpdir:
            gerber_dir = os.path.join(tmpdir, "gerbers")
            os.makedirs(gerber_dir)

            exported_files = []
            board_gerbers = []
            pc = pcbnew.PLOT_CONTROLLER(board)
            po = pc.GetPlotOptions()

            # Configure plot options for Gerber output
            po.SetOutputDirectory(gerber_dir)
            po.SetPlotFrameRef(False)
            po.SetSketchPadsOnFabLayers(False)
            po.SetUseGerberProtelExtensions(False)
            po.SetUseGerberX2format(True)
            po.SetIncludeGerberNetlistInfo(False)
            po.SetSubtractMaskFromSilk(False)
            po.SetDrillMarksType(0)  # NO_DRILL_SHAPE - exclude through-hole drill marks

            board_name = os.path.splitext(os.path.basename(board.GetFileName()))[0]
            board_dir = os.path.dirname(board.GetFileName())

            # Ask the plot controller for the exact file it wrote, rather than
            # guessing afterwards by globbing: a pre-existing .gbr in the board
            # directory (e.g. from a manual File > Plot) must never be zipped
            # (stale layer) nor deleted (it belongs to the user).
            # Snapshot the expected board-dir paths that exist BEFORE plotting:
            # anything in this set was NOT written by us and must be neither
            # zipped (stale layer) nor deleted (it belongs to the user).
            expected_board_paths = [
                os.path.join(board_dir, f"{board_name}-{suffix}.gbr")
                for _, suffix, _ in _LAYERS_TO_EXPORT
            ] if board_dir else []
            preexisting = {p for p in expected_board_paths if os.path.exists(p)}

            plot_files = []
            for layer_id, layer_suffix, _desc in _LAYERS_TO_EXPORT:
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
            # A failed/blank GetPlotFileName can repeat the previous layer's
            # path; dedupe so no file is zipped twice under one arcname.
            plot_files = list(dict.fromkeys(plot_files))

            found_gerbers = [f for f in plot_files if os.path.exists(f)]
            if not found_gerbers:
                # Fallback for KiCad versions where GetPlotFileName is empty:
                # search the temp dir, plus board-dir files that did not exist
                # before this plot (i.e. freshly written by KiCad, not the user's).
                found_gerbers = glob.glob(os.path.join(tmpdir, "**", "*.gbr"), recursive=True)
                found_gerbers.extend(
                    p for p in expected_board_paths
                    if p not in preexisting and os.path.exists(p)
                )

            # Files KiCad wrote next to the board (it sometimes resolves the
            # output dir relative to the board): ours to clean up afterwards.
            if board_dir:
                board_dir_abs = os.path.abspath(board_dir)
                board_gerbers = [
                    f for f in found_gerbers
                    if os.path.dirname(os.path.abspath(f)) == board_dir_abs
                ]

            try:
                if not found_gerbers:
                    # Diagnostic: list what IS in the temp dir
                    all_files = []
                    for root, dirs, files in os.walk(tmpdir):
                        for f in files:
                            all_files.append(os.path.join(root, f))
                    raise RuntimeError(
                        f"No .gbr files found.\n"
                        f"Temp dir: {gerber_dir}\n"
                        f"Board dir: {board_dir}\n"
                        f"Files in temp: {all_files}"
                    )

                for gerber_file in found_gerbers:
                    if os.path.getsize(gerber_file) > 0:
                        exported_files.append(gerber_file)

                if not exported_files:
                    raise RuntimeError("Gerber files were generated but are all empty.")

                # Check that at least one paste layer was exported
                has_paste = any("Paste" in os.path.basename(f) for f in exported_files)
                if not has_paste:
                    raise RuntimeError(
                        "No paste layer found. Make sure your PCB has pads with "
                        "solder paste enabled (check pad properties)."
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
