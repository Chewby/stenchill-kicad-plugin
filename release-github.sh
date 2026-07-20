#!/bin/bash
#
# release-github.sh - Publish the current plugin version as a GitHub release.
#
# Reads the version from metadata.json, ensures the ZIP exists (builds it via
# package.sh if needed), then creates the GitHub release `v<version>` with the
# ZIP as an asset and RELEASE_NOTES_<version>.md as the description.
#
# Run it from the real plugin repo (where package.sh + the ZIP live):
#   ./release-github.sh
#
# Requirements:
#   - gh CLI, authenticated (gh auth login)
#   - package.sh alongside this script
#   - RELEASE_NOTES_<version>.md alongside this script
#   - the release commit already pushed to origin/main
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

REPO="Chewby/stenchill-kicad-plugin"

VERSION=$(python3 -c "import json; print(json.load(open('metadata.json'))['versions'][0]['version'])")
TAG="v${VERSION}"
ZIP="stenchill-kicad-plugin-${VERSION}.zip"
NOTES="RELEASE_NOTES_${VERSION}.md"

echo "=== GitHub release ${TAG}  (${REPO}) ==="

# --- Preconditions ---
command -v gh >/dev/null 2>&1 || { echo "ERROR: gh CLI not found. Install: https://cli.github.com"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "ERROR: gh not authenticated. Run: gh auth login"; exit 1; }

if [ ! -f "$NOTES" ]; then
    echo "ERROR: release notes not found: $NOTES"
    exit 1
fi

# Build the ZIP if missing (package.sh reads the version from metadata.json).
if [ ! -f "$ZIP" ]; then
    echo "ZIP not found, building via package.sh..."
    ./package.sh
fi
[ -f "$ZIP" ] || { echo "ERROR: ZIP still missing after build: $ZIP"; exit 1; }

# The git tag is created at origin's default-branch HEAD, so HEAD must be pushed.
git fetch origin --quiet 2>/dev/null || true
if ! git merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
    echo "ERROR: HEAD is not on origin/main. Push first:  git push"
    exit 1
fi

# Refuse to clobber an existing release.
if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
    echo "ERROR: release $TAG already exists. Bump the version or delete it first:"
    echo "       gh release delete $TAG --repo $REPO --cleanup-tag"
    exit 1
fi

echo "Creating release ${TAG} with asset ${ZIP}..."
gh release create "$TAG" "$ZIP" \
    --repo "$REPO" \
    --target main \
    --title "$TAG" \
    --notes-file "$NOTES"

echo ""
echo "=== Done ==="
echo "  Release:  https://github.com/${REPO}/releases/tag/${TAG}"
echo "  Asset:    ${ZIP}"
echo ""
echo "Next steps (not done by this script):"
echo "  1. Update the PCM metadata repo (download_url / sha256 / sizes from package.sh)."
echo "  2. Deploy the website so the plugin page download link resolves."
