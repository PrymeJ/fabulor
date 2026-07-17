# Theming/animation — current state as of this exact commit

Committed at `5cfe3a3`, live-verified against the running app (log evidence cited below, not
inferred from code reading alone). This document describes what runs NOW. It is not a history and
proposes no fixes.

---

## 1. Every theme-apply trigger, what it calls, what it styles

| Trigger | Entry point | Code path | What gets styled (live-confirmed) |
|---|---|---|---|
| **App startup** | `MainWindow._setup_ui`, line ~682 | `theme_manager.apply_full_pass(_current_theme_name)` | **BOTH.** `apply_full_pass` calls `_apply_stylesheets` (visible: mw/title_bar/content_container/chapter_list_widget/sidebar/**settings_panel/speed_panel/sleep_panel**) then `_apply_stylesheets_deferred` (library_panel/stats_panel/book_detail_panel). Log: `[_apply_stylesheets hover=False] ... settings/speed/sleep panels=32.6ms` immediately followed by `[_apply_stylesheets_deferred] ... library_panel=4.9ms stats + book_detail panels=29.4ms` (16:31:44,752 / 16:31:44,787). |
| **Book load (no cover, or cover-theme mode "off")** | `_apply_main_cover` → `theme_manager.apply_cover_theme(pixmap)` OR `_show_no_cover_state` → `theme_manager.clear_cover_theme()` | `clear_cover_theme` → `_on_theme_changed(_current_theme_name, save=False)` | **NEITHER, in practice** — hits the same-theme-name no-op guard (`theme_name == _active_display_theme`) and returns immediately. Confirmed live: `EARLY-RETURN no-op guard theme_name='Hear Me Roar' _active_display_theme='Hear Me Roar' ... _apply_stylesheets NEVER CALLED`. This is CORRECT now (not a bug) because startup's `apply_full_pass` already styled everything with that exact theme name — there is nothing left to apply. |
| **Book load (cover-theme mode "with_pool"/"exclusive", book has a cover, and the cover's derived theme differs from the pool theme already applied)** | `_apply_main_cover` → `apply_cover_theme(pixmap)` | `build_cover_theme` succeeds → `_on_theme_changed(theme_dict, ...)` — different theme_name than `_active_display_theme`, so the no-op guard does NOT fire | **BOTH**, via the same `not hasattr(self, '_fade_anim')` early branch → `apply_full_pass(theme_dict)` (this branch only exists before `initialize_fade_overlay()` runs, i.e. still inside startup/first book load). Not separately re-verified live this session with a real cover in a fresh with_pool/exclusive launch — see open items below. |
| **Cover-theme rotation** (`T` key / rotation timer, `_rotate_theme`) | `ThemeManager._rotate_theme` | Eventually calls `_on_theme_changed(new_name, ...)`; `_fade_anim` exists by now (post-startup) | **BOTH**, via the fade-animation body: `_apply_stylesheets` (visible + settings/speed/sleep) runs synchronously inline, then `_schedule_deferred_restyle` arms `_apply_stylesheets_deferred` (library/stats/book_detail) on the next event-loop turn (`_run_deferred_restyle`, deferred further if a flow animation is running). |
| **Hover (mouse over a theme swatch in Themes tab)** | `_on_theme_hovered` → (80ms debounce) → `_fire_pending_hover` → `_on_theme_changed(name, hover=True)` | Falls through to the fade-animation body (`_fade_anim` exists); `hover=True` | **Visible pass only, including settings/speed/sleep — by design.** Log line, real user interaction, 16:21:55: `[_apply_stylesheets hover=True] ... settings/speed/sleep panels=76.7ms`. `library_panel`/`stats_panel`/`book_detail_panel` are intentionally skipped on hover (they're always hidden while the Themes tab is open — hover-exit runs a full non-hover restyle before any of them could ever be shown stale). |
| **Theme-pool selection / "Change now"** | Settings UI → `_on_theme_changed(name, user_initiated=True, ...)` | Same fade-animation body as rotation | **BOTH** — same shape as rotation. |
| **Panel open** (Library/Settings/Speed/Sleep/Stats/Tags/BookDetail, mouse or keyboard) | `PanelManager._open_*_flow` → `_complete_main_fade()` → `theme_manager.complete_main_fade()` | `complete_main_fade` calls `self.flush_deferred_restyle()` FIRST (before its own `_fade_in_flight` early-return) | Forces any PENDING deferred batch (library/stats/book_detail) to run synchronously before the panel shows, so a panel can never open onto a stale invisible-surface style. Since settings/speed/sleep are no longer part of the deferred batch (fixed tonight), this flush is now only relevant to library/stats/book_detail panels opening stale — settings/speed/sleep are always current the instant any `_apply_stylesheets` call has run, hover or not. |

---

## 2. Known-open items — status right now, in the current working tree (all committed at `5cfe3a3`)

- **Theme-hover regression (settings/speed/sleep panels not previewing on hover): FIXED.** Live-confirmed twice — once via your own real hovering at 16:21 (log: `settings/speed/sleep panels=76.7ms` under `hover=True`), and again structurally by moving that styling block out of the not-hover-gated `_apply_stylesheets_deferred` back into the always-run `_apply_stylesheets`.
- **Cover-theme-mode "OFF" no-op (bare Qt chrome bug): FIXED, but the ORIGINAL diagnosis of it was wrong and later corrected.** The real defect was never `apply_cover_theme`'s off-branch (that branch's fix, routing through `clear_cover_theme()`, was necessary but not sufficient) — it was that `_setup_ui`'s startup call never ran the deferred/invisible pass at all, so the *later* `clear_cover_theme()` call had nothing to do (hit the no-op guard) and there was no other trigger to fall back on. Fixed via `apply_full_pass`.
- **Missing-invisible-pass-at-startup bug: FIXED** — this is the same bug as the line above, described from the other direction. `_setup_ui` now calls `apply_full_pass` instead of `_apply_stylesheets` alone.
- **Uncommitted work: NONE remaining in the four theming-related files** (`app.py`, `theme_manager.py`, `logger_setup.py`) as of commit `5cfe3a3`. `NOTES.md`/`TODO.md` are still uncommitted as of this writing — docs commit is the very next step after this document.
- **Temporary trace instrumentation left in place, on purpose** (per this project's standing policy of keeping diagnostic logging rather than stripping it): the `EARLY-RETURN no-op guard` log line in `_on_theme_changed`, and the `caller=...` frame identification in `apply_cover_theme`. Neither affects behavior — both are `logger.debug` calls only.

---

## 3. Progress-persistence (Bug 1 / Bug 2) — separate system, NOT in question

These are unrelated to every line above. Restating plainly so there is one fixed point that is not
up for re-litigation:

- **Bug 1** (non-VT restore transient laundering a near-zero position permanently into the DB): **FIXED, committed, live-verified** via repeated `[PERSIST-TRACE]` log capture across natural occurrences. Mechanism: `_sync_persistence` gained a monotonic guard seeded from the incoming book's real DB progress (not `0.0`).
- **Bug 2** (VT cross-file restore rendezvous race silently dropping the restore-seek): **FIXED, committed, live-verified** via `Player._vt_file_loaded_awaiting_restore`, an order-independent rendezvous flag consumable by either the arrival of the file-loaded event or the arrival of the restore target, whichever comes second.
- Both fixes are in commit `f601da0`. Both are independent of every theme/styling mechanism described in sections 1-2 above — nothing this session touched `_sync_persistence`, `defer_vt_restore`, or `_vt_file_loaded_awaiting_restore` again after that commit.

---

## 4. What is NOT yet known — genuinely open, no fix implied

- **Library-panel stutter on open**: profiling traced one occurrence to cold `_sized_cover_cache`
  misses forcing synchronous LANCZOS resizing during the open animation, but repeat testing
  (including against the pre-narrowing baseline) has **not reproduced consistently enough to
  confirm root cause or verify a fix**. Not resolved. Not caused by tonight's theming fixes either
  (predates them).
- **Regime A** (the `setCurrentRow` visibility-gate fix for the chapter-list-populate hitch at
  animation start): implemented and re-verified as real and correctly scoped (helps VT/cover-OFF
  only), but **every benchmark number gathered for it during this investigation was run against
  the broken cover-OFF startup state** (bare Qt chrome, panels unstyled) — those numbers are void
  and have not yet been re-run against tonight's fix. No decision has been made on whether/how to
  re-run them.
- **VT/cover-ON severe stutter** (the "flow, pause, jump, pause, flow" pattern you described): root
  cause was traced to a real mechanism — `_apply_stylesheets`'s synchronous `mw.setStyleSheet(base)`
  (~193-210ms) running inside `_on_theme_changed`'s no-`_fade_anim` early branch, triggered by a
  SECOND `apply_cover_theme` call from the post-library-scan cover-refresh
  (`library_controller.py`), landing mid-flow-animation. **No fix has been proposed or implemented
  for this.** It is unclear whether tonight's `apply_full_pass` change interacts with this at all —
  not yet checked.
  - **Caller `app.py:1666 in _apply`** does appear in tonight's own log (16:31:52 and 16:31:58,
    both hitting the same no-op guard) — confirming this second-call mechanism is still live and
    unaddressed, just currently harmless in the cover-off case because there's nothing left for it
    to skip. Whether it's harmless in the cover-ON case (where a real, different theme WOULD need
    applying) is the open question this item already flagged, still unresolved.
- **Whether a real cover + with_pool/exclusive mode still produces the correct sequence live**:
  traced through the code (section 1's third row) but not independently re-confirmed live this
  session with a fresh cold launch against an actual cover image in that mode. Should be checked
  before treating that scenario as fully closed.
