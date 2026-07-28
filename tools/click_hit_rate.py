#!/usr/bin/env python3
"""Right-click delivery: exact arrivals vs. the number you actually clicked.

Branch: investigate/rclick-delivery.

Three stages, deduplicated so counts are directly comparable:

  RCLICK    QApplication filter, one line per PHYSICAL press (dedup on
            event.timestamp()) — Qt dispatched it to something
  RECEIVED  RightClickButton.mousePressEvent — it reached a theme swatch
  HANDLER   _on_theme_right_clicked — the signal reached the handler

  YOUR COUNT > RCLICK   -> Qt never received those presses. The residue this
                           branch exists to size. A bare Qt widget on the same
                           hardware loses none (tools/click_test.py), so this
                           would be specific to Fabulor's own structure.
  RCLICK > RECEIVED     -> Qt got it but routed it away from the swatch;
                           `under_cursor` says what was actually there.
  RECEIVED > HANDLER    -> lost between widget and handler.

The previous version of this script counted one press once per object in the
propagation chain (236 counts for 100 clicks), which made every ratio it printed
unreliable. Do not compare its output to this one.

Usage:  python tools/click_hit_rate.py [logfile] [--since HH:MM]
"""
import re
import sys
from pathlib import Path

DEFAULT = Path.home() / ".local/state/fabulor/log/fabulor.log"


def main():
    argv = sys.argv[1:]
    since = None
    positional = []
    i = 0
    while i < len(argv):
        if argv[i] == "--since" and i + 1 < len(argv):
            since = argv[i + 1]
            i += 2                      # consume BOTH, or the value is read as a path
            continue
        positional.append(argv[i])
        i += 1
    path = Path(positional[0]) if positional else DEFAULT
    if not path.exists():
        print(f"no such log: {path}")
        return 1

    rclick, received, handler = [], [], []
    for l in path.open(errors="replace"):
        ts = l[11:23]
        if since and ts[:len(since)] < since:
            continue
        if "[RCLICK]" in l:
            m = re.search(r"#(\d+).*under_cursor=(\w+|None).*theme=('[^']*'|None)", l)
            rclick.append((ts, m.group(2) if m else "?", m.group(3) if m else "?"))
        elif "[CLICK-TRACE]" in l and "RECEIVED" in l:
            received.append(ts)
        elif "[CLICK-TRACE]" in l and "HANDLER" in l:
            handler.append(ts)

    if not rclick:
        print("No [RCLICK] lines found. Right-click something first.")
        return 0

    print(f"log: {path}")
    if since:
        print(f"since: {since}")
    print()
    print(f"  RCLICK   (Qt dispatched a press)  : {len(rclick)}")
    print(f"  RECEIVED (reached a ThemeItem)    : {len(received)}")
    print(f"  HANDLER  (reached the handler)    : {len(handler)}")
    print()
    print("  >>> Compare RCLICK against the number you actually clicked.")
    print("      Any shortfall is a press Qt never received — the open bug.")

    agg = {}
    for _, under, theme in rclick:
        agg[under] = agg.get(under, 0) + 1
    print("\n  what was under the cursor on each press:")
    for under, n in sorted(agg.items(), key=lambda kv: -kv[1]):
        print(f"    {n:4d}x  {under}")

    swatch = sum(n for u, n in agg.items() if u == "ThemeItem")
    if swatch and len(received) < swatch:
        print(f"\n  !! {swatch - len(received)} press(es) landed on a ThemeItem "
              f"but the widget never received them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
