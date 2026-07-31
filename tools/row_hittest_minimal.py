"""Minimal repro for the last-pixel routing bug — nothing but stacked widgets.

Everything that could be blamed has been stripped: no labels, no nested
layouts, no stylesheets, no cursors, no scroll area, no margins. Just N plain
QWidgets stacked in a QVBoxLayout with setSpacing(0), each reporting which
widget received the press.

WHAT IS BEING HUNTED: in the app, and in a fuller harness, a press on the LAST
pixel of a row is delivered to the parent container instead of the row, while
`childAt()`, `QCursor`, the event's own coordinates and the widget geometry all
agree that pixel belongs to the row. A synthesized press at the same pixel
reaches the row correctly — so only real platform input shows it.

Already ruled out by measurement, each with the defect still present:
  * the container's 2px top inset (removed: dead pixel moved WITH the rows,
    from y=53 to y=51 — it tracks the row's last pixel, not any absolute y)
  * inter-row gaps (setSpacing(0), measured gap_above=0)
  * row height (exactly 52px)
  * child widgets intercepting (children made mouse-transparent — no change)
  * child cursors/handlers (none of the app's labels sets or handles anything)
  * display scaling (100%, DPR 1.0)
  * the transport-bar blur grab (reproduces with blur off)

USE:
    python tools/row_hittest_minimal.py            # geometry + synthesized sweep
    python tools/row_hittest_minimal.py --show     # REAL input; this is the test

Only --show is authoritative. The synthesized sweep is included precisely to
demonstrate that it passes while the real thing fails, which is the single most
important fact about this bug: every offscreen check ever run on it was blind.

VARIANTS to bisect toward the cause, combinable:
    --no-spacing-zero   let the layout use its default spacing
    --fixed-height      setFixedHeight instead of layout-driven sizing
    --no-layout         position rows manually with setGeometry, no layout
    --in-scroll         put the stack inside a QScrollArea
Each isolates one construction choice. If the dead pixel survives --no-layout,
no layout code is involved at all and the cause is in plain widget stacking.
"""
import argparse
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

ROW_H = 52
N_ROWS = 6
WIDTH = 252


class Row(QWidget):
    def __init__(self, index, on_press):
        super().__init__()
        self.index = index
        self._on_press = on_press
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(),
                     Qt.darkBlue if index % 2 else Qt.darkGreen)
        self.setPalette(pal)

    def mousePressEvent(self, event):
        self._on_press(f"row {self.index}", int(event.position().y()), self)


class Container(QWidget):
    def __init__(self, on_press):
        super().__init__()
        self._on_press = on_press
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), Qt.red)
        self.setPalette(pal)

    def mousePressEvent(self, event):
        self._on_press("CONTAINER", int(event.position().y()), self)


def build(args, on_press):
    container = Container(on_press)
    rows = []

    if args.no_layout:
        # No layout at all: rows positioned by hand. If the dead pixel survives
        # this, no layout code is involved in producing it.
        for i in range(N_ROWS):
            r = Row(i, on_press)
            r.setParent(container)
            r.setGeometry(0, i * ROW_H, WIDTH, ROW_H)
            rows.append(r)
        container.setFixedSize(WIDTH, N_ROWS * ROW_H)
    else:
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        if not args.no_spacing_zero:
            lay.setSpacing(0)
        for i in range(N_ROWS):
            r = Row(i, on_press)
            if args.fixed_height:
                r.setFixedHeight(ROW_H)
            else:
                r.setMinimumHeight(ROW_H)
                r.setMaximumHeight(ROW_H)
            lay.addWidget(r)
            rows.append(r)
        lay.addStretch()

    if args.in_scroll:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        scroll.resize(WIDTH, N_ROWS * ROW_H)
        return scroll, container, rows
    container.resize(WIDTH, N_ROWS * ROW_H)
    return container, container, rows


def report(container, rows):
    print(f"container: {container.width()}x{container.height()}")
    for r in rows:
        print(f"  row {r.index}: y={r.y()}..{r.y() + r.height() - 1} (h={r.height()})")
    print()


def synth_sweep(app, container, rows):
    received = {}
    state = {"y": None}

    def on_press(who, local_y, widget):
        received[state["y"]] = who

    for r in rows:
        r._on_press = on_press
    container._on_press = on_press

    for y in range(0, N_ROWS * ROW_H):
        state["y"] = y
        target = container.childAt(QPoint(WIDTH // 2, y)) or container
        local = target.mapFrom(container, QPoint(WIDTH // 2, y))
        app.sendEvent(target, QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, QPointF(local),
            container.mapToGlobal(QPoint(WIDTH // 2, y)),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

    bad = []
    for y, who in sorted(received.items()):
        owner = next((r for r in rows if r.y() <= y <= r.y() + r.height() - 1), None)
        if owner is not None and who != f"row {owner.index}":
            bad.append((y, owner.index, y - owner.y(), who))

    print("synthesized sweep:")
    if not bad:
        print("  every in-row pixel reached its row  <-- PASSES, and is WRONG:")
        print("  real input fails on the last pixel of each row. This sweep is")
        print("  included to show that offscreen testing cannot see this bug.")
    else:
        for y, idx, local, who in bad:
            print(f"  y={y:4d} row {idx} local_y={local} -> {who}")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--no-spacing-zero", action="store_true")
    ap.add_argument("--fixed-height", action="store_true")
    ap.add_argument("--no-layout", action="store_true")
    ap.add_argument("--in-scroll", action="store_true")
    args = ap.parse_args()
    if args.show:
        os.environ.pop("QT_QPA_PLATFORM", None)

    app = QApplication(sys.argv)

    status = {"label": None}

    def on_press(who, local_y, widget):
        owner = None
        if who == "CONTAINER":
            for r in getattr(on_press, "rows", []):
                if r.y() <= local_y <= r.y() + r.height() - 1:
                    owner = r.index
                    break
        text = (f"{who}   y={local_y}"
                + (f"   (geometry says row {owner})" if owner is not None else ""))
        print("   " + text)
        if status["label"] is not None:
            bad = who == "CONTAINER"
            status["label"].setStyleSheet(
                "background:%s; color:%s; padding:6px; font-family:monospace;"
                % (("#311", "#f99") if bad else ("#123", "#9f9")))
            status["label"].setText(text)

    root, container, rows = build(args, on_press)
    on_press.rows = rows

    variants = [n for n, v in (("no-spacing-zero", args.no_spacing_zero),
                               ("fixed-height", args.fixed_height),
                               ("no-layout", args.no_layout),
                               ("in-scroll", args.in_scroll)) if v]
    print(f"variants: {', '.join(variants) if variants else 'none (baseline)'}\n")

    if args.show:
        wrapper = QWidget()
        wrapper.setWindowTitle("minimal — click each row's LAST pixel")
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(root)
        lbl = QLabel("click along a row boundary; red = reached the container")
        lbl.setWordWrap(True)
        lbl.setMinimumHeight(48)
        lbl.setStyleSheet(
            "background:#111; color:#ddd; padding:6px; font-family:monospace;")
        outer.addWidget(lbl)
        status["label"] = lbl
        wrapper.resize(WIDTH + 16, N_ROWS * ROW_H + 70)
        wrapper.show()
        report(container, rows)
        sys.exit(app.exec())

    root.show()
    app.processEvents()
    report(container, rows)
    synth_sweep(app, container, rows)
    print("=" * 68)
    print("THIS RUN PROVED NOTHING. The synthesized sweep passes on every")
    print("variant, including ones that fail live. Re-run with --show and")
    print("click along a row boundary:")
    print()
    print(f"    python {os.path.basename(__file__)} --show"
          + (" " + " ".join(f"--{v}" for v in variants) if variants else ""))
    print("=" * 68)


if __name__ == "__main__":
    main()
