"""Screenshot every kiosk state at iPad sizes and check nothing overlaps.

Run:  .venv/bin/python tests/kiosk_shots.py            (needs the app or any static server on :8000)
Saves to docs/screenshots/ and prints an overlap report.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8000/kiosk.html?endpoint=/nope"
SIZES = {"landscape": (1180, 820), "portrait": (820, 1180)}
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"

# state name -> the payload the kiosk would get from GET /state
STATES = {
    "idle": {"state": "idle", "present": False, "present_for": 0},
    "hold-still": {"state": "scanning", "present": True, "present_for": 1.8},
    "dispensed": {"state": "dispensed", "item": "Kit Kat", "present": True, "present_for": 3.4},
    "already-served": {"state": "already_served", "present": True, "present_for": 3.6},
    "sleep": {"state": "sleep", "present": False, "present_for": 0},
}
# the kiosk only shows stock through the item name, so these two reuse the dispensed screen
STOCK_STATES = {
    "low-stock": {"state": "dispensed", "item": "Kit Kat (3 left)", "present": True, "present_for": 3.4},
    "out-of-stock": {"state": "idle", "item": "", "present": False, "present_for": 0},
}

WATCH = ["#caption", "#subcaption", "#timer", ".badge", ".wordmark", ".sleep-hint", "#dot", "#lang"]


def boxes(page):
    out = {}
    for sel in WATCH:
        box = page.evaluate(
            """(sel) => { const el = document.querySelector(sel);
                 if (!el) return null;
                 // effective opacity: every ancestor counts, so a faded layer hides its text
                 let opacity = 1, node = el;
                 while (node && node !== document.documentElement){
                   opacity *= parseFloat(getComputedStyle(node).opacity);
                   node = node.parentElement;
                 }
                 const r = el.getBoundingClientRect();
                 return {x: r.x, y: r.y, w: r.width, h: r.height, faded: opacity < 0.05,
                         text: (el.textContent || '').trim().slice(0, 40)}; }""",
            sel,
        )
        if box and not box["faded"] and box["w"] > 0 and box["h"] > 0:
            out[sel] = box
    return out


def overlaps(a, b, pad=2):
    return not (a["x"] + a["w"] <= b["x"] + pad or b["x"] + b["w"] <= a["x"] + pad
                or a["y"] + a["h"] <= b["y"] + pad or b["y"] + b["h"] <= a["y"] + pad)


def main():
    problems = []
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for orientation, (w, h) in SIZES.items():
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
            page.goto(URL)
            page.wait_for_timeout(1200)
            page.evaluate("clearTimeout(demoTimer)")
            for name, payload in {**STATES, **STOCK_STATES}.items():
                page.evaluate("(p) => { render('idle', {present:false}); render(p.state, p); }", payload)
                page.wait_for_timeout(900)   # let the swap and any cross-fade finish
                shot = OUT / f"kiosk-{orientation}-{name}.png"
                page.screenshot(path=str(shot))
                found = boxes(page)
                names = list(found)
                for i in range(len(names)):
                    for j in range(i + 1, len(names)):
                        if overlaps(found[names[i]], found[names[j]]):
                            problems.append(f"{orientation}/{name}: {names[i]} overlaps {names[j]}")
                print(f"  {orientation:9} {name:14} visible: {', '.join(names) or 'none'}")
            # the Spanish screens must fit too
            page.evaluate("document.querySelector('#lang button[data-lang=es]').click()")
            for name in ("idle", "hold-still", "already-served"):
                payload = {**STATES[name.replace("hold-still", "hold-still")]} if name in STATES else None
                payload = STATES.get(name) or {"state": "scanning", "present": True, "present_for": 2.0}
                page.evaluate("(p) => { render('sleep', {}); render(p.state, p); }", payload)
                page.wait_for_timeout(700)
                page.screenshot(path=str(OUT / f"kiosk-{orientation}-es-{name}.png"))
                found = boxes(page)
                names = list(found)
                for i in range(len(names)):
                    for j in range(i + 1, len(names)):
                        if overlaps(found[names[i]], found[names[j]]):
                            problems.append(f"{orientation}/es-{name}: {names[i]} overlaps {names[j]}")
                print(f"  {orientation:9} es-{name:11} {found.get('#caption', {}).get('text', '')[:28]}")
            page.close()
        browser.close()
    print()
    if problems:
        print("OVERLAPS FOUND:")
        for p in problems:
            print("  " + p)
        return 1
    print("no overlaps at either iPad size")
    return 0


if __name__ == "__main__":
    sys.exit(main())
