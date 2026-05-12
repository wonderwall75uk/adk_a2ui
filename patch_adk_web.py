"""
patch_adk_web.py
================
Fixes a theme bug in the bundled a2ui web component (google-adk 1.33.0) where
button label text is invisible because Text.all forces the same dark primary colour
as the button background.

Root cause:
  - Button background  → CSS class `color-bgc-p30`  (dark shade of primaryColor)
  - Button text colour → CSS class `color-c-n100`   (white) on the <button> element
  - Child Text component → CSS class `color-c-p30`  (same dark primary!) from Text.all
  The child Text's explicit class overrides the inherited white → dark-on-dark = invisible.

Fix:
  Remove `"color-c-p30"` from the Text.all theme entry so Text components inherit
  their colour from the parent. Inside buttons this inherits white; on Cards (white
  background) it inherits the browser's default dark body text.

Run once after installing dependencies:
  python patch_adk_web.py
"""

import importlib.util
import pathlib
import sys

OLD = 'Text:{all:{"layout-w-100":!0,"layout-g-2":!0,"color-c-p30":!0}'
NEW = 'Text:{all:{"layout-w-100":!0,"layout-g-2":!0}'


def find_browser_dir() -> pathlib.Path:
    spec = importlib.util.find_spec("google.adk.cli")
    if spec is None or spec.submodule_search_locations is None:
        raise RuntimeError("google-adk is not installed in this environment.")
    cli_dir = pathlib.Path(list(spec.submodule_search_locations)[0])
    browser_dir = cli_dir / "browser"
    if not browser_dir.is_dir():
        raise RuntimeError(f"Browser assets not found at {browser_dir}")
    return browser_dir


def patch():
    browser_dir = find_browser_dir()
    js_files = list(browser_dir.glob("main-*.js"))
    if not js_files:
        print("ERROR: No main-*.js file found in", browser_dir)
        sys.exit(1)

    js_file = js_files[0]
    content = js_file.read_text(encoding="utf-8")

    if NEW in content and OLD not in content:
        print(f"Already patched: {js_file.name}")
        return

    if OLD not in content:
        print(f"WARNING: Expected string not found in {js_file.name}")
        print("The ADK version may have changed. Check patch_adk_web.py for updates.")
        sys.exit(1)

    patched = content.replace(OLD, NEW, 1)
    js_file.write_text(patched, encoding="utf-8")
    print(f"Patched successfully: {js_file.name}")


if __name__ == "__main__":
    patch()
