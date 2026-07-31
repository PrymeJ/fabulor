"""Standalone repro for the Stats/Tags row hit-test seam (2026-07-31).

WHY THIS EXISTS: in the live app, some pixels inside a visually contiguous row
are delivered to the rows CONTAINER rather than to the row, so a click there
does nothing and the cursor stays the plain arrow. Hunting those pixels by hand
biases the sample — every manual click landed on one particular boundary, which
made the defect look like "the last pixel of a row" when the user's screenshots
plainly showed dead spots at two different vertical positions.

This harness rebuilds the same structure with the same widget types and sweeps
EVERY pixel programmatically, so the dead set is measured rather than inferred.

Run:  python tools/row_hittest_harness.py            # offscreen sweep, prints a map
      python tools/row_hittest_harness.py --show     # visible window for live poking

It deliberately mirrors BookDayRow's real construction: a QHBoxLayout with
(4,2,4,2) margins and 6px spacing, a fixed 48x48 QLabel cover, and a nested
QVBoxLayout holding two QHBoxLayouts of labels. The container uses
setSpacing(0) with a (0,2,0,0) top inset, exactly as _day_rows_layout does.
"""
import argparse
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

ROW_H = 52
COVER = 48


class HarnessRow(QWidget):
    """Same shape as BookDayRow: styled background, hand cursor, nested layouts."""

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("row_alt" if index % 2 else "row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "background-color: %s;" % ("#2f6f4f" if index % 2 else "#3f5f8f"))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        cover = QLabel()
        cover.setFixedSize(COVER, COVER)
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

    def mousePressEvent(self, event):
        print(f"    [row {self.index}] press at local y={int(event.position().y())}")


def build(app, n_rows=8, width=252, viewport_h=312, with_tracker=False):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

    container = QWidget()
    container.setAttribute(Qt.WA_StyledBackground, True)
    container.setStyleSheet("background-color: #ff0000;")
    lay = QVBoxLayout(container)
    lay.setContentsMargins(0, 2, 0, 0)
    lay.setSpacing(0)

    rows = [HarnessRow(i) for i in range(n_rows)]
    for r in rows:
        lay.addWidget(r)
    lay.addStretch()

    scroll.setWidget(container)
    scroll.resize(width, viewport_h)
    scroll.show()
    app.processEvents()

    # The live panels attach a ScrollHoverTracker, which installs an
    # application-wide event filter and turns on mouse tracking for the
    # container and viewport. That is the newest thing in this area and the most
    # likely candidate for a difference the plain structure does not explain, so
    # it is switchable rather than assumed absent.
    tracker = None
    if with_tracker:
        from fabulor.ui.hover_tracker import ScrollHoverTracker
        tracker = ScrollHoverTracker(scroll, lambda: rows)
    return scroll, container, rows, tracker


def sweep_delivery(app, scroll, container, rows):
    """Sweep by DELIVERING a real press at each y and seeing who receives it.

    This is the measurement that matters. Live, `childAt()` returned the row for
    the dead pixel too — it was event DELIVERY that went to the container
    instead. A childAt-based sweep therefore agrees with geometry everywhere and
    proves nothing about the defect.
    """
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    received = {}

    def make_handler(name):
        def handler(event):
            received[sweep_delivery.current_y] = name
        return handler

    for r in rows:
        r.mousePressEvent = make_handler(f"row{r.index}")
    container.mousePressEvent = make_handler("CONTAINER")

    viewport = scroll.viewport()
    x = container.width() // 2
    max_y = rows[-1].y() + rows[-1].height()
    for y in range(0, min(max_y, viewport.height())):
        sweep_delivery.current_y = y
        # Deliver exactly as the window system would: hand the press to the
        # viewport and let Qt route it, rather than picking a target ourselves.
        target = viewport.childAt(QPoint(x, y)) or viewport
        local = target.mapFrom(viewport, QPoint(x, y))
        app.sendEvent(target, QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, QPointF(local),
            viewport.mapToGlobal(QPoint(x, y)),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

    print("Delivery sweep — pixels inside a row's rect that did NOT reach that row:")
    bad = []
    for y, who in sorted(received.items()):
        expected = next((r for r in rows if r.y() <= y <= r.y() + r.height() - 1), None)
        if expected is not None and who != f"row{expected.index}":
            bad.append((y, expected.index, y - expected.y(), who))
    if not bad:
        print("  (none — every in-row pixel reached its row)")
    else:
        for y, idx, local, who in bad:
            print(f"  y={y:4d}  row {idx}  local_y={local:2d}  -> {who}")
    print()


def sweep(container, rows):
    """For every y, report which widget owns the pixel: a row, or the container."""
    print(f"container: {container.width()}x{container.height()}")
    for i, r in enumerate(rows):
        print(f"  row {i}: y={r.y()}..{r.y() + r.height() - 1} (h={r.height()})")
    print()

    x = container.width() // 2
    dead, owned = [], {}
    max_y = rows[-1].y() + rows[-1].height()
    for y in range(0, max_y + 2):
        child = container.childAt(QPoint(x, y))
        row = None
        node = child
        while node is not None and node is not container:
            if isinstance(node, HarnessRow):
                row = node
                break
            node = node.parentWidget()
        expected = next((r for r in rows if r.y() <= y <= r.y() + r.height() - 1), None)
        if expected is not None and row is not expected:
            dead.append((y, expected.index, y - expected.y()))
        owned[y] = row.index if row is not None else None

    print("Pixels inside a row's rect that childAt() does NOT resolve to that row:")
    if not dead:
        print("  (none — childAt agrees with geometry everywhere)")
    else:
        for y, idx, local in dead:
            print(f"  y={y:4d}  row {idx}  local_y={local}")
    print()
    print("Ownership map (y -> row index, '.' = container):")
    line = ""
    for y in range(0, max_y + 2):
        v = owned[y]
        line += "." if v is None else str(v % 10)
        if len(line) >= 100:
            print("  " + line)
            line = ""
    if line:
        print("  " + line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true",
                    help="open a real window instead of sweeping offscreen")
    ap.add_argument("--tracker", action="store_true",
                    help="attach ScrollHoverTracker, as the live panels do")
    args = ap.parse_args()
    if args.show:
        os.environ.pop("QT_QPA_PLATFORM", None)

    app = QApplication(sys.argv)
    scroll, container, rows, tracker = build(app, with_tracker=args.tracker)
    print(f"ScrollHoverTracker attached: {tracker is not None}\n")
    if args.show:
        # Same live status strip as harness2, so the two windows can be compared
        # directly by hand. This one is the KNOWN-BROKEN structure: presses in
        # the row's margins and the inter-label gap should reach the CONTAINER.
        from PySide6.QtWidgets import QLabel as _QLabel
        wrapper = QWidget()
        wrapper.setWindowTitle("BROKEN rows — expect container hits in the bands")
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll)
        status = _QLabel("click the top edge, the gap between the two text "
                         "lines, and the bottom edge of a row")
        status.setWordWrap(True)
        status.setMinimumHeight(54)
        status.setStyleSheet(
            "background:#111; color:#ddd; padding:6px; font-family:monospace;")
        outer.addWidget(status)

        def on_row_press(row, event):
            y = int(event.position().y())
            status.setStyleSheet(
                "background:#123; color:#9f9; padding:6px; font-family:monospace;")
            status.setText(f"row {row.index}  local_y={y}  -> reached the ROW")

        for r in rows:
            r.mousePressEvent = (lambda e, _r=r: on_row_press(_r, e))

        def on_container_press(event):
            status.setStyleSheet(
                "background:#311; color:#f99; padding:6px; font-family:monospace;")
            status.setText(
                f"y={int(event.position().y())} -> reached the CONTAINER, not a row")
        container.mousePressEvent = on_container_press

        wrapper.resize(272, 440)
        wrapper.show()
        sys.exit(app.exec())
    sweep(container, rows)
    sweep_delivery(app, scroll, container, rows)


if __name__ == "__main__":
    main()
