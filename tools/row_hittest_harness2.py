"""Clean-slate row harness: the structure the Stats/Tags lists SHOULD have.

Companion to row_hittest_harness.py, which reproduces the current defect. This
one is built from scratch to the intended shape so the two can be compared
side by side and a fix validated before it touches the app.

THE DEFECT THIS IS BUILT AGAINST (measured 2026-07-31): a `BookDayRow` is 52px
tall with `(4,2,4,2)` layout margins and an inner `QVBoxLayout` at
`setSpacing(2)`. That leaves horizontal bands with no child widget over them:

    y = 0, 1     row's top margin
    y = 25, 26   between the title row and the author row
    y = 50, 51   row's bottom margin

Rows stack at `setSpacing(0)`, so row N's `y=50,51` abuts row N+1's `y=0,1` —
a 4px strip that looks like solid row but is split between two rows. Clicks
there did nothing and the cursor stayed the plain arrow.

WHAT "PROPER" MEANS HERE:
  * every row is exactly ROW_H tall, no overlap, no inter-row spacing
  * the row is the single mouse target for its whole rect — children are
    explicitly transparent to mouse events, so no band can be dead regardless
    of where the labels happen to sit
  * the container is the same widget type as the live one (a plain QWidget with
    WA_StyledBackground inside a QScrollArea), so nothing about the comparison
    is confounded by a different container

Run:
    python tools/row_hittest_harness2.py           # offscreen delivery sweep
    python tools/row_hittest_harness2.py --show    # real window, poke it by hand

The offscreen sweep is NOT authoritative for this class of bug — synthesized
events did not reproduce the original defect at all. Use --show and real input
to confirm; the sweep only catches gross regressions.
"""
import argparse
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

ROW_H = 52
COVER = 48
WIDTH = 252


class CleanRow(QWidget):
    """A row that owns its entire rect as a mouse target.

    Two things make that true, and both are load-bearing:

    1. `WA_TransparentForMouseEvents` on every child. The children here are
       purely decorative — a cover pixmap and four text labels, none of which
       has its own click behaviour — so routing their events to the row costs
       nothing and removes the possibility of a child intercepting a press or
       failing to inherit the cursor. Without it, only the pixels a child
       happens to cover behave correctly.

    2. `WA_Hover`, so the row participates in Qt's hover tracking and
       `underMouse()`/cursor resolution actually apply over its own pixels.

    The layout margins are kept — they are what makes the row look right — but
    they are no longer able to create dead bands, because the row itself is the
    target everywhere inside its rect.
    """

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.press_count = 0
        self.setObjectName("row_alt" if index % 2 else "row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(ROW_H)
        self.setStyleSheet(
            "background-color: %s;" % ("#2f6f4f" if index % 2 else "#3f5f8f"))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        cover = QLabel()
        cover.setFixedSize(COVER, COVER)
        cover.setStyleSheet("background-color: #1b1b1b;")
        layout.addWidget(cover)

        block = QVBoxLayout()
        block.setSpacing(2)
        block.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title = QLabel(f"Title {index}")
        title.setFixedWidth(134)
        clock = QLabel("1h 23m")
        clock.setFixedWidth(50)
        clock.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(title, stretch=1)
        title_row.addWidget(clock)
        block.addLayout(title_row)

        author_row = QHBoxLayout()
        author_row.setContentsMargins(0, 0, 0, 0)
        author = QLabel(f"Author {index}")
        author.setFixedWidth(86)
        prog = QLabel("0% · 100% | +100%")
        prog.setFixedWidth(98)
        prog.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        author_row.addWidget(author, stretch=1)
        author_row.addWidget(prog)
        block.addLayout(author_row)

        layout.addLayout(block, stretch=1)

        # THE FIX: children never take the mouse, so the row is the target for
        # every pixel of its rect — margins and inter-label gaps included.
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def mousePressEvent(self, event):
        self.press_count += 1
        print(f"    [row {self.index}] press at local y={int(event.position().y())}")


def build(app, n_rows=8, viewport_h=312):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

    # Same container type as the live panels: a plain QWidget with a styled
    # background, so the comparison is not confounded by a different container.
    container = QWidget()
    container.setObjectName("rows_container")
    container.setAttribute(Qt.WA_StyledBackground, True)
    container.setStyleSheet("background-color: #ff0000;")
    lay = QVBoxLayout(container)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    rows = [CleanRow(i) for i in range(n_rows)]
    for r in rows:
        lay.addWidget(r)
    lay.addStretch()

    scroll.setWidget(container)
    scroll.resize(WIDTH, viewport_h)
    scroll.show()
    app.processEvents()
    return scroll, container, rows


def report_geometry(container, rows):
    print(f"container: {container.width()}x{container.height()}")
    prev_bottom = None
    for r in rows:
        top, bot = r.y(), r.y() + r.height() - 1
        gap = "" if prev_bottom is None else f"  gap_above={top - prev_bottom - 1}"
        print(f"  row {r.index}: y={top}..{bot} (h={r.height()}){gap}")
        prev_bottom = bot
    print()

    # Any red visible between rows means a gap; any overlap means a negative gap.
    gaps = [rows[i + 1].y() - (rows[i].y() + rows[i].height())
            for i in range(len(rows) - 1)]
    print(f"inter-row gaps: {set(gaps)}  (must be {{0}} — no gap, no overlap)")
    print()


def sweep_delivery(app, scroll, rows):
    """Deliver a press at every pixel of every row and record who receives it.

    Sampled across the FULL width, not one column — the original investigation's
    single-column sweep sat over the cover label and masked the row's own
    margins entirely, which is how a 4px dead strip read as one pixel.
    """
    viewport = scroll.viewport()
    received = {}
    state = {"key": None}

    def handler_for(name):
        def handler(event):
            received[state["key"]] = name
        return handler

    for r in rows:
        r.mousePressEvent = handler_for(f"row{r.index}")
    container = scroll.widget()
    container.mousePressEvent = handler_for("CONTAINER")

    xs = [8, 30, 70, 130, 200, WIDTH - 12]
    checked = 0
    for r in rows:
        for y in range(r.y(), r.y() + r.height()):
            if y >= viewport.height():
                break
            for x in xs:
                state["key"] = (x, y)
                target = viewport.childAt(QPoint(x, y)) or viewport
                local = target.mapFrom(viewport, QPoint(x, y))
                app.sendEvent(target, QMouseEvent(
                    QMouseEvent.Type.MouseButtonPress, QPointF(local),
                    viewport.mapToGlobal(QPoint(x, y)),
                    Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
                checked += 1

    bad = []
    for (x, y), who in sorted(received.items()):
        owner = next((r for r in rows if r.y() <= y <= r.y() + r.height() - 1), None)
        if owner is not None and who != f"row{owner.index}":
            bad.append((x, y, owner.index, y - owner.y(), who))

    print(f"delivery sweep: {checked} points across {len(xs)} columns")
    if not bad:
        print("  every in-row pixel reached its own row")
    else:
        print(f"  {len(bad)} points did NOT reach their row:")
        for x, y, idx, local, who in bad[:40]:
            print(f"    x={x:3d} y={y:4d}  row {idx} local_y={local:2d} -> {who}")
    print()
    print("NOTE: synthesized events did not reproduce the original defect at all.")
    print("      Use --show and real input to confirm; this sweep only catches")
    print("      gross regressions.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true",
                    help="open a real window for hand testing (authoritative)")
    args = ap.parse_args()
    if args.show:
        os.environ.pop("QT_QPA_PLATFORM", None)

    app = QApplication(sys.argv)
    scroll, container, rows = build(app)
    report_geometry(container, rows)
    if args.show:
        # Live feedback in the window itself. Watching a terminal while trying
        # to hold the pointer on a 2px band is not a usable test, and the
        # offscreen sweep is not trustworthy for this class of bug — it passed
        # on the KNOWN-BROKEN structure. Every press paints its row-local y into
        # the status strip; a press that reaches the CONTAINER instead of a row
        # says so in red, which is exactly the failure being hunted.
        wrapper = QWidget()
        wrapper.setWindowTitle("clean rows — click every band, watch the strip below")
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll)

        status = QLabel("click anywhere in a row — top edge, text, the gap "
                        "between the two lines, bottom edge")
        status.setWordWrap(True)
        status.setStyleSheet(
            "background:#111; color:#ddd; padding:6px; font-family:monospace;")
        status.setMinimumHeight(54)
        outer.addWidget(status)

        def on_row_press(row, event):
            y = int(event.position().y())
            band = ("TOP MARGIN" if y <= 1 else
                    "BOTTOM MARGIN" if y >= ROW_H - 2 else
                    "INTER-LABEL GAP" if 25 <= y <= 26 else "over a label")
            status.setStyleSheet(
                "background:#123; color:#9f9; padding:6px; font-family:monospace;")
            status.setText(f"row {row.index}  local_y={y}  [{band}]  -> reached the ROW")

        for r in rows:
            r.mousePressEvent = (lambda e, _r=r: on_row_press(_r, e))

        def on_container_press(event):
            status.setStyleSheet(
                "background:#311; color:#f99; padding:6px; font-family:monospace;")
            status.setText(
                f"y={int(event.position().y())} -> reached the CONTAINER, not a row "
                f"(this is the bug)")
        container.mousePressEvent = on_container_press

        wrapper.resize(WIDTH + 20, 440)
        wrapper.show()
        sys.exit(app.exec())
    sweep_delivery(app, scroll, rows)


if __name__ == "__main__":
    main()
