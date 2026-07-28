#!/usr/bin/env python3
"""Standalone click-delivery test with a synthetic load — no Fabulor code in the path.

WHY (2026-07-28). Across three surfaces in Fabulor (theme swatches, sidebar
right-click, VS Code's editor by the user's own observation) presses appear to go
missing before the app sees them. Ruled out by measurement so far: blur, animation
guards, hit-testing, widget state, preview-fade duration.

Then this tool's IDLE baseline came back 100/100 — zero loss on a bare widget with
the same mouse. So the input stack and the hardware are NOT the cause, and something
about the application's own state is a precondition.

The two things Fabulor does that an idle widget does not:

  RESTYLE   a synchronous ~143ms setStyleSheet on the top-level window, which Fabulor
            runs on every hover preview (measured: mw.setStyleSheet(base)=143ms of a
            ~223ms total restyle)
  ANIMATE   continuous QPropertyAnimation work (panel slides, blur tweens, a 200ms
            UI timer)

Both are toggleable here so the failing condition can be reproduced OUTSIDE Fabulor.
If presses go missing only with RESTYLE on, that is the mechanism — and it would
explain every affected surface, including VS Code's editor, without anything in
Fabulor being at fault.

PROTOCOL
  1. Baseline: both toggles OFF. Click a counted number (30+). Expect an exact match.
  2. RESTYLE on. Same count, same pace. Compare.
  3. ANIMATE on, RESTYLE off. Same again.
  4. Both on.

Counters are per-press (deduplicated), so APP and WIDGET are directly comparable.

Usage:  python tools/click_test.py
"""
import sys
import time

from PySide6.QtCore import Qt, QEvent, QPropertyAnimation, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QGraphicsBlurEffect, QLabel,
                               QVBoxLayout, QWidget)

RESTYLE_MS = 0.143   # measured: Fabulor's mw.setStyleSheet(base) cost


class ClickPad(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Click delivery test")
        self.resize(560, 560)

        self.w_left = self.w_right = 0
        self.f_left = self.f_right = 0
        self._seen = set()          # dedupe: one count per physical press
        self._press_times = []
        self._restyle_n = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)

        title = QLabel("Click anywhere in this window")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("", 13, QFont.Bold))
        lay.addWidget(title)

        self.counts = QLabel()
        self.counts.setAlignment(Qt.AlignCenter)
        self.counts.setFont(QFont("monospace", 15))
        lay.addWidget(self.counts, 1)

        self.rate = QLabel()
        self.rate.setAlignment(Qt.AlignCenter)
        self.rate.setFont(QFont("monospace", 10))
        lay.addWidget(self.rate)

        self.cb_restyle = QCheckBox(
            f"RESTYLE — blocking {RESTYLE_MS * 1000:.0f}ms setStyleSheet, 3x/sec")
        self.cb_animate = QCheckBox("ANIMATE — continuous blur tween + 200ms timer")
        for cb in (self.cb_restyle, self.cb_animate):
            cb.setFocusPolicy(Qt.NoFocus)      # keep keyboard on the pad
            lay.addWidget(cb)

        hint = QLabel("R = reset counters   ·   Q = quit\n"
                      "Compare TOTAL against how many times you actually clicked.")
        hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint)

        # Synthetic load ------------------------------------------------------
        self._blur = QGraphicsBlurEffect()
        self._blur.setBlurRadius(0.0)
        self.counts.setGraphicsEffect(self._blur)
        self._anim = QPropertyAnimation(self._blur, b"blurRadius")
        self._anim.setDuration(1500)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(8.0)
        self._anim.finished.connect(self._bounce_anim)

        self._load_timer = QTimer(self)
        self._load_timer.setInterval(333)
        self._load_timer.timeout.connect(self._do_restyle)
        self._load_timer.start()

        self._tick = QTimer(self)
        self._tick.setInterval(200)
        self._tick.timeout.connect(lambda: None)

        self.cb_animate.toggled.connect(self._set_animate)
        self._refresh()

    # -- synthetic load ------------------------------------------------------
    def _do_restyle(self):
        """Block the main thread the way Fabulor's restyle does."""
        if not self.cb_restyle.isChecked():
            return
        end = time.perf_counter() + RESTYLE_MS
        while time.perf_counter() < end:
            self._restyle_n += 1
            self.setStyleSheet(
                f"QLabel {{ color: #{self._restyle_n % 0xFFFFFF:06x}; }}")

    def _set_animate(self, on):
        if on:
            self._anim.start()
            self._tick.start()
        else:
            self._anim.stop()
            self._tick.stop()
            self._blur.setBlurRadius(0.0)

    def _bounce_anim(self):
        if self.cb_animate.isChecked():
            self._anim.setDirection(
                QPropertyAnimation.Backward
                if self._anim.direction() == QPropertyAnimation.Forward
                else QPropertyAnimation.Forward)
            self._anim.start()

    # -- counting ------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.w_left += 1
        elif event.button() == Qt.RightButton:
            self.w_right += 1
        self._press_times.append(time.perf_counter())
        self._refresh()

    def note_filter_press(self, event):
        # Dedupe by timestamp: Qt propagates one press through several objects, and
        # counting each would inflate the APP column (it read 236 for 100 clicks in
        # the first version of this tool — a bug in the probe, not a finding).
        key = int(event.timestamp())
        if key in self._seen:
            return
        self._seen.add(key)
        if event.button() == Qt.LeftButton:
            self.f_left += 1
        elif event.button() == Qt.RightButton:
            self.f_right += 1
        self._refresh()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_R:
            self.w_left = self.w_right = self.f_left = self.f_right = 0
            self._seen.clear()
            self._press_times.clear()
            self._refresh()
        elif event.key() == Qt.Key_Q:
            self.close()

    def _refresh(self):
        load = []
        if self.cb_restyle.isChecked():
            load.append("RESTYLE")
        if self.cb_animate.isChecked():
            load.append("ANIMATE")
        self.counts.setText(
            f"           APP   WIDGET\n"
            f"  LEFT  {self.f_left:5d} {self.w_left:8d}\n"
            f"  RIGHT {self.f_right:5d} {self.w_right:8d}\n"
            f"  TOTAL {self.f_left + self.f_right:5d} "
            f"{self.w_left + self.w_right:8d}\n\n"
            f"  load: {' + '.join(load) if load else 'none (idle baseline)'}"
        )
        t = self._press_times
        if len(t) >= 2:
            g = [(t[i] - t[i - 1]) * 1000 for i in range(1, len(t))]
            self.rate.setText(f"inter-click gap: min {min(g):.0f}ms  "
                              f"median {sorted(g)[len(g) // 2]:.0f}ms  max {max(g):.0f}ms")


class PressFilter(QWidget):
    def __init__(self, pad):
        super().__init__()
        self.pad = pad

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            try:
                self.pad.note_filter_press(event)
            except (AttributeError, RuntimeError):
                pass
        return False


def main():
    app = QApplication(sys.argv)
    pad = ClickPad()
    app.installEventFilter(PressFilter(pad))
    pad.show()
    pad.setFocus()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
