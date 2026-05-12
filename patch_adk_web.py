"""
patch_adk_web.py
================
Applies two patches to the bundled ADK web UI (google-adk 1.33.0):

PATCH 1 — Button text colour fix
---------------------------------
Fixes a theme bug where button label text is invisible because Text.all forces
the same dark primary colour as the button background.

Root cause:
  - Button background  → CSS class `color-bgc-p30`  (dark shade of primaryColor)
  - Button text colour → CSS class `color-c-n100`   (white) on the <button> element
  - Child Text component → CSS class `color-c-p30`  (same dark primary!) from Text.all
  The child Text's explicit class overrides the inherited white → dark-on-dark = invisible.

Fix: Remove `"color-c-p30"` from the Text.all theme entry.


PATCH 2 — Button action forwarding fix
---------------------------------------
Fixes a bug where clicking A2UI buttons (e.g. "Submit Report") does nothing.

Root cause:
  - The a2ui processor (`fN`) has an `events` RxJS Subject that emits when a
    button is clicked: `{ message: { userAction: {...} }, completion: Subject }`
  - The `app-a2ui-canvas` component injects the processor but never subscribes
    to `processor.events`, so button click events are silently discarded.
  - ADK web's chat component has no wiring to receive these events.

Fix:
  1. Subscribe to `processor.events` in `app-a2ui-canvas` (ngOnInit/ngOnDestroy).
     On event, format the userAction as a USER_ACTION: text prompt and dispatch a
     native DOM CustomEvent('a2ui-action') on the document.
  2. In the main chat component's ngOnInit, add a listener for 'a2ui-action' that
     calls `this.sendMessage(...)` with the formatted text as a user message.


Run once after installing dependencies:
  python patch_adk_web.py
"""

import importlib.util
import pathlib
import sys

# ─── Patch 1: Button text colour ─────────────────────────────────────────────

_P1_OLD = 'Text:{all:{"layout-w-100":!0,"layout-g-2":!0,"color-c-p30":!0}'
_P1_NEW = 'Text:{all:{"layout-w-100":!0,"layout-g-2":!0}'

# ─── Patch 2a: app-a2ui-canvas subscribes to processor events ────────────────

_P2A_OLD = (
    'var zy=class t{processor=w(CL);beginRendering=null;surfaceUpdate=null;'
    'dataModelUpdate=null;surfaceId=bA(null);activeSurface=bA(null);'
    'surface=pe(()=>this.activeSurface());constructor(){}ngOnChanges(e){'
)

_P2A_NEW = (
    'var zy=class t{processor=w(CL);beginRendering=null;surfaceUpdate=null;'
    'dataModelUpdate=null;surfaceId=bA(null);activeSurface=bA(null);'
    'surface=pe(()=>this.activeSurface());_a2uiSub=null;constructor(){}'
    'ngOnInit(){'
        'this._a2uiSub=this.processor.events.subscribe(ev=>{'
            'let m=ev.message;'
            'if(m&&m.userAction){'
                'let ua=m.userAction;'
                'let ctx=ua.context&&Object.keys(ua.context).length>0'
                    '?Object.entries(ua.context).map(([k,v])=>"  "+k+": "+JSON.stringify(v)).join("\\n")'
                    ':"  (no form data submitted)";'
                'let txt="USER_ACTION: "+(ua.name||"unknown")+'
                    '"\\nSurface: "+(ua.surfaceId||"")+'
                    '"\\nSubmitted form data:\\n"+ctx;'
                'document.dispatchEvent(new CustomEvent("a2ui-action",{detail:{text:txt}}));'
            '}'
            'let r=ev.completion;'
            'if(r&&typeof r.next==="function")r.next(void 0);'
        '});'
    '}'
    'ngOnDestroy(){if(this._a2uiSub){this._a2uiSub.unsubscribe();this._a2uiSub=null;}}'
    'ngOnChanges(e){'
)

# ─── Patch 2b: Chat component listens for the CustomEvent ────────────────────

_P2B_OLD = 'ngOnInit(){if(this.syncSelectedAppFromUrl(),'

_P2B_NEW = (
    'ngOnInit(){'
    'document.addEventListener("a2ui-action",(ev)=>{'
        'let txt=ev.detail&&ev.detail.text;'
        'if(!txt)return;'
        'let msg={role:"user",parts:[{text:txt}]};'
        'this.sendMessage(msg);'
    '});'
    'if(this.syncSelectedAppFromUrl(),'
)


def find_browser_dir() -> pathlib.Path:
    spec = importlib.util.find_spec("google.adk.cli")
    if spec is None or spec.submodule_search_locations is None:
        raise RuntimeError("google-adk is not installed in this environment.")
    cli_dir = pathlib.Path(list(spec.submodule_search_locations)[0])
    browser_dir = cli_dir / "browser"
    if not browser_dir.is_dir():
        raise RuntimeError(f"Browser assets not found at {browser_dir}")
    return browser_dir


def _apply(content: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if new in content and old not in content:
        print(f"  {label}: already applied.")
        return content, True
    if old not in content:
        print(f"  {label}: WARNING — target string not found. ADK version may differ.")
        return content, False
    print(f"  {label}: applied.")
    return content.replace(old, new, 1), True


def patch():
    browser_dir = find_browser_dir()
    js_files = list(browser_dir.glob("main-*.js"))
    if not js_files:
        print("ERROR: No main-*.js file found in", browser_dir)
        sys.exit(1)

    js_file = js_files[0]
    print(f"Patching {js_file.name} ...")
    content = js_file.read_text(encoding="utf-8")

    content, ok1  = _apply(content, _P1_OLD,  _P1_NEW,  "Patch 1 (button text colour)")
    content, ok2a = _apply(content, _P2A_OLD, _P2A_NEW, "Patch 2a (canvas event subscription)")
    content, ok2b = _apply(content, _P2B_OLD, _P2B_NEW, "Patch 2b (chat event listener)")

    if ok1 or ok2a or ok2b:
        js_file.write_text(content, encoding="utf-8")
        print(f"\nDone. Hard-refresh the browser (Ctrl+Shift+R) to pick up the changes.")
    else:
        print("\nNothing was changed.")


if __name__ == "__main__":
    patch()
