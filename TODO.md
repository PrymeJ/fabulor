# TODO

Deferred work — short, dated, status-tracked entries. Not for root-cause writeups (those go in
NOTES.md) or session logs (SESSION.md). When an entry is started, move it under "In Progress" with
the date; when done, delete it (the commit/SESSION.md entry is the permanent record).

Closed/fixed/superseded entries live in [TODO_ARCHIVE.md](TODO_ARCHIVE.md), not here — this file is
open/pending work only, grouped by topic (not by date) with a summary index below.

## Summary index

### General app jank — traced to system/KWin level, NOT Fabulor's own code; two concrete leads, neither pursued yet
- [2026-09-25] Continuation of the "General app sluggishness investigation" (below) and the
  two-month bisect that found the same jank at a commit predating any of this session's own
  changes. See NOTES.md, "General jank investigation, continued," for the full trail. Confirmed
  via THREE independent methods, all outside Fabulor's own process: two real screen recordings
  (with and without VS Code open — ruled out VS Code contention a second time) showing real,
  extracted per-frame gaps (32-38 stutters >100ms per ~90s recording); GPU frequency sampling
  showing the Intel iGPU never leaves its floor frequency even during active jank (rules out
  render/compute saturation); and real kernel-level `trace-cmd`/ftrace captures (a genuine system
  package install + root access, confirmed with Pryme first) showing the same gap pattern via i915
  driver plane-update events, with scheduler data proving Fabulor and KWin both get scheduled
  normally during the gaps (rules out simple CPU starvation).
  - **Two concrete, real, previously-unknown system-level leads found by checking `dmesg`/
    `journalctl` directly**: (1) a single kernel warning inside the i915 driver's own timer code
    (`hrtimer_forward`, `timer->is_queued` assertion, fired once this session — too rare alone to
    be the main cause); (2) **the more promising one** — KWin's own compositor logging `Failed to
    create an offscreen framebuffer` (preceded by a `GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT` /
    `glTexStorage2D` error), recurring 16 times across one session in irregular bursts, a pattern
    shape consistent with genuinely intermittent jank. This is KWin itself failing to allocate a
    GPU render target — plausibly for a blur effect — which this app leans on heavily.
  - **Not yet started, concrete next steps**: search for this exact KWin error against known
    KDE/Mesa/i915-Optimus bug reports; check KWin's Effects debug-console tab for which effect is
    active when it fires; test whether disabling KWin's own (system-level, not Fabulor's) blur
    effect changes the error's frequency; consider the Mesa/i915 driver version and this laptop's
    specific Optimus/PRIME setup (Dell Inspiron 7577, Intel HD 630 + NVIDIA GTX 1060 Mobile) as a
    real variable. This is genuinely a system/distro-level question now, not an application one —
    any fix here would not be a Fabulor code change.
  - Also see: `trace-cmd` is now installed on this machine (`sudo zypper install trace-cmd`) —
    available for reuse without a re-install next time this angle is picked up.
  - **[2026-09-25] GPU-offload angle closed for good, with a real mechanism**: tried forcing
    Fabulor onto the NVIDIA GPU (both Wayland and, after Pryme logged into an X11 session
    specifically to get a working offload path, X11 too — `xrandr --listproviders` confirmed a
    real NVIDIA offload sink, `glxinfo` and Fabulor's own process both genuinely loaded the NVIDIA
    GLX stack). GPU utilization stayed flat 0%/7MiB across 30 samples at 0.3s intervals with a book
    playing and a panel open. Root cause: Fabulor has **zero `QOpenGLWidget` usage anywhere** — it's
    entirely Qt software/CPU raster painting, and the blur effect (`_blur_pixmap`,
    `transport_bar_blur.py`) is `QGraphicsBlurEffect` via an offscreen `QGraphicsScene`, CPU-side,
    not a GPU shader. mpv is `vo='null'` (no video output — audiobook player) so there's nothing on
    that side either. **This was independently found once before, months earlier, in an unrelated
    Claude 4.6 session investigating Library panel sliding** — same conclusion, same "CPU-only,
    GPU can't help" answer. Now recorded as a standing CLAUDE.md Debugging-discipline rule so a
    third GPU-offload investigation doesn't happen. Full trace: NOTES.md, two entries dated
    2026-09-25 ("Tried forcing Fabulor onto the NVIDIA GPU..." and the follow-up X11/mpv-vo=null
    correction).
  - **[2026-09-25] Sharper characterization of the jank itself, from Pryme directly**: "somewhat
    sporadic... sometimes I get a smooth run for a minute, then it is janky again, or I get mixed
    result with two very smooth slides, then three janky ones." Confirms a consistent severity
    ranking across panels: **Stats always worst, Library best, Tags in between.** **Caveat, Pryme's
    own words, not glossed over**: "I am testing the app on one machine, one desktop environment.
    That's a problem but I can't do anything about it" — every finding in this whole thread
    (GPU-offload, KWin leads, kernel trace, this severity ranking) is single-machine/single-DE
    evidence only, real but not confirmed to generalize.
  - **[2026-09-25] RETRACTED — the original theory here (widget-tree complexity → paint cost)
    was tested and is WRONG; the real signal is somewhere else, now identified precisely.**
    `_wire_paint_probe` (extended with a `from=` context, see the fix commit) was pointed at real
    Book Detail opens from all three sources: paint cost is statistically IDENTICAL across
    Library/Stats/Tags (avg 5.82/5.82/6.11ms, Library and Stats literally tied) — this flatly does
    not track the reported ranking and rules out "Stats' widgets are expensive to paint" entirely.
    **The real signal is in frame-delivery timing, not paint cost** — `_wire_timing_probe`'s
    existing `max_frame_gap`/`jank_frame_rate` data from the SAME test session (n=337/421/354,
    much larger sample) shows the reported ranking cleanly on three independent metrics:
    avg max_frame_gap 40.0/49.3/58.3ms and jank_frame_rate 44.8/51.0/55.4% for library/tags/stats
    respectively, with Stats' single worst frame gap (349.3ms) more than double either other
    panel's worst.
  - **[2026-09-25] Three further candidates checked, ALL ruled out or inapplicable — this is now
    a harder question than "which piece of Stats' own code does more work."** (1) Event-filter
    dispatch cost (`StatsPanel.eventFilter`, `TagManagerWidget.eventFilter`,
    `hover_tracker.py`'s trackers, via a new `_wire_event_filter_cost_probe`): real numbers, but
    Tags' cost (avg 61.9ms, driven by `GridHoverTracker`) is 7x Stats' (8.8ms) — the OPPOSITE of
    what would explain Tags being less janky than Stats. Ruled out. (2) `TasselOverlay`'s ~30fps
    sway timer: ruled out architecturally, no live test even needed — it's parented inside the
    Timeline tab's own page (`stats_panel.py:4027`, `_build_time_tab`), so `QTabWidget` hides it
    (stopping the timer via `hideEvent`) whenever Day/Week/Month is active — and Book Detail can
    only open from clicking a book row, which only exists on Day/Week/Month. Structurally cannot
    overlap. (3) Every other Stats-owned `QTimer` checked: `_kbdnav_hover_poll` (60ms) is gated on
    keyboard nav having been used, inactive during the mouse-driven test samples so far;
    `_scroll_active_timer` is single-shot and scroll-triggered, not continuous; the shared 200ms
    `ui_timer` has exactly one panel-specific branch in its whole sync path and it's for LIBRARY
    (`library_panel.update_current_book_progress()`), not Stats — if anything this would
    disadvantage Library's own slide, the opposite of the reported ranking. **Not yet considered**:
    whether Stats' widget tree DEPTH itself (Qt event-propagation/geometry overhead from more
    nested widgets, independent of what any widget's paint/filter code actually does) could produce
    this pattern — a different mechanism than anything checked, not yet designed or tested. Also
    still not checked: whether the ranking holds with playback OFF (all samples so far had a book
    playing — would help isolate `transport_bar_blur`'s per-tick re-grab cost as a confound).
  - **[2026-09-25] Fourth measurement layer — Qt's own event-dispatch volume/cost (new
    `_wire_event_dispatch_probe`, real `installEventFilter`, all event types not just paint):
    real signal, PARTIAL match, not a full explanation.** On OPEN specifically (had to separate
    from CLOSE — the two are wildly different in cost and averaging them together was hiding this
    initially), Stats is confirmed clearly worst on every metric: avg 696 events/8.07ms dispatch
    cost/477 watched widgets, vs. Library's 416/5.99ms/282 and Tags' 235/4.42ms/162 — the first
    real, measured confirmation that Stats' widget tree genuinely is larger and genuinely does
    cost more to dispatch events to. **But Library costs MORE than Tags here (5.99ms vs
    4.42ms) — the OPPOSITE order from the frame-gap data**, where Library was the BEST/least
    janky panel. So this metric correctly flags Stats as worst but gets Library-vs-Tags backwards.
    On CLOSE, dispatch cost is flat/cheap across all three (all under 1ms) — not a factor there at
    all, though Stats still shows structurally more watched widgets (a snapshot property, not
    active work).
  - **Honest state after four measurement layers**: paint cost (ruled out — identical across all
    three), event-filter dispatch cost (ruled out — inverted from the ranking), Stats-owned timers
    (ruled out or inapplicable), and Qt event-dispatch volume (partial match — correctly flags
    Stats, wrong on Library-vs-Tags). None of these four IS the full explanation. The severity
    ranking itself remains solid on frame-gap timing (`max_frame_gap`/`jank_frame_rate`), but
    nothing checked so far has been shown to actually BE what that timing measures — only
    correlated-or-not with it. **A genuinely different angle, not yet tried**: whether the
    `valueChanged` signal's own delivery timing (what frame-gap timing measures) is itself
    delayed by something upstream of both paint and generic event dispatch — e.g. GPU/compositor
    round-trip cost specific to Stats' larger backdrop-frost/blur composite area, which is a
    precedented mechanism in this codebase (see `covers_opaquely()`'s docstring in `stats_panel.py`
    — a real, already-measured compositor-cost difference tied to the Timeline tab's own opaque
    background, just for a different tab/reason than this investigation). Not yet designed or
    tested for the Book Detail slide specifically.
    Full numbers and reasoning across all four checks: NOTES.md, entries titled "Severity ranking
    now measured, not just felt," "Event-filter dispatch cost ALSO ruled out," "TasselOverlay's
    ~30fps sway timer ruled out by architecture," and "Qt event-dispatch volume confirms Stats'
    tree is genuinely larger... but does NOT fully explain the ranking."
  - **[2026-09-25] Fifth measurement layer, and the strongest evidence yet — a real kernel trace
    at the i915 compositor level (outside Fabulor's process entirely), confirming the ranking is
    real at the layer that actually reaches the screen.** `trace-cmd` capture of
    `i915:intel_plane_update_arm`/`_noarm` events, split into a Library-opens block (06:56:44-
    06:57:20) and a Stats-opens block (06:57:20-06:57:44), confirmed by Pryme directly. Library:
    1701 events, avg gap 20.8ms, worst gap 216.5ms. Stats: 903 events, avg gap 27.2ms, **worst gap
    482.9ms** (more than double Library's worst). Median gap nearly identical (16.6ms vs 16.7ms) —
    the difference concentrates in the worst-case tail, matching the "sometimes smooth, sometimes
    janky" bursty character reported earlier, not a constant slowdown. Normalized >100ms-gap rate
    is closer (1.58/s vs 1.75/s, ~11% higher for Stats) than the raw average/worst-case numbers —
    reported honestly, not cherry-picked. **This is real ground truth, not just another correlated
    signal**: it's the GPU/compositor's own frame-commit events, unfakeable by anything in
    Fabulor's Python process. Confirms the ranking exists at the layer downstream of everything
    checked so far, without yet explaining WHY frames arrive later for Stats specifically.
  - **[2026-09-25] Attempted, hit a real boundary — NOT completed, and the earlier "16 times"
    count is corrected to 115.** A session switch (Wayland↔X11, for the NVIDIA offload testing)
    triggered a full reboot, so the kernel trace above (this boot, started 06:50:14) and the KWin
    offscreen-framebuffer errors (previous boot, `-b -1`) sit in different journal scopes and
    can't be directly timestamp-correlated. Re-counting on the correct boot: **115** occurrences,
    not 16 — 21 under `kwin_wayland` (the session this investigation is scoped to), 94 under
    `kwin_x11` (the brief NVIDIA-testing session, not yet normalized by duration). Real bug, both
    backends, count previously undercounted for an unknown reason. Full detail: NOTES.md, "Cross-
    referencing the kernel trace against KWin's offscreen-framebuffer errors hit a real boundary."
  - **[2026-09-25] One real same-boot hit found (07:19:01, kwin_wayland), but two trace attempts
    (a 60s targeted one, a 15-min opportunistic one 07:26-07:41) both missed overlapping it —
    genuinely a timing/luck problem given the error's irregular recurrence, not a method flaw.**
    `/tmp/fabulor_correlate_trace.dat` (the 15-min attempt) preserved but unused, no matching error
    inside its window. Full detail: NOTES.md, "First real same-boot KWin offscreen-framebuffer
    hit..."
  - **[2026-09-25] CLOSED — overlap finally achieved (4th attempt, a 30-min trace), correlation
    checked properly, and the result is negative.** 8 KWin errors landed inside a 30-min trace
    window (14:04-14:34). A naive first pass (error windows vs. whole-trace percentiles) looked
    suggestive but was a methodological trap — redone against a matched random-window baseline
    from the SAME trace, KWin-error windows (mean 147.1ms max plane-update gap) are
    indistinguishable from ordinary moments (baseline mean 150.9ms, median 181.3ms). **The KWin
    offscreen-framebuffer error does not correlate with compositor-level plane-update stalls.**
    Combined with the earlier finding that it fires with Fabulor not even running, this rules out
    the KWin bug as the mechanism behind the Stats > Tags > Library severity ranking. This
    sub-investigation is closed — no further kernel-trace/KWin-error correlation attempts planned.
    The severity ranking itself (established via 5 other measurement layers, above) stands
    unexplained at the mechanism level; whatever causes it is not this. Full detail: NOTES.md,
    "KWin offscreen-framebuffer / kernel-trace correlation attempt CONCLUDED".

### Transport-bar blur got visibly stuck in the background — one-off, not reproducible, cause unknown
- [2026-09-23] Pryme's own report, verbatim: "I was trying to open Settings or the Library, my
  finger slipped and I pressed right click too fast by mistake. Blur got stuck in the background. I
  can't reproduce it again as I don't know how it happened exactly. A race for sure." Screenshot
  showed the transport bar/cover area frozen with an old blurred frame composited behind the live
  UI, inconsistent with the panel actually open at the time. Surfaced during the same session as the
  general-sluggishness investigation (see the entry below) but is a DIFFERENT kind of symptom — a
  genuine stuck/stale visual state, not felt jank — and is being tracked separately rather than
  folded into that inconclusive investigation.
  - **Not something to chase by reading code and guessing.** Per CLAUDE.md's own standing rule
    ("never substitute a plausible explanation for a checked one") and this exact file's history
    with `transport_bar_blur.py` (a documented, previously-fragile area — see the "Hover-flicker"/
    grab-feedback-loop entries already in NOTES.md), a fix attempted without first reproducing the
    actual mechanism would be exactly the kind of unverified patch this codebase has been burned by
    before. Pryme's own framing: log it, don't attempt a fix without knowing the mechanism.
  - **The actual TODO item: build a synthetic rapid-click stress harness**, not a fix. Needs a
    script (or an in-app diagnostic mode) that fires rapid right-click/panel-open events at
    load-boundary moments — right before, during, and right after a panel's slide animation starts/
    finishes, right before/after `frost_panel_backdrop`'s one-shot grab fires, right at a book-switch
    boundary — specifically trying to catch a race between two panel-open requests or a grab firing
    against a half-torn-down panel state. `is_overlay_open_or_committed()` (`panels.py`) is
    supposed to prevent exactly this class of double-open race (see CLAUDE.md's "DO NOT add an
    overlay-open path that skips `is_overlay_open_or_committed()`" rule) — if a real repro is found,
    check whether it's a gap in that gate specifically, or something in `transport_bar_blur.py`'s
    own hide/show/grab sequence racing against a panel teardown that the gate doesn't cover.
  - No repro yet. Do not schedule fix work until one exists.

### General app sluggishness — intermittent stutter, cause NOT found despite four measurement approaches and a two-month bisect
- [2026-09-22/23] Superseded both of this section's prior entries ("Transport-bar blur's
  `_grab_and_blur` occasionally spikes..." and "Book Detail open cost — confirmed dominated by
  app-wide eventFilter overhead...") — both were provisional leads from mid-investigation that did
  NOT hold up once tested directly against Pryme's live verdicts. Full trace, all four measurement
  attempts, and the six-commit bisect: **NOTES.md, "General app sluggishness investigation"
  (2026-09-22/23)**.
  - Symptom, Pryme's own precise description: intermittent VISUAL STUTTER/JANK during panel-open/
    close slides — explicitly not overall duration, not input lag, not general unresponsiveness.
  - Four different measurements were tried (wall-clock panel-open duration; per-frame
    `QPropertyAnimation.valueChanged` tick-gap; own-process CPU% via `os.times()`; external
    `kwin_wayland`-vs-Fabulor compositor-load sampling) — **every one failed to correlate with a
    live verdict**, including one case where the SINGLE WORST measured frame-gap in a batch was on
    the one book Pryme rated smoothest.
  - A `git worktree`-isolated bisect spanning six commits from tonight back to 2026-07-19 (the last
    commit before the transport-bar blur system existed at all) found the SAME qualitative
    "sometimes smooth, sometimes janky, Stats-worse-than-Tags" pattern at every point tested,
    including the oldest, pre-blur one — arguing against a discrete code regression as the
    explanation. Pryme's own call ending the bisect: "if 7-19 is confusing rather than clean all
    around, that is telling by itself. We won't get anywhere by bisecting further."
  - **The `event.type()` caching fix** (`MainWindow.eventFilter`/`BookDetailPanel.eventFilter`,
    `app.py`/`book_detail_panel.py`) and the `valueChanged`/CPU%/loadavg additions to
    `install_panel_timing_probe` (`panels.py`) both shipped this session regardless — real,
    tested, harmless improvements that survive the investigation's inconclusive outcome, but
    neither explained the symptom.
  - **Genuinely open, not yet investigated**: whether the intermittency correlates with something
    outside every measurement tried (thermal throttling, background I/O, other desktop processes,
    though a structured test with other apps closed still showed "janky everywhere"); whether a
    fundamentally different measurement layer (real screen-capture frame timing, a GPU/compositor
    trace tool external to both Fabulor and Qt) would see something none of tonight's four
    Qt/process-level probes could; whether Pryme's own perception/attention to the issue has
    changed independent of the app's actual behavior (raised, never resolved). Do not re-run any of
    the four failed measurement approaches expecting a different result without new information —
    see NOTES.md for exactly what each one showed.

### Book Detail slide paint-suppression — mechanism landed on its own branch; the real A/B answer is "source, not mode"
- [2026-09-23/24, commits `c640885`, `991d71c`] `PanelManager._wire_slide_paint_suppression`
  (`panels.py`) suppresses Book Detail's per-frame slide repaint cost via a static-pixmap proxy —
  full mechanism, four live-found regressions and their fixes in **NOTES.md, "Book Detail slide
  paint-suppression"**. `[FROST-DEBUG]` diagnostic logging was TEMPORARY and has since been
  removed (see the same session's later commits). The progress-bar-area exclusion decision
  (RESOLVED, not a gap) is unchanged.
- [2026-09-24/25] **The follow-up A/B test is done — see NOTES.md, "Book Detail backdrop-mode A/B
  test."** A real harness (`tools/book_detail_backdrop_ab_test.py`) drove the real app via real
  simulated input across 3 backdrop modes × 3 open-sources, 540 total clean cycles across a
  heavy-load and a cold-idle pass. **Conclusion: backdrop mode barely moves wall-clock time.**
  What DOES move it, consistently, in every mode and under every load condition tested, is which
  panel Book Detail opens FROM: **Stats-sourced opens run ~50-150ms slower than Library- or
  Tags-sourced opens** — this is the exact original report that started the whole investigation
  ("Book details panel opens slower in Stats"), now independently confirmed with real numbers by
  a test built to answer a different question. The earlier "jankier over the 84-book dummy tag"
  observation (below) is superseded by this — it was never really about tag SIZE, it tracks
  which PANEL Book Detail opened from.
  - A small cProfile-enabled diagnostic pass (27 opens, `FABULOR_BOOKDETAIL_PROFILE=1`) found
    Frosty/Opaque and Transparent are slow over Stats for two DIFFERENT reasons, not a
    contradiction (a real correction happened mid-investigation — see NOTES.md for the full
    trace): Frosty/Opaque pay extra `_grab_and_blur` cost compositing through Stats' own
    already-active `visual_area` blur (a documented, existing architectural cost — see
    `_book_detail_frost_rect`'s own docstring); Transparent pays real, unsuppressed live-paint
    cost from Stats' own heavier widget tree. Both point at the same root: **Stats' own panel
    architecture costs more to render than Library's or Tags' does**, independent of backdrop
    mode.
  - [2026-09-25] **Root cause found — see NOTES.md, "Why Stats-sourced Book Detail opens cost
    more."** `StatsRowDelegate.paint()` was checked and ruled out (real but small — fresh
    `QFont`/`QFontMetrics` construction per row, 0.031s/24 calls, not the dominant cost). The
    real mechanism: `StatsPanel.eventFilter` and `hover_tracker.py`'s `ScrollHoverTracker`/
    `GridHoverTracker` both install via `QApplication.instance().installEventFilter(self)`
    (app-wide) rather than scoped to their own widget the way `LibraryPanel` does
    (`self._list_view.viewport().installEventFilter(self)`) — and because Book Detail occludes
    rather than hides its underlay, Stats' `hideEvent` never fires while Book Detail is open, so
    its app-wide filter stays fully installed and taxes EVERY event anywhere in the app for the
    panel's whole open duration. **Correction (2026-09-25): Stats installs exactly ONE app-wide
    filter of its own (`StatsPanel.eventFilter`), not two — `StatsRowListView` never uses
    `hover_tracker.py` at all, confirmed by grep. Tags installs two (`TagManagerWidget`'s own +
    whichever `hover_tracker` class is active). Stats' single filter still outpaces Tags' two
    combined in raw call volume, so filter COUNT alone doesn't explain the full cost ordering —
    see NOTES.md for the corrected picture.**
  - [2026-09-25, commit `e55fdb6`] **SHIPPED**: the same occlusion-guard shape already proven for
    Tags (early-return in `eventFilter` when `book_detail_panel.isVisible()`), applied to
    `StatsPanel.eventFilter`. Risk traced first (the filter's only job — dismissing the "Reset all
    stats" 7s confirmation — already has an independent hard-timeout `QTimer`, so silencing it
    while occluded can't strand anything). Verified with two independent full 270-cycle A/B runs:
    **Stats-sourced Book Detail opens are consistently faster** — ~51-58ms in Transparent mode,
    ~18-21ms in Frosty/Opaque, reproduced closely across both runs. See NOTES.md, "`StatsPanel.
    eventFilter` occlusion guard shipped," for full numbers and the honest caveat: the same two
    runs ALSO showed Library/Tags (a code path this guard never touches) consistently slower by a
    similar margin, with no confirmed cause found (thermal/memory/competing-process all ruled
    out) — kept the guard anyway per Pryme's own call, since it can't logically cause a slowdown
    in code it doesn't touch.
  - **[2026-09-25] Upgraded from "open question" to confirmed, higher-priority, still-open bug —
    this is not just a Book-Detail-open-cost theory anymore.** A live bisect (see NOTES.md,
    "General app sluggishness: live bisect finds a real, precisely-dated regression") pinned
    `hover_tracker.py`'s `ScrollHoverTracker`/`GridHoverTracker` as the exact cause of a real,
    felt Playback-smoothness regression — not confined to Tags or Book Detail. Origin commit
    `a4e3d65` (2026-07-31): both trackers are constructed in `TagManagerWidget._build_ui()`
    (called once from `__init__`, i.e. app startup) and each installed a PERMANENT app-wide
    `QApplication.instance().installEventFilter(self)` with no removal, walking every Qt event
    anywhere in the app — including plain Playback interactions with zero relation to Tags —
    for the whole session, whether or not Tags was ever opened. `4fecc29` (2026-09-22) paired
    `install_filter()`/`remove_filter()` to `showEvent`/`hideEvent`, live-confirmed as a real,
    large improvement ("definitely better than bad 07-31"). **But the fix pairs to
    show/hide, not occlusion** — same gap `e55fdb6` already fixed for `StatsPanel.eventFilter`
    specifically, never applied here. Book Detail occludes rather than hides Tags, so with Tags
    open behind Book Detail, both trackers' filters stay live. This plausibly explains a real,
    smaller residual Pryme reported at the 09-22 checkpoint ("slightly worse than good 07-31 —
    subtle").
  - **[2026-09-25] SHIPPED**: occlusion guard applied to `ScrollHoverTracker.eventFilter`/
    `GridHoverTracker.eventFilter` (`hover_tracker.py`), mirroring `e55fdb6` exactly — both
    reach `book_detail_panel` via `self.parent().window()` (these are `QObject`s, not
    `QWidget`s, so `.parent()` reaches the owning `TagManagerWidget` first, mirroring that
    file's own existing `self.window().book_detail_panel` lookup). 707/707 tests pass, no
    regressions. **Also a real, important confound surfaced and checked before shipping** (see
    NOTES.md for full detail): the historical bisect that pinned `a4e3d65` ran every "old"
    build on TODAY's kernel/Mesa, never the version actually live at that commit's date.
    Checked `/var/log/zypp/history*` directly — openSUSE Tumbleweed kernel updated ~13 times
    and Mesa-libGL1 updated on a similar cadence between June and now, with real version bumps
    landing on 07-30 (one day before the pinned regression), 08-02, 08-05, and 08-14 (all
    inside or adjacent to the bisect's own window). The code-level bug is real and now fixed
    regardless, but system drift cannot be ruled out as ALSO contributing to the felt
    slowdown. Live-tested post-fix: "Playback opens normally... possible [improvement]... still
    not perfectly smooth" — the expected, honest result given the confound, not a sign the fix
    failed. No further action planned on this specific thread unless new evidence reopens it.
  - **[2026-09-25] Tags > Stats > Library Book Detail jank ordering QUANTIFIED and root-caused
    at the mechanism level — genuinely understood now, but NOT closed.** 21 real, live-logged
    Book Detail opens (via the existing `_wire_timing_probe`/`_wire_event_filter_cost_probe`
    instrumentation, reading `platformdirs.user_log_dir("fabulor")`'s `fabulor.log` directly —
    NOT stdout, which the app never writes to): Library avg jank ratio 0.39/82% CPU, Stats
    0.66/99% CPU, Tags 0.82/103% CPU. Matches Pryme's very first report of the whole night.
    Isolated benchmark (`QApplication.sendEvent` through a bare `QObject.eventFilter`, no probe,
    no guard): **~2.3µs/event with zero app-wide filters installed vs. ~17.35µs/event with one**
    — a ~15µs marginal cost per installed app-wide filter, PER EVENT, that is fixed PySide6/Qt
    C++↔Python marshalling overhead, paid regardless of what the filter's Python body does.
    Library has zero app-wide filters active; Stats has one (occlusion-guarded); Tags has up to
    TWO simultaneously (`TagManagerWidget.eventFilter` + one hover tracker, both
    occlusion-guarded this session) — each independently taxing every one of the hundreds of
    app-wide events that fire during a single panel slide. This is why the occlusion guard above
    helps (each filter is cheap once occluded) but cannot close the gap to Library (Qt still
    dispatches to every installed filter at all, guard or no guard). **Not started, and not a
    small follow-up**: closing this further needs either a hover-tracking mechanism that doesn't
    require an app-wide filter at all (the module's own `hover_tracker.py` docstring already
    records that the obvious narrower-scope alternative — viewport/scroll-area level — was tried
    and confirmed NOT to work, since row/cell events land on the rows themselves, not any
    ancestor a narrower filter could watch), or reducing how many app-wide filters can be live at
    once (would need checking against every live-reported bug each filter currently fixes — Tab/
    Backtab interception, click-outside detection, keyboard handling — before removing any of
    them). Full measurement detail in NOTES.md.
  - **[2026-09-25] Correction, same night, caught by Pryme directly: the mechanism above explains
    only the TAGS-specific escalation, not the original Stats-vs-Library gap.** Pryme: "we had
    these issues, especially the book details slowness, before these filters were implemented
    though" — correct. This session's own earlier bisect data (`6002e4d`, 2026-06-11, seven
    weeks before `a4e3d65`/the hover trackers existed) already had Pryme reporting Book Detail
    "just as bad as today when opened from the Stats, but better from the Library and the Tags"
    — Tags was BETTER than Stats at that point, the opposite of tonight's ordering. The real
    fit for the ORIGINAL gap: `StatsPanel.eventFilter` (a separate, Stats-specific app-wide
    filter, unrelated to the hover trackers) was introduced by `8257546` at 01:41 on the SAME
    day as the `6002e4d` build tested (confirmed via `git merge-base --is-ancestor`, i.e.
    already present in that build) — plausibly the real, seven-week-older cause of Stats being
    worse than Library, independent of anything shipped tonight. The hover trackers (07-31) are
    a separate, later effect that pushed TAGS specifically from better-than-Stats to worse than
    both — not a restatement of the same cause. `StatsPanel.eventFilter`'s own real per-call cost
    (as opposed to the generic ~15µs synthetic-filter benchmark above) has not been separately
    measured. Full correction in NOTES.md.
  - **[2026-09-25] Third correction, same night: a controlled retest shows "Tags worst" itself
    doesn't hold up.** Extended `_book_detail_probe_context()` (`panels.py`) to log open/close
    direction and, for Tags, the exact tag name + live book count, then had Pryme redo the test
    deliberately varying tag size (3/4/19/84 books). Isolated to opens only: Library still
    clearly best (0.56 jank ratio), but Stats (0.64 jank, 102.6% CPU) vs. Tags (0.76 jank, 98.0%
    CPU) now DISAGREE across metrics — jank ratio says Tags worse, CPU% says Stats worse. Worse
    for the size theory: Tags' jank ratio does NOT scale with book count at all (3 books = 0.84
    jank, the WORST; 19 books = 0.69, the BEST; 84 books = 0.78, in between) — directly confirms
    Pryme's own observation that grid size isn't what's driving Tags' variance. **Standing
    conclusion, honestly: Library is reliably best; Stats-vs-Tags cannot currently be ordered
    with confidence; tag size is ruled out as Tags' variance driver.** Not yet identified: the
    actual driver of Tags' open-to-open variance. 707/707 tests pass after the probe extension.
    Full data and analysis in NOTES.md.

### Library List mode and Timeline/Streak view are janky at EVERY tested historical checkpoint — no bisectable regression exists
- [2026-09-25] During the same-session Playback bisect (see the entry above and NOTES.md), both
  were checked incidentally at nearly every checkpoint tested, back to the earliest practical
  points: Library List mode janky as far back as `4700b31`/`21ac097`/`0658e58` (all 2026-07-28
  through 07-31); Timeline/Streak janky as far back as StreakGrid's own FIRST commit (`6002e4d`,
  2026-06-11 — "still worse [than Heatmap]... could be slightly better than today, but hard to
  say"). **Neither has a "before" state to bisect against — they read as janky at every point
  tested, including the very first commit that made the feature exist at all.** This rules out a
  recent regression as the explanation for either. Two honest possibilities, not distinguished
  yet: (1) this is simply the inherent/structural cost of what each does (List mode paints many
  more visible rows without thumbnails competing for a different paint budget than the other
  Library modes; StreakGrid paints 364 cells vs. HourlyHeatmap's much smaller 14x24 grid — a
  real, likely unavoidable size difference), or (2) both have carried a real inefficiency since
  their very first implementation that was simply never fast to begin with, rather than having
  regressed. **Git bisection cannot distinguish between these two** — the tool only finds
  boundaries, and there isn't one here. The tractable next step, if this is picked up again, is
  the same live-instrumentation approach used for Book Detail above (`_wire_paint_probe`-style
  probes wired to Library's/Stats' own panel-open animations) to get an absolute cost number for
  each, rather than another round of relative-to-history comparison.

### Book Detail panel's tab bar — not wired into the shared `_kbdnav_active_panel_key` mechanism
- [2026-09-15, scope corrected 2026-09-17] Still true and unrelated to the (now implemented, see
  TODO_ARCHIVE.md) tag chip grid navigation: Book Detail's own tab bar was never wired into the
  shared `_kbdnav_active_panel_key` mechanism (`MainWindow`) the way
  Settings/Speed/Sleep/Sprint/Stats were, so it gets no `kbdnav` property or arrow-key handler for
  switching tabs by arrow key specifically (Left/Right via `keyPressEvent`'s own `_cycle_tab`
  still works today, just not through the shared mechanism) — cosmetic/consistency gap, not a
  functional block. Small enough to fold into whatever next touches this file's keyboard
  handling, rather than warranting its own dedicated pass.

### Small visual/cosmetic bugs (batch logged 2026-09-17, mostly not yet reproduced in detail)
- [2026-09-17] Restart button has jagged edges — visual, minor. Not yet investigated.
- [2026-09-17] No-cover-art placeholder's "author - title" text: font, style, and position need a
  visual pass — flagged VISUAL, MAJOR (the strongest severity in this batch). Not yet scoped
  further than "needs a look."
- [2026-09-17] FIXED — no-cover-art placeholder showed the literal text "None - Book Title" instead
  of blank/just-the-title when a book's author field was empty. `app.py:3602`'s `metadata_label`
  text built `f"{book.author} - {book.title}"` with no guard for `book.author` being `None`, unlike
  every other author-display site in the codebase (`library.py`, which uses `book.author or ""`
  throughout). Pryme's own note when logging this: "BUG no author - none > just blank. I am not
  sure what I meant when I wrote this. I'll wipe author and title fields to check" — found and
  fixed from the code alone before he could reproduce it live; matches his description exactly.
  Fixed to fall back to just the title (no dangling " - ") when author is empty.

### Cover/metadata scan gaps (batch logged 2026-09-17, need reproduction)
- [2026-09-17, SEQUENCED behind the ID refactor 2026-09-18] POSSIBLE BUG, needs repro: changing a
  book's cover image file outside the app is not reflected in the library after a rescan — only
  after a full app restart. Suggests the cover cache (`_cover_cache`/`_sized_cover_cache`, see
  CLAUDE.md's cover-caching rules) isn't being invalidated on a rescan-detected cover change, only
  ever read fresh at process start. Needs a live repro (change a cover file, rescan, observe) before
  diagnosing further. **Deliberately deferred until after the content-hash book-identity refactor
  (see the folder-move item below) lands, Pryme's own call, 2026-09-18: the cache is keyed by
  `book_id`, and any fix here needs to reliably tell "same book, cover file changed" apart from
  "different book, coincidentally same path" — exactly the identity ambiguity the ID refactor
  exists to resolve. Fixing this first risks either a narrow patch that gets thrown away once the
  refactor lands, or accidentally reinforcing more path-keyed logic that then has to be unwound.**
- [2026-09-17, ESCALATED to BLOCKING 2026-09-18] BUG: moving a book's folder to a different path is
  not picked up by the scanner — the book has to be manually deleted from the library and rescanned
  from the new location. **Confirmed live by Pryme (2026-09-18): tags and listening sessions do NOT
  survive that manual delete-and-rescan — real data loss on an ordinary user action (reorganizing
  folders), not just an inconvenience.** Planned fix direction (Pryme's own call, 2026-09-18): move
  the library's identity model from path-keyed to an ID based on a content hash, so a book is
  recognized as the same book after a folder move/rename regardless of its current path. This is a
  large refactor — path is currently the identity key threaded through `books`/`book_tags`/
  `listening_sessions`/`book_events`/`book_covers`/`book_files`, the scanner's `known_paths` dedup,
  every soft-delete flag (`is_deleted`/`is_excluded`/`is_missing`), and the stats queries' `book_id`
  vs. `book_path` dual-write pattern (see CLAUDE.md's "DO NOT join `book_events` directly..." and
  the soft-delete-flags section) — touches most of `db.py` and `library/scanner.py`. Needs its own
  dedicated design/implementation session, not a quick patch. **Reminder for whoever picks this up:
  the "cover image changed outside the app" item directly above this one was deliberately sequenced
  to follow this refactor rather than being fixed independently — once book identity survives a
  path change, revisit that item as a natural, much simpler follow-up.**
- [2026-09-17] TEST, minor: add a deliberately corrupted image file as a book's cover and confirm
  the app handles it gracefully (no crash, some sane fallback) rather than assuming it does. Not a
  known bug — a gap in test coverage to close.

### Carousel/blur edge cases around book removal (batch logged 2026-09-17, need reproduction)
- [2026-09-17] BUG, visual, minor, needs repro: the no-book carousel's blur shows half-static/
  half-scrolling when the currently-active book is deleted. Also check what happens if that book's
  path is later rescanned (does the carousel recover cleanly, or does the stale-half persist).
  Possibly related to the already-tracked "Garbled backdrop after excluding the playing book from
  Book Detail" entry (see "Blur grab hide/show side effects" above) — that entry's own symptom
  (frosted region half-stale, half-live after excluding the playing book) sounds similar enough
  that these may be the same underlying issue reached via a different removal path (deleted outright
  vs. excluded from Book Detail); check for overlap before treating as fully separate.

### VT missing-file handling — design already covers most of this (see "VT / seek / progress tracking")
- [2026-09-17] Pryme's own restated version of the already-designed-but-unimplemented VT
  missing-file handling: count and compare audio files before loading, show a sticky banner on
  discovery, enter no-book mode, offer to rescan-and-rebuild or remove. This matches the existing
  "VT missing-file handling — consolidated design" entry's three parts almost exactly (load-time
  count comparison, sticky banner with Dismiss/Rescan actions, unload-on-discovery) — see that
  entry (VT / seek / progress tracking, and its fuller Pending write-up) rather than duplicating a
  second design here. Logged as a pointer, not a new entry, so the existing design stays the single
  source of truth for this feature.

### Not-yet-decided small features (batch logged 2026-09-17)
- [2026-09-17] Play button on the Book Detail panel — feature, minor, not decided whether/how to add
  it. No design yet (where it goes, what it does that the main transport doesn't already cover from
  outside the panel).
- [2026-09-17] Custom mouse pointers — feature, visual, minor. No design yet.
- [2026-09-17] A fourth theme-shuffle mode that updates the theme pool based on the current book's
  cover colors (distinct from the existing "Cover art based theme" Off/With pool/Exclusive modes,
  which apply the cover's colors directly rather than using them to pick pool members) — feature,
  visual, minor, not decided.
- [2026-09-17] Hide the Themes-tab interval row entirely when only one theme is selected in the
  pool (an interval is meaningless with nothing to rotate to) — feature, visual, minor, not decided.
- [2026-09-17] If the longest streak is also the currently-active streak, remove the outline and
  show the cells bare (today the longest run always gets a border via `streak_grid_outline`,
  computed in `StreakGrid._compute_longest_run`/rendered around `stats_panel.py:3645`, regardless of
  whether it's still ongoing) — feature, visual, minor, not decided. Would need a way to tell
  "longest run" and "currently active run" apart in that rendering path, which doesn't exist today.
- [2026-09-17] Volume slider color steps based on the current volume level (e.g. color shifts as
  volume increases) — feature, visual, minor, not decided.
- [2026-09-17] Series information in Book Detail, after the Year field — feature, QOL, not decided.
  Library has the horizontal space; Book Detail's Year field is fixed-width and short enough that it
  works invisibly-until-populated, but Series would face the same "empty most of the time" problem
  without an obvious place to hide when unused. Needs feasibility/layout thinking before deciding,
  not just a yes/no.

### Keyboard/mouse focus quality-of-life gaps (batch logged 2026-09-17)
- [2026-09-17] In Book Detail's metadata edit mode, if the Year or Narrator field is empty, it can't
  be tabbed/arrowed to directly — another field has to be clicked first before keyboard navigation
  can reach the empty one. QOL, minor. Not yet traced to a specific mechanism (candidate: an empty
  field's edit-mode widget may not be constructed/shown until some other field interaction triggers
  it — needs checking against `_cycle_metadata_field`/`_enter_edit_mode` in `book_detail_panel.py`).

### Theme-pass-adjacent items (batch logged 2026-09-17 — group with the eventual full theme pass)
- [2026-09-17] Add an optional per-theme dict key providing two colors for the Speed/Sleep/Sprint
  grid ramp buttons, to be done BEFORE the full theme pass (not after) since it changes what that
  pass will actually be tuning. Relates to the existing "Some themes need a preset-ramp colour
  override" entry (Theme color/data) — check whether this generalizes that entry's fix (a per-theme
  ramp-endpoint override) rather than being a separate mechanism; if so, fold together rather than
  building two overlapping override systems.
- [2026-09-17] Check ramp-button-vs-label text contrast specifically when a cover-based theme is
  selected (not just the fixed theme palette) — to be done BEFORE the full theme pass. Pryme's own
  example: book cover "2666" produces a low-contrast case. Needs automated testing across a range of
  real covers, not just the one example, to find the actual worst cases before designing a fix.
- [2026-09-17] Book Detail's session-history row colors are wrong when a cover-based theme is
  selected — they need to be derived from the theme's background colors rather than using whatever
  they currently use, which apparently doesn't account for the cover-theme case. To be done AFTER
  the same row colors are manually fixed for all the FIXED (non-cover-based) themes first, not
  before — per Pryme, the derivation formula should be reverse-engineered by analyzing the
  already-correct fixed-theme values once those exist, not designed from scratch. Blocked on that
  manual fixed-theme pass landing first.

### Tags panel: count display and widget-per-row architecture
- [2026-09-17] FEAT + possible refactor: show "N/50 tags" at the top right of the tag list, and when
  the list is already at 50 and the user tries to add another, show a real notification in addition
  to the existing red-field-edge indication. Pryme's own architectural flag, confirmed by reading
  the source: both the tag list (`TagManagerWidget`'s `_tag_list_container`, a `QVBoxLayout` of
  individual row widgets inside a scroll area) and the per-tag book grid (`_TagBookThumb`/
  `_TagBookGrid`) are widget-per-item, not a model/delegate pair — the same shape Stats used to have
  before its 2026-08-05/09 migration to `StatsRowModel`/`StatsRowDelegate` for exactly this kind of
  scaling concern. Raising the 50-tag cap (a real possibility this feature invites people to ask
  for) would multiply that cost. Before implementing the count display itself (cheap, no
  architecture question): check the feasibility of migrating Tags to the same model/delegate
  pattern Stats already proved out, as its own scoped investigation — don't let the display feature
  quietly justify or block on a full rewrite without that being a deliberate decision.

### Listening Sprint backward-seek compensation doesn't net forward+backward excursions
- [2026-08-11] The pure tick-to-tick `_last_known_pos` diff in `SprintPanel.update_sprint_state`
  can't tell a genuine rewind from "seeked forward then came back" — seeking forward 20 minutes then
  back to the same spot on a 10-minute sprint currently inflates it to ~30 minutes, since the diff
  has no memory of the position before the forward jump. Needs the detector to track more than one
  prior sample (e.g. a high-water mark, or the position at each direction change) rather than a
  single previous-tick value. Deliberately shipped gated behind a config toggle
  (`sprint_backward_seek_compensation`, default Off) rather than fixed — see NOTES.md 2026-08-11 for
  the full mechanism and the earlier (already-fixed) wall-clock/audio-position unit-mismatch bug in
  the same feature.

### Right-click / theme-restyle performance
- [2026-08-02] Theme-apply ordering/deferral proposed for book-switch flow stutter (cover-theme on) — directional (A→B stutters, B→A doesn't), root cause not instrumented yet
- [2026-08-02] **ROOT CAUSE FOUND:** ANY `mw.setStyleSheet()` call costs **~436ms live** (offscreen harness reads ~25% high) regardless of argument — full sheet, 1 rule, identical string, and EMPTY string all measure the same; Qt does not no-op an identical sheet and clearing is not cheaper. Cost tracks VISIBILITY (~22% higher with the four heavy panels shown, at identical widget count). **(A), (E) and (F) are all now dead** — splitting the sheet saves nothing, emptying the root saves nothing (the 8ms figure was a measurement error), and E's guard sites fire only 1-5×/session while the existing no-op guard already catches 44. **The "depth is the multiplier" framing needs re-checking**: `review/Investigation_260802_restyle_cost_depth_and_narrowing.md` (same day, later) measured depth flat over a 2-month window across this exact codebase — re-verify against current widget-tree depth before treating depth reduction as the remaining lever; the Stats delegate migration (2026-08-05..09) may have already addressed the VISIBILITY lever instead. See NOTES.md 2026-08-02
- [2026-08-02] Settings dismiss with a preview showing blocks ~600ms before the slide starts (vs ~1.2ms without) — same root call; a timer-fallback fix is NON-VIABLE (the wait is synchronous; the snapback fade never renders a frame)
- [2026-08-02] Stats refactor has TWO restyle levers, not one: reduce nesting DEPTH **and** reduce how many widgets are VISIBLE at once (~22% swing on its own, measured at identical widget count) — but see the depth re-check note directly above before assuming depth is still the open half
- [2026-08-01] NEXT: first restyle after launch is 87ms, every later one ~410ms — a deterministic 4.7x step, reproduced across launches; bisect what runs in between (deferred pass / load_book / LibraryPanel.refresh 382 books / cover art)
- [2026-08-01] Blur on/off and fade 0/750/1500 RULED OUT by a 120-sample matrix — the ~580ms floor is independent of both
- [2026-08-01] RE-MEASURED at ~700-900ms, ~3x the figure below: `mw.setStyleSheet(base)` ~460ms + settings/speed/sleep panels ~215ms = 95% of it (NOTES.md)
- [2026-07-29] App-wide performance pass needed — theme restyle measured ~205-265ms per hover/click
- [2026-07-28] ~250ms full restyles during ordinary interaction — caller not yet identified
- [2026-07-20, untriaged, to be measured] General responsiveness reported slow after the
  (now-closed) theme-bleed fix — Pryme's plan is to measure it at some point to check if it's
  responsive enough, not yet done

### Blur grab hide/show side effects
- [2026-08-18] **`chapter_preview_label` frost redraw: faint border can linger after the preview
  fully fades, even after the fresh-grab fix (`0d39b38`).** Deprioritized by Pryme, not chased
  further this session — confirmed live to cause no further update/hitching cost, and not visible
  under a real (non-transparent) panel background, so the cosmetic residual itself is the only open
  question. If picked up: the fresh-grab-on-clear fix (see `_paint_preview_label`'s epsilon branch,
  `transport_bar_blur.py`) replaced a stale-snapshot restore and fixed most cases, but Pryme reported
  it "still there" at least once after that fix was live — not yet traced to why the fresh grab
  itself would leave a residual (candidates, none checked: the grab landing on a frame that hasn't
  fully settled post-fade; the rate-limit window (`_SUPPRESS_PREVIEW_S`, 0.080s) delaying the clear
  tick long enough that something else re-composites over it first). Full trace: NOTES.md, 2026-08-18.

- [2026-08-14] **Re-measure `_GRAB_FEEDBACK_SUPPRESS_S`.** Live again as of the 2026-08-15 revert
  above — the panel hide/show cycle this guard was sized against is back (it was briefly absent
  2026-08-14–15 while the grab source was content_container). Not re-tuned in the 2026-08-15 revert,
  deliberately, so this measurement is still needed: re-run the `FABULOR_GRAB_TRACE=1` accepted-paint
  histogram against the current code (`main_window` grab, panel hide restored) and confirm the 50ms
  deadline still misses by the same 8-15ms margin the 2026-08-14 measurement found, before deciding
  whether to widen it or replace it with state-based suppression.

- [2026-08-14, pre-existing, not a regression] The padding comment in `_grab_and_blur` claims 4x
  blur radius "fully converges corner alpha to 255"; measured corner alpha is actually **253** at
  DPR=1 — verified identical on the pre-change code path, so this is an inaccuracy in the original
  2026-07-19 measurement, not something this change introduced. Center alpha is a correct 255. Left
  alone as out of scope; worth a look only if edge tinting is ever reported.

- [2026-08-15] **Re-measure per-source suppress windows after the panel-hide removal.**
  `_SUPPRESS_MARQUEE_S=100ms` (and the other three windows) are test values chosen to match the
  category table handed down for this pass, not calibrated against a live histogram the way
  `_GRAB_FEEDBACK_SUPPRESS_S` originally was. Re-run `FABULOR_GRAB_TRACE=1` against real usage
  (marquee running, time labels during playback, slider during a real chapter) before treating any
  of the four as settled. Related to, but distinct from, the existing `_GRAB_FEEDBACK_SUPPRESS_S`
  re-measurement entry above — that guard gates whether a SCHEDULED grab executes; the per-source
  windows gate whether a dirty event schedules one at all. Both may need separate tuning passes.

- [2026-08-15] **Implement proportional slider rate.** `_DirtyRectTracker.set_chapter_duration()`
  exists as a stub (`self._chapter_duration_s`, written but never read) — the slider category is
  fixed at the `_SUPPRESS_SLIDER_S` (200ms) floor regardless of chapter length. The real formula
  (`_slider_suppress_s()`, linear scale between a 120s-or-shorter floor and a 1800s-or-longer
  ceiling of 15s) was specified but deliberately not wired in this pass. Blocked on an injection
  point: confirmed at Checkpoint A that `PanelManager` has no chapter-change signal and holds no
  player reference, so chapter duration cannot reach `set_chapter_duration()` without either (a) a
  new signal path added to `PanelManager` (explicitly out of scope — "do not add a new signal
  path"), or (b) a forwarding call from `app.py`'s real chapter-change path
  (`player.chapter_changed` → `_update_chapter_label_from_index`, app.py:483), which was out of
  scope for this pass ("app.py is not touched"). Whoever picks this up needs to either extend scope
  to app.py for one forwarding call, or get a different injection point approved first.

### Garbled backdrop after excluding the playing book from Book Detail (SYMPTOM FIXED, ROOT CAUSE UNCONFIRMED, 2026-08-14)

**STATUS (updated 2026-08-14, end of session):** the artifact no longer reproduces on branch
`fix/book-detail-blur-park` — Pryme confirmed it gone. It is kept open because the fix was arrived
at by *acting on* the lead below, never by probing the clip rect to confirm that lead was the
mechanism. So the symptom is gone and the diagnosis is still an inference.

What landed, both on this branch:
- `63838bc` — recomputes the blur clips and drops the parked frame when the layout reflows under an
  open panel. This is the "clip boundary in the wrong place" lead described at the bottom of this
  entry, acted on directly.
- `d52be3a` — fades the `visual_area` blur back in when the layout reflowed under the panel, fixing
  the crisp-then-snap that surfaced once the clip was corrected.

**Before closing this, do the probe the entry already asks for**: log the `visual_area` clip rect
and blur radius at removal time, and confirm they were in fact wrong pre-`63838bc` in the way
predicted. Without that, a future regression here will re-open a bug whose cause was never actually
verified — and this session already recorded three separate mechanisms that were probe-confirmed to
execute correctly while the artifact persisted, so "the fix worked" is weaker evidence here than
usual.

---

**Original entry (2026-08-14), kept verbatim for the ruled-out list:**
**Repro:** play a book, open Stats, wait for the blur to settle, open Book Detail on that book,
exclude it via the trash button (Book Detail stays open — `_on_book_detail_removed` only closes it
for `context=='library'`), then close the panel.

**Symptom (Pryme's words):** the top part scrolls without blur while the bottom is stale from the
open, showing the half speed button and the transport buttons blurred. Then it catches up and shows
the full blurred scrolling carousel. Only the garbling is wrong — the frosted scrolling afterwards
is correct.

**Three candidate mechanisms were each ruled out BY PROBE, not by reasoning.** Do not re-propose
any of them without new evidence:
1. *The carousel's own blur clip* — `blurred_panel()` returned the underlay (Stats) instead of Book
   Detail, giving an empty clip. Fixed, artifact unchanged. Reverted (`7251782`).
2. *The parked transport frame* — `force_refresh_now` no-ops while parked, so the frozen frame
   survived. Fixed via a `_parked_frame_invalid` flag; probe confirmed the branch fires
   (`parked=True`, no follow-up grab) and the artifact was unchanged. Reverted (`b15b76a`).
3. *The Book Detail panel frost* — `frost_panel_backdrop` grabs once at slide-finish and never
   refreshes. Dropping it on invalidation was implemented and probe-confirmed to run
   (`frosted_panel='book_detail_panel'`, cleared, never re-grabbed). Artifact unchanged. Not
   committed.

**So the image is held by something not yet identified.** Unchecked candidates: Book Detail's own
QSS background (`QWidget#book_detail_panel`, themes.py ~4019 — the panel sets
`WA_StyledBackground`), the `visual_area` clip rect during that specific transition, or a cached
pixmap elsewhere.

**CORRECTION (same session, after comparing against `main`): this is NOT reachable on main.** An
earlier version of this entry claimed it was; that was an assumption, never tested, and it is
wrong. Checked live on `main`: panel closes, carousel scrolls sharp, blur fades in cleanly — late,
but coherent, and Pryme calls it acceptable-if-not-ideal. The artifact is branch-specific.

**What that comparison points at, and it is the most promising lead — but UNVERIFIED.** `main`'s
`_suspend_blur_for_book_detail` does four things at open; the branch keeps only the first two
(`b94a315` deliberately removed the other two):

    self._clear_transport_bar_blur()      # branch: park_for_panel() instead
    self.blur_animation.stop()            # branch: kept
    self.blur_effect.setBlurRadius(0)     # branch: REMOVED
    self._clear_visual_area_clip()        # branch: REMOVED

So on the branch, when the book is excluded, the `visual_area` blur is still LIVE at radius 10 with
its clip still describing the Stats panel — which is gone, with the carousel now in that region.
"Top part scrolling without blur, bottom stale" reads like a clip boundary in the wrong place
rather than a frozen snapshot, which would also explain why all three snapshot fixes above changed
nothing. **Probe the clip rect and radius at removal time before writing any fix.**

Note the tension if that lead is right: removing those two lines is exactly what fixed the original
crisp-flash complaint (`b94a315`), so the fix is NOT to restore them. It would be to clear or
recompute the clip when the underlay goes away.

**The deeper question Pryme raised, worth settling first: why is anything grabbed here at all?**
`ClippedBlurEffect` is a live paint-time effect that follows moving content — it is what keeps the
carousel scrolling frosted on `main`. The grab-and-blur overlay exists only because `visual_area` is
inset 10px and does not contain the transport bar, and because a panel parented to `main_window`
sits in a different subtree — i.e. it is a workaround for widget-tree geometry, not a statement
about how blur should work. For Book Detail over Stats, most of the frosted region
(`QRect(0, 56, 270, 498)`) is territory the live effect already covers correctly. Pryme's summary:
*"there is nothing to grab cleanly here, it is scrolling all the time, and the grab rect is
colliding."* Measure which parts of that rect are genuinely outside `visual_area`'s reach (x=0..10,
x=260..270, and the transport bar) before assuming a grab is needed for the middle at all.

**Agreed fallback if a proper fix does not land:** accept `main`'s behaviour for this one
transition — crisp, then blur fading in — for the no-book carousel state after a book is removed
from Stats. Not ideal, but coherent, and strictly better than the patchwork.

**Next step should be to colour the widgets, not to read more code** — this is precisely the case
CLAUDE.md's "colour widgets first when a bug is about which widget owns which pixel" bullet covers,
and four inference-led attempts in one session each produced a correct-but-irrelevant fix. The two
probes that were actually run (a stack trace on `hide_for_panel`, a state dump at
`force_refresh_now`) each settled their question immediately.

**Branch-specific** — see the CORRECTION above. Introduced by this branch's blur-park work, most
likely by `b94a315` leaving a live `visual_area` blur and clip where `main` had already zeroed
both. Do not treat it as pre-existing.

### Book Detail frost — stale content on the frosted side (found live 2026-08-14)
Both reported with the panel alpha dropped to make the two sides comparable. The frosted region
shows a stale snapshot while the un-frosted right gutter (x=270..300, live since `0a0ed3c`) updates
correctly — the contrast is what made these visible, so they are not regressions from that fix.
- [2026-08-14] **Transport button hover/press state sticks.** Hover the speed button and leave: the
  frosted side stays highlighted while the gutter side reverts. Also the reverse (pressed on the
  live side, unhighlighted on the frosted side). Dropping the hover style while a panel is open in
  blur mode would mask it, but is explicitly NOT the direction wanted.
- [2026-08-14] **Next-chapter tooltip is stale.** Hovering Next shows the next chapter's title; the
  frosted side keeps or omits it depending on what was on screen at grab time. Rare enough to be
  low priority, and does not need to be 100% live.
- **Mechanism, established 2026-08-14 (an earlier draft of this entry got it wrong).**
  `frost_panel_backdrop` installs no `_DirtyRectTracker`, calls `frost.setPixmap(blurred)` exactly
  once, and nothing else in the file touches that pixmap — the frost really is fully STATIC, as its
  docstring says. The ticking remaining-time text is NOT the frost refreshing. A live geometry probe
  against the real `MainWindow` shows **five tracked widgets straddle the frost's x=270 right edge**,
  so each is split between a frozen left part and a live right part:

  | widget | x..right | frosted | live gutter |
  |---|---|---|---|
  | `speed_button` | 230..290 | 230..270 | 270..290 |
  | `next_button` | 244..290 | 244..270 | 270..290 |
  | `chap_duration_label` | 242..290 | 242..270 | 270..290 |
  | `total_time_label` | 210..290 | 210..270 | 270..290 |
  | `chapter_progress_slider` | 10..290 | 10..270 | 270..290 |

  The ticking text is `total_time_label`'s last 20px showing through the un-frosted gutter.

  **CORRECTION (2026-08-14, same day):** an earlier version of this entry went on to claim the seam
  "is why the symptom reads as half the button is stuck", i.e. that it explained the reported
  hover bug. **It does not.** The hover/press symptom is the shared `_grab_and_blur` hide/show
  loop, it affects every panel, and it has its own entry above (2026-08-01, measured 2026-08-14).
  Book Detail's frost does not use the shared overlay at all. The geometry above is real and
  worth keeping — the seam genuinely splits five widgets — but it is a *separate, cosmetic*
  issue from the hover bug, and the two were conflated for most of a session.
- **Why the obvious fix is blocked.** Adding a tracker to the frost re-arms `_grab_and_blur`, whose
  hide/show cycle re-exposes the tracked widgets and triggers the next grab — the ~64ms
  self-sustaining loop measured 2026-07-27 and **re-confirmed live 2026-08-14** (225 grabs/21s
  sustained; the 50ms guard is cleared by 8-15ms every cycle — see NOTES.md's top entry). An
  earlier draft of this entry claimed that loop had been fixed on 2026-07-20 and the blocker was
  stale; **that was wrong and is retracted.** The blocker is live. Needs either a refresh path that
  skips hide/show, or targeted invalidation on the specific events that matter. Not a small change.
- **And refreshing on hover would not look right even if it were cheap.** With the seam mid-button,
  the live 20px follows Qt's own paint schedule while the frosted 40px follows the refresh path —
  two writers on one widget, load-dependent. Same shape as `stash@{0}`'s undiagnosed intermittency.
- **Option not previously considered: move the seam instead of chasing it.** The 270px width exists
  to keep the carousel's right edge live and scrolling, but the carousel occupies y≈56..300 while
  every straddling widget sits at y≥356. A 300px-wide frost below y=356, keeping 270px above it,
  puts all five widgets wholly on the frosted side. That does not make hover live — it makes the
  staleness uniform, which is the tradeoff the design already accepts, instead of a visible seam
  across a single button. Needs Pryme's read on whether the seam or the staleness is the real
  complaint; they point at different fixes.
- Acceptable target per Pryme: does not have to be fully live, just not visibly stuck.

### Theme color/data
- [2026-07-07] Per-theme library color pass only covers A–S alphabetically (`library_bg`/`library_row_one`/`_two`/`library_item_hover_color`/`_alpha`/`library_title`/`_author`/`_narrator`/`_elapsed`/`_total`/`_percentage`/`library_slider_bg`/`_fill`/`library_input_bg`/`_text`) — letters T onward still need the same tuning pass (`ae4441c`)
- [2026-07-28] Some themes need a preset-ramp colour override (known theme-data issue)
- [2026-07-28] Three-state panel background shipped and working; clicking an option has perceptible lag
- [2026-07-21] "Cover art based theme": hover should preview the cover-derived theme regardless
  of the current Off/With pool/Exclusive mode (right-click-to-activate-from-Off half fixed
  2026-09-17 — see TODO_ARCHIVE.md; not yet live-verified by Pryme)
- [2026-06-19] Remove theme inheritance from "The Color Purple"

### Chapter list / library click
- [2026-07-21, not reproduced in a long time as of 2026-09-17] Chapter list highlight fluctuates
  and scrolls to bottom on click — likely already fixed by `787bfaa`, per Pryme's own report; not
  formally re-verified under instrumentation
- [2026-07-21] `SUSPECT_MASKED_STASH` diagnostic marker has a false-positive gap (diagnostic-only)

### VT / seek / progress tracking
- [2026-07-18] `closeEvent` can save near-zero progress on a SIGTERM race (narrow, not confirmed to matter)
- [2026-07-14, confirmed live 2026-09-17] VT missing-file handling — consolidated design, not yet
  implemented. Pryme reproduced the documented gap directly: deleting a file mid-VT-book shows the
  missing-file banner correctly, but navigating TO that chapter resets to the book's start (the
  cross-file jump in `seek_async` commits `_current_vt_index`/`_file_offset` and calls
  `instance.play()` with no `os.path.exists` pre-check — confirmed at player.py:992-1006, unlike
  the same-file branch's existing check at :975); using the chapter list to skip PAST the missing
  chapter works. This matches part 2 of the design below exactly. **This remains the eventual/
  bigger design (load-time check, sticky banner, Dismiss/Rescan) — see the separate INTERIM fix
  entry below for a smaller, immediately-shippable fix to just the corruption/reset symptom,
  worked out in a follow-up conversation the same night.**

- [2026-09-17] **INTERIM FIX (smaller than the consolidated design above, not a replacement for
  it) — "never load a missing file; always skip forward to the next present one, always notify."**
  Worked out with Pryme specifically because he's "not keen on refusing to play the whole book"
  for what could be an unimportant missing chapter (author's note, biography, end credits), and
  explicitly rejected silent skip-ahead as worse than an alarming-but-honest stop (a listener not
  looking at the screen could miss a whole chapter with no idea it happened). Unifies FOUR distinct
  code paths under one rule — three of them currently uncovered by any existence check at all, and
  the fourth (the same-file case, already shipped) currently does something more drastic
  (whole-book exclusion) than this design calls for:
  1. **Load-time, first VT file missing** (`_resolve_playlist`, `player.py:404-450`) — currently no
     existence check on `db_files[0]['file_path']` before returning it as the file to load.
  2. **Natural end-of-file advance** (`_advance_or_finish`, `player.py:367-390`) — currently no
     existence check on `next_file['file_path']` before `self.instance.play(...)`. The MORE
     common trigger than a deliberate jump (every listener who reaches that point hits it, not
     just someone who clicks ahead) — was nearly designed to "stop at the boundary" instead of
     skip, then unified to match the other three call sites for consistency rather than leaving an
     inconsistent exception; flagged here in case that unification is revisited.
  3. **Deliberate jump onto a missing file** (`seek_async` VT cross-file branch, `player.py:992-
     1007`) — the originally-reported bug. Unlike the other three, this one has a genuine "stay
     put" option: refuse the jump, leave `_current_vt_index`/`_file_offset`/playback state
     completely untouched (per Pryme: "leave playback state as-is" — paused stays paused, playing
     keeps playing from the old position), just show the notice. Does NOT reset to book start.
  4. **Same-file seek onto a missing file** (`seek_async` same-file branch, `player.py:975`,
     ALREADY SHIPPED as of July) — currently routes through `_abandon_seek_missing_file()` →
     `load_failed("File missing.")` → `_mark_book_missing()`, which excludes the WHOLE BOOK from
     the library for one missing file. Explicitly brought into the same "skip forward + notify,
     book stays loaded" rule rather than left as the more drastic pre-existing behavior — confirmed
     with Pryme directly rather than assumed, since it means changing already-shipped behavior.

  **Shared primitive needed:** a `_find_next_present_vt_file(start_idx) -> int | None` walk over
  `_virtual_timeline`, returning the first index at/after `start_idx` whose file passes
  `os.path.exists`, or `None` if nothing from there on exists (book effectively ends at that
  point — needs its own decision on what happens then, not yet worked out).

  **Notice mechanism:** reuse the `load_failed` signal but with a NEW reason string distinct from
  the existing `"File missing."` (which `_on_load_failed` in app.py currently routes to
  `_mark_book_missing` — that routing must NOT fire for this new reason, or it reintroduces the
  exact whole-book exclusion this fix removes). Needs to be a persistent banner naming the skipped
  chapter, not a transient toast — deliberately per Pryme's "never silently skip" requirement.

  **Scope note, said plainly by Pryme:** this is explicitly NOT the fully-designed load-time
  count-and-compare check from part 1 of the consolidated design above ("not keen on" a bigger
  overhaul right now) — this fix never proactively checks for missing files before they're
  actually about to be loaded; it only ensures that whenever the normal playback flow is ABOUT to
  load one, it skips forward instead. A VT book with every file already gone before the user ever
  opens it still behaves however case 1 above resolves (skip forward through the whole book,
  eventually finding nothing — see the shared primitive's own open "what then" question).

  **This touches `seek_async`/`_advance_or_finish`/`_resolve_playlist` — the exact "Seek/position
  tracking — VT+Undo is the known-fragile zone" CLAUDE.md rule.** Four independently-reverted
  attempts in this same zone are already on record. Needs its own investigate-then-plan session,
  not a quick patch, and must be live-verified against VT cross-file seeking, Undo, and the
  existing missing-file live repro (delete a file mid-VT-book) specifically — not just a clean
  unit-test pass — before being considered done. NOT started; design only, worked out via
  conversation, not yet reduced to a concrete implementation plan.

### Seek-landing precision at chapter boundaries — GROUPED, deliberately not picked up piecemeal
**Read [SEEK_CONSTANTS.md](SEEK_CONSTANTS.md) and NOTES.md's 2026-07-14
`_PAUSED_SEEK_UNDERSHOOT_COMP` boundary-crossing-gate writeup FIRST, before touching any entry
below.** All six items share one underlying fact: mpv's seek landing is imprecise at a chapter
boundary (overshoots ~0.09s while playing, undershoots ~0.37s while paused — see
`SEEK_CONSTANTS.md`'s measurement table), and every attempted fix so far has been a per-symptom
epsilon/offset patch rather than a fix to the underlying imprecision. One such patch
(`_PAUSED_SEEK_UNDERSHOOT_COMP` boundary-gating, 2026-07-14) was implemented, unit-tested, and
found STRUCTURALLY WRONG before being fully reverted — not a tuning miss, a category error (it
checked the inflated mpv *command* against a boundary instead of tracking the caller's actual
*intent*, discarding information — "was this seek meant to land exactly, or is approximate fine"
— that only exists at the call site). The corrected direction that investigation converged on:
pass an explicit intent signal into `seek_async` at the call site, not infer it from arithmetic
after the fact. Decided 2026-09-16 (Pryme): this whole cluster should be picked up as ONE
dedicated investigation against that corrected direction, not fixed symptom-by-symptom — grouping
these entries here is prep for that session, not a signal any one of them is ready to fix in
isolation.
- [2026-09-16] Chapter-start narration clipping ("apter two" instead of "Chapter two") — likely the
  same root cause as the entry below, corroborating 2026-09-16 sighting via smart rewind/Prev
- [2026-07-22] Intermittent chapter-number flicker on backward seek to a boundary — possibly a
  distinct undershoot magnitude (~0.435s) from the characterized 0.37s; more captures needed
- [2026-07-13] Chapter-elapsed label reads ~1s short near a chapter boundary
- [2026-07-12] Chapter-slider load-time retrace disagrees with the restore seek by 0.35s
- [2026-07-12] `_PAUSED_SEEK_UNDERSHOOT_COMP` applied unconditionally, not gated on boundary
  proximity — the 2026-07-14 reverted attempt; canonical writeup, read before re-attempting
- [2026-07-14] Right-click a chapter notch while paused can leave a small residual clip (notch-click
  starts playback, so the paused-undershoot compensation's benefit is only partial) — minor,
  deferred; see TESTING.md's "Undo / right-click notch (paused embedded)" checklist

### Panel focus / keyboard navigation
- [2026-09-22] General app slowness suspected tied to the keyboard-navigation event-filter stack
  added over the prior two weeks (traveling focus marker, hover-pickup polling, GridHoverTracker,
  the per-panel eventFilters this all layered on). A `cProfile` capture of a live Book Detail open
  (openable from Library, Stats, OR Tags — `PanelManager.active_full_panel()` checks all six panel
  types as a possible underlay; see TODO_ARCHIVE.md's now-closed "Book Detail slide-in..." entry)
  showed 43-64% of the open window's wall time spent walking the app-wide `eventFilter` chain
  (MainWindow's permanent filter + whichever panel-specific filters are currently installed, e.g.
  Stats' own stays live as Book Detail's underlay since Book Detail layers on top rather than
  replacing it — plus PySide's own per-call `QEvent.type()`/enum/shiboken feature-import overhead)
  — not application logic, and not specific to Book Detail; this cost is paid on every Qt event
  anywhere in the app.

  **Root cause of the raw event VOLUME (5,873 filtered events in one ~0.5s open), checked directly
  rather than assumed: NOT book/tag/library count** — confirmed by re-deriving the number rather
  than guessing. Two independent multipliers: (1) how many separate `eventFilter` objects are
  stacked and each independently re-walk the SAME event (`installEventFilter`/`removeEventFilter`
  audited across the codebase: most panel-specific filters correctly install on `showEvent`/remove
  on `hideEvent` — Sprint/Sleep/Tags(panel)/Stats/BookDetail all do this — but `ScrollHoverTracker`/
  `GridHoverTracker` (`hover_tracker.py`, constructed once inside `TagManagerWidget.__init__` at
  app startup) install in `__init__` and are NEVER removed, so both stay permanently live for the
  app's entire session regardless of whether the Tags panel is ever opened); (2) the raw Qt event
  count generated during the ~0.5s slide window, which is dominated by the ALREADY-DOCUMENTED
  transport-bar blur/frost grab's repeated hide/show cycling of the underlay to capture a clean
  backdrop (`transport_bar_blur.py`'s `_grab_and_blur`, CLAUDE.md: "hides and re-shows the active
  panel roughly every ~65-200ms") — a pre-existing mechanism, not something new from the last two
  weeks' keyboard-nav work. Each hide/show cycle fires a burst of Show/Hide/Enter/Leave/Paint
  events that every stacked filter has to see and immediately discard.

  So the two suspects are NOT the same thing: the recent keyboard-nav work added MORE stacked
  filters (raising multiplier (1)), while the blur/frost grab (pre-existing) is a candidate for
  what's driving the raw event volume (multiplier (2)) each filter has to chew through — UNCONFIRMED,
  not settled either way. Pryme did an informal check the same session (blur toggled off in
  Settings, several Book Detail opens tried that way) and did not notice a clear difference — but
  flagged this himself as "not extensive, not conclusive... I wouldn't lean too much into it without
  a real test with real numbers." Also noted: Sprint/Speed/Settings (simple panels, none of which
  frost/grab the way Book Detail does) have ALSO felt less smooth recently, which cuts against blur/
  frost being the dominant or sole driver — but this is also an informal observation, not measured.
  Pryme's own current best guess, also unconfirmed: the two things that changed most recently are
  more tags/tagged-books and the full keyboard-navigation rollout — see the two concrete follow-ups
  below, both more directly actionable than the blur question. A real A/B (blur on vs. off, same
  panel, same conditions, `FABULOR_PANEL_TIMING=1` wall-clock numbers on both sides) is still the
  way to actually settle the blur/frost question, whenever someone picks this up.

  **Two concrete follow-ups Pryme named, not yet started, sequenced for a future session:**
  1. **Fix the tracker leak (small, low-risk, ready to implement).** Give `ScrollHoverTracker`/
     `GridHoverTracker` the same `showEvent`/`hideEvent` install/remove pattern every other
     panel-specific filter already uses correctly (Sprint/Sleep/Stats/BookDetail all do this) —
     mechanical, well-precedented, should shrink the filter-stack depth for every panel's open/close,
     not just Book Detail's.
  2. **Migrate Tags from widget-per-thumb to a delegate model, matching Stats' own August migration**
     (`StatsRowModel`/`StatsRowDelegate`, see CLAUDE.md's Stats Panel section). `TagManagerWidget`
     (`tag_manager.py`, 2094 lines) is still entirely widget-per-row/widget-per-thumb — every
     `_TagBookThumb` shown in a tag's detail grid is a real `QWidget` instance, each independently
     receiving its own share of Qt's paint/enter/leave/focus event traffic, unlike a delegate-painted
     `QAbstractItemView` which has no per-item widgets at all. This is a genuinely large undertaking
     (Stats' own migration spanned Day/Week/Month across two separate August sessions) — not
     scoped or started this session, deliberately left as its own future investigation rather than
     begun at the tail end of this one.
  `FABULOR_BOOKDETAIL_PROFILE=1`/`FABULOR_PANEL_TIMING=1` (`panels.py`) are both still in the tree,
  off by default, ready to reuse for measuring either follow-up's actual impact once implemented.
- [2026-07-31] ScrollHoverTracker.suspend() is the hook for mouse/keyboard highlight coexistence
  — worth confirming the shipped Stats/Tags hover-pickup mechanism (`_pickup_cursor_anchor`/
  `GridHoverTracker`, 2026-09-15) actually routes through `suspend()` as this entry predicted,
  or used a different mechanism instead.
- [2026-07-11] History tab delete-session animation still pauses near the end — the viewport-
  quantization item it was blocked on shipped (`b20a1ff`, 2026-08-12); unblocked, not yet resumed
- [2026-07-10] PageUp/PageDown jump distance in the library list — undecided

### Test infrastructure
- [2026-08-09] `QSettings.setDefaultFormat(IniFormat)` + `setPath` does NOT isolate test writes from the real `~/.config/Fabulor/Fabulor.conf` on this platform/PySide6 build — confirmed live (a test write actually leaked into the real config file during `tests/test_sidebar_hotspot.py` development, caught via `stat` mtime, cleaned up manually). `test_hover_excludes_speed_sleep.py` uses this exact pattern and may have the same latent gap (never surfaced there because it doesn't check default-value isolation against the real file). `test_sidebar_hotspot.py` works around it locally via a `QSettings` subclass monkeypatch that always resolves to an explicit `tmp_path` `.ini` file; the underlying gap in the established pattern is unaddressed for other test files

### Volume / transport UI
- [2026-06-23] Slider→muted-icon transition is abrupt

### Misc UI polish
- [2026-07-30] In-app help section — the home for all reference material, incl. search operators
- [2026-07-03] Excluding the currently-playing book behaves differently for M4B vs VT — design decision

### Cleanup / process
- [2026-06-27] Excluded Books popup corner-radius mismatch
- [2026-06-25] Pre-release cleanup pass (remove Q-key shortcut, stray debug prints)

### Big deferred architecture
- [2026-07-14] Incremental `@Property` color animation instead of whole-theme stylesheet swap (40-80h, high risk)
- [2026-07-14] Close the P1↔P2 race precondition structurally (insurance, not a live bug)
- [2026-07-14] App-start flow-animation baseline roughness (Regime A) — standalone ~70ms hitch

## Pending

- **[2026-08-02] Theme-apply ordering/deferral for book-switch flow stutter (cover-theme on).**
  Confirmed directional: Book A (80% progress) → Book B (11.5%) stutters during the flow animation;
  the reverse (B→A) does not. Root cause not yet instrumented — likely tied to `_apply_stylesheets`
  paying its full ~640ms pipeline (see 2026-08-02 narrowing report) synchronously during/near the
  flow animation window, but the directional asymmetry is unexplained and must be captured before
  any fix is attempted.

  **Proposed design (not yet built, needs instrumentation first):** reframe from "skip invisible
  work" (dirty-flag idea, rejected — on a book-switch everything genuinely needs repainting
  eventually, so nothing is actually skippable) to **ordering/deferral** — apply what's visible
  now, queue what isn't, drain the queue once the flow animation completes.
  - **Immediate tier** (runs synchronously, feeds the flow animation / visible chrome): step 1
    (`mw.setStyleSheet(base)`), title/content, icons, sidebar/chapter-UI if visible, library_panel
    if visible. Matches the report's existing "visible surfaces" ~278ms bucket.
  - **Deferred tier** (queued, not skipped): settings/speed/sleep panels, stats/book_detail
    panels, the TAIL (`_refresh_panel_visuals`, `theme_applied.emit`,
    `update_theme_list_visuals`). Drains once flow-animation-complete fires — there is already a
    completion signal for this, since it's the same event that was colliding with theme
    application before the 2026-07-2x flow-animation fixes.
  - **Panel-open-during-drain interrupt case** — two options, decide by measurement not guess:
    (a) defer the panel open until the queue drains (simplest, but adds latency to a
    user-initiated action — usually the thing to protect most), or (b) jump the queue: apply just
    that panel's slice immediately out of order, open it, resume draining the rest (more
    responsive, more moving parts). Pryme's instinct is (a) will rarely if ever be perceptible —
    build (a) first, measure, only build (b) if the wait is shown to be noticeable.

  **Before building anything:** instrument to explain the A→B vs B→A asymmetry specifically —
  worth checking whether it correlates with which theme is already applied vs. being applied (i.e.
  whether cost differs between "restyle to theme already partially warm" vs "cold"), since that
  could either explain the direction or turn out unrelated. Do not assume the ordering/deferral
  design fixes the directional bug until the asymmetry itself is understood — it may be a separate,
  compounding issue.

  Not scheduled — instrumentation-first per standing methodology, own session.

- **[2026-07-29] App-wide performance pass needed; theme restyle cost is one confirmed contributor.**
  While instrumenting the right-click investigation above, a WARNING-level probe
  (`[SETSTYLE-PROBE]` in `theme_manager.py`'s `_apply_stylesheets`) measured the real, DEBUG-off cost
  of `mw.setStyleSheet(get_base_stylesheet(...))` — the synchronous restyle that fires on every theme
  hover-preview and click — at a consistent **~205-265ms** across 55 clean samples (one hover/click
  cycle each), no new themes added and no obvious stylesheet bloat to explain it. This is notably
  higher than the ~143ms figure `tools/click_test.py`'s docstring cites (source/conditions for that
  older number unknown — not confirmed to be a logging-overhead artifact; DEBUG-on measurements this
  session ran 212-281ms, DEBUG-off 205-265ms, so DEBUG logging is not the main driver of the
  discrepancy). This single call is one piece of a restyle pipeline that in earlier sessions measured
  550-600ms total per hover-preview cycle end to end. Needs its own investigation/pass, scoped
  separately from any specific bug — likely candidates worth checking first: whether
  `get_base_stylesheet`'s generated QSS string has grown, whether `setStyleSheet`'s repolish cost
  scales with total widget count (relevant given CLAUDE.md's "test at 10x library size" rule elsewhere
  in the codebase), and whether this cost is inherent to Qt's stylesheet engine at this app's window
  complexity or genuinely regressed from a past baseline. `[SETSTYLE-PROBE]` is left in place
  (WARNING-level, harmless) and can be reused directly for before/after comparisons.

- **[2026-07-28] OPEN — ~250ms full restyles during ordinary interaction; the earlier "fixed" claim
  was measured on an IDLE app.** `a41698c` genuinely fixed a 3/sec storm (a restyle wrongly placed
  on the settings visual-sync path). It was then verified by counting restyles over 25 idle seconds
  — zero, because nothing was happening. The user doubted it; re-measured under real interaction,
  **23 full restyles at ~250ms each in two minutes**, bursts 1.5-2.5s apart, ~160-186ms of each
  being `mw.setStyleSheet(base)`.
  **Caller unidentified:** none of the 23 has a `[BLEED-TRACE] _on_theme_changed`,
  `_toggle_sidebar ENTRY` or `complete_main_fade ENTRY` alongside it, so the obvious paths are out.
  Predates tonight's work; very likely what reads as a rough panel slide. Lesson recorded in
  NOTES.md: measuring a cost on an idle app answers nothing — the same trap as the 2026-07-27
  blur-grab measurement.

- **[2026-07-20, untriaged, plan set 2026-09-17] General responsiveness was reported slow after
  the theme-bleed fix landed — not soak-related (the bleed itself is now closed, see
  TODO_ARCHIVE.md, weeks of soak confirmed by Pryme 2026-09-17), separate open question.**
  Candidate follow-up (not started): the new responsiveness complaint may be the hover gate's
  decline path adding overhead elsewhere, or may be unrelated. Pryme's plan (2026-09-17): "We can
  measure it at some point to determine if it is responsive enough" — this needs a live-profiling
  pass to actually quantify current responsiveness before deciding whether it's a real regression
  worth chasing or was never as bad as the original report suggested; not scheduled yet.

- **[2026-07-28] Some themes need a preset-ramp colour override — known theme-data issue, not a code
  bug.** Exposed (not caused) by `fa6d301`, which replaced the Sleep/Speed alpha ramp with an honest
  `bg_main` -> `accent` colour blend. The old alpha version composited against the cover art as well
  as the panel, which incidentally lifted the low steps; the blend does not, so themes whose accent
  and background are close in luminance, or whose midpoint is unflattering, now show it.
  **Examples confirmed live by the user** (first three ramp steps of 13, computed against the real
  theme dicts):
    Gravity's Rainbow  bg #2B0052 -> accent #00FF00 : 30,75,58 / 28,90,53 / 25,105,48
                       (purple to green passes through muddy olive; button text also goes
                        light-on-light at the top of the ramp)
    Plum Island        bg #1E2A2E -> accent #6A4A6A : 52,51,64 / 57,53,67 / 61,55,71
                       (accent only ~40 units from bg — the whole ramp is compressed)
    Blindsight         bg #141414 -> accent #3A6A8A : 31,45,55 / 33,50,62 / 36,55,69
                       (same shape on near-black)
  **Plan:** per-theme dict overrides for the ramp endpoints, so a theme can supply its own
  ramp start/end rather than deriving both from `bg_main`/`accent`. `preset_ramp_rgb`
  (`themes.py`) is the single place that reads them, and it already falls back cleanly on missing
  keys (pinned by `tests/test_preset_ramp.py`). If the new keys are optional and only some themes
  set them, check whether they belong in `_NO_BASE_INHERIT_KEYS` — see the CLAUDE.md rule, since
  "The Color Purple" is the base every theme inherits unset keys from and a literal value there
  would silently override every other theme's derived fallback.
  Also worth deciding at the same time: `button_text` contrast, which is the other half of the
  Gravity's Rainbow case — the ramp can be fixed and the label still be unreadable.

- **[2026-07-28] SHIPPED and confirmed working (`3132be7`): three-state panel background —
  Transparent | Frosty glass | Opaque.** Design notes below are kept as reference, not as an
  unstarted plan — the feature is live and the user has confirmed it works.
  **Perceptible lag when clicking an option — investigated and partially fixed.** `149c647`
  (2026-08-02, "perf: scope the backdrop-mode restyle to the surfaces that read the panel alpha")
  measured the lag directly (~1040ms) and cut it to ~555ms by scoping the restyle to only the
  surfaces that actually read `panel_opacity_hover`/the backdrop mode, rather than a full restyle
  pass. A further residual (~140ms, achievable by also skipping hidden panels) was deliberately
  not bundled into that fix — that residual is the only part of this item still open.

  **Original design notes, kept for reference:** smaller than it first looks, because the opacity
  machinery already exists. **What was already there** (found 2026-07-28 after the user pointed at
  `tab_hover_opacity`, renamed 2026-09-09 from `settings_tab_hover_opacity`): `panel_opacity_hover`
  is a per-theme float (0.88-0.95 across the
  theme set, every theme sets one) and the panel background is ALREADY painted as
  `rgba(bg_main, panel_opacity_hover)` — `themes.py:3458` in `get_settings_stylesheet`, with a
  second consumer around `:3724`. So the three states are mostly a matter of choosing the alpha and
  whether the blur runs:
    Opaque        -> force alpha 1.0 (probably a one-line override at the stylesheet site)
    Frosty glass  -> today's blur + the theme's own `panel_opacity_hover`
    Transparent   -> no blur + the theme's own `panel_opacity_hover`
  The per-theme values stay as the Transparent/Frosty look; only Opaque overrides them.
  Open questions noted at the time, status against the shipped implementation not rechecked:
  (a) whether stats/tags/book-detail panels use this same rule or paint their own backgrounds —
  only the settings/speed/sleep group was traced; (b) whether Opaque should skip the blur work
  entirely. If the panel is fully opaque the blur behind it cannot be seen, which is exactly what
  `_panel_hides_everything` (`transport_bar_blur.py`) already exploits for the Timeline tab —
  reusing it would make Opaque CHEAPER than the other two rather than equal cost.
  **The widening that remains:** confirmed in `config.py` — `blur_enabled` has been fully migrated
  to the three-state `panel_backdrop` key; the old boolean is kept only as a one-time
  backward-compatibility read on upgrade, not as the live setting.

- **[2026-06-19] Remove theme inheritance from "The Color Purple."** Every theme currently resolves
  via `_resolve_theme()` as `THEMES["The Color Purple"].copy()` overlaid with the requested theme's
  own dict — any key a theme doesn't define falls back to Purple's literal value, not to that
  theme's own derived fallback (e.g. an accent-derived color). `_NO_BASE_INHERIT_KEYS` in
  `themes.py` is a manually-maintained escape hatch for keys where this is wrong, and it's easy to
  forget to update when adding a new optional key (see CLAUDE.md rule on `_NO_BASE_INHERIT_KEYS`,
  added 2026-06-19). Made sense early when Purple was a stable default; doesn't anymore — Purple
  probably won't even ship as the default theme. Target design: no theme inherits literal values
  from another theme; every key is either required (defined in all themes) or has a documented
  code-level fallback chain, never "whatever the base template happened to set."
  **Blocked on:** user's planned full pass over every theme (adding keys where current fallbacks
  don't look right) — doing the inheritance refactor before that pass would only have a partial
  picture of which keys actually need it. Revisit once that pass is done.

- **[2026-07-22] Investigate intermittent chapter-number flicker on backward seek to boundary — repros via
  both Prev key and chapter-list click; UI briefly shows previous chapter before correcting.
  Low-frequency (weeks between occurrences), instrumentation already in place. See NOTES.md
  for captured instance + working theory (mpv settle undershoot, ~0.435s, outside
  `_CHAPTER_BOUNDARY_EPSILON`). Do not fix speculatively — needs more captures first.**
  **May be distinct from the `787bfaa` fix — the 2026-07-22 working theory was settle undershoot
  (landing short of the boundary), not the stale post-settle sample `787bfaa` targets. Monitor; do
  not assume closed.** Part of the "Seek-landing precision at chapter boundaries" group (see that
  heading in the summary index) — read `SEEK_CONSTANTS.md` before touching this.

- **[2026-07-21, not reproduced in a long time as of 2026-09-17] Chapter list: clicking a chapter
  sometimes made the current-chapter highlight fluctuate between chapter rows and scroll the list
  to the bottom — visual bug, likely already fixed.** User-reported, intermittent ("sometimes"),
  never reproduced under instrumentation, no confirmed root cause at the time (candidate areas
  flagged for whenever it resurfaces: `chapter_list.py`'s selection/scroll handling on click, and
  whether this interacts with `_on_time_pos_change`'s chapter-walk-driven `chapter_changed` emits
  racing the click's own selection — see the CLAUDE.md chapter-navigation rules — but that was
  always a guess, not confirmed). **Likely closed by `787bfaa`** — same mechanism, same code path
  (chapter-list clicks route through `activate_chapter_index` → `seek_async`, same as Prev/Next)
  confirmed in the chapter-flicker investigation. **2026-09-17: Pryme reports he "can't produce [it]
  for a long time," probably fixed** — real evidence toward closing this, but not the formal
  instrumented re-verification this entry has always asked for before removal (the bug was
  intermittent enough originally that a stretch of non-reproduction isn't automatically proof).
  Leave open one more round; if it still doesn't resurface, close outright rather than requiring a
  deliberate repro attempt that may never come.

- **[2026-07-21] `SUSPECT_MASKED_STASH` diagnostic marker has a false-positive gap — deal with
  later, not a functional bug.** Confirmed via a real 15-minute live session (03:00–03:15) after
  the guard-masking + hover-confinement fixes landed: the marker fired `True` 15 times, but every
  one was `hover=True` (an ordinary, correct hover no-op, not the actual bug — which is `hover=False`
  + the marker). The marker doesn't distinguish "guard blocked a real pending apply" from "guard
  correctly no-op'd a redundant hover re-entry," because only non-hover applies update the
  `_theme_ever_applied` comparison value it checks against. Diagnostic-precision issue only — does
  not affect app behavior, both real fixes are confirmed working via the same session's log. Full
  detail: NOTES.md, "Guard-masking bug ... and hover-preview confinement" entry, 2026-07-21.

- **[2026-07-18] `closeEvent` can save a near-zero progress if SIGTERM/close lands between
  `load_book` and the VT restore-seek landing — found via a 400-cycle cold-launch stress test,
  narrow and not confirmed to matter in real usage.** Test: 5 VT + 5 M4B books, 40 cold launches
  each (`entr -r` restart via touching `book_quotes.py`, ~2s between touches), cover-theme ON,
  checking DB `progress` for corruption after every launch. Result: 398/400 clean; 2 anomalies, both
  isolated single-event drops that then held perfectly stable for the rest of that book's 40-launch
  batch (no repeating/systematic corruption). One (Colorless Tsukuru Tazaki, launch 24) was traced
  to a burst of `seek_async` calls ~10.75s apart milliseconds apart — stray wheel-scroll input
  landing on the progress slider during this interactive session, not an app bug. The other
  (Austerlitz, launch 2) is real: the first Austerlitz launch's `load_book` fired but
  `_restore_position` had not yet run when `entr` sent SIGTERM (~1.4s later) for the next cycle;
  `closeEvent` (`app.py:3370`) unconditionally calls `_save_current_progress()` whenever
  `current_file` is set, with no check for whether the VT restore-seek actually landed, so it saved
  the just-loaded (~0) position over the real 10420.78s. **Caveat from the user, load-bearing:**
  this test's rapid restart cadence doesn't reproduce the original bug's shape — the original issue
  was progress restoring correctly in the GUI and then *later* dropping to zero, not a load
  interrupted before restore ever ran. Real usage doesn't SIGTERM the app mid-book-load, so it's
  unclear this narrow race is worth pursuing on its own. Not triaged as a priority; revisit only if
  a similar shape shows up from real usage, not from stress-test cadence alone.

- **[2026-07-14, confirmed live 2026-09-17] VT missing-file handling — consolidated design
  (supersedes three earlier, narrower entries from the same night: the cross-file
  chapter-cycling bug, the discovery-timing/banner-permanence gaps, and the original "richer
  design deferred" sketch — all folded into one plan since they turned out to be facets of the
  same design, not separate problems).** Current shipped behavior (same-file missing-file case
  only): unload + `is_missing`, reusing the existing M4B runtime path. Below is the actual intended
  design, decided in conversation but NOT implemented — needs its own session, deliberately kept
  off this branch to avoid sidetracking from the drift-adjacent fixes it exists for.
  **2026-09-17: Pryme reproduced part 2's exact gap live** — deleted a file mid-VT-book; the
  missing-file banner appeared correctly, but navigating directly TO the now-missing chapter
  resets playback to the book's start rather than showing the error, while skipping past it via
  the chapter list works fine. This matches the diagnosis below almost exactly: `seek_async`'s VT
  cross-file branch (`player.py:992-1006`) has no `os.path.exists` check before committing
  `_current_vt_index`/`_file_offset` and calling `instance.play()`, unlike the same-file branch's
  existing check (`player.py:975`).

  **1. Load-time check (closes the M4B/VT discovery-timing asymmetry — mostly decided, one open
  question).** M4B is a single file: if it's missing, the book can't even load, so the failure is
  exposed immediately and unconditionally. VT is a folder of files: today, the book loads fine
  even if a file is already gone, because nothing checks at load time — a missing file is only
  discovered *reactively*, contingent on some later action (Play, Next, a seek/skip) happening to
  target it. This means a VT book can sit in the library for an arbitrary stretch — across
  sessions, across restarts — reporting as a normal, fully playable book while a file is silently
  gone. Decided direction: at load time, compare the file count the book was built/scanned with
  (`book_files` row count in the DB) against the count of matching audio files actually present in
  the folder (not a full per-file `os.path.exists` sweep — a single directory listing/glob + count
  comparison, cheap regardless of file count, unlike hundreds of individual stat calls). **Open
  question, not yet resolved:** is a listdir+count comparison actually fast enough to add zero
  perceptible load-time latency, including on slow/network-mounted storage or very large VT books?
  Needs to be measured against a real large book (Zhivago, 260 files, is the natural test case)
  before trusting it — this is the one piece of the design that's still genuinely open; everything
  else below is decided pending implementation.

  **2. Post-load discovery (file goes missing after the book already loaded/played once) — the
  bug this actually started from.** `seek_async`'s cross-file `else` branch (`player.py`
  ~820-833, `self.instance.play(target_file['file_path'])`) has no existence check and commits
  `_current_vt_index`/`_file_offset` to the target BEFORE confirming it loaded. When the file is
  missing, mpv's ERROR end-file fires, and `_on_end_file`'s ERROR-path reset (already shipped)
  clears seek state but never touches `_current_vt_index`/`_file_offset` — leaving them pointing
  at a file that was never actually loaded. Live-reproduced result: banner shows mpv's own generic
  error text (not "File missing."); Play does nothing; Next/Prev cycle a fixed subset of the
  book's chapters forever, permanently unable to reach the missing file or anything past it; no
  freeze, no crash. Full mechanism, traced step-by-step, in NOTES.md "VT cross-file missing-file
  jump corrupts `_current_vt_index`/`_file_offset` — DIAGNOSED, NOT FIXED" (2026-07-14) — that
  writeup also settles that no rollback/snapshot mechanism is needed: a pre-check
  (`os.path.exists`, same shape as the already-shipped same-file fix) before committing any state
  resolves the "file doesn't exist" case cleanly, since nothing is ever committed to roll back. A
  file that exists but is corrupt/unreadable (passes `os.path.exists`, still fails at
  `instance.play()`) is the one remaining case needing `_on_end_file`'s ERROR path to recognize a
  VT cross-file jump was in flight and route it into the same handling as (3) below, rather than
  leaving `_current_vt_index`/`_file_offset` stranded. Loose thread, not yet reconciled: a second,
  earlier live test (moved a different file, skipped over it, played the first file successfully,
  then some later navigation triggered an unload the user couldn't precisely reconstruct) is very
  likely this exact bug — but was never deliberately re-reproduced against this now-understood
  mechanism, so treat it as likely-explained, not confirmed, until someone runs that exact sequence
  again on purpose.

  **3. What happens on discovery — decided, and deliberately the SMALL version of this design.**
  Explicitly rejected: blocking playback/UI until the user chooses an action. That was floated and
  immediately ruled out — it would mean disabling the overall progress slider, the chapter slider,
  every transport button, and the chapter list, which is a large, risky surface for what looks
  like a small edge case, and isn't worth the blast radius. **Decided instead: unload the book
  immediately** (reusing the exact same `_mark_book_missing` → `_on_book_removed` path already
  shipped tonight — nothing new needed here), **and show a sticky banner with two actions: Dismiss
  (= exclude — closing the banner without choosing Rescan is equivalent to accepting the
  exclusion) and Rescan.** Banner must not auto-hide, needs a real close button, and — restart
  behavior carried over from the earlier draft of this entry — should never reappear at app start
  just because the book is already excluded; the book should simply already be excluded (via the
  self-healing `is_missing` flag) and the app comes up in its normal state, silently. **Rescan
  means: re-scan just that book's folder** (not a full naming-pattern-style rebuild, not
  timeline-renumbering) — missing files stay missing, but the rest of the book plays normally
  around the gap; this reuses the scanner's existing per-folder rescan machinery rather than
  building something new. **Cover-art flash concern, already raised and already answered:** the
  user doesn't want the excluded/reloaded book's cover art visibly popping in the main UI while
  this resolves — same reasoning as why the existing library-panel slide already hides book-switch
  transitions from view. The intended fix (matching an existing app pattern, not a new one) is to
  route the Rescan-and-reload through the library panel slide, the same way a normal book switch
  already avoids showing intermediate cover-art states in the open.

  **Net effect of this design vs. today's shipped behavior:** (1) closes the "sits broken
  indefinitely" discovery gap for the common case (missing before the book is ever loaded); (2)
  fixes the specific cycling/stuck-book corruption for the case a file goes missing after load;
  (3) gives the user a real choice (exclude vs. rescan-and-keep-playing-around-the-gap) instead of
  today's unconditional silent exclusion, without taking on the blocked-UI design that was
  considered and rejected as disproportionate risk for the size of the problem.

- **[2026-07-13] Chapter-elapsed label reads ~1s short for up to `_CHAPTER_WALK_TOLERANCE` after
  crossing a chapter boundary (chapter-relative display only; absolute position is exact).**
  Surfaced (NOT caused) by the `_logical_pos` seek-drift fix — with absolute position now exact,
  this pre-existing chapter-display artifact became cleanly visible instead of being drowned in the
  old compounding drift (per the user: "it was worse before, drifting all around, impossible to
  tell them apart"). Mechanism: `_sync_chapter_ui` (`app.py`, ~line 1987) resolves the current
  chapter with the tolerance-padded walk `chap.time <= pos + _CHAPTER_WALK_TOLERANCE` (0.5s), then
  computes `c_elapsed = max(0, pos - chap_start)`. When a skip/seek lands within ~0.5s BEFORE a
  boundary, the walk already resolves to the NEXT chapter (tolerance), so `c_elapsed` clamps toward
  0 while the true position is still just short of the boundary — a chapter-relative offset up to
  ~1s (the chapter-remaining label uses `end - pos` with no tolerance, so the two can disagree at
  the seam). **Confirmed observationally NOT the drift bug:** absolute total-elapsed / total-
  remaining / chapter-remaining all read reliably ("10s is 10s, 30s is 30s"); the step size is
  steady (5s skips land 5s apart), it only shifts ~1s at a boundary crossing and stays consistent
  within the new chapter. Also: this touches `_CHAPTER_WALK_TOLERANCE` and the chapter-walk block,
  both of which the drift-fix plan explicitly did NOT touch (heavily-scarred epsilon zone). **Its
  own investigate-first cycle** — the tolerance exists to stop paused Next/Prev sticking (see the
  constant's own comment in `player.py`), so narrowing/removing it for the display walk risks
  reintroducing that; a display-only fix (e.g. resolve the chapter-elapsed label's chapter without
  the tolerance, or clamp `c_elapsed` differently at the seam) is the likely direction but needs
  its own repro + verification against the stuck-Next/Prev symptom. Not blocking the drift fix.
  Part of the "Seek-landing precision at chapter boundaries" group (see that heading in the summary
  index) — read `SEEK_CONSTANTS.md` before touching this.

- **[2026-07-12] Chapter-slider load-time retrace: the flow-animation target and the actual
  restore seek disagree by `_CHAPTER_BOUNDARY_EPSILON` (0.35s).** Found while investigating the
  compounding seek-drift bug (branch `fix/seek-drift-logical-position`, not yet merged) — this
  started as a hypothesis (originally called "Finding 5" on that branch) that the retrace was the
  same `_logical_pos`-fixable raw-`time_pos` residual as the drift bug, but that hypothesis was
  **disproven by live log data, not assumption**: every captured book-load restore-seek settles
  with zero residual (`_is_embedded_m4b` isn't set yet when `_restore_position`'s seek runs, so the
  paused-undershoot compensation never applies to it — separate quirk, not this bug). The REAL
  cause, traced after that disproof: `_on_file_loaded_populate_chapters` (`app.py:1574`,
  `_on_file_loaded_populate_chapters`) computes the CHAPTER SLIDER's flow-animation target with
  `_CHAPTER_BOUNDARY_EPSILON` (+0.35s) baked in unconditionally for every non-VT book
  (`seek_offset = 0.0 if VT else _CHAPTER_BOUNDARY_EPSILON`), while `_restore_position`'s actual
  seek (`app.py:1665`, `seek_async(book_data.progress)`) deliberately omits any offset — per its
  own comment, restore is not chapter navigation and has no boundary to clear. **The bug is that
  these two independently-computed values disagree, not that either is individually wrong for its
  own purpose** — the animation target assumes a chapter-navigation-style landing offset that the
  real seek was never going to produce. On a short chapter (5-25s, confirmed live) the mismatch is
  a large, highly visible fraction of the slider's width: the slider animates to
  `progress + 0.35`, then visibly retraces back to the true `progress` once the 200ms timer starts
  reading the real (unoffset) position. **This is a separate, third bug from the compounding-drift
  fix on that branch and is NOT fixed by `_logical_pos`** — neither of the two mismatched values
  reads `player.time_pos`, so nothing about the drift-fix branch's `time_pos`-getter change touches
  this at all. If revisited: `_on_file_loaded_populate_chapters` should not apply
  `_CHAPTER_BOUNDARY_EPSILON` when computing the load/restore animation target, mirroring
  `_restore_position`'s own no-epsilon reasoning. **Correction (2026-09-16): the "Finding 5" trace
  this cited (`SEEK_DRIFT_MEASUREMENTS.md` on branch `fix/seek-drift-logical-position`) is a dead
  reference — that branch is already merged and deleted, and the file has no commit history
  anywhere in the repo (`git log --all -- SEEK_DRIFT_MEASUREMENTS.md` returns nothing; confirmed
  via `git branch -a`). Re-derive from `app.py:1574` vs `app.py:1665` (the two line numbers cited
  above) rather than looking for that file — see `SEEK_CONSTANTS.md`'s own "dead link" note on the
  same file for the parallel case.** Part of the "Seek-landing precision at chapter boundaries"
  group (see that heading in the summary index).

- **[2026-07-12] `_PAUSED_SEEK_UNDERSHOOT_COMP` (0.37s) is applied unconditionally to every paused
  embedded-M4B seek, not gated on chapter-boundary proximity. Still UNFIXED — a fix attempt was
  made and reverted 2026-07-14; read that writeup FIRST, it is not this entry's original framing.**
  Found while investigating the compounding seek-drift bug (branch `fix/seek-drift-logical-position`,
  not yet merged). The constant's ORIGINAL purpose (CLAUDE.md, Session 3, 2026-06-13) was
  chapter-boundary landing precision — Prev/Next skipping a chapter's first word, or paused
  Prev/Next re-resolving the chapter just left. But the actual gate in `seek_async`
  (`if self._is_embedded_m4b and self._cached_pause:`) checks only file format and pause state — no
  boundary-proximity check at all. It fires on every paused seek, including genuinely mid-chapter
  ones (`seek_within_chapter` via a chapter-slider click, `_restore_position` on book-load) that
  have nothing to do with chapter navigation. Real but NOT compounding/urgent — a single bounded
  per-seek error, not a progressive drift.

  **2026-07-14 attempt — implemented, unit-tested, found structurally wrong, fully reverted (no
  code merged to `main`).** A "gate on whether the compensated command crosses a `_chapter_list`
  boundary" design was built, then failed its own test for ordinary chapter navigation, then was
  traced to a category error, not a tuning problem: the gate checked whether the artificially
  inflated mpv COMMAND crosses a boundary, when the whole point of the compensation is that the
  command and mpv's real landing are different numbers by design (the command is inflated
  specifically because mpv undershoots it back down). A bare position number can't recover whether
  a given seek's crossing was INTENDED (chapter nav, labeled skips — every "must land exactly"
  caller) or accidental (only freeform slider drag/click has no stated numeric contract, and is
  the one "approximate is acceptable" case) — that information exists at the call site and is
  discarded before it reaches `seek_async` today. **Full mechanism, the two-category model, and the
  corrected direction for a next attempt (destination seeks should pass an explicit intent signal
  to `seek_async`, not have it inferred from arithmetic) are written up in NOTES.md,
  "`_PAUSED_SEEK_UNDERSHOOT_COMP` boundary-crossing gate — IMPLEMENTED, TESTED, FOUND STRUCTURALLY
  WRONG, REVERTED" (2026-07-14) — read that before attempting this again; do not restart from this
  entry's original 07-12 framing or from the abandoned plan file
  (`.claude/plans/come-to-think-of-silly-sun.md`, which reflects the now-known-wrong design and is
  NOT a blueprint).** Also separately confirmed and worth carrying forward: the visual "sliver,
  retraces" drift on short chapters is a DISPLAY/ANIMATION-timing problem distinct from landing
  precision — even a perfect seek-precision fix would not by itself resolve it. `seek_async` remains
  exactly the heavily-scarred, repeatedly-reverted function the "Seek/position tracking — VT+Undo
  is the known-fragile zone" CLAUDE.md rule is about; any future attempt needs its own
  investigate-then-plan cycle, live-verified against the exact stuck-Next/Prev bug this constant
  was built to fix, same as before. **This is the anchor entry for the "Seek-landing precision at
  chapter boundaries" group** (see that heading in the summary index) — the other entries in that
  group are downstream symptoms/sightings of the same underlying imprecision, and a future
  investigation should tackle all of them together against the corrected "explicit intent signal"
  direction above, not just re-attempt this one constant's gating in isolation. Also read
  `SEEK_CONSTANTS.md` for the full constant-interaction map before changing anything in this area.

- **[2026-09-16] Chapter-start narration clipping — corroborating sighting, part of the "Seek-landing
  precision at chapter boundaries" group above, no new information beyond confirming the issue is
  still live.** Surfaced during live testing of an unrelated smart-rewind fix (see CLAUDE.md's
  "Smart rewind on resume" section, 2026-09-16): landing exactly at a chapter's nominal start —
  via smart rewind's chapter-start clamp, the `|<`/Prev button, or ordinary chapter nav through
  `_chapter_seek_offset()` — can clip the first fraction of a second of narration (e.g. "apter two"
  instead of "Chapter two"). Confirmed to reproduce identically via plain Prev with smart rewind not
  involved, so it is not a smart-rewind bug. This matches the ORIGINAL purpose statement of
  `_PAUSED_SEEK_UNDERSHOOT_COMP` in the entry directly above ("Prev/Next skipping a chapter's first
  word") almost exactly — very likely the same root cause, not a new issue. No fix attempted; folded
  into this group rather than opened as a separate investigation.

- **[2026-07-14] Right-click a chapter notch while paused can leave a small residual clip on books
  with audio at the very chapter start — minor, deferred.** Notch-click starts playback as part of
  the seek, so `_PAUSED_SEEK_UNDERSHOOT_COMP`'s paused-seek compensation only partially covers the
  landing (by the time compensation would fully apply, playback has already begun). See TESTING.md's
  "Undo / right-click notch (paused embedded)" checklist, which marks this as a known, accepted gap
  rather than a checklist failure. Part of the "Seek-landing precision at chapter boundaries" group.

- **[2026-07-31] DESIGN: `ScrollHoverTracker.suspend()` is the coexistence hook for mouse vs.
  keyboard highlighting.** `ui/hover_tracker.py` keeps the hovered row as explicit state
  (`hovered_row`) rather than leaving it implicit in Qt's styling, and exposes `suspend(bool)` so
  keyboard navigation can take ownership of the selection without a second highlight rendering.
  Written for the eventual Stats/Tags keyboard nav, which has since shipped via a different
  mechanism (`_pickup_cursor_anchor`/`GridHoverTracker`, 2026-09-15) — worth confirming whether
  that mechanism actually routes through `suspend()` as this entry predicted, or supersedes it.

  The Library-specific instance of this same problem (mouse resting over a row producing two
  highlights during PageUp/PageDown, and `Alt+Enter` opening the mouse's book instead of the
  keyboard-selected one) is now FIXED — see TODO_ARCHIVE.md, "[2026-09-08, FIXED 2026-09-18]
  Library keyboard nav didn't yield to mouse hover during pagination." The remaining open question
  here is narrower: whether `ScrollHoverTracker.suspend()` itself is the mechanism other panels
  should converge on, or whether the poll-based design Stats/Library both ended up using instead
  should be considered the standard going forward.

- **[2026-07-10] DECIDE: PageUp/PageDown jump distance in the library list.** `52b7abb` fixed
  PageUp/PageDown/Home/End so the viewport actually follows the selection (they were never
  broken navigation-wise, just invisible — `setAutoScroll(False)` ate the native scroll-follow).
  Left as Qt's native page-jump distance, unexamined. Native Qt typically pages by roughly one
  viewport's worth of rows, which may or may not be the right feel per view mode (five very
  different row heights: List's ~28px rows vs. Square's ~95px cells vs. 1-per-row's ~159px).
  Decide whether to override the jump distance (and if so, to what — e.g. a fixed row count, or
  something tied to `ITEM_DIMENSIONS`/`cols` like the existing wheel-scroll fix's
  `rows_per_screen * cell_h` computation) or leave native behavior alone. Not yet tested live
  across all five modes to see whether native feels right or wrong anywhere.

- **[2026-06-23] Slider→muted-icon transition is abrupt.** When volume hits 0% with no sleep timer
  active, `_show_volume_overlay` jumps straight to the muted icon with no transition (see
  `ed563a4`/`81734d3` — this was a deliberate choice to skip the slider preview, not an oversight).
  Visually it reads as a hard cut. Idea floated: a quick two-sided mask/wipe that conceals the
  volume bar first, then reveals the muted icon, rather than an instant swap. Needs a concrete
  animation design before implementing — not just "add a fade."

- **[2026-07-03] DECIDE: excluding the currently-playing book behaves differently for M4B vs VT.**
  Not a bug to fix — a design decision to make later. When the loaded/playing book is excluded
  (user-trash) or flagged missing while playing, single-file **M4B** books keep playing (only the
  library row disappears); **VT** (multi-file MP3) books drop to the no-book-loaded screen. Both
  are "correct" in isolation — the divergence is the open question. Observed while verifying the
  `is_missing OR is_excluded` teardown fix (`a48dc3d`, 2026-07-03); the fix itself is format-
  agnostic (it just decides *whether* teardown fires), so this divergence lives downstream in how
  playback survives an excluded/missing book, not in `_on_scan_finished`. Known and deliberately
  tolerated: an M4B continuing to play a since-removed book hurts nothing and only holds memory
  already loaded, so it's been left as-is. Decide later whether to (a) make both formats keep
  playing, (b) make both drop to no-book, or (c) formally document the split as intended. No action
  until then; captured so it isn't rediscovered as a "bug" and reflexively "fixed."

- **[2026-07-01] Book Detail panel slide-in feels less smooth from Library than from Stats.**
  User observation, unconfirmed and not yet investigated: right-clicking a book row in the Library
  panel to open Book Detail feels janky compared to clicking a book row in the Stats panel to open
  the same panel — same target panel (`open_book_detail` → `_start_book_detail_entry`,
  `panels.py:578`), so if real, the difference is in what's already on-screen underneath, not the
  panel itself. One structural note found while checking: `_start_book_detail_entry` does NOT touch
  `blur_animation` at all (every other `_start_*_entry` — library/settings/speed/stats/sleep/tags —
  starts/stops it), so whatever blur state the currently-open panel left in place just carries over
  unchanged; unclear if that's relevant. User also flagged this may just be "noticing now because
  I'm paying attention" rather than a real regression — needs a clean side-by-side comparison
  before concluding anything. Do not conflate with the sidebar-bleed-through investigation
  (NOTES.md, same date) — confirmed structurally unrelated: Book Detail never routes through
  `_on_sidebar_closed_for_panel` (no sidebar trigger button opens it; it's reached only from
  library rows, stats rows, and tag chips), so that fix does not touch this path at all.

- **[2026-07-30] In-app help section.** The intended home for all in-app reference material.
  Raised while looking for somewhere to document the library search operators (`#tag`, `_prefix`,
  `@author`, `=year`, `>year`, `<year`, ranges — shipped 2026-07-30, `456796c`), which currently
  exist only in `KEYBINDINGS.md`. That is the same state that let `_` be forgotten by its own
  author for months.

  **Two placements were tried and rejected on evidence, not theory:**
  - A tooltip on the search field. Built, then removed the same session (`6f82141`) — the full
    operator set needs eight rows, which in a 300px-wide window either renders outside the app
    or covers the library behind it. Both observed live.
  - Settings > Library. Measured at ~120px tall for eight rows at settings body-font size, versus
    a folder-list box capped at 70px in a tab already holding five sections plus the Excluded
    Books line. Would have needed the `ExcludedBooksSection`/`ExcludedBooksPopup` popup pattern,
    and the tab has no room even for the toggle line.

  The Controls tab had been informally reserved for this, but controls are settled and it is the
  wrong home for reference material generally.

  Blocked on: nothing technical — it is a design/scope decision about what the help surface is
  (a panel? a popup? its own overlay?) and it should be built once, after the feature set stops
  moving, so it can cover everything at once rather than growing per-feature.

- **[2026-06-27] Excluded Books popup (`ui/excluded_books.py`) corner-radius mismatch.**
  The popup's selection highlight is flat/square; `settings_folder_list`'s is rounded (`4px`).
  Should match (one or the other) since they're both "selected row in a themed list" in the same
  panel. Narrowed 2026-07-15 from a four-issue entry after audit: the `::item:selected` color
  inconsistency is moot (the popup now disables selection entirely — `NoSelection`, see
  `excluded_books.py`'s `set_theme` comment); the bg_deep/bg_dropdown background mismatch was
  closed as not worth chasing.
  **Reminder for the eventual full per-theme color pass** (see the "Remove theme inheritance from
  The Color Purple" entry below, and SESSION.md's alphabetical library-color pass): re-check the
  Excluded Books popup generally as part of that pass — both this corner-radius mismatch and
  general contrast/legibility across themes — since the popup is hidden whenever no book is
  excluded and is easy to forget about otherwise. Not theme-specific; no single theme needs
  singling out.

- **[2026-06-25] Pre-release cleanup pass (bundle into one commit, not piecemeal).** Narrowed
  2026-07-15 after audit — the third original sub-item (switch VT playlist-resolution temp files
  from `delete=False` to `delete=True`) is stale: that `ffmetadata`/`concat` tempfile mechanism in
  `_resolve_playlist` no longer exists, removed in `95ab53e` before this entry was even written.
  Remaining:
  - Remove the `Q`-key quote-rotation shortcut (`app.py`, testing-only — already flagged inline as
    `# TODO: remove before release — testing only`).
  - Remove stray debug `print()`/timing instrumentation left in `player.py` (`[load_book]`,
    `[VT-DESYNC]`, metadata-extraction-error, af-command-error) — the original sub-item named
    `_close_session`/`_on_file_ready`/`_on_book_selected_from_library` specifically, but session-close
    logic has since moved into `SessionRecorder.close()`, so those exact function names are gone;
    the underlying ask (strip leftover debug prints before release) still applies to what's there now.
  See NOTES.md "Cleanup Deferrals — Pre-existing, Deliberate" (~line 2108) for original context.

- **[FUTURE REDESIGN, 2026-07-14] Incremental/`@Property` color animation instead of whole-theme
  stylesheet swap + overlay punch-through — explicitly SEPARATE from Findings 1/2/3 and from the
  RANK-1 fix; not investigated, not designed, out of scope for now.** Raised by Pryme while the
  cold-launch theme work was in flight. The reasoning worth preserving: the current architecture can
  only change colors by regenerating and re-applying whole stylesheets — a full-widget-tree
  `_apply_stylesheets` pass — which is precisely the ~400ms synchronous main-thread cost that is the
  measured root of Race 3, Regime B, and RANK-1 in the first place (median 318ms, pipeline median
  442ms, max 759ms; `mw.setStyleSheet(base)` alone is ~180ms because Qt re-polishes every
  descendant — see `review/Report_260714_synchronous_main_thread_work.md`). An incremental approach
  — animating individual colors via `@Property` on the widgets that need them, rather than swapping
  the whole stylesheet and masking the transition with a full-window overlay — might not need that
  pass at all, which would dissolve the cost rather than sequence around it.
  **Known prior art / why this is big, not a quick win:** NOTES.md 2026-06-19 ("Main-window theme
  fade interrupt ... full color-animation rework DEFERRED") records that this exact rework was
  **started in a prior session and abandoned as ~40–80h with high regression risk** — every
  QSS-styled widget (buttons + their `:hover`/`:pressed`/`:disabled` states, panel chrome, Themes-tab
  pool items, gradients, cover-derived colors) would need converting from QSS-driven coloring to
  custom-paint `@Property` coloring, because QSS pseudo-states have no custom-paint equivalent and
  would each be reimplemented by hand. The cheaper middle path (snap panel chrome instantly, keep
  slider tweens) was **explicitly rejected by Pryme** — instant theme snaps read as jarring/violent,
  which is the whole reason the overlay fade exists. Also relevant: `ClickSlider` ALREADY paints from
  `@Property` colors rather than QSS at paint time — it is the one widget class where this model is
  already proven in-tree (and, not coincidentally, the one whose colors can get stranded — see the
  2026-06-19 entry).
  **Status:** a real, recorded idea with a real prior estimate against it. Do NOT fold into
  Findings 1/2/3 or the RANK-1 fix — if it is ever picked up it needs its own investigate-then-plan
  cycle sized against that 40–80h prior estimate, not a mid-fix scope expansion.

- **[RANK-2, 2026-07-14] Close the P1↔P2 race precondition structurally (insurance, not a live-bug
  fix) — deferred, deliberately separate from the RANK-1 theme-apply fix.** The structural hazard:
  a Qt-queued writer (`_vt_restore_pending`, written via the `book_ready`→`_on_file_ready`
  QueuedConnection at `app.py:389`) racing an mpv-thread reader (`_on_file_loaded`'s read of it),
  exposed whenever ANY ~100ms+ synchronous main-thread op starves the Qt queue in that window. Today
  the only such op is theme-apply (fixed narrowly by RANK-1), but the pattern re-opens for the next
  heavy sync op anyone adds later (a heavier chapter populate, a sync DB migration, etc.). Feasibility
  already investigated (see `review/Report_260714_theme_apply_safety_feasibility.md`, RANK-2 section):
  - **VT path:** both `book_ready` emit sites (`ungate_play`, `_on_playlist_resolved`) run on the Qt
    main thread, so a Direct (non-queued) connection COULD run `_restore_position`/`defer_vt_restore`
    synchronously before the subsequent `_apply_pending_cover_theme`, removing the race precondition
    entirely for VT. **But** `book_ready`/`_on_file_ready` is a single shared connection (can't be
    Direct-for-VT / Queued-for-non-VT without a second signal or per-emit juggling), the VT emit is
    deliberately placed BEFORE `instance.play()` (CLAUDE.md book_ready invariant), and making restore
    synchronous there changes the timing the shipped VT fixes (`_on_vt_file_switched` gated clear,
    `_on_end_file` ERROR reset, `_logical_pos`) were verified against — so it TOUCHES the blast radius
    of the VT-fragile zone even without editing those functions.
  - **Non-VT path:** `book_ready` is emitted from the mpv thread, so the QueuedConnection is
    MANDATORY thread-marshaling — the precondition cannot be removed at all; non-VT's only protection
    is "don't run a long sync op in the window" (i.e. the RANK-1 fix).
  - **Why deferred, not done now:** it's insurance against a hypothetical future sync op, not a live
    bug (RANK-1 closes all three currently-observed victims); its cheapest shape still re-architects a
    connection in the highest-risk zone in the codebase. If ever attempted, it needs its own
    investigate-then-plan cycle and the full VT+Undo verification bar (`tools/fs_race_harness.py`,
    `tools/vt_restore_race_harness.py`, live checklist) re-run — NOT bundled with RANK-1. Captured
    here so this structural risk is dated and tracked, not left buried in a review report.

- **[RANK-LOW, MEASURED 2026-07-14] App-start flow-animation baseline roughness (Regime A) — a
  standalone ~70ms hitch at animation start, independent of everything else.** Present on EVERY cold
  launch of EVERY book type, cover on or off, with no theme apply anywhere near the window (worst
  frame gap ~70–76ms median, never observed >108ms). A synchronous burst at animation start:
  chapter-list `populate` + repeated `_update_chapter_label_from_index setCurrentRow` calls + the
  first mpv `time_pos` samples, all landing in the animation's first ~50–90ms. Real but
  sub-perceptible-to-mild — a rough *start*, not a freeze. **Independent of P1/P2/P3 (confirmed by
  measurement — occurs on M4B and MP3, which have no `_vt_restore_pending`/`file_switched` at all)
  and independent of the RANK-1 theme-apply hazard.** This is the ONLY part of the old combined
  "flow-animation stutter" item that is a genuine standalone animation-timing bug — it is what the
  original 2026-07-13 trace-only investigation correctly found (it was right about this, blind to
  Regime B). **Verification bar for any fix touching this or near-app-start VT load timing:** re-run
  `tools/fs_race_harness.py`, `tools/vt_restore_race_harness.py`, and the VT+Undo checklist, since
  any timing change near app-start VT loading risks interacting with the `_vt_restore_pending`/
  `file_switched`-guard fixes. Full detail in NOTES.md (2026-07-14) and
  `review/Data_260714_flow_animation_stutter.md`.

  *Historical note: these two entries replace a single 2026-07-13 "first-app-launch-only VT
  flow-animation stutter" item that was traced (code-reading only) to the progress slider's own
  `QPropertyAnimation` glide and believed to be one isolated bug. The 2026-07-14 live measurement
  found it was two genuinely different bugs with different ranks — keeping them as one entry would
  recreate the "one bug wearing two names" confusion the investigation resolved. The original trace
  was right about Regime A and blind to Regime B; its "the trace found nothing, not a live-forced
  test showed nothing" caveat is what prompted the measurement that split them.*

- **Dead-code cleanup: `QComboBox`/`QScrollArea`/`theme_selector_container` rules in
  settings stylesheet.** Surfaced during the same stylesheet-split investigation.
  These selectors (`QComboBox` and all sub-selectors, `QScrollArea`,
  `QWidget#theme_selector_container`, `QScrollArea QWidget#qt_scrollarea_viewport`)
  don't match any widget currently constructed in Settings, Speed, or Sleep — no
  `QComboBox` or `QScrollArea` is built anywhere in these three panels today. Left
  in place (bucketed as settings-specific, no-op either way) during the split rather
  than investigated. Needs its own pass to confirm they're genuinely dead (not
  matching something constructed dynamically or in a code path not checked) and, if
  so, remove them. Not urgent — no live effect either way.

## In Progress

(none)
