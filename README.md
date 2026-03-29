# Stenchill KiCad Plugin

Generate 3D-printable solder paste stencils directly from KiCad.

## Installation

### Via KiCad Plugin & Content Manager (PCM) — recommended

1. Open KiCad → Plugin and Content Manager
2. Search for "Stenchill"
3. Click Install

### Manual installation

Copy the `plugins/com_stenchill_kicad/` folder to your KiCad plugins directory:

| OS | Path |
|----|------|
| Linux | `~/.local/share/kicad/8.0/scripting/plugins/` |
| macOS | `~/Library/Preferences/kicad/8.0/scripting/plugins/` |
| Windows | `%APPDATA%\kicad\8.0\scripting\plugins\` |

Then restart KiCad.

## Usage

1. Open a PCB in KiCad's PCB Editor
2. Click the **Stenchill** button in the toolbar (or Tools → External Plugins → Stenchill)
3. Adjust parameters:
   - **Thickness**: stencil plate thickness (default 0.4 mm)
   - **Shrink**: pad size reduction (negative = enlarge)
   - **Nozzle diameter**: your 3D printer nozzle (affects adaptive compensation)
   - **Shoulders**: registration supports for PCB alignment
4. Choose output directory
5. Click **Generate Stencil**

The plugin exports your paste layers as Gerber files, sends them to the Stenchill API, and saves the resulting STL files.

## Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| Thickness | 0.4 mm | 0.05–10 | Stencil plate thickness |
| Shrink | 0 mm | -1–5 | Pad reduction (negative = enlarge) |
| Nozzle diameter | 0.4 mm | 0.1–2 | Adaptive compensation threshold |
| PCB thickness | 1.6 mm | 0.1–10 | Shoulder height |
| Shoulder length | 15 mm | 1–500 | L-bracket length |
| Shoulder width | 3 mm | 0.5–50 | L-bracket wall thickness |
| Shoulder clearance | 0.3 mm | 0–5 | Gap PCB ↔ shoulders |

## Requirements

- KiCad 8.0 or later
- Internet connection (generation is done server-side on stenchill.com)
- No external Python packages required (stdlib only)

## Privacy

Your Gerber files are sent to stenchill.com for processing and are **not stored** on the server.

## License

MIT — see [LICENSE](LICENSE).
