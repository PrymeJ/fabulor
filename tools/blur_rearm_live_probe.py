"""Live reproduction attempt for the transport-bar blur's declined-tick
re-arm path (transport_bar_blur.py: refresh_dirty's hover/cooldown gates and
_rearm_after_decline/_fire_rearm).

Investigation only — no fix, no assertion of correctness beyond reporting
what actually happened. ac87e0a ("re-arm a blur-refresh tick declined by the
hover or cooldown gate") shipped this fix unit-pinned but explicitly marked
"not live-verified" in its own commit message. This script drives the real,
on-screen app (NOT offscreen — the standing rule is that offscreen harnesses
cannot see compositing defects in this area) through the exact stranding path
described in that commit and in TODO.md's 2026-07-20 entry:

  1. Open Settings (arms the blur overlay via show_for_panel).
  2. Hover a theme swatch that is DIFFERENT from the currently-applied theme,
     long enough for the hover preview to actually apply (so
     _is_hover_active=True and a dirty repaint is pending).
  3. While hover is active, force a tracked-widget repaint (so refresh_dirty
     runs and hits the hover gate -> declines -> _rearm_after_decline arms a
     retry) -- done by directly calling refresh_dirty() after confirming the
     hover gate is live, mirroring what a real repaint would trigger.
  4. Un-hover BEFORE ever letting the hover's own preview genuinely apply a
     new resolved color that differs from the committed theme -- i.e.
     reproduce the specific "declined tick, then a same-theme no-op snapback"
     case the commit describes: hover a theme, then immediately re-hover the
     SAME committed theme (or call _on_theme_unhovered when the preview never
     diverged), so _on_theme_changed's no-op guard fires on the snapback and
     no _apply_stylesheets/Paint event follows.
  5. Watch whether _rearm_pending/_fire_rearm actually fires the retry
     (~450ms later) and whether the overlay pixmap changes as a result, or
     whether the overlay is left holding a stale pixmap forever.

Run with a real platform plugin:
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/blur_rearm_live_probe.py
"""
import sys, os, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer


def main():
    app = QApplication(sys.argv)
    from fabulor.app import MainWindow

    mw = MainWindow()
    mw.show()

    tm = mw.theme_manager
    pm = mw.panel_manager
    blur = pm._transport_bar_blur

    log = []

    def report(msg):
        print(msg)
        log.append(msg)

    def step1_open_settings():
        report("=" * 70)
        report(f"STEP 1: open Settings panel "
               f"overlay_or_committed={pm.is_overlay_open_or_committed()} "
               f"settings_visible_before={pm.settings_panel.isVisible()}")
        pm._open_settings_flow()
        report(f"STEP 1b: settings_visible_after_call={pm.settings_panel.isVisible()} "
               f"anim_state={pm.settings_panel_animation.state()}")

    def step2_check_blur_armed():
        active = blur._active if blur else None
        report(f"STEP 2: blur overlay active={active} "
               f"settings_visible={pm.settings_panel.isVisible()} "
               f"anim_state={pm.settings_panel_animation.state()} "
               f"bounding_rect={getattr(blur, '_bounding_rect', None)}")
        if not active:
            report("blur not armed yet -- waiting longer")
            QTimer.singleShot(1000, step2b_recheck)
            return
        QTimer.singleShot(600, step3_hover_other_theme)

    def step2b_recheck():
        active = blur._active if blur else None
        report(f"STEP 2b (recheck): blur overlay active={active} "
               f"settings_visible={pm.settings_panel.isVisible()} "
               f"anim_state={pm.settings_panel_animation.state()}")
        if not active:
            report("ABORT: blur overlay never armed -- cannot proceed with repro")
            QTimer.singleShot(500, app.quit)
            return
        QTimer.singleShot(600, step3_hover_other_theme)

    committed_before = None

    def step3_hover_other_theme():
        nonlocal committed_before
        committed_before = tm._current_theme_name
        # pick any theme different from the committed one
        import fabulor.themes as themes_mod
        all_names = list(themes_mod.THEMES.keys())
        other = next(n for n in all_names if n != committed_before)
        report(f"STEP 3: committed theme={committed_before!r}, hovering {other!r}")
        tm._on_theme_hovered(other)
        QTimer.singleShot(300, lambda: step4_check_hover_state(other))

    def step4_check_hover_state(other):
        report(f"STEP 4: _is_hover_active={tm._is_hover_active} "
               f"_active_display_theme_internal={getattr(tm, '_active_display_theme_internal', None)!r}")
        # Force a refresh_dirty tick while hover is active -- this is the
        # decline path (hover gate) that must arm a re-arm retry.
        rearm_before = blur._rearm_pending
        blur._tracker.take_dirty_union() if blur._tracker else None
        # Manually mark something dirty by touching the tracker's union so
        # refresh_dirty has something to decline (mirrors a genuine repaint).
        if blur._tracker is not None:
            blur._tracker._dirty_union = blur._bounding_rect
        blur.refresh_dirty()
        rearm_after = blur._rearm_pending
        report(f"STEP 4b: refresh_dirty() called while hover active -- "
               f"_rearm_pending {rearm_before} -> {rearm_after}")
        overlay_pixmap_before = blur._overlay.pixmap()
        report(f"STEP 4c: overlay pixmap isNull={overlay_pixmap_before.isNull() if overlay_pixmap_before else True}")
        QTimer.singleShot(200, lambda: step5_unhover_same_theme(other))

    def step5_unhover_same_theme(other):
        # Reproduce the exact "no-op snapback" case: un-hover back to the
        # SAME committed theme that was active before hovering. Since the
        # hover preview may have already applied 'other' as the live display,
        # the snapback via _on_theme_unhovered should restore committed_before.
        # The critical case per the commit is when the DECLINED tick's target
        # theme never became the applied one -- i.e. the snapback is a genuine
        # duplicate of the state already on screen.
        report(f"STEP 5: un-hovering (should snap back to {committed_before!r})")
        last_apply_before = getattr(tm, '_last_apply_stylesheets_at', None)
        tm._on_theme_unhovered()
        last_apply_after = getattr(tm, '_last_apply_stylesheets_at', None)
        report(f"STEP 5b: _last_apply_stylesheets_at changed: "
               f"{last_apply_before} -> {last_apply_after} "
               f"(unchanged means the no-op guard fired, no _apply_stylesheets ran)")
        report(f"STEP 5c: _rearm_pending={blur._rearm_pending}")
        QTimer.singleShot(700, step6_check_rearm_fired)

    def step6_check_rearm_fired():
        report(f"STEP 6 (~700ms later, past _DECLINE_REARM_MS=450): "
               f"_rearm_pending={blur._rearm_pending}")
        overlay_pixmap_after = blur._overlay.pixmap()
        report(f"STEP 6b: overlay pixmap isNull={overlay_pixmap_after.isNull() if overlay_pixmap_after else True} "
               f"active={blur._active}")
        report("=" * 70)
        report("If _rearm_pending is False here (having been True at step 5c) "
               "and no crash/hang occurred, the re-arm mechanism fired its "
               "retry as designed. Check the app log for "
               "'[TIMER-TRACE] refresh_dirty tick=' lines with "
               "reason=hover_active_gate followed by a later COMPOSITED or a "
               "second decline, to see the actual retried tick's outcome.")
        QTimer.singleShot(500, lambda: step7_close_and_quit())

    def step7_close_and_quit():
        report("STEP 7: closing settings panel")
        pm._close_settings_flow()
        QTimer.singleShot(500, app.quit)

    QTimer.singleShot(800, step1_open_settings)
    QTimer.singleShot(2000, step2_check_blur_armed)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
