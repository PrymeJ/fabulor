# Investigation: restyle-cost depth provenance, and the theme-narrowing "Frankenstein" bug

**Date:** 2026-08-02  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Part 1 complete. Part 2 (base-sheet-only narrowing) disproven as viable in its original form,
superseded by a four-mechanism inventory that reframes the actual defect. No fix implemented yet —
see `review/Investigation_260802_double_fire_reentrancy.md` for the follow-on investigation this
one's live testing surfaced.

---

## Part 1 — Depth provenance: did the tree actually get deeper?

**Question:** the 2026-08-02 root-restyle investigation found `mw.setStyleSheet()` cost scales
with tree DEPTH in a synthetic harness (flat 600 widgets = 11.9ms, deep 600 = 123.3ms). That harness
never established whether the REAL app's tree is deep, or has gotten deeper recently. This answers
that, independent of any cost-narrowing question.

### Method

A standalone probe (`tools/depth_probe.py`) launches the real `MainWindow` (not offscreen-synthetic)
and reports total `mw.findChildren(QWidget)` count, max ancestor-chain depth from `mw` to any leaf,
and per-subtree count/depth for `settings_panel`, `stats_panel`, `book_detail_panel`,
`library_panel`, `sidebar`. Run via `git worktree` against three historical checkpoints plus current
HEAD, so the same code runs unmodified at each point (adapted only where a file didn't exist yet —
`main_window_builders.py` postdates checkpoint A, confirmed not to affect the measurement since the
probe reads `mw.<attr>` regardless of which file constructs it).

Checkpoints: **A** (`b2482c2`, 2026-06-02, start of the 2-month window) → **B** (`5ba3816`,
2026-06-11, immediately before the StreakGrid commit — the single largest widget-adding commit found
in the window) → **C** (`6002e4d`, 2026-06-11, immediately after it) → **D** (current HEAD,
2026-08-02).

### Results

| checkpoint | date | total widgets | overall max depth | `stats_panel` widgets | `stats_panel` own max depth |
|---|---|---|---|---|---|
| A | 06-02 | 606 | 11 | 166 | 10 |
| B | 06-11 | 606 | 11 | 169 | 10 |
| C | 06-11 | 611 | 11 | 174 | 10 |
| D (now) | 08-02 | 632 | 11 | 177 | 10 |

### Finding: depth has NOT changed. Count grew modestly; depth is flat.

**Overall max depth is 11 at every single checkpoint, including before the StreakGrid commit that
added two new `QWidget` subclasses (`StreakGrid`, `TasselOverlay`) to `stats_panel`.**
`stats_panel`'s own max depth is 10 at every checkpoint too. Widget count grew 606→632 (+4.3%
overall, +6.6% for `stats_panel` alone) — real but modest, and entirely uncorrelated with the depth
number, which never moved.

This is not the tidy narrative the investigating task expected ("depth grew, here's when"). It
raises a genuinely open question instead: **if depth hasn't changed in two months, and cost
(measured elsewhere in this investigation) is dominated by depth, then whatever made the restyle
cost feel worse recently is not tree-depth growth.** Candidates not ruled in or out here: the
~4-6% widget-count growth alone (contradicts the earlier synthetic-harness framing that count
"doesn't matter" — it may matter at the margin, just not as the dominant factor); something
unrelated to the widget tree's static shape entirely (the run-to-run drift documented elsewhere,
2026-08-01/02, is real and unexplained); or the *feeling* of it getting worse being driven by usage
pattern (more panels open more often) rather than the code changing at all.

**Stated plainly, per the task's own instruction: this investigation cannot explain why the restyle
cost feels worse now than historically remembered, only that it isn't tree-depth growth.** No
narrative is forced onto this beyond what's measured.

### Consistency check against the earlier "cost tracks visibility, not depth alone" finding

The 2026-08-01/02 investigation's closed/heavy-panels-shown/hidden test (527ms closed → 643ms with
four heavy panels shown → 516ms hidden again, all at an identical 632-widget count) is **consistent**
with this result, not contradicted by it: that test held widget count and tree SHAPE constant and
varied only what was currently visible/mapped, and found a real cost swing from visibility alone.
This investigation shows tree shape itself hasn't changed in two months. The two findings compose
cleanly: depth is a static property of the current tree (unchanged since June), visibility is a
dynamic property that swings the cost independently of it. Neither explains the other; both are real.

### Worktrees

Created and removed cleanly (`git worktree add`/`remove --force`) for checkpoints A/B/C;
`tools/depth_probe.py` copied into each rather than symlinked, so it ran unmodified, standalone
Python with no dependency on code that postdates the checkpoint.

---

## Part 2 — Base-sheet-only narrowing on hover-out/snapback: DISPROVEN, and a deeper bug found

**Original proposal (Pryme):** during hover-out/snapback/gutter-dismiss, apply only
`mw.setStyleSheet(get_base_stylesheet(theme))` instead of the full `_apply_stylesheets` pipeline,
since an EARLIER isolated offscreen test (same-session, prior investigation) measured base-alone at
~585ms against a ~615ms full pipeline — suggesting panel restyling was a small, skippable slice.

### The patch

`_on_theme_unhovered` was temporarily short-circuited to call `mw.setStyleSheet(get_base_stylesheet(...))`
directly and return, bypassing `_on_theme_changed` entirely for this one trigger. `snap_theme_forward`
needed no edit — with `_on_theme_unhovered` never reaching `_on_theme_changed`, it never populates
`_pending_fade_call`, so `snap_theme_forward`'s drain naturally becomes a no-op on this path.
Confirmed via full-repo grep that `_on_theme_unhovered` has exactly one call site
(`panels.py:1382`, inside `_close_settings_flow` — the gutter-dismiss path) plus the swatch-leave
path, both of which funnel through the one patched method.

### Finding 1 — narrowing did NOT reduce the perceived cost

Live, on-screen (not offscreen), 74 samples across the test session:
`min=426.1ms  median=534.5ms  max=618.2ms`. Statistically indistinguishable from the ~585ms isolated
base-sheet-alone measurement from the prior session, and barely below the ~615ms full pipeline. **The
base sheet was never the cheap part being skipped past — it IS ~95% of the cost.** Skipping the
remaining panel-restyle steps (~30ms) saved almost nothing perceptible. This directly disproves the
premise the proposal was built on; the disproof came from the isolated offscreen test in the prior
session, and this live test confirms it holds on-screen too.

### Finding 2 — the patch produces a real, live-observed "Frankenstein" visual bug

Reported live by Pryme with two screenshots: after hovering multiple themes and letting them
revert, panels showed pieces of **three different themes simultaneously** — main window/overall
slider correctly reverted to the active theme; Sleep-timer preset grid buttons stuck on a stale
theme's red; transport buttons and panel buttons stuck on a hovered theme's blue, never reverting.
Explicitly distinguished by Pryme as "the problem is upstream... but it doesn't mean the downstream
is correct either" — two separate things, not one.

Traced to source, not guessed:

- **Blue (transport/panel buttons):** `content_container`'s stylesheet, via `get_player_stylesheet`
  — which owns a generic `QPushButton:hover` rule (themes.py:3263) — is applied at
  `theme_manager.py:1532`, inside `_apply_stylesheets`'s fast pass, entirely separate from
  `get_base_stylesheet`. The patched `_on_theme_unhovered` never reaches this line. **This is the
  one component of the FAST pass (which normally runs on every hover, patched or not) that the
  narrowing incorrectly dropped.**
- **Red (Sleep preset grid):** `sleep_timer.py`'s `update_panel_styling()` sets **per-instance**
  `setStyleSheet()` directly on each preset button (a colour ramp, `preset_ramp_rgb`), explicitly
  overriding the panel-level QSS (comment at sleep_timer.py:179: "wins over the panel-level
  QPushButton:hover/:pressed QSS"). This method is called only from `sync_all_settings_visuals`
  (`settings_controller.py:176-177`), which is bound to `MainWindow._refresh_panel_visuals`
  (`settings_controller.py:27`), which is called only from the two `theme_applied`/deferred-flush
  sites — **both already gated `if not hover:`** (theme_manager.py:705 and the
  `_flush_deferred_restyle_now` call chain). So on STOCK code, this call never fires during a hover
  preview at all, and only fires on a genuine non-hover apply (rotation/select/cover-switch/snapback)
  — meaning stock code's snapback DOES correctly refresh it. The patch broke this specifically
  because it makes snapback (`hover=False`) skip this call too, when stock code wouldn't.

### Finding 3 — full mechanism inventory (built to answer this properly, not guessed)

Confirmed against source, not assumed from names, all 68 app-wide `setStyleSheet()` call sites
classified:

**A. Fast pass (`_apply_stylesheets`) — runs on every apply, hover or not:**
`mw` (base sheet) → `title_bar` → `content_container` (player sheet — **owns the transport-button
hover rule**) → icon retint → `sidebar` → `settings_panel`/`speed_panel`/`sleep_panel` (shared panel
QSS, visibility-gated since `7f5ea40`).

**B. Deferred pass (`_apply_stylesheets_deferred`) — `if not hover:` gated:**
`library_panel`, `stats_panel`/`book_detail_panel`, `tags_panel`.

**C. TAIL (`theme_applied` signal + `_refresh_panel_visuals`) — same `if not hover:` gate as B:**
`stats_panel.on_theme_changed`, `tags_panel.on_theme_changed`, `book_detail_panel.on_theme_changed`
(chains to `cover_panel.on_theme_changed`) — all confirmed-safe signal receivers, matching the
2026-07-20 theme-reach audit's own "confirmed safe" finding for this shape — **plus
`sleep_timer.update_panel_styling()` and `speed_controls.update_visuals()`, which are NOT signal
receivers: they are hand-rolled, per-instance `setStyleSheet()` bypasses that happen to be reached
through the same TAIL call, not through the dispatcher's stylesheet functions at all.**

**Architectural finding, not previously documented:** C4/C5 (`sleep_timer`/`speed_controls`) are two
independently-written implementations of the identical pattern — a per-button colour ramp that must
override panel-level QSS, each with its own comment acknowledging the other exists
("same shape as the sleep panel's time-preset ramp", speed_controls.py:263). Both bypass every
`get_*_stylesheet` function in `themes.py` entirely. They are not currently broken on stock main
(the `if not hover:` gate protects them correctly) — they were only exposed as stale by the
experimental patch skipping their one trigger path. Recorded here as a real, pre-existing
architectural wart independent of the narrowing question: two hand-maintained duplicates of one
mechanism, invisible to `themes.py`'s otherwise-centralized stylesheet-function model.

### Conclusion

The narrowing-for-speed premise (Part 2 as originally scoped) is dead: base-alone costs the same as
the full pipeline, live-confirmed. What the test surfaced instead is more valuable — a precise map
of which of the ~6 independent theme-coloring mechanisms are (correctly) hover-gated versus which
are (also correctly, on stock code) part of the always-runs-on-hover fast pass, and confirmation
that `content_container`/`get_player_stylesheet` belongs in the latter category. Any future
narrowing attempt must preserve mechanism A in full; only B/C are hover-skippable, and they already
are, by design, on stock code.

### What this investigation is NOT

Not a fix. Not a recommendation to ship base-only narrowing in any form — it's disproven on cost
grounds alone, independent of the correctness bug it also produced. The experimental patch and its
temporary probes were reverted after this write-up (see the follow-on double-fire investigation for
what was found live while testing it, and confirmation the revert holds before that investigation
began).
