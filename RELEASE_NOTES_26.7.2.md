# Stenchill for KiCad, v26.7.2

One headline feature this time: see your stencil in interactive 3D before you
print it, plus a batch of robustness fixes under the hood.

## ✨ New
- **"View in 3D"** button after a successful generation. One click uploads
  your gerbers to a private link (expires after 30 minutes) and opens an
  interactive 3D preview of your stencil on stenchill.com. Your exact
  parameters (thickness, shrink, nozzle, shoulders...) travel with it, so the
  preview matches what you print.

  *Why in the browser and not inside KiCad?* I did try an embedded Python
  viewer first. A KiCad plugin only gets what ships with KiCad's bundled
  Python: no PyOpenGL, and the Plugin Manager has no way to pull binary
  dependencies, while wx's WebView widget isn't reliably available across
  the platforms KiCad supports. Rendering an STL mesh smoothly (rotation,
  zoom, per-face tabs) without any of that means writing a software rasterizer
  in pure wxPython, slow and fragile for real boards. The website already has
  a full Three.js/WebGL viewer, so the plugin hands your browser a short-lived
  link instead: same result, GPU-accelerated, zero extra dependencies.
- **`stenchill-params.json`** is now saved next to your STL files: a record
  of the exact parameters used, handy to reproduce a stencil later.

## 🔧 Improved
- Sharing sends the parameters of the **last generation**, not whatever is
  currently in the form, so the preview always matches the files on disk.
- Buttons are disabled while a share upload is in flight, and closing the
  dialog mid-upload no longer risks an error.
- Hardened SSE progress parsing and SSL context reuse for flaky networks.

## 🧪 Under the hood
- 40 pure-stdlib unit tests now ship with the source (version comparison,
  progress labels, SSE dispatch, share params).

---
Requires an internet connection. Files are processed on stenchill.com and not
stored on the server (shared previews auto-expire after 30 minutes).
