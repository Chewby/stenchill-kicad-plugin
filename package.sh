#!/bin/bash
#
# package.sh - Build a KiCad PCM-ready ZIP for the Stenchill plugin
#
# Usage:
#   ./package.sh                    # reads version from metadata.json
#   ./package.sh 26.4.0             # override version
#
# What it does:
#   1. Reads version from metadata.json (or CLI arg)
#   2. Resizes icon-96.png → 64x64 for resources/icon.png (PCM requirement)
#   3. Copies icon-96.png into plugins/ (used by dialog.py at runtime)
#   4. Builds the ZIP with the correct PCM structure
#   5. Computes SHA256, download_size, install_size
#   6. Optionally updates the metadata repo metadata.json + icon
#
# Requirements: python3, Pillow (pip install Pillow)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# --- Config ---
IDENTIFIER="com.stenchill.kicad"
ICON_SOURCE="icon-96.png"
METADATA_REPO="../kicad-metadata-fork"  # adjust path to your metadata fork

# Plugin source files to include in plugins/
PLUGIN_FILES=(
    "__init__.py"
    "api_client.py"
    "dialog.py"
    "exporter.py"
    "plugin.py"
    "share_params.py"
)

# --- Version ---
if [ -n "${1:-}" ]; then
    VERSION="$1"
else
    VERSION=$(python3 -c "import json; m=json.load(open('metadata.json')); print(m['versions'][0]['version'])")
fi

ZIP_NAME="stenchill-kicad-plugin-${VERSION}.zip"
BUILD_DIR=$(mktemp -d)

echo "=== Stenchill KiCad Plugin Packager ==="
echo "Version:    $VERSION"
echo "Output:     $ZIP_NAME"
echo ""

# --- Verify source icon ---
if [ ! -f "$ICON_SOURCE" ]; then
    echo "ERROR: Icon not found: $ICON_SOURCE"
    rm -rf "$BUILD_DIR"
    exit 1
fi

# --- Build directory structure ---
mkdir -p "$BUILD_DIR/plugins"
mkdir -p "$BUILD_DIR/resources"

# Copy plugin files
for f in "${PLUGIN_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "ERROR: Missing plugin file: $f"
        rm -rf "$BUILD_DIR"
        exit 1
    fi
    cp "$f" "$BUILD_DIR/plugins/"
done

# Copy icon-96.png into plugins/ (dialog.py loads it at runtime)
cp "$ICON_SOURCE" "$BUILD_DIR/plugins/icon-96.png"

# Copy metadata.json (without sha256/sizes - those go in the metadata repo only)
cp metadata.json "$BUILD_DIR/metadata.json"

# Also copy metadata.json INTO plugins/ next to __init__.py. KiCad's PCM only
# extracts plugins/* into 3rdparty/plugins/<id>/ and does NOT place the root
# metadata.json there, so __init__._read_version() (which reads metadata.json
# from its own dir) would resolve VERSION to "unknown" in a real install. The
# in-package copy keeps VERSION accurate at runtime (dialog title, User-Agent,
# and the update-notice version check all depend on it).
cp metadata.json "$BUILD_DIR/plugins/metadata.json"

# Resize icon to 64x64 for resources/icon.png (PCM requirement)
python3 -c "
from PIL import Image
img = Image.open('$ICON_SOURCE')
img = img.resize((64, 64), Image.LANCZOS)
img.save('$BUILD_DIR/resources/icon.png')
"
echo "Icon: $ICON_SOURCE → 64x64 (resources/icon.png)"

# --- Create ZIP ---
ZIP_TMP="$BUILD_DIR/$ZIP_NAME"
(cd "$BUILD_DIR" && zip -r "$ZIP_TMP" \
    metadata.json \
    resources/icon.png \
    plugins/ \
)

# Move ZIP to script dir
cp "$ZIP_TMP" "$SCRIPT_DIR/$ZIP_NAME"
ZIP_PATH="$SCRIPT_DIR/$ZIP_NAME"

# Cleanup
rm -rf "$BUILD_DIR"

# --- Compute stats ---
SHA256=$(shasum -a 256 "$ZIP_PATH" | awk '{print $1}')
DOWNLOAD_SIZE=$(wc -c < "$ZIP_PATH" | tr -d ' ')
INSTALL_SIZE=$(python3 -c "
import zipfile
z = zipfile.ZipFile('$ZIP_PATH')
print(sum(e.file_size for e in z.infolist() if not e.is_dir()))
z.close()
")

echo ""
echo "=== Package Stats ==="
echo "  download_sha256: $SHA256"
echo "  download_size:   $DOWNLOAD_SIZE"
echo "  install_size:    $INSTALL_SIZE"
echo ""

# --- Update metadata repo if available ---
METADATA_REPO_FILE="$METADATA_REPO/packages/$IDENTIFIER/metadata.json"

if [ -f "$METADATA_REPO_FILE" ]; then
    echo "Updating metadata repo: $METADATA_REPO_FILE"

    python3 -c "
import json

with open('$METADATA_REPO_FILE', 'r') as f:
    meta = json.load(f)

# Find or create version entry
version_found = False
for v in meta['versions']:
    if v['version'] == '$VERSION':
        v['download_sha256'] = '$SHA256'
        v['download_size'] = $DOWNLOAD_SIZE
        v['install_size'] = $INSTALL_SIZE
        v['download_url'] = 'https://github.com/Chewby/stenchill-kicad-plugin/releases/download/v$VERSION/stenchill-kicad-plugin-$VERSION.zip'
        version_found = True
        break

if not version_found:
    meta['versions'].append({
        'version': '$VERSION',
        'status': 'stable',
        'kicad_version': '8.0',
        'download_url': 'https://github.com/Chewby/stenchill-kicad-plugin/releases/download/v$VERSION/stenchill-kicad-plugin-$VERSION.zip',
        'download_sha256': '$SHA256',
        'download_size': $DOWNLOAD_SIZE,
        'install_size': $INSTALL_SIZE
    })

with open('$METADATA_REPO_FILE', 'w') as f:
    json.dump(meta, f, indent=4)
    f.write('\n')

print('  done')
"
    # Copy 64x64 icon to metadata repo
    ICON_DEST="$METADATA_REPO/packages/$IDENTIFIER/icon.png"
    python3 -c "
from PIL import Image
img = Image.open('$ICON_SOURCE')
img = img.resize((64, 64), Image.LANCZOS)
img.save('$ICON_DEST')
"
    echo "  Icon copied to metadata repo (64x64)"
else
    echo "Metadata repo not found at: $METADATA_REPO_FILE"
    echo "Copy these values manually into the metadata repo metadata.json"
fi

echo ""
echo "=== Done ==="
echo "Next steps:"
echo "  1. Create GitHub release v$VERSION and upload $ZIP_NAME"
echo "  2. Commit & push changes in metadata repo"
echo "  3. The MR pipeline will validate everything"
