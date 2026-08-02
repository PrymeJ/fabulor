#!/usr/bin/env python
"""Part 1 depth-provenance probe (investigate/restyle-cost-depth-and-narrowing).

Reports, for the REAL MainWindow (not the offscreen synthetic harness), at a fixed
point after full construction with settings_panel/stats_panel/book_detail_panel all
built:
  - total mw.findChildren(QWidget) count
  - max ancestor-chain depth from mw to any leaf widget
  - per-major-subtree (settings_panel, stats_panel, book_detail_panel, library_panel,
    sidebar): its own widget count and its own max depth from mw to its deepest leaf

Designed to run standalone against ANY checkout via `git worktree`, so it can be
pointed at historical commits without disturbing the current working tree.

Usage: python tools/depth_probe.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("FABULOR_LOG_LEVEL", "ERROR")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

app = QApplication([])

from fabulor.app import MainWindow

mw = MainWindow()
app.processEvents()


def max_depth_from(root):
    """Max ancestor-chain length from root to any descendant leaf, walking .parentWidget()."""
    best = 0
    for w in root.findChildren(QWidget):
        d = 0
        p = w
        while p is not None and p is not root:
            p = p.parentWidget()
            d += 1
        if d > best:
            best = d
    return best


total = len(mw.findChildren(QWidget))
overall_depth = max_depth_from(mw)

print(f"TOTAL_WIDGETS={total}")
print(f"OVERALL_MAX_DEPTH_FROM_MW={overall_depth}")

subtrees = ["settings_panel", "stats_panel", "book_detail_panel", "library_panel", "sidebar"]
for name in subtrees:
    w = getattr(mw, name, None)
    if w is None:
        print(f"SUBTREE {name:20s} MISSING")
        continue
    count = len(w.findChildren(QWidget))
    depth = max_depth_from(w)
    print(f"SUBTREE {name:20s} widgets={count:5d}  own_max_depth={depth:3d}")
