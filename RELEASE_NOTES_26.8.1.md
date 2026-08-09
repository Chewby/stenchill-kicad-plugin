# Stenchill for KiCad, v26.8.1

The settings panel now mirrors the website, so the same stencil is one click
away whichever one you start from. It also gains the option the site got
recently, a help icon on every setting, and a round of display fixes and
hardening.

## New
- **"Fill in unprintable grids".** A fine-pitch BGA has walls thinner than your
  nozzle. Left as openings they print as one big puddle, so Stenchill fills
  them in. On a BGA the balls carry the solder and this costs nothing; on an
  LGA you will need a finer nozzle. The option was already applied server-side,
  the plugin simply had no say over it. It is now a checkbox, on by default,
  and your choice travels with the shared 3D preview.
- **A help icon next to every setting.** The explanations existed but were
  reachable only by resting the cursor on a field, with nothing announcing it.
  They now live in one place: click the icon and a titled panel opens, no
  hover delay, no frozen mouse. The icon stays clickable even when its group
  is disabled, so you can read what a shoulder setting does before enabling
  shoulders. It is drawn by the plugin rather than taken from the host, so it
  looks the same in every KiCad theme and on every platform.

## Changed
- **The settings match the website.** Three groups in the same order, under the
  same names, with the same labels and the same help text: Printability,
  Stencil, Alignment. If you have used the site, nothing here needs relearning.
- "Registration" is gone, on both sides. It is printing-shop jargon, and every
  translator of the site had already quietly replaced it with a word meaning
  alignment. The panel now says what it does.
- The nozzle recommendation moved out of the field label, which read
  "Nozzle (mm), 0.2 rec.:", and sits under the field as a plain hint.

## Fixed
- Group titles were clipped on macOS: the descender of the "g" in "Alignment"
  was cut off by the frame. Titles now sit above their group rather than inside
  the frame border.
- Two of the three groups had no vertical spacing at all and ran into each
  other.

## Hardening
- The check that decides whether a "View in 3D" link may be opened in your
  browser could be fooled by a backslash in the URL: Python and browsers
  disagree on where the host ends. Any URL containing a backslash is now
  refused outright. As before, anything untrusted is shown as text instead of
  opened.

## Under the hood
- The dialog is now covered by tests. The suite goes from 60 to 237 tests and
  from 19% to 99.3% coverage, including the window itself, the API client, the
  gerber export and the KiCad entry point. Running the window outside KiCad is
  what made this possible.
- Several of the fixes above were surfaced by that suite or by a full code
  review of the plugin, including checkboxes parented to the wrong widget,
  which macOS tolerates but Windows and GTK do not.
- Still zero issues under static analysis.

---
Requires an internet connection. Files are processed on stenchill.com and not
stored on the server (shared previews auto-expire after 30 minutes).
