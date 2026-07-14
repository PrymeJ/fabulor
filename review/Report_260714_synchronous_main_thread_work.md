Investigation Report: Synchronous main-thread work during app start / book load / theme change / panel slide
Method note
I added no instrumentation — the working tree is clean (git diff empty). All timings below come from two sources:

Pre-existing DEBUG instrumentation captured in today's fabulor.log (the [BOOKSWITCH-TRACE], [_on_theme_changed], and [_apply_stylesheets] tags left in place during the diagnosis session). This is a large real sample: 70 _apply_stylesheets runs, 33 full pipeline runs, 6 fully-traced book-switches.
One isolated read-only measurement of build_cover_theme in a throwaway subprocess (no repo writes).
The single most valuable finding is that the log already contains the exact race in bimodal form (below), so item 3 (mapping the known races) is not reconstructed — it's read directly off captured timestamps.

Item 1 — Inventory of synchronous main-thread operations
Durations are measured, not guessed. "Sync" = blocks the Qt event loop.

Theme change (the dominant cost by an order of magnitude)
Operation	Trigger	Sync?	Measured duration	Shared state touched
_apply_stylesheets (full, hover=False)	_on_theme_changed	SYNC, main thread	median 318ms, p90 463ms, max 639ms (n=70)	Rewrites QSS on the entire widget tree
↳ mw.setStyleSheet(base) (sub-step)	—	sync	median ~180ms, max 355ms — the single largest sub-step	Global base stylesheet → repolishes every descendant, including chapter sliders (→ collides with _set_chapter_ui_active, _bg_suppressed)
↳ settings/speed/sleep panels	—	sync	~68–127ms	—
↳ stats + book_detail panels	—	sync	~59–118ms	—
_on_theme_changed full pipeline	rotation / cover-art / hover-exit / apply_current_state re-apply	SYNC	median 442ms, max 759ms (n=33)	Wraps _apply_stylesheets + grab() + mask-build + theme_applied.emit fan-out + _refresh_panel_visuals
↳ theme_applied.emit(...) fan-out	inside pipeline (DirectConnection)	sync inline	~part of the 124ms pipeline−apply_stylesheets delta	stats_panel/tags_panel/book_detail_panel.on_theme_changed all run inline
build_cover_theme (dominant-color extraction)	apply_cover_theme	sync	~4–5ms (downsamples to 64×64 first — source size irrelevant)	none
Critical correction to the working model: the "cover-art-based theme" cost is not the pixel extraction — that's ~4ms. The cost is that a cover-art book-switch unconditionally forces a full _apply_stylesheets pass (the ~400ms above), whereas a plain non-cover book-switch does not fire one at all. The color scan is cheap; the theme application it triggers is the whole cost. Any future "make cover-theme async" work should target _apply_stylesheets/setStyleSheet, not cover_theme.py.

Book load
Operation	Trigger	Sync?	Measured / status	Shared state
_ensure_mpv() (MPV instance construction)	load_book	SYNC	Cold-start only — guarded by instance is None, instance persists across switches. Not a per-switch cost.	mpv thread lifecycle
_resolve_playlist (mode detection, file scan)	load_book → _ResolveWorker	ASYNC (QThreadPool)	off main thread	writes VT/chapter state, delivered back via queued _playlist_resolved
_restore_position → defer_vt_restore	_on_file_ready (queued off book_ready)	sync, cheap	~1–3ms itself	writes _vt_restore_pending (the race's consumer side)
_load_cover_art / _apply_main_cover	singleShot(0) in book-select	sync, cheap	QPixmap load; extraction deferred if a panel is visible	sets _pending_cover_pixmap
_update_cover_art_scaling	singleShot(0)	sync	cheap scale	—
flow animation (progress_slider.animate_to, _animate_percentage_label)	_on_file_ready	ASYNC (QPropertyAnimation/QVariantAnimation)	non-blocking	reads _switch.take_progress_target()
_on_file_loaded_populate_chapters	mpv file-loaded → queued	sync	chapter list rebuild; 150ms retry if duration not yet cached	_chapter_list, chapter UI
_on_file_loaded (VT seek issue + file_switched.emit)	mpv event thread	runs off-Qt	—	reads _vt_restore_pending, _seek_target, is_seeking (producer side of all three races)
App start
Operation	Sync?	Status
build_streak_grid_cache	SYNC	one-time, DB seed of 364 rows + active-day flip. Not measured live but bounded (single rolling window); runs before UI shown.
_setup_ui (widget construction)	SYNC	one-time
_check_library_status → apply_current_state	sync	can call _apply_stylesheets (via _set_bg_suppressed) at startup
_ensure_mpv (first book)	SYNC	the heavy one-time MPV init
start_idle_preload	deferred 4–5s, batched, off-thread LANCZOS	non-blocking by design
Panel slide
Operation	Sync?	Status
All panel slide animations (*_animation.start(), blur)	ASYNC (QPropertyAnimation)	non-blocking
_on_library_hidden handler body	SYNC	This is the load-bearing one — it calls ungate_play() (queues book_ready consumer) and then synchronously calls _apply_pending_cover_theme() → the ~400ms theme apply, in the same call stack. This is where the starvation is injected relative to the restore consumer.
Item 2 — Cross-thread producer/consumer pairs
The one hazardous pattern, plus a full enumeration of what sits on each thread:

Threads involved: (a) Qt main thread (all UI, _apply_stylesheets, _restore_position, all singleShot/queued slots); (b) mpv MPVEventHandlerThread — a single background thread dispatching all mpv event_callback + observe_property handlers (confirmed in NOTES.md by reading python-mpv's installed source); (c) QThreadPool workers (_resolve_playlist, CoverLoaderWorker) — results always marshaled back via queued signals, so not directly hazardous.

#	Producer	Consumer	Mechanism between	When consumer can be delayed enough to miss
P1	ungate_play emits book_ready (main thread)	_on_file_ready → _restore_position → defer_vt_restore (sets _vt_restore_pending)	Qt.QueuedConnection (app.py:389)	Consumer is queued behind whatever runs synchronously next on the main thread. In _on_library_hidden, that next thing is the ~400ms _apply_pending_cover_theme. ← the confirmed race
P2	mpv file-loaded event fires _on_file_loaded (mpv thread) — reads _vt_restore_pending	itself	direct (mpv thread), no lock vs the main-thread writer	mpv thread runs immediately, unaffected by Qt being blocked. If P1's writer hasn't run yet, this reads None.
P3	_on_file_loaded issues VT seek + file_switched.emit() (mpv thread)	_on_vt_file_switched clears is_seeking (main thread)	Qt.QueuedConnection	Clear can land before the seek's settle sample arrives → orphans _seek_target (the general file_switched race — fixed by the gated clear).
P4	theme_applied.emit (main thread)	stats/tags/book_detail on_theme_changed	DirectConnection (sync inline)	Not a race — but it's why the pipeline (442ms) exceeds bare _apply_stylesheets (318ms).
The structural hazard is P1↔P2: a Qt-queued writer (_vt_restore_pending) racing an mpv-thread reader that is immune to Qt being blocked. Any long synchronous main-thread op landing between book_ready emit and the queued consumer opens this window. Today it's cover-art theme apply; it could be any future ~hundreds-of-ms sync op in that stack.

Item 3 — Mapping the three known races onto the inventory
All three place cleanly. The mapping is read directly from captured log timestamps, not reconstructed.

Race 1 — VT restore-on-load racing book_ready's pre-play() emit (fixed: _vt_restore_pending/defer_vt_restore). This is pair P1↔P2. At cold start nothing competes for the Qt loop, so P1's writer wins — which is exactly why 200 automated cold restarts passed. The mechanism (deferred restore) is the fix for the structural pair; it just assumed P1 always wins the race.

Race 2 — general _on_file_loaded "seek then unconditionally emit file_switched" (fixed: gated _on_vt_file_switched clear + _on_end_file ERROR reset). This is pair P3. Independent of theme timing — it's the mpv-thread emit racing the queued main-thread clear.

Race 3 — cover-art theme application starving _restore_position on book-switch (found, not fixed). This is P1↔P2 again, but on book-switch instead of cold start, with the ~400ms _apply_stylesheets (inventory item #1) as the blocker injected by _on_library_hidden's synchronous _apply_pending_cover_theme call. The captured bimodal proof:


book_ready emit → _on_file_ready gap, per switch:  420ms  444ms  419ms  |  2ms  0ms  1ms
When a theme apply lands in the window: ~420–444ms (restore starved, _on_file_loaded already read None). When none competes: ~0–2ms (restore wins). No values in between — the signature of a single ~400ms sync blocker. This is not a fourth pattern; it's Race 1's structural pair (P1↔P2) reached via a different trigger (book-switch's own theme apply) instead of cold-start timing.

All three fit. Nothing is forced. They are two structural pairs (P1↔P2 for races 1 & 3; P3 for race 2), differing only in what delays the queued consumer.

Item 4 — Ranked risk assessment (judgment, not fixes)
RANK 1 — CRITICAL: _apply_stylesheets / _on_theme_changed pipeline (median 442ms, max 759ms, synchronous).
This is the only operation in the inventory long enough to lose a queued consumer a race, and it has already done so — corrupting state (silent progress reset), not just visuals. It's the confirmed cause of Race 3 and the documented cause of two prior cosmetic bugs (2026-07-04 hover-fade, tonight's measurement). Its position is the worst possible: injected synchronously into _on_library_hidden right after the book_ready emit whose consumer it then starves. Any P1↔P2-shaped consumer scheduled anywhere near a theme apply is at risk. This is the single thing whose duration+position makes the whole territory fragile. It is the correct target for a future fix cycle (the NOTES.md direction — async/deferred theme application — points here; note the target is setStyleSheet, not the cheap extraction).

RANK 2 — MODERATE: the P1↔P2 cross-thread pattern itself, independent of theme.
Even if theme apply were made async tomorrow, the structural hazard remains: a Qt-queued writer racing an mpv-thread reader with no synchronization. Any future sync op ≥ ~100ms landing in that window (a heavier chapter populate, a synchronous DB migration, a future cover pipeline) reopens it. The deferred-restore mechanism papers over the common case but doesn't remove the pattern. Worth ranking above cosmetic items because it's the reusable failure shape.

RANK 3 — LOW: _ensure_mpv (cold-start MPV init, synchronous, one-time).
Genuinely heavy but runs once, before steady-state, with no queued consumer racing it. Safe as-is.

RANK 4 — LOW: build_streak_grid_cache (startup, synchronous DB).
Bounded (364-row window), one-time, pre-UI. No evidence of risk; recorded for completeness per the "don't assume safe" instruction — but nothing races it.

NEGLIGIBLE — flow animation, panel slides, cover scaling, _resolve_playlist, idle preload, build_cover_theme. All either async (QPropertyAnimation/QThreadPool) or <5ms. build_cover_theme specifically is ~4ms — explicitly cleared of the suspicion its name invites.

Answers to the two specific questions
TODO.md flow-animation-stutter entries — independent, or instances of this pattern?

The cover-theme-specific entry (2026-07-14, "VT progress restore silently resets on book-switch") is not independent — it is Race 3, i.e. P1↔P2 starved by the RANK-1 theme apply. It's the same thing this investigation maps, already correctly identified in that entry as "the third instance of synchronous main-thread theme cost."
The VT-specific entry (2026-07-13, "first-app-launch-only VT flow-animation stutter") appears independent of the starvation pattern. Per NOTES.md it was traced (code-trace only, not live-forced) to the progress slider's own QPropertyAnimation glide — an async animation that neither reads nor writes the deferred-restore seek or _on_file_loaded state. It sits in the RANK-negligible async-animation bucket, not the P1↔P2 hazard. Caveat carried from NOTES.md: that separability was established by code trace, not a live A/B against the actual stutter, and the VT chapter-walk in _on_time_pos_change now emits chapter_changed at a shifted time — so it should be re-verified live before being treated as fully closed. I did not re-verify it here (out of scope: investigation, no behavior change).
Anything related-in-kind but outside the four named moments?

Yes — theme_applied.emit's DirectConnection fan-out (P4). It's not one of the four moments and not a race, but it's the same shape (synchronous main-thread work chained onto a signal) and it silently adds the stats/tags/book_detail restyle inline to every theme apply — it's a meaningful slice of the pipeline−apply_stylesheets delta (~124ms). Any accounting of "how expensive is a theme change" that stops at _apply_stylesheets undercounts it. Worth noting for whoever sizes the RANK-1 fix: making _apply_stylesheets async doesn't automatically make this fan-out async — it's a separate synchronous chain hanging off the same emit.

Deliverables recap: full inventory (item 1) and cross-thread pairs (item 2) with real measured timings; all three known races placed as two structural pairs read off captured timestamps (item 3, nothing forced); ranked risk with RANK-1 theme apply as the load-bearing hazard (item 4). No fixes proposed. No code changed — working tree clean, no instrumentation to remove.

One decision worth surfacing before any follow-up work: the pre-existing [BOOKSWITCH-TRACE] DEBUG instrumentation is still in the tree (deliberately, per the diagnosis session's note). It's what made this investigation possible from a log alone — I'd recommend leaving it until Race 3 is actually fixed and the fix verified against it, matching the discipline NOTES.md already calls for. Want me to write this up as a NOTES.md entry, or leave it as this report?
