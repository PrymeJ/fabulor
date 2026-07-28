#!/usr/bin/env python3
"""Right-click delivery audit for theme selection.

TEMP diagnostic (2026-07-28). A deliberate 30-click run (blur on) + 30 (blur off)
produced only 33 clicks that reached the widget: ~45% of right-presses never
arrived, in BOTH conditions.

FOUR stages, so a loss is attributable rather than merely counted:

  DISPATCHED  QApplication event filter   -- Qt dispatched the press to SOME widget
  RECEIVED    RightClickButton.mousePress -- it reached the right widget
  HANDLER     _on_theme_right_clicked     -- the signal reached the handler
  APPLIED     _apply_stylesheets ran      -- the theme actually switched

  DISPATCHED but not RECEIVED  -> Qt routed it to the wrong widget (see `to=`)
  neither                      -> Qt never got the press at all; the loss is
                                  upstream of the app (input stack / compositor)

NOTE ON "APPLIED": a click arriving during a fade is STASHED and applies ~300ms
later via the drain. An earlier version of this script checked the outcome
synchronously and reported every stashed click as a miss — producing a bogus
8-16% hit rate. Applies are now detected by scanning forward to the next click.

Usage:  python tools/click_hit_rate.py [logfile]
"""
import re
import sys
from pathlib import Path

DEFAULT = Path.home() / ".local/state/fabulor/log/fabulor.log"


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.exists():
        print(f"no such log: {path}")
        return 1

    lines = list(path.open(errors="replace"))
    dispatched, received, handler = [], [], []

    for i, l in enumerate(lines):
        if "[RCLICK-AUDIT]" in l:
            m = re.search(r"press dispatched to (\w+) .*under_cursor=(\w+)", l)
            if m:
                dispatched.append((i, l[:23], m.group(1), m.group(2)))
            else:
                m2 = re.search(r"press dispatched to (\w+)", l)
                dispatched.append((i, l[:23], m2.group(1) if m2 else "?", "?"))
        elif "[CLICK-TRACE]" in l and "RECEIVED" in l:
            received.append((i, l[:23]))
        elif "[CLICK-TRACE]" in l and "HANDLER" in l:
            m = re.search(r"theme_name='([^']+)'.*blur_enabled=(\w+)", l)
            if m:
                handler.append((i, l[:23], m.group(1), m.group(2) == "True"))

    if not (dispatched or received or handler):
        print("No click instrumentation found. Right-click some theme names first.")
        return 0

    print(f"log: {path}\n")
    print(f"  DISPATCHED (Qt gave the press to a widget) : {len(dispatched)}")
    print(f"  RECEIVED   (reached a ThemeItem)           : {len(received)}")
    print(f"  HANDLER    (reached the handler)           : {len(handler)}")

    # Where did dispatched-but-not-received presses go?
    misrouted = [d for d in dispatched if d[2] != "ThemeItem"]
    if misrouted:
        print(f"\n  {len(misrouted)} press(es) dispatched to a NON-ThemeItem widget:")
        seen = {}
        for _, ts, cls, under in misrouted:
            seen[(cls, under)] = seen.get((cls, under), 0) + 1
        for (cls, under), n in sorted(seen.items(), key=lambda kv: -kv[1]):
            verdict = ("  <-- ROUTING BUG: a swatch WAS under the cursor"
                       if under == "ThemeItem" else "  (nothing clickable there)")
            print(f"       {n:3d}x  dispatched->{cls:<14} under->{under}{verdict}")

    # Real apply detection: scan from each handler click to the next one.
    stats = {True: [0, 0], False: [0, 0]}
    misses = []
    for idx, (i, ts, name, blur) in enumerate(handler):
        end = handler[idx + 1][0] if idx + 1 < len(handler) else len(lines)
        window = lines[i:end]
        applied = any("_apply_stylesheets hover=False" in w for w in window)
        noop = any("EARLY-RETURN no-op guard" in w and f"theme_name='{name}'" in w
                   for w in window)
        ok = applied or noop
        stats[blur][0 if ok else 1] += 1
        if not ok:
            misses.append((ts, name, blur))

    for blur, label in ((True, "BLUR ON "), (False, "BLUR OFF")):
        ok, bad = stats[blur]
        tot = ok + bad
        if not tot:
            continue
        print(f"\n{label} | reached handler {tot:3d} | switched {ok:3d} | "
              f"lost {bad:3d} | {ok / tot * 100:5.1f}%")

    if misses:
        print("\n  Clicks that reached the handler but never switched:")
        for ts, name, blur in misses:
            print(f"       {ts}  blur={'ON ' if blur else 'OFF'}  {name}")

    print("\n  NOTE: the number YOU clicked is the ground truth for the top line —")
    print("  a press Qt never received leaves no trace anywhere in this log.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
