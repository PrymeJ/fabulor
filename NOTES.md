## Library cover thumbnails looked "pretty much the same" after a discovery + resampling fix — the real bottleneck was the paint-time downscale, not the source (2026-06-24)

**Starting complaint:** small grid thumbnails (3-per-row/Square, ~88-96px cells) had crumbling
cover text. User compared against The StoryGraph at a similar thumbnail size and confirmed the
size itself wasn't unusual — this was a resampling-quality question, not a "we're doing the size
wrong" one.

**Two real, independent bugs found and fixed first, both in `scanner.py`'s `_extract_metadata`:**

1. **Cover discovery only matched exact filenames** `cover`/`folder`/`front`/`art` (case-insensitive
   stem). 98% of the library was silently falling back to tiny embedded MP3/M4B tag art instead of
   available high-res external cover images. Fixed with a fallback: if no name match and the folder
   has exactly one image file, use it (almost certainly the cover, just unconventionally named); if
   multiple unmatched images exist, leave unset and fall through to the embedded-tag path rather than
   guess. Verified via a live survey of the real 380-book library DB: match rate rose from 8/380 (2%)
   to 354/380 (93%).
2. **Thumbnail resampling was `Qt.SmoothTransformation` (bilinear) into a no-quality-argument JPEG
   (~75 default) capped at 226×344** — both lossy and, on HiDPI, already short of the largest grid
   cell's real pixel needs. Replaced with a PIL pipeline: `QImage.convertToFormat(Format_RGBA8888)`
   → `Image.frombuffer` → `Image.Resampling.LANCZOS` to a 320×480 cap → `.convert("RGB")` →
   `.save(..., "JPEG", quality=88, optimize=True)`. New cache dir `thumbnails_v2` (old `thumbnails/`
   left orphaned on disk, never deleted — mixed-library safety).

**Both fixes landed, force rescan run — user reported "Made no difference."** This was not a
re-test-it-and-see situation: the user had old thumbnails saved locally and did an actual
before/after comparison, twice, and was right both times. The first time I'd claimed success off
metadata alone (resolution, filename match) without doing a real pixel comparison — wrong. The
second time I mischaracterized an aside the user made about Dolphin-file-manager-vs-app rendering
softness as if it were in-app evidence of a regression — the user had explicitly said Dolphin
doesn't matter, and called this out sharply. Both of those are logged in case the pattern repeats:
**when the user says "no difference," verify pixel-for-pixel at the real render size before
re-asserting anything — don't lean on file size/resolution proxies, and don't reframe an aside as
evidence for a claim the user didn't make.**

**Actual root cause:** the discovery + resampling fixes only improve the *source* thumbnail
(226×344 → 320×480, bilinear → LANCZOS). They never touch the *paint-time* step —
`BookDelegate._draw_cover`'s `painter.drawPixmap(rect, cover, src_rect)` — which still does one
more Qt bilinear downscale from the cached thumbnail down to the actual grid cell size (as small as
~88×88 up to ~292×159 depending on view mode). Feeding that final bilinear step a sharper, larger
source doesn't survive the step itself. Confirmed by simulating both old and new cached thumbnails
downscaled to real cell sizes with PIL `BILINEAR` (matching Qt's behavior) and visually comparing —
they were, as the user said, pretty much the same.

**Fix: pre-render per-cell-size pixmaps so paint time becomes a near-1:1 blit.** Added to
`BookDelegate` in `library.py`:
- `_sized_cover_cache: dict` (instance state, not the module-level `_cover_cache`) keyed by
  `(book_id, device_w, device_h)`.
- `_get_sized_cover(book, cover, target_w, target_h)` — lazily builds and caches a pre-scaled
  pixmap bounded to the target size (device-pixel-ratio aware), called from `_draw_cover` before
  its existing square/crop/letterbox branching. Deliberately a plain aspect-preserving bounded fit
  (NOT `KeepAspectRatioByExpanding` to the cell) — those branches derive their own crop/inset math
  from the source pixmap's real proportions, so over-cropping here breaks letterbox specifically.
  Only shrinks; never upscales a smaller source.
- `_lanczos_scale(cover, w, h)` — the actual resize, via the same PIL round-trip as the scanner fix
  (`Format_RGBA8888` before `constBits()`, same packing requirement and corruption risk if reordered).
- `evict_sized_cover(book_id)` wired into `LibraryPanel.evict_cover` and `refresh_book_cover` so a
  replaced/refreshed source cover doesn't leave stale pre-scaled entries behind. View-mode switches
  don't need eviction — the cache key already includes target size, so old-size entries just become
  unused, same low-volume staleness as the existing `_placeholder_cache`.

**Verified properly this time** — not metadata, actual pixel comparison at real cell size (96×146,
the 3-per-row dimension), both via a synthetic text image and a real cached cover ("Under Heaven").
Old bilinear-paint-time path vs. new pre-scaled-LANCZOS path: text was visibly, measurably sharper
in the new path on both. Then confirmed against the live app by the user directly.

**Second-round finding: plain LANCZOS swap measurably improved text but lost contrast/"punch" on
flat-color graphic covers** (SF Masterworks-style art was the clearest case — user's own framing:
"the same trade-off as the Dolphin vs app test — you lose crispness if it becomes more legible").
Real effect, not a regression in the new code: bilinear's edge ringing/overshoot was incidentally
reading as punchy contrast; LANCZOS is more correct and doesn't do that. Added a PIL `UnsharpMask`
pass after the LANCZOS resize in `_lanczos_scale`, RGB channels only (alpha untouched, so transparent
cover edges aren't affected). First attempt at `radius=1.0, percent=60` overshot — user's words:
"out of focus, then we slapped an HDR filter on it to salvage it," with visible haloing on
photographic gradients (skies, faces) where LANCZOS leaves no real edge for the mask to find, so it
amplifies noise instead. Settled on `radius=0.8, percent=25` — confirmed by the user to keep the
text legibility gain without the cartoonish/HDR look. **Any future change to this sharpen strength
must be re-checked against a photographic cover, not just a flat-color graphic one — the latter
tolerates much more sharpening before artifacts become visible**, which is exactly how the first,
too-strong value got picked without anyone noticing on the graphic-art test case alone.

**Scope note:** this only touches the library grid/list thumbnails (`BookDelegate` in `library.py`).
The main player view's cover (`cover_art_label`, `_update_cover_art_scaling` in `app.py`) is a
separate code path and was not part of this change.

## `book_info_layout` 2px centering drift: missing `setSpacing(0)`, not an icon/font/style issue (2026-06-23)

**Symptom:** the volume slider, sleep-timer countdown label, and new muted-volume icon — all three
pages of the `vol_stack` `QStackedWidget` — read as shifted right relative to the play button and
the chapter name label above them. Visually subtle (a few px) but real, confirmed by the user with
two identical squares drawn in an image editor and placed against each widget's own left/right
margins.

**Wrong diagnoses tried first, in order, each disproven before moving to the next:**
1. The muted icon's SVG had an asymmetric `viewBox` (`viewBox="-3.5 0 24 24"`) — measuring the
   rendered glyph's bounding box at high resolution showed it was in fact centered within ~1%, so
   this wasn't the cause. A "nudge the icon a few px left" workaround was applied anyway (tuned by
   eye to 6px, since the *layout* bug was still present and uncorrected at that point) and later
   fully reverted once the real fix landed — see below.
2. "Optical centering" (the icon's solid speaker body reads as visually heavier than its thinner
   left side, even with a centered bounding box) — plausible-sounding, and the rendered icon really
   does look asymmetric at small sizes, but this was the wrong explanation: it doesn't explain why
   the volume *slider* and the sleep *label* — both completely different render paths with no
   shape-weight component — showed the exact same rightward drift.
3. `QPushButton` (the sleep-timer label) text-centering quirks under Fusion style, stylesheet
   specificity, `SE_PushButtonContents` content-rect margins — multiple isolated PySide6 scripts
   were built to test `QStyleOptionButton`/`subElementRect`/raw pixel renders of the button alone,
   and every one of them came back correctly centered. This was real evidence, but it was evidence
   about a synthetic reconstruction, not the actual running app — the gap between the two turned out
   to be the actual bug.

**Root cause:** `book_info_layout` (`main_window_builders.py`, the row containing
`current_time_label | vol_stack | total_time_label`) never called `setSpacing(0)`, so Qt's default
inter-item spacing (Fusion style default, several px) was inserted at every gap between consecutive
layout items — including the two `addStretch(1)` spacer items flanking `vol_stack`. Spacer items and
real widgets don't necessarily get identical treatment from the default spacing in every Qt layout
configuration, and the net effect measured here was a 4px asymmetry: `vol_stack`'s left margin from
the window edge measured 100px, its right margin measured 96px (confirmed via real `QWidget.geometry()`
and `mapTo()` dumps from a temporary debug keypress handler in `app.py`, not from any isolated
synthetic script). The sibling `chapter_info_layout` row (which centers "Chapter 1" correctly, and
was the reference the user kept comparing against) has only 3 items with the centered widget itself
stretching — no `addStretch()` spacer items at all — so it never hit this asymmetry.

**Fix:** `book_info_layout.setSpacing(0)`, plus adding a matching `addStretch(1)` before
`current_time_label`'s sibling `vol_stack` (previously there was a stretch only *after* `vol_stack`,
left-packing the row instead of centering it) — see
[main_window_builders.py:401-407](src/fabulor/ui/main_window_builders.py#L401-L407). Confirmed fixed
via the same debug-geometry dump: `vol_stack` now sits at x=98 with a symmetric 98px margin on both
sides of a 300px window. The muted-icon nudge workaround from diagnosis #1 was removed entirely once
this landed — the icon needed zero compensation once the real layout bug was fixed.

**Lesson for future layout-centering bugs:** when a `QHBoxLayout` mixes `addStretch()` spacers with
real widgets and a row reads as off-center by a small, consistent amount, check `setSpacing()` on
that specific layout before suspecting the painted content (icons, fonts, button styles) — and when
synthetic reconstructions keep disagreeing with a user's direct visual report, get real
`geometry()`/`mapTo()` numbers from the running app rather than continuing to refine the
reconstruction. A temporary keypress-triggered debug dump (this session used `G`, removed after the
fix) is fast to wire up and far more conclusive than re-deriving Qt's layout math by hand.

---

## StreakGrid gutter labels: both descender clipping ("Aug") AND left-edge first-letter clipping ("Jan"/most months) fixed by the same band-height change (2026-06-22)

**Symptom:** Two distinct-looking clips on the `StreakGrid` left-gutter row labels turned out to
share one fix. (1) Descenders clipped vertically — e.g. "Aug 28" cut off at the bottom of the "g".
(2) The left-edge first-letter clip — e.g. "Jan 01" → "an 01" — an offscreen sweep across all 12
months suggested this affects most months, not just "J" ones (Sep, Aug, May, Apr, Nov, Oct appeared
to lose their first letter the same way; "Jul" looked like the one exception in that sweep).

**Root cause:** the label rect (`QRect(0, y, GUTTER_W-3, CELL)`, `Qt.AlignVCenter`) only spanned a
single 14px cell row, but labels are drawn only every 3rd row (`drawn = range(0, N_ROWS, 3)`) — each
visible label visually "owns" the unlabeled rows below it too, down to the next label (3 cells, or 2
for the last band, since `N_ROWS=26` isn't a multiple of 3). Squeezing the label into one 14px row
left it cramped on both axes — vertically against descenders, and apparently tight enough that
`Qt.AlignRight`'s left-side overflow also reached the widget edge more readily than once the rect
had more room.

**Fix:** compute each label's owned band height from its row to the next label's row
(`band_h = (next_r - r) * CELL + (next_r - r - 1) * GAP`), anchor with `Qt.AlignTop` instead of
`Qt.AlignVCenter`, with a small calibrated vertical offset (`y - 1`, tuned against two rounds of
live visual feedback: first `+2` margin from band top, then `-2`, settled at `-1` net from the
original `y`). See [stats_panel.py:1757-1771](src/fabulor/ui/stats_panel.py#L1757-L1771). Confirmed
fixed live, on the real running app, for both the descender clip and the left-edge first-letter
clip across multiple months — no further gutter-label work outstanding.

Caveat for future offscreen verification of this widget: an offscreen render taken after this fix
still showed the left-edge clip in a quick scripted check, but it did not reproduce on the real
app — same divergence already seen earlier this session with the sidebar margin fix (offscreen
render and the live app disagreed there too). The offscreen month-sweep script is still useful as a
coarse regression check (loop `date(2026, month, day)` across all 12 months, call
`StreakGrid.set_data({}, {...}, set(), d)`, render to `QPixmap`, crop to the gutter region) for
catching gross regressions like wrong band assignment or rect math, but its pixel-level clipping
verdict should not be trusted over a live visual check on real fonts/DPI/rendering stack.

---

## HourlyHeatmap top date labels: "J" clipped — fixed; several intermediate approaches tried and reverted (2026-06-21)

**Symptom:** In the Stats panel's Timeline tab, both views had a "J" clipping bug. `HourlyHeatmap`'s
rotated top date labels showed "un 19" / "un 20" / "un 21" instead of "Jun 19" / "Jun 20" / "Jun 21"
— originally on the rightmost (most recent) column only; `StreakGrid`'s left-gutter row labels
showed "un 21" / "ul 20" instead of "Jun 21" / "Jul 20". This is a continuation of the unresolved
2026-06-10 NOTES.md entry "Timeline header date labels — 'J' glyph clipped at top edge", whose
fix (`QRect(2, -CELL, DATE_LABEL_H, CELL*2)`, doubling the rotated rect's height) turned out to
only fix the *non-rightmost* columns — the rightmost column has a second, independent clip source
that the 2026-06-10 fix didn't touch.

**Root cause (heatmap, rightmost column only):** the doubled rect height (`CELL*2=28`, centered at
`y=-CELL`) needed by the 2026-06-10 fix made the rotated rect's far edge extend past the widget's
own right boundary for the last column only — `wx_max = (HOUR_LABEL_W + col*(CELL+GAP) + CELL//2 +
2) + CELL`, which for `col=N_DAYS-1` exceeds the fixed widget width by ~8px. Qt clips painting at
the widget boundary regardless of the QRect passed to `drawText` (the QRect only controls
alignment/wrapping, not a hard clip region) — so the "J" of the rightmost label(s) is cut by the
widget edge, not by the rect. Every other column has a following cell's width to absorb that same
~8px overhang, so only the last column showed it.

**Root cause (StreakGrid gutter labels, "Jun 21" / "Jul 20"):** unrelated mechanism, same visual
symptom. The row-date rect is `QRect(0, y, GUTTER_W-3, CELL)` with `Qt.AlignRight` — Qt anchors the
text's **right** edge to the rect's right edge; the "Mon DD" string (e.g. "Jun 21", advance ~35px at
9pt) is wider than the 29px rect, so the string's left side already extends past `x=0` for every
label in the 14-day cycle (confirmed via `QFontMetrics.boundingRect` on all 9 labels — all had
negative left bounds). For most letters that overflow is invisible: `boundingRect.x()` being
negative is normal side-bearing whitespace with no dark pixels there. "J" is the exception — its
descender hook is real ink sitting in exactly that overflow band, so it alone gets clipped at the
widget's left edge (`x=0`) while "May 10", "Mar 29", etc. render fully despite the same or larger
nominal overflow.

**Approaches tried and reverted for the StreakGrid gutter (all confirmed bad, in order):**
1. **Widen the rect's right edge** (`GUTTER_W+3` instead of `GUTTER_W-3`) to shift the whole
   AlignRight-anchored string rightward, off the left boundary. Fixed "Jun 21"/"Jul 20" in isolated
   testing, but in the real app — where active/listened cells render at high opacity — the shifted
   text's *right* edge now reached into the first grid cell column (`x=32`) and got visibly
   overpainted by the opaque cell fill ("Jun 2" with the "1" eaten). Moving the anchor only relocates
   which end of the string clips; the string is wider than the available 0–32px slot at 9pt
   regardless of where it's positioned.
2. **Shrink font to 8pt (rect unmoved).** Verified-by-math first (wrongly) as sufiscient; in an actual
   render it still clipped "Jun 21" → "un 21" — the earlier ink-bound calculation for 8pt had been
   conflated with a combined "8pt + shift" case, not 8pt alone. 8pt alone was not enough margin.
3. **Shrink font to 7pt (rect unmoved).** This one *did* render every label fully with no clipping
   and no cell overlap (verified via `tightBoundingRect`/`boundingRect` math and an offscreen
   render) — but the user rejected it on sight as illegibly small, with too much resulting dead
   whitespace in the gutter. **Deferred** — needs a different approach (e.g., a shorter date format
   at a readable size, or restructuring the gutter) the next time this is picked up. Do NOT default
   back to shrinking this font as "the fix" without re-confirming legibility first.
4. **User then fully reverted the gutter changes.** StreakGrid's "Jun 21"/"Jul 20" clipping is
   UNFIXED and deferred — see TODO.md.

**Approaches tried and reverted for the HourlyHeatmap rightmost column (in order):**
1. **Widen the whole widget by `+CELL`** (`_update_size`: `w = HOUR_LABEL_W + N_DAYS*(CELL+GAP) +
   CELL`). Fixed the rightmost-column overflow in isolation, but violates the hard constraint that
   `HourlyHeatmap` and `StreakGrid` must stay pixel-identical in size (242×448) for the
   heatmap↔streak `TasselOverlay` transition to align cell-for-cell — reverted.
2. **Shrink the rotated rect's height from `CELL*2` down to a tightly-measured ~16px** (instead of
   widening the widget) — this approach did NOT regress to the pre-2026-06-10 bug as long as the
   measured worst-case ink height (~15px across all "Mon DD" labels at 11pt, via
   `QFontMetrics.tightBoundingRect`) still fits with margin. Combined with also changing the
   rotation anchor from `cx+2` to `cx`, this brought the rightmost column's overflow to exactly 0 in
   calculation — **the user then independently reverted this entire session's changes before this
   approach was committed**, so it is NOT the shipped fix; recorded here only so it isn't
   re-investigated as if it were untried.

**Shipped fix (heatmap only):** kept the original `CELL*2`-tall rect and the original widget size
(both untouched), and instead shifted only the rect's `y`-offset in the rotated coordinate frame
from `-CELL` to `-CELL-4` (`QRect(2, -self.CELL - 4, self.DATE_LABEL_H, self.CELL * 2)` at
[stats_panel.py:1052-1057](src/fabulor/ui/stats_panel.py#L1052-L1057)). After `rotate(-90)`, the
rect's local +y axis maps to widget **-x** (leftward); increasing the magnitude of the negative `y`
offset by 4 shifts every rendered label 4px left in widget space, off the widget's right edge for
the last column, without touching `cx` (the cell-anchor x, shared with cell positions), the hour
labels, or the widget's overall size. (An initial pass shifted by `-5`; the user visually confirmed
that overshot by 1px and asked for `-4`.) Verified via offscreen render: no clipping on any column
including the rightmost, and the labels no longer encroach on the cell grid. The `StreakGrid` gutter
clip is a **separate, still-open bug** — see TODO.md — do not assume this fix also covers it; the
two labels live in different widgets with different alignment/rotation mechanics.

---

## Session recorded twice on graceful app close (2026-06-21)

**Symptom (user-reported):** closing the app while a listening session is active records that
session **twice** in `listening_sessions`. It records correctly (once) when force-killing the
process, when the 3-minute pause timeout fires, or when loading another book mid-session.

**Root cause — a daemon-thread-vs-checkpoint race.** `SessionRecorder` writes a crash-recovery
checkpoint (`session_checkpoint.json`) every 30s while a session is live; on startup,
`_recover_checkpoint()` re-writes any checkpoint with `listened >= 60`. In the original
`close()`, the DB write **and** the checkpoint `unlink` both happened inside the `_write` closure
running on a **daemon** thread. `closeEvent` called `close()` then immediately `event.accept()`,
and the process tore down. Daemon threads are killed on process exit — so the in-flight `_write`
typically *completed its DB write* (the row landed: copy #1) but never reached the `unlink`. The
checkpoint survived on disk, and the **next startup's `_recover_checkpoint()` re-wrote the same
session** (copy #2, with a fresh `session_end`).

Why only the graceful-close path:
- **Load another book / 3-min timeout** — `close()` runs but the app keeps running, so the daemon
  thread completes the `unlink` before any restart; checkpoint gone, no duplicate.
- **Force-kill** — no `closeEvent`, so `close()` never runs; the session is written only once, by
  recovery on the next startup.

Only graceful close left *both* a landed DB write *and* a surviving checkpoint.

**Fix — two independent guards, because the duplicate and a potential lost-write are different
failure modes:**
1. The checkpoint `unlink` was removed from the `_write` daemon closure entirely and moved into a
   new synchronous `SessionRecorder.clear_checkpoint()`.
2. `close()` now builds the flush thread into a **local** (not `self._flush_thread` — avoids
   unnecessary shared state) and returns it (`None` on the sub-60s/no-book discard branch).
   `closeEvent` does: `t = close(); if t: t.join(timeout=0.5); clear_checkpoint(); event.accept()`.

The join gives the DB write a bounded chance to land; the **unconditional** synchronous
`clear_checkpoint()` makes the duplicate impossible regardless of how the join resolved. Critically,
the clear must *not* live inside `_write` after the DB write (its original spot) — if it did, a
join *timeout* could leave the thread killed after the write committed but before the unlink,
resurrecting the exact bug. Ordering is load-bearing: `join → clear_checkpoint → event.accept()`,
all before `accept()` (the point of no return).

**Branch table (every case pinned):**

| Join outcome | Write landed? | Result |
|---|---|---|
| Completes (normal) | yes | checkpoint cleared → exactly one row |
| Times out (DB stalled) | yes | checkpoint cleared anyway → one row, no duplicate |
| Times out (DB stalled) | no | checkpoint cleared, no row → session lost |

The third row is the only loss case and is reachable only if a **single-row** WAL insert exceeds
500ms — i.e. the DB is locked/broken, where losing one session row is the least of the problem. The
DB uses `journal_mode=WAL` with `synchronous` at its WAL default `FULL` (fsync per commit), which
is routinely sub-millisecond for one row; 500ms absorbs an occasional fsync spike under disk
pressure with comfortable margin. (Orthogonal lever if it ever proves marginal:
`PRAGMA synchronous=NORMAL`, safe under WAL — not done.) `losing-at-worst` beats `duplicating`; the
prior behavior was a *guaranteed* duplicate.

The recovery path's own `unlink` (`finally` in `_recover_checkpoint`) is unchanged — it runs at
startup while the app stays alive, so its daemon thread completes normally.

**Files:** `session_recorder.py` (`close()` returns the thread, no inline unlink; new
`clear_checkpoint()`), `app.py` (`closeEvent`).

---

## Streak count / grid cell mismatch (2026-06-19 Session 4)

**Symptom (user-reported):** while testing different `day_start_hour` settings, the streak grid's
lit-cell count and the displayed streak number disagreed. Concretely: a session running
04:53→06:02 on 2026-06-10, `day_start_hour` 5 or 6. The session's adjusted start-date is 06-09
(04:53 falls before the 5am/6am boundary) and its adjusted end-date is 06-10 (06:02 falls after
it) — so the session was genuinely listened to across parts of *both* adjusted-days.

**First diagnosis (wrong, reverted):** assumed the streak grid was the bug, on the theory that the
Day tab and `get_active_periods` are start-date only, so the grid (which lights a cell on EITHER a
session's start OR end adjusted-date) should be made start-only too, "to match." This was
implemented, then the user caught the actual intent before it landed: **the grid was correct.** A
session spanning the day_start_hour boundary really was listened to on both of those adjusted-days
— lighting both cells reflects reality, the same way a session spanning real midnight should light
both calendar days. The Day tab intentionally shows it as one entry on its start-date only (see
"Day/Week/Month session-splitting, scoped out" below) — that's a deliberate, different design
choice for that view, not a bug to be reconciled by changing the grid. The grid-only-start-date
change was fully reverted (`build_streak_grid_cache`, `_update_streak_grid_cache_for_date` both
restored to their original start∪end behavior).

**Actual root cause:** `get_streaks` (which computes the streak NUMBER/label, not the grid cells)
builds its day-set from `get_active_periods('day', ...)` — start-date only, by design, since
`get_active_periods` also drives the Day/Week/Month period navigator and must stay start-only
there — plus a separate finished-event query. It never unioned session **end**-dates. So for a
session spanning the boundary, the grid correctly lit two cells, but `get_streaks`'s day-set (and
therefore the streak count) only ever credited the start-date — undercounting relative to what the
grid visibly showed. This is exactly the cross-check invariant already documented in CLAUDE.md
("`StreakGrid` cross-checking its longest run against `get_streaks()['longest']`") — the two paths
had drifted because an end-date source was present in one (the grid) and absent in the other
(`get_streaks`).

**Fix:** added a session_end-date query directly inside `get_streaks` (NOT inside
`get_active_periods` — that function's start-only contract is load-bearing for Day/Week/Month nav
and must not change) and unioned its results into `active_set`, alongside the existing
session-start set (from `get_active_periods`) and the finished-event set. `get_streaks`'s day-set is
now built from the same three sources as `build_streak_grid_cache` (start, end, finished) — start
and end via separate queries since `get_active_periods` can't be reused for the end-date half
without breaking its start-only contract elsewhere.

**Verification:** scripted repro — write one session 04:53→06:02, rebuild the grid and call
`get_streaks` at `day_start_hour` 4/5/6. At 5 and 6 (where the session spans the boundary), both
the grid's lit-cell count and `get_streaks()['longest']` now read 2; at 4 (where the whole session
falls after the boundary, no spanning) both read 1. Matched exactly at all three offsets after the
fix; before the fix `get_streaks()['longest']` read 1 at all three offsets regardless of how many
cells were actually lit.

**Day/Week/Month session-splitting — considered, scoped out:** the same boundary-spanning session
also raises the question of whether the Day tab should show it on both adjusted-days too (split
proportionally, the way the Hourly Heatmap already splits sessions across clock-hour cells). This
was deliberately NOT done: it would require splitting `listened_seconds`, `position_start`/
`position_end`, `furthest_position`, and the per-book `is_finished` flag proportionally across two
rows, touching `get_daily_book_breakdown`'s aggregate `SUM`/`MAX` columns, the Book Detail Panel's
per-book stats grid, and the delete-session/delete-book-stats cascade (deleting one half of a split
session would need to correctly re-derive both affected days). Large blast radius for a genuinely
rare case (only sessions that straddle the configured `day_start_hour`, not all spanning sessions).
The Day tab stays start-date-only by design; a spanning session shows as one entry, attributed to
its start day, with its full (unsplit) duration and position range — same as before this session's
fixes, unchanged.

**Lesson:** before "fixing" a discrepancy between two views that are SUPPOSED to represent different
granularities of the same data (a coarse "did I listen at all that day" grid vs. a precise per-book
Day-tab listing), confirm which one is actually wrong by reasoning about what real listening
behavior should produce — not by assuming the two should always show identical numbers. The
correct fix here was almost the opposite of the first instinct: bring the under-counting path
(`get_streaks`) up to match the correct one (the grid), not bring the grid down to match the
under-counting Day tab.

## TasselOverlay: dangling tassel design iteration (2026-06-19 Session 3)

**Goal:** make the Timeline bookmark tab feel like a real bookmark by adding a decorative
dangling tassel — cord + bound head + fringe — that sways. New animation category for this
codebase (no prior rotation/curve-based or perpetual-idle animation existed anywhere; everything
else is position/opacity/color `QPropertyAnimation` or state-gated repeating `QTimer`s).

**Round 1 (built under a full plan-mode design — see the now-resolved plan file): "pendulum with
a circle," not a tassel.** The first implementation drew a single straight cord ending in a plain
filled circle, floating to the *side* of the tab like a clock pendulum. Two real problems, both
caught immediately on the first screenshot: (1) a tassel has three visually distinct parts — cord,
a bound "head" knot, and a fanned fringe of threads — not a dot; reference photos make this
unambiguous. (2) `setCursor(PointingHandCursor)` was applied to the WHOLE widget in `__init__`, so
the hand cursor appeared over dead/empty space (the swing area) where clicking did nothing — a
real UX bug, not a cosmetic one. **Lesson:** "this beats physics" / "circle ≠ tassel" feedback
meant the shape itself was wrong at a structural level, not just under-detailed — redrawing more
detail onto a circle would not have fixed it; the anatomy needed rebuilding from reference images.

**Fix for round 1's issues — `_in_hit_region()`.** A single property is now the SOLE source of
truth for both `mousePressEvent` (click) and a new `mouseMoveEvent` (cursor): `tab_rect.contains(pt)
or tassel_rect.contains(pt)`. `mouseMoveEvent` calls `setCursor`/`unsetCursor` based on the same
test, so the hand cursor can never show over a region where clicking is a no-op. `tassel_rect` is a
*tight* box around the resting tassel body (head + fringe + sway slack) — NOT the full widget
bounding box — so the empty corners between the tab and the tassel (and above/right of the tassel)
correctly do NOT show a hand or accept clicks. Fixed at the rest position (not tracking the live
sway) so the clickable region doesn't move under the pointer.

**Round 2: cord geometry, two sub-rounds.** A tassel's cord isn't taut — it drapes/loops (visible
in every reference photo: the cord visibly loops through the bookmark hole before reaching the
knot). (2a) First attempt used a quadratic Bezier with the control point only modestly offset —
read as "goes straight" / "pretty much the same thing" even after changing to a cubic, because both
cubic control points were placed *below* the anchor with only a small horizontal offset: the curve
never swung out far enough past the head's x-position to read as a loop rather than a slightly-bent
line. (2b) Second attempt fixed the bulge (control point pushed above-and-right of the anchor, the
loop's widest point) but then the curve arrived at the head *diagonally from the right*, because the
second control point was placed to the side of the head rather than above it — "bulge doesn't
align." **Fix:** the curve's approach angle at an endpoint is set by the control point immediately
before it, independent of the rest of the path — placing `c2` directly above `head_top_pt` (same x)
makes the tangent at the endpoint point straight down, so the cord visibly drops into the head
vertically regardless of how the loop bulges earlier in the path. Also shortened the drop
(`_HEAD_Y` 50→34) and pulled the head closer to the tab (`_HEAD_X`, `SWAY_PAD` reduced) per
feedback that the original proportions were too long/far. **Lesson:** when a Bezier "doesn't look
right," diagnose bulge (shape, mid-path control points) and approach angle (endpoint, the control
point closest to that endpoint) as separate, independently-tunable concerns — fixing one doesn't
fix the other, and conflating them wastes iteration rounds.

**What's preserved/unchanged throughout all rounds:** the tab's own `_tab_rect`, its 7px rest-peek,
`REST_Y`/`EXT_Y` (still derived from the original `TASSEL_H=56`), and the caller's
`.move(2, REST_Y)` in `_build_time_tab` — verified numerically at every round via a headless
offscreen-Qt script (`QT_QPA_PLATFORM=offscreen`) computing widget size, hit-region containment,
and control-point bounds before ever launching the real app. The `showEvent`/`hideEvent` timer
lifecycle was also verified empirically (not assumed) with a probe subclass mounted in a real
`QTabWidget`, confirming both `hideEvent` firing AND `isVisible()` flipping `False` on tab-switch-
away and panel-close, and both recovering on return.

## Main-window theme fade interrupt (sidebar mid-fade) FIXED; full color-animation rework DEFERRED (2026-06-19 Session 2)

**Symptom:** press `T` (theme rotate), then right-click the drag area to open the sidebar while the
fade is still running → a slider (progress and/or chapter) stays painted in the OLD theme's color
while everything else is already the NEW theme. Hard to hit deliberately, and self-corrects on the
next theme change, but real.

**Root cause (two parts, from instrumented logs).** The non-Themes-tab fade
(`_do_fade_with_slider_animation`) excludes the sliders from the overlay snapshot and instead
animates their `bg_color`/`fill_color`/`notch_color` `@Property` values from old→new. Those animations
are kicked off from a deferred `QTimer.singleShot(0, _start_color_anims)` (deferred so the new QSS has
polished first). (1) If a panel/sidebar opens in the window between the fade starting and that
deferred callback firing, the callback still runs and *re-resets* the sliders to the OLD start colors
before animating — and if the fade is then torn down, they're stranded there. (2) There was no
main-window-appropriate way to *complete* an in-flight fade on interrupt — `snap_theme_forward` exists
but is Settings-panel-oriented (it re-applies stylesheets in a way tuned for the Themes-tab preview)
and was never intended for the main window; calling it there (an earlier attempted fix) did not
resolve the stranding.

**Why the sliders specifically (not the rest of the UI).** `ClickSlider.paintEvent` paints directly
from its `@Property` colors (`self._bg_color` etc.), NOT from QSS at paint time. The new-theme colors
reach those properties only via `_apply_stylesheets` → Qt `polish()` reading the
`qproperty-bg_color`/etc. declarations in `get_player_stylesheet`. So once the fade's color animation
has overridden the `@Property` and is then stopped mid-flight, the slider keeps the stranded value
until something re-polishes it. The rest of the UI (buttons, panels, labels) reads its colors from QSS
at paint time, so it was already correct the instant `_apply_stylesheets` ran.

**Fix:** `ThemeManager.complete_main_fade()` — stops the main `_fade_anim` and any running slider color
animations, hides the overlay, unfreezes the fade labels, then re-applies the stylesheet for
`_active_display_theme`, which re-polishes the slider `@Property` colors to the correct new-theme
values (overriding whatever the stopped animation left). A new `_fade_in_flight` flag (set when a
fade starts, cleared in `_on_fade_finished` and `complete_main_fade`) ALSO guards the deferred
`_start_color_anims` so it returns early once the fade is completed/interrupted — closing the
re-strand window in cause (1). `_toggle_sidebar` (the sidebar is the gateway to every panel, and the
target of the drag-area right-click) calls `complete_main_fade()` before sliding; it's a no-op if no
fade is running. Future panel hotkeys (`l`/`s`/etc., planned) would hit the identical race and should
make the same call.

**DEFERRED — the deeper friction (full per-element color-animation rework).** The real reason theme
changes are restricted to "main window only, no panel open" is that the main-window theme transition
is a heavyweight FULL-WINDOW animated fade: an overlay snapshot of the whole window + frozen time/
chapter labels (text pinned so it can't change under the overlay and ghost) + the slider color
tweens. That heaviness is what risks morph/ghost artifacts if anything is moving (a panel sliding)
during the fade. If theme changes were *only* cheap per-element `@Property` color animations (nothing
positional, no overlay, no frozen labels), they could run freely even with a panel open — the
original desired behavior. That rework was started in a prior session and abandoned as enormous:
every QSS-styled widget (buttons and their hover/pressed/disabled states, panel chrome, the Themes-tab
pool items with their regular/underline/bold variants, gradients, cover-art-derived colors) would
need converting from QSS-driven coloring to custom-paint `@Property` coloring, because QSS pseudo-
states (`:hover`/`:pressed`/`:disabled`) have no equivalent in custom-paint land and would each be
reimplemented by hand. Rough estimate 40–80h+ with high regression risk against a system that works.
The cheaper middle path (snap panel chrome instantly while keeping slider tweens, dropping the overlay
for the panel-open case) was floated and **rejected by the user**: instant theme snaps look jarring/
violent — the overlay fade exists precisely to avoid that, and snapping would be a worse experience,
not a better one. So: the overlay fade stays; `complete_main_fade` is the pragmatic interrupt fix.

## Percentage label tween oscillation FIXED; tassel click hang FIXED; streak grid catch-up reveal added (2026-06-19)

**Percentage label oscillation — truncate-vs-round mismatch, not a timing race.** The progress
percentage label's book-load count-up animation (added 2026-06-18) animated toward
`new_val / 10`, where `new_val = int((new_progress/dur)*1000)` — `int()` truncates toward zero, so
a true value like 739.97 becomes 739, displaying "73.9%". The live 200ms tick that resumes right
after the flow instead computes `percent = (pos/dur)*100` and formats it with `f"{percent:.1f}%"`,
which *rounds* — for the same ~739.97-ish true percentage, that's "74.0%". Every book whose saved
progress's true percentage rounds up in its last digit reproduced this, consistently, every time —
not intermittently, which in hindsight should have been the tell that it wasn't a race. First
attempt was a settle-delay guard (`_pct_label_settling`, cleared 250ms after the tween finished) on
the theory that the live tick was racing the tween's completion. Confirmed wrong by testing it: the
jump was bit-for-bit identical with the delay in place. Real fix: compute the tween's end value
directly as `round((new_progress/dur)*100, 1)` in `_animate_percentage_label`, matching the live
tracker's own rounding exactly, instead of re-deriving a coarser value from the slider's truncated
`new_val`. The settle-delay plumbing was removed entirely once the root-cause fix made it
unnecessary — it's a math/formatting consistency issue, not a timing one, so no delay of any length
would have fixed it.

**Tassel click hang — caller didn't check the busy guard it relied on.** Rapid-clicking the
Timeline tassel while a heatmap↔streak transition was already running could hang the view
indefinitely (reported via screenshot: bookmark visible but frozen, both grids blank, no further
clicks doing anything). `TasselOverlay.play()` already had a `_busy` flag that correctly no-oped on
repeat clicks for the bookmark slide animation itself (added in an earlier session). But
`StatsPanel._on_tassel_clicked` called `self._switch_timeline_view()` unconditionally on every
click, regardless of whether `play()` had actually done anything that time — so every extra click
during the busy window independently kicked off another full `_switch_timeline_view()` cycle: a new
`animate_conceal()`/`animate_labels_out()` pair racing against the one(s) already in flight, another
`_show_streak_grid` flip, multiple `_seam()` closures fighting over the same grid's
`setVisible`/`set_label_progress` calls. Enough overlapping cycles left both grids hidden with no
surviving callback able to flip either back to visible — the hang. Fix: added a public
`TasselOverlay.is_busy` property (`return self._busy`) and `_on_tassel_clicked` returns immediately
if it's `True`, before touching either the bookmark or the grid transition. General lesson for this
codebase: a guard living inside one method (`play()`'s `_busy` check) does not protect a caller that
also independently triggers side effects alongside that method — the caller needs to check the same
guard itself if it wants the same protection.

**Streak grid catch-up reveal.** The newest `current - previous` day-cells (`day_index` 0 through
`N-1`, where `day_index=0` is today) now render as plain "not listened" — regardless of what's
actually in `_cache`/`_longest_dates`/`_finished` — for the full duration of the counter's leg 1
count-up to the old value and the pause that follows, via two new `StreakGrid` fields
(`_pending_reveal_days`, `_revealed_days`) checked in `paintEvent` as a `still_pending` gate. Once
leg 2 starts, cells pop in one at a time in the exact same frame as each integer increment of the
counter — both are driven by one discrete `QTimer` (`_run_streak_leg2`), not two independently-timed
animations, specifically so they can't drift a tick apart from each other. This required replacing
leg 2's previous continuous `QPropertyAnimation` tween with a stepped timer entirely. Total leg-2
duration: `raw = LEG2_BASE_MS + (sqrt(days) - 1) * LEG2_SCALE_MS`, capped at `LEG2_CAP_MS` (1200ms);
1 day lands exactly on `LEG2_BASE_MS` (250ms, matching the original single-tick feel). Per user
feedback, anything beyond `LEG2_SPEEDUP_AFTER_DAYS` (3) is further compressed: the time *past* the
3-day mark runs at `LEG2_SPEEDUP_FACTOR` (0.25, i.e. 75% faster than the raw curve for that portion
— tuned down from an initial 0.8/~20%-faster after visual testing showed it wasn't enough), so the
curve stays continuous at the boundary instead of jumping. Net effect: 9 days ≈ 565ms (was 850ms
pre-tune), 25 days ≈ 715ms, 100 days ≈ 1090ms (still under the 1200ms cap). `catch_up_streak_count`
(the panel-slide-reopen path) explicitly zeroes
`_pending_reveal_days`/`_revealed_days` before calling into the same leg-2 timer, so the grid itself
is never touched there — the established "never animate the grid on a slide-reopen" rule still
holds; only the counter shows the catch-up tick in that case.

**Deferred (minor): background-refresh race with an in-flight catch-up reveal.** If
`StatsPanel.refresh_all()` (a background data refresh, e.g. from the session-write live-refresh
path) runs while `StreakGrid`'s leg-2 reveal is mid-flight, `set_data()` refreshes
`_cache`/`_longest_dates`/`_finished` from the database but does not touch
`_pending_reveal_days`/`_revealed_days` at all (by design — those fields are owned exclusively by
`animate_streak_count`/`catch_up_streak_count`/`_run_streak_leg2`). Confirmed by the user to behave
exactly as predicted: a narrow timing collision, cosmetic only (the dimmed cells can briefly look
stale relative to the freshly-loaded cache until the reveal timer finishes or the next refresh
corrects it). Accepted as-is for now — not worth the added state-reconciliation complexity for how
rarely the two events overlap. Candidate fix if it's ever worth doing: on detecting an interrupting
`set_data()` call while `_pending_reveal_days > self._revealed_days`, reveal all remaining pending
cells at once (snap `_revealed_days = _pending_reveal_days`) before applying the new data, rather
than trying to keep the staged per-day reveal in sync with a cache that just changed under it.

## Timeline tab visual rework: grid pop transition, label cascades, streak counter (2026-06-18)

**Grid transition style.** Replaced the cell reveal/conceal alpha-only fade with a "pop": cells
also scale up from a center-anchored inset as they reveal (and shrink back on conceal), using the
same diagonal Mexico-wave timing as before. Implemented as a shared `_grid_cell_anim(progress, row,
col, n_rows, n_cols, style)` helper in `stats_panel.py` so `HourlyHeatmap` and `StreakGrid` can't
drift apart. A `GRID_TRANSITION_STYLE` module constant selects the style; `"pop"` is the shipped
default, `"rows"` (a deliberately underwhelming row-curtain sweep) is kept in code as an internal
comparison baseline only — never exposed as a user-facing option. Tried and rejected: `"ripple"`
(radial wave from center — left the panel empty too long before anything appeared) and `"cols"`/
`"cols_zig"` (symmetric column curtain converging on center, with/without a wave-style zigzag — too
slow, and speeding it up felt off). None matched the original wave's diagonal path for visual
interest; the wave's longer travel distance is what makes it read as intricate. The longest-run
border and finished-day dot are gated on `anim_scale >= 0.999` so they never float over a still-
shrunk "pop" cell.

**Label cascades (top dates, left-gutter dates/hours) — mirrored, not reversed.** Each label now
fades in/out in place (opacity ramp) instead of the old internal clip-rect wipe, with an even
per-label stagger (`_LABEL_STAGGER_FRACTION` split across columns/rows) replacing the old lead-
fraction/sharp formula. The critical fix: enter and exit must be TRUE MIRRORS of each other, not the
same sweep played in reverse. The first implementation reused one opacity-ramp formula for both
directions and relied on clamping to mask the asymmetry — this silently made the "leading" label
hold at full opacity until late in the exit animation instead of fading first, which read as wrong
direction even though the cascade-rank assignment was correct. Fix: the exit formula anchors each
label's fade window from the END of the timeline (`end - span` to `end`) instead of reusing the
enter formula's start-anchored window. Verified by hand-computing local opacity at several progress
values for both cascade ranks before trusting it visually (see git history for the throwaway
verification script). Top labels: enter sweeps left-to-right (col 0/newest leads), exit sweeps
right-to-left (oldest leads). Left-gutter labels (Heatmap hours, Streak dates): enter top-to-bottom,
exit bottom-to-top. A second real bug surfaced after the math fix: `_label_sweep_in` was only ever
set inside `animate_labels_in`/`animate_labels_out`, never initialized in `__init__`, so the very
first paint before either had run raised `AttributeError` — fixed by initializing it `False` in both
`HourlyHeatmap.__init__` and `StreakGrid.__init__`.

**Streak counter animation — two legs, persisted across restarts.** The streak number now counts
up instead of appearing statically. Leg 1: linear (NOT eased — `OutCubic` was tried first and its
natural deceleration near the end was indistinguishable from a deliberate "pause before the last
tick," which is misleading when the streak hasn't actually changed) 0 → previously-shown value, 800ms
(`_STREAK_LEG1_MS`). Leg 2 (only if the streak grew since it was last shown): a 550ms pause
(`_STREAK_PAUSE_MS`, raised from an initial 400ms — 1-day deltas at 400ms were not perceptible) then
a snappy 250ms (`_STREAK_LEG2_MS`) linear tick from previous → current. If the streak is unchanged
(or decreased) since last shown, leg 2 is skipped entirely — single count straight to current, no
pause. The "previous" value MUST be persisted (`Config.get_last_shown_streak()` /
`set_last_shown_streak()`, QSettings-backed) rather than kept only in an in-memory
`StreakGrid._last_animated_streak` — an in-memory-only value resets to `None` on every app launch,
so the very first reveal of a new session always fell into the "no prior value, skip the pause"
branch even when the streak had genuinely grown since the app was last closed. Returns `None` (not
`0`) when never set, so a fresh install or pre-feature upgrade with a real non-zero streak doesn't
misread "never tracked" as "previous was 0" and spuriously animate a 0→N count with a pause that
implies growth from nothing.

**Panel-reopen catch-up gap (the trickiest part).** `QTabWidget.currentChanged` only fires when the
active tab index actually changes. If the Stats panel slides open with Timeline already the
remembered active tab (normal case: panel was last closed on Timeline/Streak), `_on_tab_changed`
never runs this session — the only code path that executes is the plain `refresh_current_tab() ->
_refresh_time() -> StreakGrid.set_data()` slide-reopen flow, which (correctly, by design) never
triggers `animate_reveal()`/`animate_labels_in()` on the grid. Before this fix, that same flow also
silently swallowed the streak count-up: `set_data()` just snapped the displayed number straight to
the new value with no comparison against the persisted previous value at all, so a streak that grew
while the app/panel was closed showed the new number immediately with no visual call-out — and the
user only ever saw the pause-then-tick by accident, on the next *manual* tab switch (which doesn't
re-derive "previous" correctly either, since at that point the display already shows the new value).
Fix: `_refresh_time()` takes a `streak_mode` parameter (`"full"` | `"catch_up"` | `"none"`) instead
of a single animate-or-not boolean. `"catch_up"` is wired only from `refresh_current_tab`'s Timeline
branch (the slide-reopen path) and calls `StreakGrid.catch_up_streak_count(previous)`: snaps the
display straight to the persisted previous value (no count-up, no grid touch at all — the hard "no
animation on slide-reopen" rule still applies to the grid), then after the same pause used
elsewhere, ticks up to current via the existing leg-2 logic. `"full"` (tab click, view-switch seam)
runs the normal two-leg `animate_streak_count()`. `"none"` (background refreshes like `refresh_all`)
leaves `set_data()`'s plain snap untouched, no persistence write. This is the only place where the
streak number's animation rule deliberately diverges from the grid's: the grid stays fully static on
every slide-reopen, the number gets one exception so a real change is never silently swallowed.

**Deferred:** matching the pause-then-tick effect inside the grid itself — dimming the
`current - previous` newest day-cells and revealing them one at a time, in lockstep with the
counter's leg 2 tick, while still drawing the longest-run border and finished-dot correctly on
already-revealed cells. Estimated moderate-to-high complexity (new per-cell "pending reveal" state,
likely replacing leg 2's continuous tween with a discrete step timer, careful interaction with the
existing `is_longest`/`_finished`/pop-scale logic) — explicitly scoped as a separate future pass, not
attempted here.

## VU-meter oscillation on embedded M4B FIXED (2026-06-16)

**Symptom:** clicking Next/Prev or a chapter-list item **while playing** caused the chapter slider
to spike full-right (~100%), chapter labels to show "00:00:00 / -00:00:00", and the chapter name to
flash the wrong chapter — all for one 200ms tick before self-correcting. Only while playing; never
while paused.

**Root cause:** `player.chapter_list` (property) fell back to `self.instance.chapter_list` for
embedded M4B — a live read from the mpv C layer on every call. During/after a seek, mpv's C thread
updates chapter boundary data asynchronously; one tick where `_sync_chapter_ui` reads a transient
state produces either near-zero `chap_dur` (labels write "00:00:00"; slider `setValue` is already
guarded by `chap_dur > 0` at line 1678 so it skips) or `c_elapsed ≈ chap_dur` with stale boundary
(slider full-right). While paused, mpv's C thread is quiescent after settle — no race.

**Hypothesis confirmed:** the `[CHAP-UI]` Step-0 instrument ran during a multi-hour soak with no
spike tick ever appearing, which means the cache eliminated the race entirely before it could be
observed. The specific hypothesis (A: near-zero chap_dur / B: stale boundary) was never confirmed
from a log line — the fix held for all soaked seeks. The `setValue` guard at line 1678 is an
independent safety net that remains.

**Fix:** `cache_chapter_list()` in `player.py` snapshots `instance.chapter_list` into `_chapter_list`
once at file-loaded time (called from `_on_file_loaded_populate_chapters` after `dur` is confirmed).
The `chapter_list` property already prefers `_chapter_list` when non-None → all reads during playback
hit the stable Python list, never the live C layer.

**Sentinel swap:** two code sites previously used `_chapter_list is None` as a proxy for "this is
embedded M4B" — `seek_async` (paused undershoot comp) and `_chapter_seek_offset()` (−0.09 offset).
After the cache, `_chapter_list` is non-None for embedded M4B too, so both were switched to a
dedicated `_is_embedded_m4b` flag set by `cache_chapter_list()`. The `chapter_list` property's own
early-return (`if self._chapter_list is not None`) is unchanged and correct.

## Chapter-slider paused "sliver" FIXED; load-time transient sliver DEFERRED (2026-06-15)

**Fixed (paused sliver):** at a freshly-landed chapter start, the chapter slider showed a thin fill
("sliver") while paused — the VT/CUE nav target is `nominal + _CHAPTER_BOUNDARY_EPSILON` (0.35), so
`c_elapsed = pos − chap_start ≈ 0.35`, rendered as a few-percent fill on a short chapter. Visible ONLY
while paused (live playback advances `pos` and swallows it within a frame). Fix is display-only:
`_sliver_clamp(pause, c_elapsed)` in `app.py` reads the slider value as 0 when paused AND
`c_elapsed < _CHAPTER_SLIVER_EPS` (= `_CHAPTER_BOUNDARY_EPSILON + 0.25` = 0.60, tied to the constant so
it tracks any retune). Applied at both the 200ms `_sync_chapter_ui` setValue and the flow-anim
`new_chap_val`. Released instantly on play (gate opens, `pos` already moving → no jump, no animation).
Labels untouched (already floor to 00:00). Measured paused settle jitter ~0.0004s, so 0.25 headroom is
~600× the real landing error (soak logs `/tmp/fabulor_{run,vtfix,vtboth}.log`). Headless tests:
`tests/test_sliver_clamp.py`.

**Deferred (load-time transient sliver):** on book load at a chapter start, the slider can show a brief
sliver then self-correct on the next tick. This is the one-frame flow-path residual (pause/value settle
ordering at load), NOT the paused artifact above — it's transient, cosmetic, self-healing, and tied to
the delicate `load_book` cache-reset / flow-animation ordering we deliberately don't want to disturb.
Deferred. If chased later: the `_sliver_clamp` at the flow-anim site depends on `load_book`'s
`_cached_pause = True` reset running first — do not reorder the computation above that reset.

## First-chapter Prev rewinds to 0:00 (drop the 2s threshold in chapter 0) (2026-06-15)

In the FIRST chapter there is no previous chapter, so `previous_chapter`'s `2.0 × speed`s
restart-vs-previous threshold doesn't apply. Previously, sitting in the first 2s of chapter 0 made Prev
a no-op (the `curr_chap > 0` branch dead-ended), leaving e.g. 0:01 awkward to clear to 0:00 without the
right-click progress-reset (which casual users won't know). Now `curr_chap == 0` always
`seek_async(0.0)` → rewinds to book start (both VT and non-VT branches). The `seek_async` 0.05 floor
still applies (true-0/negative absolute seek can land mpv at EOF — see the floor rule), so it lands at
0.05s ≈ 00:00 (and the sliver clamp reads it as 0). Freeze invariant preserved: `seek_async` sets
`is_seeking` WITH a matching `_seek_target`, so no stranding. Tests updated in `tests/test_vt_seek.py`
(the old "chapter-0 Prev is a no-op" contract was intentionally replaced).

## VT loads are STRICTLY SERIALIZED — no overlapping-seek clobber (2026-06-15)

Proven by a both-edges capture (`[PLAY-ISSUE]` at each `play()`, `[FILE-LOADED]` at `_on_file_loaded`):
every `play()` produces its matching `file-loaded` ~12–18ms later, IN issue order, before the next
`play()` is issued. So the rapid-backward-seek "overlapping cross-file seeks clobber `_file_offset`/
`_seek_target`" theory does NOT occur in practice. This retired a large amount of explored machinery
(a single seek-state object, PendingLoad records keyed by index, generation counters, FIFO-vs-path
disambiguation) — all of it solving a clobber that can't happen while loads are serial. If a future
mpv version or refactor ever makes loads async/batched, the committed `[VT-DESYNC]` tripwire in
`_on_file_loaded` will fire (loaded path != `_virtual_timeline[_current_vt_index]` path), and the
shelved design in `experiments/seek_state_desync/` becomes relevant. Until then: `_current_vt_index`
and `_file_offset` set speculatively in `seek_async` before `play()` ARE correct at `_on_file_loaded`
time, because nothing overlapped to change them.

## VT cross-file seek froze because `_seek_target` was stored LOCAL, settle compares GLOBAL (2026-06-15, FIXED `29b266c`)

Permanent chapter-UI freeze on VT books after a cross-file seek (e.g. rapid backward seek). Root
cause: `_on_file_loaded`'s cross-file follow-up set `self._seek_target = pending` where `pending` is a
LOCAL offset into the new file, but the settle in `_on_time_pos_change` is
`abs((value + _file_offset) − _seek_target) < 1.0` — i.e. it expects `_seek_target` in GLOBAL space.
So `abs(global − local) ≈ the file's cumulative_start` (e.g. 110107), never `< 1.0`, `is_seeking`
stuck True forever, chapter slider + remaining-time frozen. Signature in the log: `seek=True tgt=0.35`
while `gpos` is in the thousands. Fix: `self._seek_target = pending + target_file['cumulative_start']`
(GLOBAL); the mpv `command_async('seek', pending, ...)` stays LOCAL. Uses the timeline entry
(self-consistent with the index that drives the seek) not the bare `_file_offset` field. Validated:
`tests/test_vt_seek.py` is RED with the old LOCAL line and GREEN after, against the real captured
`vtidx=0` (target 0.35) and `vtidx=27` (target 0.35+108000) cases. The same coordinate-space bug was
identifiable in the very first agent trace weeks ago; it got buried under an offset-clobber theory and
re-surfaced only when the real both-edges capture was read.

## Boundary nav stranded `is_seeking` → freeze; the unconditional app-level set was the bug (2026-06-15, FIXED `29b266c`)

Separate permanent freeze (reproduces on M4B AND VT). `handle_prev`/`handle_next`/`_on_prev_right_click`
in app.py set `self.player.is_seeking = True` UNCONDITIONALLY after calling the player nav method. At
the **chapter[0] Prev boundary** (within ~first 2s, where the "go to previous chapter" branch runs but
there is no previous chapter) and the **last-chapter Next** boundary, `previous_chapter()`/
`next_chapter()` no-op WITHOUT calling `seek_async`, so `_seek_target` is never set. The unconditional
`is_seeking = True` then strands the flag: `is_seeking=True, _seek_target=None` → the settle
(`...and self._seek_target is not None`) can never run → permanent freeze. Log signature: `seek=True
tgt=None` while `value` climbs freely. Fix: REMOVE the redundant app-level `is_seeking = True`; the
nav methods set `is_seeking` via `seek_async` ONLY when they actually seek. This is the SAME class as
the chapter-list-click freeze fixed earlier (`_on_chapter_list_selected` already carries the warning
comment). User-confirmed by soak (markers: "chapter[0] within first second, left-click Prev → freeze;
wait 2s → correct; right-click Prev always works"). Harness adds contract guards that the nav methods
at a boundary leave `is_seeking` False.

## Playing-seek chapter-UI oscillation — RESOLVED by M4B cache fix (2026-06-16)

Isolated while verifying the position-creep fix (2026-06-13). Clicking Next/Prev or a chapter-list
entry **while playing** made the chapter slider jump to the chapter's END and bounce between chapters
before settling; the chapter label flickered identically.

**Resolution (2026-06-16):** no bounce/stick observed during multi-hour soak after the embedded M4B
`cache_chapter_list()` fix landed. The two symptoms (VU-meter spike full-right and bounce/stick) were
the same bug: `player.chapter_list` for embedded M4B was a live C-layer read on every call; during a
playing seek mpv's C thread updated boundary data mid-read, producing transient `chap_dur ≈ 0` or
wrong `c_elapsed`. The cache eliminated the race entirely. The stale-backward-sample hypothesis below
was the best theory at the time but the cache fix made it moot.

**History (kept for reference):** the earlier "settle clears too early" hypothesis was disproven by
instrumentation (`dist=0.0` clean settles). The updated hypothesis was a stale BACKWARD `time_pos`
sample mpv emits after a clean settle (~0.56–0.87s back). A fix (`b6a4023`, drop backward global
jumps while not seeking) was reverted (`4ae0783`) because it regressed VT backward-seek + play/pause
icon + chapter[1]→[0] click. That revert is still in the tree and correct — do not re-apply it.

## Position creep on restart was an epsilon on the restore seek (2026-06-13, FIXED `3bb14cf`)

`_restore_position` added `+_CHAPTER_BOUNDARY_EPSILON` (0.35) to the non-VT restore seek. Restore is
NOT chapter navigation — no boundary to clear — so this was wrong. The save path
(`_save_current_progress` / `_sync_persistence`) saves the true `time_pos`; on restart the seek landed
at `progress + 0.35`, the 200ms sync saved that inflated landing, and it became the next restore's
input → ~0.35s forward every restart until EOF. The VT branch (`seek_async(progress)`, no epsilon)
never crept — direct proof non-VT needed none. Fix: collapse both branches to a single
`seek_async(book_data.progress)`. The `_CHAPTER_BOUNDARY_EPSILON` import stays — still used by the
VT-gated flow-animation display offset at app.py:1250 (unrelated). This fixed ONLY the creep; the
load-time sliver/clip are the separate pre-existing oscillation family above.

## Chapter-seek precision: mpv overshoots ~0.09s playing, undershoots ~0.37s paused (2026-06-13)

The single biggest non-obvious finding of the Session 3+4 chapter-seek work. **mpv's exact seek
(`command_async('seek', pos, 'absolute+exact')`) does NOT land on `pos`.** Measured across 5
embedded M4Bs / 67 chapter seeks (temporary `[CHAP-MEASURE]` instrumentation, since removed):

- **Playing:** lands ~**+0.09s** PAST the target (1–2 AAC frames of overshoot). Consistent across
  files; the spread is frame-quantization (~0.046s steps at 1024/22050Hz), not per-file variance.
- **Paused:** lands ~**−0.37s** SHORT of the target, and the `time-pos` observer reports unstable
  intermediate values while paused (e.g. `settled=28101` for a `nominal=1289` seek — do not trust a
  single post-seek `time_pos` sample while paused).

This overturns the old documented rationale ("mpv chapter floats land ~0.25s short of nominal").
Switching to `exact`/`hr-seek` is a **no-op** — the code already uses `absolute+exact`; the residual
is decoder/frame landing, not keyframe snapping. Do not re-propose it.

**Why the old single `_CHAPTER_BOUNDARY_EPSILON = 0.35` "worked" and what it cost:** it was doing
two jobs at once — a read-side position→chapter-index walk tolerance AND a seek-target epsilon.
As a walk tolerance, 0.35 *barely* covered the ~0.37 paused undershoot (which is why paused Next/Prev
got stuck "occasionally" — the undershoot sometimes exceeded 0.35). As a seek epsilon, +0.35 on top
of mpv's own +0.09 overshoot skipped ~0.44s of every chapter's opening audio ("Part 3"→"3",
"Nineteen"→"teen"). The user's prior manual sweep finding "0.35 is the only reliable value" was the
walk-tolerance constraint, not an audio sweet spot.

**The three-constant split (player.py):**
- `_CHAPTER_WALK_TOLERANCE = 0.5` — ALL position→index walks (`time <= pos + X`) in player.py and
  app.py. Must exceed the ~0.37 paused undershoot; 0.5 is still far below the ~2s minimum real
  chapter spacing, so it can't misattribute to an adjacent chapter.
- `_EMBEDDED_CHAPTER_SEEK_OFFSET = -0.09` — embedded-M4B chapter-nav seek targets (via
  `_chapter_seek_offset()`). Cancels mpv's playing-overshoot.
- `_PAUSED_SEEK_UNDERSHOOT_COMP = 0.37` — forward correction added to the mpv seek **command only**
  when paused + embedded, inside `seek_async`. `_seek_target`/`_cached_time_pos` keep the logical
  (uncompensated) position so the walk/UI stay correct. Guarded so it doesn't push into the near-EOF
  deadzone.
- `_CHAPTER_BOUNDARY_EPSILON = 0.35` — now ONLY the VT/CUE seek-target epsilon. Do NOT reuse for
  walks or embedded seeks.

**`seek_async` target floor (`if pos < 0.05: pos = 0.05`):** the negative embedded offset turns a
Prev/Next that resolves to chapter 0 (nominal ≈ 0) into a NEGATIVE absolute seek. mpv treats a
negative/zero absolute seek as undefined and **lands at EOF** — observed as "previous chapter near
book start jumps to 100% and marks the book finished." The floor prevents this and also self-heals
the secondary "next is stuck" symptom (a bad seek had set `_eof`, after which `next_chapter`'s
`if self._eof: return` did nothing).

VT first-word clipping (multi-file) is the same *class* of issue but a different *cause* (VT chapter
boundaries are file starts from summed mutagen durations vs mpv's decoded sample count) and is
**deferred** — VT clicks/nav still use `+0.35`.

## Chapter-list click freeze was a stuck `is_seeking` flag, not a seek problem (2026-06-13)

Embedded-M4B chapter-list clicks froze the chapter slider + chapter time labels (audio and the
overall slider were fine) until a manual slider click revived them. Root cause: the embedded click
navigated via native `self.player.chapter = idx`, whose setter sets `instance.chapter` and
`_eof = False` but NOT `_seek_target`. `_on_chapter_list_selected` set `is_seeking = True`
unconditionally; `_sync_chapter_ui` and `_update_chapter_label_from_index` early-return while
`is_seeking` is True; and `is_seeking` is cleared ONLY by `_on_time_pos_change` when
`_seek_target is not None` (`_on_chapter_change` is fully suppressed). Native chapter assignment never
set `_seek_target`, so the clear condition could never fire → permanent freeze. A manual slider drag
calls `seek_async` (which sets `_seek_target`), which is why it "revived" the UI.

**Fix:** new public `Player.activate_chapter_index(idx)` seeks to
`chapter_list[idx]['time'] + self._chapter_seek_offset()` via `seek_async` (mode-aware offset). All
book types now route chapter-list clicks through it; the embedded native-nav branch is gone, as is
`ChapterList`'s reach into `_virtual_timeline`/`_chapter_list` (the coupling violation previously
flagged in NOTES is now RESOLVED — `_activate_item` calls one public method, no private-attr access).
Removed the redundant `is_seeking = True` from `_on_chapter_list_selected` (`seek_async` sets it
synchronously, before the slot fires, with `_seek_target` set). This crossed the former CLAUDE.md
"embedded clicks must use `self.chapter = idx`" rule — that exception (git `e243193`, 2026-05-17)
existed only because the *then-current* `seek_async + 0.35` drifted, which the −0.09 model fixed.
The native `chapter` **getter** is still read by `apply_smart_rewind` (clamp to chapter start) and
remains valid: mpv updates its native chapter from playback position regardless of how the seek was
issued. CLAUDE.md (all references) revised in the same commit.

## `refresh_current_tab()` dispatch must use the live tab name, not the old one (2026-06-13)

`refresh_current_tab()` dispatches by `tabs.tabText(currentIndex())`. When a tab is renamed, every dispatch branch in every dispatch function must be updated in the same commit — there is no compile-time check. The Timeline tab was renamed from `"Hour"` to `"Timeline"` in `addTab` and `_on_tab_changed` but the `refresh_current_tab()` branch was missed, silently skipping `_refresh_time()` on every panel-open and session-write while that tab was active. If a tab name changes in the future, grep for the old string across the whole file before committing.

## Per-session delete must emit `history_deleted` to refresh the stats StreakGrid (2026-06-12)

The "delete all history for this book" button (`_on_delete_book_stats_confirmed`) emits
`BookDetailPanel.history_deleted`, which is wired to `stats_panel.refresh_all` **and**
`library_panel.refresh` (`main_window_builders.py:556-557`). The **per-session** delete
(`_on_history_delete_confirmed`, the 2026-06-10 `_HistoryRow` flow) originally did NOT emit it — it
only called `_refresh_stats()` (the book-detail panel's own widgets). `db.delete_session` correctly
invalidates the streak-grid cache cell in-transaction, but the stats panel's `StreakGrid` (mounted
underneath the book-detail overlay when opened from a stats row) never re-queried, so a deleted day
could keep showing as listened until a tab change. Fix: emit `self.history_deleted.emit()` in the
per-session delete's `_finish` callback too — reuses the existing fan-out, no new signal. The emit
fires from a `QPropertyAnimation.finished` callback (UI thread), so the existing direct connection is
correct. The recorder is NOT involved in deletes (`db.delete_session` is called straight from the
panel) — do not route deletion notifications through `SessionRecorder`. Was REVIEW_PASS7 finding #9.

## StreakGrid invariant: a 'finished' day is ALWAYS a listened day (2026-06-12)

**Bug fixed:** the grid could show a finished dot on an UN-filled cell — a book taken to
finished on a day with no session ≥ 60s lit the dot (`book_events`) but not the fill
(`streak_grid_cache`, which is session-only). Worse, even after filling the cell, the day didn't
count toward the streak number (`get_streaks` reads sessions only).

**Rule now enforced everywhere:** `finished ⟹ listened`. A 'finished' `book_event` marks its day
as listened in the cache, counts toward `get_streaks()` current/longest, counts in
`StreakGrid._compute_longest_run`, AND the dot shares the filled cell. All using the **same
day_start_hour adjustment as sessions** — finished dates used to be raw calendar dates (different
cell for a non-midnight day-start); they are now adjusted dates so dot and fill always coincide.

**The six touch-points (keep them consistent — this is the new sync invariant):**
1. `build_streak_grid_cache` — the `listened=1` UNION includes finished adjusted-dates.
2. `_update_streak_grid_cache_for_date` — if no session backs the day, falls through to a finished-event check before darkening (so deleting the last session on a finished day keeps it lit).
3. `write_book_event(event_type='finished', day_start_hour=…)` — marks the cell at finish time (immediate, no rebuild needed).
4. `unfinish_book(book_id, day_start_hour=…)` — re-evaluates the day; darkens if nothing else backs it.
5. `delete_book_stats` — gathers finished-event days (not just session days) into its recompute set.
6. `get_streaks` — unions finished adjusted-dates into its day set; `get_streak_grid_finished_dates(day_start_hour)` uses the adjusted date for the dot.

**Date-space:** ONE space now — day_start_hour-adjusted — across sessions, finished events, cache,
streaks, and dot. Do NOT reintroduce a raw-calendar finished date; it desyncs dot from fill.
**Existing data self-heals:** `build_streak_grid_cache` runs on every app startup (`app.py:319`),
so finished-but-dark days from before this fix light up on next launch — no migration.
Cross-check still holds: `len(StreakGrid._longest_dates) == get_streaks()['longest']` (both now
include finished days; if they diverge, an attribution change hit some sites but not all six above).

## StreakGrid — four facts that will confuse whoever touches it next (2026-06-11)

The streak-grid panel (`StreakGrid` + `TasselOverlay` in `stats_panel.py`) has four non-obvious points.
Full narrative is in SESSION.md (2026-06-11 Session 3); this is the quick "why is it like this" reference.

1. **`load_themed_icon` tints `currentColor` SVGs anyway — but use `load_currentcolor_icon` regardless.**
   clock.svg / calendar.svg use `fill="currentColor"`, not `fill="#000000"`. We expected the existing
   `load_themed_icon` (which only swaps `#000000`) to render them untinted — it doesn't, because its
   `<style>`-injection fallback (`if '<style' not in svg_data and 'stroke=' not in svg_data`) lands a
   `path { fill: color }` rule that Qt applies over `currentColor`. So both loaders produce a tinted icon.
   The new `load_currentcolor_icon` recolors `currentColor` **explicitly via regex** and is the preferred
   path for these icons — the `load_themed_icon` success is incidental to that fallback firing, not a
   contract. Don't revert clock/calendar to `load_themed_icon` "because it works the same."

2. **`books.finished_at` is dead — query `book_events` (`event_type='finished'`) for finished state.**
   `books.finished_at` is in the schema but never written (only reset to NULL). Every finished-book query
   uses `book_events`; `get_streak_grid_finished_dates()` does too. Querying `books.finished_at` returns
   silently empty.

3. **Longest-streak DATES are computed in the widget; `get_streaks()` returns only COUNTS.**
   `get_streaks(day_start_hour)` → `{'current','longest'}` ints, not which days. `StreakGrid` derives the
   date set itself (`_compute_longest_run` over the cache; ISO sort + consecutive-run scan; most-recent
   wins on a tie via `>=`). **Cross-check invariant:** `len(self._longest_dates) == streak_info['longest']`
   — two independent paths over the same `listening_sessions` data (SQL count vs. Python run scan over the
   cache). They were equal (16==16) against the real DB. A divergence means the cache and `get_streaks`
   have drifted (an attribution change applied to one site but not the four cache sites — see the
   Session-1 "change all four" note). That mismatch is the diagnostic; do not clamp one to the other.

4. **`animate_conceal()` is additive-only; keep it separate from `animate_reveal()`.**
   `HourlyHeatmap.animate_reveal` and `paintEvent` are byte-for-byte unchanged. `animate_conceal` is a NEW
   method on both grids that reuses `reveal_progress` in reverse (1.0→0.0, 600ms) and **restores 1000ms in
   its `finished` callback** so the following construct wave runs full-length. Do NOT fold a
   `setDuration(600)` into `animate_reveal` to share code — the asymmetric restore is the whole point.
   It tracks its pending slot in `self._conceal_slot` and disconnects only when present (no
   `Failed to disconnect (None)` warning). Relatedly, `StreakGrid.set_data` does NOT self-reveal — the
   caller fires exactly one `animate_reveal()`, else the tab-change reveal double-fires and hitches.

## Timeline header date labels — "J" glyph clipped at top edge (2026-06-10, unresolved)

**Goal:** The rotated date labels at the top of `HourlyHeatmap` show months starting with "J" (Jan, Jun, Jul) as "un", "ul" — the top of the "J" glyph is cut off. May, Sep, Oct etc. render fine.

**Setup:** Labels are drawn rotated -90° via `painter.save() / translate / rotate(-90) / drawText / restore`. The translate anchor is at `(cx+2, DATE_LABEL_H - 3)`. After rotation, `AlignLeft` means text grows in the +x direction of the rotated frame, which maps to the -y direction (upward) in widget space. So the *start* of the string (the "J") is nearest the widget's top edge (y=0).

**What the red background diagnostic showed:** The `QRect` passed to `drawText` is fully inside the widget — there is plenty of space above the rect. The "J" is not being clipped by the widget boundary or the rect boundary in any obvious geometric sense. Despite `setClipping(False)` on the painter, the glyph is still truncated.

**Approaches tried and why they all failed:**

1. **Increase top container margin** (`outer.setContentsMargins(8, 12→30, 8, 8)`) — moves the widget down so its y=0 is further from the screen edge. With 30px margin the "J" rendered. But this adds ugly whitespace and doesn't fix the root cause; it just hides it.

2. **Increase `DATE_LABEL_H`** (44→48→50→52→58) — grows the widget header zone and pushes the grid down. Tried in combination with adjusting the translate offset to keep labels visually in place. Never fixed the clipping regardless of value.

3. **Adjust translate y** (`DATE_LABEL_H - 1`, `-3`, `-17`) — shifts the anchor point. Moving it down (larger subtract) pushes text further from the grid. Moving it up (smaller subtract) pushes text closer to y=0 and makes it worse. None fixed "J".

4. **Offset the text rect x** (`QRect(4, ...)`, `QRect(6, ...)`) — in rotated space, positive x maps to downward in widget space, so this pushes the text start away from y=0. Visually this just clipped May and other months too — the rect was now too short for the full text.

5. **Negative x on the text rect** (`QRect(-6, ...)`) — intended to let the "J" glyph bleed past x=0 in rotated space (= above y=0 in widget space). Made no visible difference.

6. **`painter.setClipping(False)`** before the label loop — no effect. Qt clips painter output at the widget boundary regardless of this flag when painting inside a `paintEvent`.

7. **`AlignRight`** — anchors the text end (the day number) near the grid, so "J" starts further from y=0. User confirmed this was already tried independently and still showed "un" not "Jun".

8. **Per-label `j_offset`** — tried shifting J-month labels by 4px via `DATE_LABEL_H - 3 + j_offset` in the translate. No effect.

9. **Font metrics `descent_extra`** — tried computing `fm.descent() - fm.leading()` and using it as either a translate offset or a rect x offset. Didn't fix it; the x/y confusion in rotated space made results unpredictable.

**What is actually happening (hypothesis):** Qt's `drawText` clips the rendered glyph to the bounding rect even when the glyph's ink extends outside it (e.g. a "J" whose hook descends below the baseline, which in rotated-90° space maps to above the rect's left edge). `setClipping(False)` on the painter does not disable this per-glyph clipping — that is internal to Qt's text renderer. The fix likely requires either: (a) painting the text at a position where the glyph's natural ink extent stays inside the rect (i.e. add padding at the rect's start equal to the font's descent), or (b) using a `QPainterPath` to stroke the text outline instead of `drawText`, which respects `setClipping(False)`. Option (a) is the sane path but requires knowing the exact descent in rotated coordinates.

**Resolution:** The clipping was the rect *height* being too tight, not the widget boundary or the rect's x origin. After rotate(-90), the rect's height maps to horizontal ink space in widget coordinates. `CELL=14` is too narrow for glyphs whose ink extends outside the em square (e.g. "J"'s hook). Fix: `QRect(2, -self.CELL, self.DATE_LABEL_H, self.CELL * 2)` — doubling the height and centering it with `y=-CELL` gives all glyphs enough room. The `x=2` is the 2px margin from the grid edge.

---

## Semi-transparent session history rows — investigation dead end (2026-06-10)

**Goal:** Make `_HistoryRow` widgets in the Book Detail Panel History tab render semi-transparently like the tag rows in the Tags panel, so the panel background (and cover art behind it) bleeds through.

**Why it looks like it should work:** The panel background is `rgba(bg_main, panel_opacity_hover)` set via QSS. The Tags panel rows use `rgba(bg_deep, 0.6)` in `get_tags_stylesheet` via a class-level `QWidget#tag_list_row` rule — no instance `setStyleSheet` — and they visually appear semi-transparent.

**Approaches tried and why they failed:**

1. **`rgba()` in instance `setStyleSheet` on the row** — an instance stylesheet has higher specificity than a parent/class rule in Qt's QSS cascade. The row's own `setStyleSheet` set a fully opaque background that won every time. Removing the instance stylesheet was necessary but not sufficient.

2. **`rgba()` in `get_stats_stylesheet` as a class rule (`QWidget#history_row_odd` / `even`)** — the stylesheet was generated correctly (verified via unit test: `rgba(19,8,72, 224)`). The row widget resolved the correct semi-transparent color in `palette()`. But visually the rows were still fully opaque. The scroll area viewport was painting an opaque fill on top.

3. **Making the scroll area transparent** — tried `QScrollArea#history_scroll QWidget#qt_scrollarea_viewport { background: transparent }`, `viewport().setAutoFillBackground(False)`, and `viewport().setAttribute(WA_NoSystemBackground, True)`. Palette tests confirmed `autoFill=False` on the viewport, but visual result unchanged. The `WA_StyledBackground` + `WA_NoSystemBackground` combo also didn't help.

4. **Making the container transparent** — added `WA_StyledBackground` to `_history_container` and named it `"history_container"` with a `background: transparent` rule. Container correctly resolved to alpha=0 in tests. Still no visual change on rows, and the changes broke slider fill/bg colors in the stats panel (unintended stylesheet interaction via the shared `get_stats_stylesheet`).

**Root cause hypothesis:** The `QScrollArea` internal viewport widget has special paint handling that isn't fully controlled by QSS or the `WA_*` attributes. The Tags panel works because its scroll area is inside `TagManagerWidget` which has its own stylesheet (`get_tags_stylesheet`) applied directly to it — not shared with other panels. The history scroll area shares `get_stats_stylesheet` with `stats_panel`, making scoped rules fragile.

**Current state:** Solid alternating row colors (`session_history_row_one` / `two` per theme, fallback `library_row_one` / `two`). Alzabo has explicit values. This is the working baseline.

**Possible future path:** Give `BookDetailPanel` its own dedicated stylesheet function instead of sharing `get_stats_stylesheet`. That would allow unscoped `QScrollArea { background: transparent }` rules without risking stats panel regressions. Not pursued — the effort/risk ratio is poor for a cosmetic change.

---

## TODO (before release): suppress shimmer when speed is already the default (2026-06-10)

`_on_speed_right_clicked` unconditionally plays the shimmer sweep on every right-click. Before release, add a guard: if `round(current, 9) == round(config.get_default_speed(), 9)` (same float-drift tolerance as `sync_btn`), skip both `set_default_speed` and `play_shimmer` — the speed is already the default, so there is nothing to confirm. Or allow one play but not repeated triggering on the same value. Decision deferred.

---

## "Delete listening history" button has manually managed cursor states — skip in bulk cursor pass (2026-06-10)

The button in the History tab has two explicit cursor states set in code:
- `PointingHandCursor` when idle (clickable)
- `ArrowCursor` while the "Click to delete all history for this book" confirm label is visible (not clickable)

Any bulk pass that sets `PointingHandCursor` globally (via QSS or a sweep of all interactive widgets) must **exclude this button**. Overriding it would break the disabled-state cursor and remove the visual signal that the button is temporarily inert.

Managed in `_on_delete_book_stats` (sets `ArrowCursor`, disables button) and `_cancel_delete_history` (restores `PointingHandCursor`, re-enables button).

---

## eventFilter safe-zone pattern for floating confirm labels (2026-06-10)

When a confirm label is floated absolutely above a button (not in the layout), the eventFilter's click-outside dismissal must include **both** the confirm label **and the button underneath** in the safe zone. Without the button in the safe zone, clicking the button while confirm is visible triggers this sequence:

1. `MouseButtonPress` fires eventFilter → confirm not hit → `_cancel_delete_history()` → confirm hidden, button re-enabled
2. Click propagates to now-enabled button → `_on_delete_book_stats()` → confirm shown again

The fix: `if not hits(confirm_label) and not hits(button): _cancel_delete_history()`. The button being disabled doesn't help here because the eventFilter fires before Qt's normal event routing.

---

## `_eof_event_written` resets only in `_on_file_ready` — never in `_on_revert_finish` (2026-06-08)

`_eof_event_written` guards the EOF block (app.py:1361-1363) from writing a
duplicate `finished` `book_event` on every 200ms UI tick while the player
sits at EOF — it's set `True` the first time the event is written, and the
*only* place it is reset to `False` is `_on_file_ready` (app.py:1092, on
the next book load).

An earlier version of `_on_revert_finish` also reset it to `False`, on the
theory that reverting "undoes" the finish and should let it re-fire later.
This was wrong and caused a re-arm bug: the player is *still sitting at
EOF* when revert is clicked (nothing seeks away), so the very next 200ms
tick saw `_eof_event_written == False` again, re-wrote the `finished`
event, and silently undid the revert the user just performed.

**Do not add that reset back to `_on_revert_finish`.** The flag's job is
"have we written a finished-event for *this* EOF arrival" — revert changes
the DB's finished status, not whether this EOF arrival already wrote its
event. `_on_file_ready` remains the sole legitimate reset point, because a
new `book_ready` means a genuinely new EOF can occur later.

---

## Known gaps — missing-file edge cases not yet exercised (2026-06-08)

While hardening the missing-folder/ghost-playback bug (guard in
`_on_book_selected_from_library` + try/except in `player.py`'s
`_ResolveWorker.run`), two related scenarios were identified but not
verified — both would need a populated multi-file (VT) book or real
removable media to test meaningfully, so they're logged rather than
speculatively patched:

- **Partial VT folder removal**: `_resolve_playlist` builds the virtual
  timeline straight from `db.get_book_files(path)` with no per-file
  existence check. If some (not all) files in a multi-file book are
  deleted externally, behavior is unverified — it may rely on the
  existing `end-file`/`ERROR` → `load_failed` → `_on_load_failed` banner
  path firing per missing file during VT advancement, or it may stall
  mid-book when `_advance_or_finish` tries to play a vanished path.
- **Removable/network drive unmount mid-buffer**: path exists at
  selection time, then the drive unmounts while mpv is buffering. Almost
  certainly funnels through the same `end-file`/`ERROR` →
  `load_failed` mechanism that already handles in-flight I/O errors
  (case "file disappears mid-playback", confirmed working), but the
  timing/UX — does the banner appear promptly, or does mpv hang during
  the buffer stall before the error event fires — is unverified without
  real removable media.

Two adjacent scenarios were checked and confirmed already handled:
file-vanishes-mid-playback fires mpv's `end-file` event with
`reason == ERROR (4)`, which `_on_end_file` turns into `load_failed` →
`_on_load_failed`'s "Failed to load: {reason}" banner (player.py:426-433,
app.py:1220-1222); and startup restore of a missing last-played book is
guarded by `os.path.exists(last_book)` at app.py:390, falling through
cleanly to the empty-library state with no stale UI.

---

## HoverButton + setToolTip on small buttons causes an enter/leave feedback loop (2026-06-08)

`eof_revert_btn` (24×24, in the status banner) was built as a `HoverButton`
with `setToolTip` and `setCursor(Qt.PointingHandCursor)`, intended to swap its
icon color (`accent` → `accent_light`) on hover. In practice the tooltip
popup overlapped the small button, stealing the hover — which fired
`leaveEvent`/`enterEvent` on the button again, re-showing the tooltip, in a
loop. Symptoms: the tooltip flickered in and out, and the cursor cycled
between arrow and pointing-hand.

Systematic elimination ruled out the obvious suspects: disabling the icon
swap entirely (`setIcon` calls) had no effect, and `cancel_scan_btn` /
`eof_close_btn` — both plain `QPushButton`s with `setCursor` + `setToolTip` —
were completely stable. The cause was specifically `HoverButton`'s
`enterEvent`/`leaveEvent` overrides and `hovered`/`unhovered` signal emission
interacting badly with native Qt tooltip tracking on a small widget.

**Fix:** use plain `QPushButton` + `installEventFilter(self)`, handling
`QEvent.Enter`/`QEvent.Leave` directly in the global `eventFilter` to drive
hover-based icon swaps. Avoid `HoverButton` for small (<~30px) widgets that
also need a tooltip — or skip the tooltip (the eventual choice here: both
banner buttons are visually self-explanatory, so tooltips were dropped
entirely rather than chasing precise `QToolTip.showText` placement, which has
no window-bounds awareness and is fragile on small widgets near window edges).

---

## Startup animation stutter (2026-06-07)
On app startup, `book_ready` fires while the event loop is under pressure
from background work (stats panel cache, cover cache, library population).
The flow animation competes for main-thread time, producing a stutter around
the 15-25% mark. Library loads are smooth because the app is idle at that
point.

This is not a race condition — it is event-loop contention during a
legitimately busy startup window. It cannot be fixed at the animation layer.

Three options for future revisit:
1. **Skip animation on startup** — detect `_switch.phase == IDLE` (startup
   never calls `begin()`, so phase stays IDLE), go straight to `setValue`.
   Low risk, zero complexity, inconsistent with library-load behavior.
2. **Defer/cheapen background work** — lazy-load stats/cover cache, move
   population off the main thread. Correct long-term fix, large scope.
3. **Delay animation** — fragile, hardware-dependent. Rejected.

**Intermittent chapter[0] flash on **
Pre-existing. Probably only occurs on app start, not on library book loads. Not
addressed this session.

---

## Startup flow animation: pre defaults to 0, not None — 2026-06-06

`_on_file_ready` and `_on_file_loaded_populate_chapters` both do `pre = SM.take_*_target(); pre = pre if pre is not None else 0`. The `None` case covers startup, EOF-restart, and post-removal loads (no `begin()` was called).

Defaulting to 0 is safe for all three:
- **Startup / post-removal with progress:** animates from 0 to the saved position — correct, there is no meaningful "old" slider position.
- **EOF-restart:** `new_progress == 0` so `new_val == 0`, `pre == new_val`, falls into `setValue(0)` — no animation, no visible change.
- **DB duration fallback (`book_data.duration`):** used as fallback when `player.duration` is not yet cached. Sufficient to compute `new_val`; the 200ms timer corrects with the live mpv value once available. Does not affect the `_chaps_dur_retried` retry path, which guards against `player.duration` being `None` independently.

---

## flow_pending_chapter gate in _update_chapter_label_from_index — 2026-06-06

`_update_chapter_label_from_index` has two gates: `player.is_seeking` and `self._switch.flow_pending_chapter`. The second gate was added because `is_seeking` alone is insufficient in the deferred populate path.

When `_on_file_loaded_populate_chapters` is deferred (library still animating) and the seek settles before the 50ms drain fires, `_is_seeking` is already False by the time `populate()` is called. `populate()` sets row 0, emitting `currentRowChanged(0)`, which fires `chapter_changed(0)` and writes chapter 0's name to the label before `_sync_chapter_ui` can correct it.

`flow_pending_chapter` is True throughout `_on_file_loaded_populate_chapters` — `take_chapter_target()` is called after the `try` block, after `populate()`. So the gate blocks the spurious index-0 update and lifts only after the chapter animation target is established.

---

## _set_bg_suppressed re-assert uses direct color assignment, not _set_chapter_ui_active — 2026-06-06

After `content_container.setStyleSheet(...)`, Qt calls `polish()` on all child widgets, which re-reads QSS and overwrites `bg_color`/`fill_color` back to theme colors on the chapter slider. The re-assert in `_set_bg_suppressed` uses direct property assignment (`s.bg_color = QColor("transparent")`), NOT `_set_chapter_ui_active(False)`.

Calling `_set_chapter_ui_active(False)` here would: stop in-flight `bg_color`/`fill_color` QPropertyAnimations (breaking theme fades mid-transition), reset cursor and label stylesheets (side effects wrong at this site), and caused chaptered→chaptered regressions in testing. Direct color assignment is the minimal correct fix and avoids all of these.

---

## Removed preemptive _set_chapter_ui_active(False) from _on_book_selected_from_library — 2026-06-06

The unconditional `_set_chapter_ui_active(False)` before every book load hid the chapter slider regardless of whether the outgoing book had chapters. For chaptered→chaptered switches this destroyed the flow animation: the slider cleared, triggered a hide/show cycle that disrupted `when_animations_done` timing, and caused the chapter ghost. The old position — which is the animation's start point — was gone before `animate_to` could use it.

Protection for chapterless books moved to `_set_bg_suppressed`, which is the correct architectural home: it fires exactly when the repolish that needs countering happens, and only when `_chapter_ui_active` is already False (so chaptered books are unaffected).

---

## Scanner known_paths must be unfenced — 2026-06-06

`scanner.py` uses `known_paths` to skip re-extracting metadata for books already in the DB. Previously built from `get_all_books()` which filters `is_excluded=0 AND is_deleted=0`. Excluded/deleted books were therefore absent from `known_paths`, treated as new by the scanner, and passed to `upsert_books_batch` — which resets `is_excluded=0` and `is_deleted=0`, resurrecting them on every scan.

Fix: `get_all_book_paths()` queries `SELECT path FROM books` with no filter. Excluded/deleted books are now recognised as known and skipped. Side effect: folder removal + re-add no longer auto-resurrects `is_deleted` books via a non-force scan. A manual Rescan (force_refresh=True) still works. Silent resurrection was worse than requiring an explicit rescan.

---

## Theme fade must not start while any slider value animation is running — 2026-06-05

`animate_to()` on a slider while a theme fade overlay punch-through is active causes ghosting. The overlay punches a hole for each included slider, exposing the live widget. If the slider's fill position is moving, the animated fill produces a visible ghost against the static overlay screenshot.

**What is safe for themes:** color animation only (`bg_color`/`fill_color`/`notch_color` via `QPropertyAnimation` in `theme_manager.py`). Colors change inside the widget without moving the fill, so no position-ghost is produced.

**What causes ghosting:** `animate_to()` (value/fill animation) overlapping with the fade overlay's active window.

**Progress slider:** safe because `_apply_pending_cover_theme` defers via `progress_slider.when_animations_done()`. The theme fade starts only after the progress animation completes.

**Chapter slider:** safe because `_apply_pending_cover_theme` chains a SECOND wait through `chapter_progress_slider.when_animations_done()` after the progress slider. Both must settle before `apply_cover_theme` fires.

**Invariant (enforced by `_apply_pending_cover_theme`):** cover art theme fade starts only after BOTH `progress_slider` AND `chapter_progress_slider` animations have finished. If any new slider gets `animate_to()` during book switches, add it to the chain.

---

## _set_bg_suppressed must use _active_display_theme, not _current_theme_name — 2026-06-05

`_set_bg_suppressed` regenerates `content_container`'s stylesheet by calling `get_player_stylesheet(theme_name, suppress_bg_image=...)`. Using `_current_theme_name` (the named pool theme) instead of `_active_display_theme` (which holds the cover dict when a cover theme is active) causes a one-frame flash to the pool theme on every book switch, because `apply_library_state` calls `_set_bg_suppressed(False)` on each switch.

Fix: `theme_name = getattr(tm, '_active_display_theme', None) or tm._current_theme_name`.

---

## Chapter slider background: preemptive _set_chapter_ui_active(False) at book switch — 2026-06-05

The chapter slider background becomes briefly visible during book switches. Root cause: `apply_current_state → apply_library_state → _set_bg_suppressed` repolishes child widgets (via `content_container.setStyleSheet`) resetting the chapter slider's `bg_color` from transparent back to the theme color, before `_on_file_loaded_populate_chapters` calls `_set_chapter_ui_active(False)`.

Fix: call `_set_chapter_ui_active(False)` preemptively in `_on_book_selected_from_library` at selection time. The slider stays transparent throughout the loading window. `_on_file_loaded_populate_chapters` restores it to active only when chapters are confirmed.

Also: `_set_chapter_ui_active(False)` must stop any running `bg_color`/`fill_color` QPropertyAnimations on the chapter slider before setting transparent. A theme fade that started while the book had chapters creates color animations targeting non-transparent values; they override the transparent assignment on the next animation frame.

---

## Library sort: computed keys must not be passed to get_all_books() — 2026-06-05

`"finished"` is computed in-memory by `BookModel` from `_finished_dates`; it is not a DB column and is not in `db._ALLOWED_SORT_COLUMNS`. Any code path that passes a `SORT_KEY_MAP` value to `get_all_books()` must guard against computed keys:

```python
if sort_key not in self.db._ALLOWED_SORT_COLUMNS:
    sort_key = "title"
```

Currently applies to `start_idle_preload`. Any future method with the same shape needs the same guard.

---

## _finished_dates is the source of truth for Finished sort/filter — 2026-06-05

`BookModel._finished_dates: dict[int, datetime]` is populated via `db.get_finished_book_data()` in `LibraryPanel.refresh()`. It is the sole authority for whether a book is "finished" and when it was last finished.

`books.finished_at` exists on the schema but is **never written** anywhere in the codebase. Do not read it for Finished-related logic. Either implement the write or drop the column in a future migration — currently harmless but confusing.

The `effective_val` / `have-missing` split in `_apply_filter_and_sort` handles `"finished"` via `self._finished_dates.get(b.id)` — **not** `getattr(b, "finished", None)`. The field does not exist on `Book`; `getattr` would return `None` for every book, silently dumping the entire Finished view into `missing`.

---

## Sort key and direction must be saved to config together — 2026-06-05

`_on_sort_changed` saves both `sort_key` and `sort_ascending` to config whenever the user switches sort keys. `_toggle_sort_direction` saves only the direction. This means config always reflects exactly what's shown.

Saving the key without the direction (or vice versa) produces wrong state on next startup: if the key's default direction differs from the last-saved direction, restoring only the key applies the default instead of the user's last state.

When `_rebuild_sort_combo` falls back to Title (because a conditional key like Progress/Finished is no longer valid), it applies Title's default direction and saves both key and direction to config immediately — not the removed key's direction.

---

## Finished-books carousel cover loading (stats_panel.py) — 2026-06-04

`FinishedBookThumb._on_cover_loaded` now writes to `_cover_cache[self._book_id]` before
calling `_apply_cover`, matching the library grid's pattern. Previously the worker result
was consumed locally and discarded, causing cold-cache misses on every carousel rebuild for
custom-cover books and excluded/deleted finished books (which the preloader skips entirely,
since `get_all_books` is fenced by `is_deleted = 0 AND is_excluded = 0`). Fix: cache write
in `_on_cover_loaded` + `self._book_id` stored in `__init__`.

`FinishedScrollRow.set_items`:
- **2026-06-08 revision:** the original `_current_ids` guard (set equality on `book_id`)
  caused the Overall tab's "recently finished" carousel to go stale — its top-20 membership
  rarely changes day-to-day, so the guard kept skipping rebuilds even when order, covers, or
  `is_deleted` (location-resurrection) changed. Day/Week/Month's churnier period-scoped lists
  masked the same bug because their membership changes often enough to pass the set check.
  Replaced with `_current_sig`: an order-sensitive list of
  `(book_id, event_time, active_cover_path/cover_path, is_deleted)` tuples. This deliberately
  re-introduces order-sensitivity — order changes ARE meaningful now (re-finishing reorders
  the list) — while still skipping the rebuild in the common truly-unchanged case, preserving
  the perf/flash guard the original code wanted (no widget churn during the panel-open slide).
- ~~`_current_ids` guard (set equality, not list equality)~~ — superseded above. The original
  concern (`_invalidate_period_cache()` re-running the query and changing row order with no
  real change) is still valid, but set-equality threw out too much signal; the richer
  signature distinguishes "real reorder" from "incidental reorder" via `event_time`.
- `setParent(None)` replaces `deleteLater()` for synchronous widget removal — `deleteLater`
  is deferred and left old widgets in the layout during rapid successive calls.
- `setMinimumWidth` computed after population (`n × 47 + (n−1) × 4`) so the container
  overflows correctly with `setWidgetResizable(True)`. Without this, `setWidgetResizable(True)`
  forces the container to viewport width, compressing fixed-size thumbs instead of scrolling.

First-visit cold-cache flash (startup, books not yet reached by preloader) is accepted
behaviour. All subsequent visits for the same book IDs are cache hits.

---

## Suppressing a theme `bg_image`: only regeneration works, not child override (2026-06-03)

The theme `bg_image` (Overlook hexagons, etc.) is painted by `content_container`'s
`QWidget#visual_area { background-image: url(...) }` rule (`get_player_stylesheet`). In
the no-book and empty-library states it overlapped the prompts / carousel / quote. Goal:
strip the image in those two states, keep it everywhere a book is loaded.

**What was tried and failed:**

1. **Rename `carouselActive` → `bgSuppressed` and set the property in the state machine.**
   No change. The original `carouselActive` mechanism never actually suppressed anything —
   the no-book state already showed the image with the carousel fully built (so the
   property *was* set). Renaming a non-working rule does nothing.
2. **Instance stylesheet on `visual_area` itself: `background-image: none`.** No change.
   A red-background diagnostic proved why: setting `QWidget#visual_area { background-image:
   none; background-color: red }` as the child's own stylesheet **did** turn the area red,
   but the image layered *on top of the red*. So the child stylesheet applies fine — but
   **Qt's QSS cascade treats `background-image: none` as "unspecified"**, so the ancestor
   rule's `url()` wins on the child per-property. `background-color` (a real value) overrode;
   `background-image: none` was silently dropped. No child override can kill an ancestor's
   background-image. (The `QGraphicsBlurEffect` on `visual_area`, suspected as a pixmap-cache
   culprit, was a red herring — `blurRadius` is 0 except during panel transitions, and the
   red proved repaints propagate fine.)

**What worked:** regenerate `content_container`'s stylesheet **without** the image.
`get_player_stylesheet(theme_name, suppress_bg_image=True)` omits the `bg_image` from the
`#visual_area` rule entirely — the only reliable kill, since the image is simply never
emitted. `MainWindow._set_bg_suppressed` is the single authority: it sets `_bg_suppressed`,
calls `setAutoFillBackground(False)` (so the transparent `visual_area` lets the carousel
stripe / themed window bg show through), and re-applies the regenerated stylesheet.
`apply_library_state` drives it (`True` for empty + no-book, `False` for has_book), and
`ThemeManager._apply_stylesheets` reads `_bg_suppressed` so a theme change in those states
doesn't re-introduce the image.

**Why this over hiding image-themes from the pool:** the alternative (suppressing the
themes themselves) would have meant a visible gap in the theme pool shown in Settings —
ugly and confusing. Stripping the image per-state keeps every theme selectable.

---

## Wrapping a `QHBoxLayout` in a `QWidget` loses inter-item spacing (2026-06-03)

When a `QHBoxLayout` is assigned directly to a parent `QVBoxLayout` (via `addLayout`), it fills the parent's full width and inherits style-derived spacing (~6px). When the same layout is instead assigned to a `QWidget` wrapper (for naming/visibility purposes) and that widget is added via `addWidget`, two things break: (1) the widget shrinks to wrap its children's fixed sizes instead of filling available width, and (2) `setContentsMargins(0,0,0,0)` on the inner layout does NOT reset spacing — but the previous lack of an explicit `setSpacing` relied on style defaults that may not apply in all states. Always call `setSpacing(N)` explicitly on any `QHBoxLayout` inside a `QWidget` wrapper so the spacing is not state-dependent. Also set `setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)` on the wrapper widget so it fills available width like a bare layout would.

Root cause of the transport button alignment regression introduced in the `4b55058` refactor.

---

## Carousel geometry (2026-06-03)

- `CoverCarousel` is parented to `content_container`, not `visual_area` or `carousel_holder`. `setGeometry(0, y, CAROUSEL_STRIPE_W, carousel_h)` where `y = carousel_holder.mapTo(content_container, QPoint(0, 0)).y()`. `stackUnder(self.visual_area)` keeps it behind the label and button.
- `visual_area`'s `bg_image` must be suppressed while the carousel shows, or a theme with a bg_image paints over the stripe center. This is now handled by the state machine, not the carousel: `apply_library_state`'s no-book branch calls `set_bg_suppressed(True)` before `show_carousel()`. Suppression works by regenerating `content_container`'s stylesheet without the image (`get_player_stylesheet(..., suppress_bg_image=True)`) — see the bg_image-suppression note above for why a child-widget override (the old `carouselActive` property) could not work. `_show_carousel`/`_hide_carousel` no longer touch `carouselActive` or `autoFillBackground`.
- `carousel_bg` → fill. `carousel_stripe` → 1px border lines. Both fall back to `bg_main` (not `bg_deep` — every theme has `bg_main`).
- `set_stripe_color` always recomputes line color; `_line_color_explicit` is `__init__`-only. If this flag ever bleeds into `set_stripe_color`, themes will steal each other's line colors on rotation.

---

## Cover placeholder (2026-06-03)

- `_show_cover_placeholder()` intercepts both no-cover exits in `_load_cover_art` — the `else` branch only. The early `not file_path` return (no-book state) is untouched; `cover_art_label` stays hidden there.
- `render_logo_placeholder(color, size)` lives in `icon_utils.py` — single implementation. Stats panel and tag manager both import it as `_render_svg_placeholder`. Don't reimplement it locally.
- `render_logo_placeholder_bordered(color, icon_size, canvas_w, canvas_h, offset_y=0)` also lives in `icon_utils.py` — renders the logo centered on a fixed canvas with a 2px border. Used by book detail panel, stats panel, and tag manager thumbnails.
- `_showing_placeholder` flag: set by `_show_cover_placeholder()`, cleared at the top of `_apply_main_cover`. Theme refresh: `_reload_button_icons` calls `_show_cover_placeholder()` again if flag is set.
- Placeholder border: shown in thumbnail contexts (book detail header, stats rows, tag thumbnails) only — not in the main cover area where the logo fills sufficient space.
- Theme keys: `placeholder_cover` (main player), `placeholder_stats`, `placeholder_tags` — documented in `themes.py` docstring with fallback chains.

---

## Theme rotation weight exponent — tuned to 1.0 (2026-05-31)

`_do_rotate` weights candidates as `1.0 / (distance ** exp + ε)`. The original exponent was 1.5. Simulated over 10,000 rotations with all 57 themes in the pool:

| Exponent | Min pick rate | Max pick rate | Ratio |
|---|---|---|---|
| 1.5 (original) | 0.9% | 3.0% | 3.4× |
| **1.0 (current)** | **1.1%** | **2.5%** | **2.2×** |
| 0.5 | 1.2% | 2.3% | 1.9× |

1.0 was chosen: flattens the distribution meaningfully without the ordering inversions that appear at 0.5 (e.g. Lilac Girls surges above themes that beat it at 1.5 for no perceptual reason). The "prefer visually different" ordering is preserved — just less aggressively amplified.

Do not lower the exponent further without re-running the sim. At 0.5 the weights are so flat that the distance exclusion filter (step 4) does most of the work alone, and the weight curve stops adding meaningful signal.

## Theme fade — slider color animation + label freeze (2026-05-30)

`ClickSlider` widgets repaint immediately on QSS repolish, producing a ghost during the overlay fade. Fixed in `theme_manager.py` by punching slider rects out of the overlay mask and animating `bg_color`/`fill_color`/`notch_color` via `QPropertyAnimation`. Works because sliders paint their full rect — the hole exposes the slider itself, not the window background.

**Labels** cannot use punch-holes (transparent background would expose the freshly-themed window bg = rectangle flash). Six overlay/rendering approaches failed (see SESSION.md 2026-05-30 Session 2). Fixed instead with `FreezableLabel` — text is pinned for the fade duration so the live label and overlay screenshot are always identical, making a ghost impossible.

**`FreezableLabel(QLabel)`** in `controls.py`: `setText` is a no-op while frozen. `ScrollingLabel` inherits it. The four time labels are `FreezableLabel` at construction; `ScrollingLabel` (chapter label) gains freeze for free. Chapter label is force-refreshed on unfreeze via `chapter_list` + `time_pos` epsilon walk so a chapter change during the freeze doesn't leave it stuck.

**Tradeoff:** Labels pause for 750ms on every theme change. The freeze feels more prominent than expected because there is no color motion to mask it — earlier experiments with color animation on frozen labels made the freeze less perceptible but introduced other artifacts. Accepted as the cleanest outcome.

---

## App audit pass — 2026-05-29 (refactor/app-audit)

Six audit passes applied as a single branch. All items below confirmed landed.

**Invariant violations fixed:**
- `self.player.chapter` direct read in `_sync_playback_state` replaced with epsilon walk (invariant #1 — async chapter property). Now walks `chapter_list` finding last entry `<= pos + _CHAPTER_BOUNDARY_EPSILON`.
- `refresh_overall()` inside EOF block was firing every 200ms at EOF — now inside the `if not self._eof_event_written` guard, fires exactly once per EOF event.
- `#Temporary` comments removed from EOF handling block — the behavior is permanent, not provisional.

**None guards added:**
- `_on_slider_released`: `old_pos = self.player.time_pos or 0.0`
- `_on_chap_slider_released`: same
- `_on_slider_right_clicked`: added `if self.player.mp3_seek_reload_pending: return` after the duration guard

**Initialization fixes:**
- `_mpv_ready`, `_pre_switch_slider_value`, `_pre_switch_chap_slider_value` now all initialized unconditionally in `__init__` (previously only set on some code paths, causing `AttributeError` if relevant methods ran before first book load)
- `session_written.connect` moved from `_build_book_detail_panel` to the player signal block in `__init__`

**Dead inner imports removed:**
- `import re` inside `_classify_filter`
- `from PySide6.QtCore import Qt` inside `_update_chapter_label_clickability`
- `from PySide6.QtGui import QPainter` inside `_update_cover_art_scaling`

**Method relocations:**
- `_classify_filter` and `save_search_filter` moved from `MainWindow` to `LibraryPanel` — they belong with the widget that owns the search field. `closeEvent` now calls `self.library_panel.save_search_filter()`.

**SessionRecorder extraction:**
- All session state and persistence moved to `SessionRecorder(QObject)` in `session_recorder.py`
- `MainWindow` retains `_current_book`; recorder reads it via lambda
- `session_written` signal ownership transferred to `SessionRecorder`; `MainWindow.session_written` removed
- `update_furthest_position()` replaces inline furthest-pos tracking in the 200ms UI loop
- `notify_seek()` replaces duplicated seek-credit logic in both slider released handlers
- `threading` and `datetime` imports removed from `app.py` (now owned by recorder)
- Session record and discard paths confirmed working manually

**DB migration:**
- `set_started_at` / `get_book_started_at` migrated to `book_id` parameter (no `book_path` lookup). Only call site is `session_recorder.py`.

---

## Deferred: drop deprecated `book_path` args from write_session / write_book_event (2026-05-29)

`write_session` and `write_book_event` still accept and write `book_path` alongside `book_id`. The `book_path` columns in `listening_sessions` and `book_events` are not queried but are retained for easy rollback. When ready: remove the `book_path` parameter from both method signatures, drop the column writes, then run the column-drop migration pass described in the existing "drop deprecated book_path columns" entry below.

## Deferred: book_files not yet migrated to book_id FK (2026-05-29)

`book_files` still uses `book_path TEXT` as its composite primary key `(book_path, file_path)`. Migrate when VT is next being actively worked on.

## Deferred: panel construction and animation sequencing debt — P2-C + P6-A + P6-D (2026-05-29)

Three fragilities with a shared root. Fix together in one deliberate structural pass — do not touch individually.

**P2-C — PanelManager patched post-construction (low):**
`PanelManager` is constructed before `_build_book_detail_panel` runs. `panel_manager.book_detail_panel` and `panel_manager.book_detail_panel_animation` are manually patched at lines ~1321–1322 after the fact. `PanelManager` does not own all its panels at construction time. Not broken, but fragile.

**P6-A — `book_ready` two-slot deferred mechanism (medium):**
`player.book_ready` connects to both `_on_file_ready` and `_on_file_loaded_populate_chapters`. Both check `library_panel._is_animating` and set their own deferred flags (`_file_ready_deferred`, `_chaps_deferred`). `_drain_deferred_file_ready` handles both. The two independent flags are functional but fragile — if one fires but the other fails to drain (e.g. due to a VT file-load ordering race), state is inconsistent.

**P6-D — `QTimer.singleShot(320ms)` in `_on_open_tag_manager_from_detail` (known debt):**
`app.py:1075` (was ~1713): `QTimer.singleShot(320, self.panel_manager._open_tags_flow)`. 320ms is a magic number covering the longest panel *position* close animation (300ms) + 20ms margin. The correct fix is an `all_panels_hidden` signal from `PanelManager`, emitted when the last running close animation completes. **Design must decide whether `blur_animation` (500ms) counts toward "hidden" — see the "hide_all_panels then open: timer vs signal" entry below for the full design and the blur caveat.** Single site, no duplication (confirmed REVIEW_PASS8 #6).

**Fix trigger:** When mini player mode is built, panel construction order will be rationalized anyway. Fix all three then.

## Deferred: `_update_pattern_visuals` duplication (2026-05-29)

`_update_pattern_visuals` in `app.py` and its equivalent in `settings_controller.py` share overlapping responsibility for updating the pattern button visual state. The duplication was noted but not resolved in the audit pass — fixing requires confirming which call sites use which path and whether either can be removed. Address in the next settings-panel pass.

## `KEY_Q` quote rotation shortcut — remove before release (2026-06-02)

`keyPressEvent` fires `library_controller._rotate_quote()` when `Key_Q` is pressed and `not self.current_file and self.quote_section.isVisible()`. Testing aid only. Remove before release. Marked `# TODO: remove before release — testing only` in `app.py`.

---

## mpv hangs silently on seeks within 2s of file end — buffer required on every seek path (2026-05-29)

Seeking mpv to a position within approximately 2 seconds of a file's `duration` causes it to hang silently — no error, no EOF event, no recovery. The buffer must be present in every seek path that calls `command_async` or `loadfile start=`.

Current guards in `seek_async` (player.py):
- **VT same-file branch**: `if target_file['duration'] - local_pos < 2.0: return` — placed after the stop-and-load block, before `command_async`.
- **Non-VT branch**: `if dur and dur - pos < 2.0: return` — placed before the stop-and-load check.
- **stop-and-load (VT)**: condition already includes `local_pos < target_file['duration'] - 5.0` — covered.
- **stop-and-load (non-VT)**: `_mp3_stop_and_load` uses `loadfile start=X`; the non-VT guard above fires first and prevents it from being called near EOF.

Do not remove these guards. Do not add a seek path to `command_async` or `loadfile` without including a 2s (minimum) buffer from the file's duration.

## Stats inflation: `LEFT JOIN book_events` before GROUP BY produces cartesian product (2026-05-29)

`get_daily_book_breakdown` and `get_books_listened_in_period` in `db.py` were joining `book_events` before the `GROUP BY`, producing one row per `(session, finished_event)` pair. If a book had N finished events, `SUM(listened_seconds)` was inflated by N. Fixed by replacing the join with a correlated scalar subquery:

```sql
(SELECT MAX(CASE WHEN be.event_type = 'finished' THEN 1 ELSE 0 END)
 FROM book_events be WHERE be.book_id = b.id) as is_finished
```

Rule: never join `book_events` directly into a query that also aggregates `listening_sessions`. Always use a scalar subquery for the `is_finished` flag.

## `_cached_time_pos` holds local position for VT books — never set it to global (2026-05-29)

`_cached_time_pos` is the raw value observed from mpv's `time-pos` property. For VT books mpv only knows about the current file, so `_cached_time_pos` is always file-local. The `time_pos` getter adds `_file_offset` to translate to global book position: `return self._file_offset + self._cached_time_pos`.

Consequence: **never assign a global position to `_cached_time_pos` in a VT context**. Doing so causes `time_pos` to return `_file_offset + global_pos`, inflated by exactly `_file_offset`. This was the root cause of the 0% reset bug in VT stop-and-load: `_mp3_stop_and_load` was setting `_cached_time_pos = target_pos` (global), inflating `time_pos` during the reload window, and `handle_forward`/`handle_rewind` were reading that inflated value and seeking to a wrong position.

Correct assignment: `_cached_time_pos = local_pos if local_pos is not None else target_pos`. For single-file calls `local_pos is None` and `target_pos == local_pos`, so no change in behaviour.

## `handle_forward` / `handle_rewind` — two independent guards required (2026-05-29)

Both methods must guard on `not self.player.mp3_seek_reload_pending` **and** check `if old_pos is None: return` after reading `time_pos`. These are separate failure modes:

1. `mp3_seek_reload_pending` guard: prevents entering the method at all while a reload is in flight, which avoids reading a potentially corrupt `time_pos`.
2. `old_pos is None` guard: `time_pos` can still return `None` during the reload window (mpv observer fires before the property is populated after `loadfile`). `None - skip` in Python raises `TypeError`; historically the code used `(old_pos or 0) - skip` which silently became `0 - skip` and sought to near the start of the book.

Both guards are required. Removing either reintroduces a distinct bug.

## Theme repolish overrides `_set_chapter_ui_active` state — always reapply after theme change (2026-05-29)

`_apply_stylesheets` calls `setStyleSheet` on `content_container`, which triggers a Qt repolish of all child widgets. This clears instance stylesheets and cursor overrides set by `_set_chapter_ui_active(False)` — after a theme change, the chapter UI appeared interactive again for books without chapters.

Fix: `_chapter_ui_active: bool` flag in `app.py` tracks the logical state. `_set_chapter_ui_active` sets the flag. `_apply_stylesheets` calls `mw._set_chapter_ui_active(mw._chapter_ui_active)` at its end to reapply. `_set_chapter_ui_active` is idempotent so repeated calls are safe.

## `_mp3_seek_reload_pending` concurrent reload guard (2026-05-29)

`_mp3_stop_and_load` must not be called while `_mp3_seek_reload_pending` is already `True`. Without this guard, stacked `loadfile` calls cause the second `_on_file_loaded` to go through the normal post-load path instead of the early-return block, emitting `book_ready` and triggering position restore from DB — resetting playback to the saved progress position.

Both call sites in `seek_async` (VT same-file branch and non-VT branch) include `and not self._mp3_seek_reload_pending` in their conditions. If a reload is already in flight the new seek request is silently dropped (normal `command_async` fallthrough still available for the non-VT path if the distance check also fails).

## `seek_within_chapter` has no EOF guard — intentional (2026-05-28)

`seek_within_chapter` does not guard on `self._eof`. An EOF guard was added and removed in the same session. The reason: `seek_async` clears `_eof` internally, so any positional seek correctly transitions out of EOF state. Mouse wheel on the chapter slider already worked at EOF for this reason. Click/drag on the chapter slider must behave the same way. The EOF guard belongs on directional advances (`next_chapter`, `handle_forward`) that should be inert once EOF is reached — not on positional seeks that the user explicitly initiates.

## `next_chapter` last-chapter boundary — no fallback to `_book_duration` (2026-05-28)

Both VT and non-VT branches of `next_chapter` now return early when `curr_chap >= len(chap_list) - 1`. The old `else: seek to _book_duration or duration` fallback is gone. For non-VT: seeking past the last chapter caused state corruption on rapid >| clicks. For VT: EOF is reached naturally when the last file finishes playing — forcing a seek to `_book_duration` was redundant and wrong. If `next_chapter` is ever touched again, do not restore the `_book_duration` fallback.

## `chap_duration_label` cursor owned by `_set_chapter_ui_active` (2026-05-28)

`chap_duration_label.setCursor(Qt.PointingHandCursor)` was set unconditionally in `_build_secondary_controls`. It was moved to `_set_chapter_ui_active` so the cursor state is managed alongside the chapter UI active/inactive toggle. Active: `PointingHandCursor`. Inactive (no chapters): `ArrowCursor`. If `_build_secondary_controls` is ever refactored, do not re-add the unconditional cursor set there.

## Deferred: drop deprecated `book_path` columns from session/event/tag tables (2026-05-28)

`listening_sessions`, `book_events`, and `book_tags` retain `book_path TEXT` columns that are no longer written or queried — kept for now to allow easy rollback. When ready to drop: a single migration pass in `_create_tables` using `PRAGMA table_info` + `CREATE TABLE … AS SELECT` (SQLite doesn't support `DROP COLUMN` below 3.35; check version or use the full table-rebuild pattern). No logic changes required — all query paths already use `book_id`.

## Deferred: migrate `book_files` to `book_id` FK (2026-05-28)

`book_files` still uses `book_path TEXT` as its composite primary key `(book_path, file_path)`. Migrate this when VT (virtual timeline) is next being actively worked on — the table is internal to the VT/scanner path and the change is isolated there.

## `get_listening_time_per_period` — orphaned sessions collapse under NULL book_id (2026-05-27)

`get_listening_time_per_period` groups by `period, book_id` and selects `book_path` alongside it. For rows where `book_id IS NULL` (sessions whose book path had no match in `books` during the migration backfill, or sessions written before the migration), SQLite treats all NULLs as equal in GROUP BY, so multiple orphaned books collapse into a single row. The `book_path` column in that row will be whichever path SQLite happens to pick from the group — not reliable.

This was already a degenerate case: before the migration, `book_path` was the key and orphaned sessions were at least grouped correctly per path. After migration, correctness depends on the backfill having matched all paths. In practice, all in-library sessions (including for `is_deleted=1` books) are backfilled correctly because `books.id` still exists. Only sessions for paths that were hard-deleted from the `books` table (which the app never does) would have `book_id = NULL`.

**Consequence:** `get_listening_time_per_period` results are only consumed by the stats heatmap (`get_hourly_heatmap` is separate). Low impact. No fix planned; document for awareness.

## `ContextIconMenu` — `self.window()` returns the menu itself under Popup window type (2026-05-27)

`ContextIconMenu` uses `Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint`. Under this window type, `self.window()` returns the widget itself — not the top-level application window — because Popup creates a new top-level window in Qt's hierarchy. Using `self.window().width()` / `.height()` for position clamping therefore clamps against the menu's own 126×36px bounds, not the app window. Fix: use `QApplication.activeWindow()` instead. Guard against `None` (returns `None` when the app is not focused or during shutdown).

## `ContextIconMenu` — `WA_TranslucentBackground` wipes the background despite `WA_StyledBackground` (2026-05-27)

Setting `WA_TranslucentBackground` on a `QWidget` subclass that also uses `WA_StyledBackground` causes the QSS `background:` rule to be ignored — the widget renders fully transparent even with a valid stylesheet. The two attributes conflict: `WA_TranslucentBackground` forces alpha compositing at the window level, which punches through the QSS paint. Remove `WA_TranslucentBackground` and rely solely on `WA_StyledBackground` + the QSS `background:` rule for solid background rendering.

## `hide_all_panels` then open: timer vs signal (2026-05-26)

`_on_open_tag_manager_from_detail` in `app.py` calls `panel_manager.hide_all_panels()` then uses `QTimer.singleShot(320, panel_manager._open_tags_flow)` to delay the open until all close animations have finished. 320ms is chosen to clear the longest panel close animation (300ms).

**Why this is debt:** The 320ms is a magic number. If any panel animation duration is changed, this delay silently breaks. The correct approach is a signal: `PanelManager` should emit an `all_panels_hidden` signal after the last running close animation completes. `hide_all_panels` would need to track which animations were started (count or set), and each `_on_*_hidden` callback would decrement the count and emit the signal when it hits zero. The caller would connect to `all_panels_hidden` with a one-shot connection.

**Why the timer was used:** `hide_all_panels` runs multiple close animations in parallel with no shared completion point. Adding the count-down mechanism was a larger change than warranted for a single use case. If a second "hide-all-then-open" flow is added anywhere, the signal approach becomes mandatory.

**⚠ Blur caveat — decide this when designing the signal (REVIEW_PASS8 #6):** the close flow runs TWO kinds of animation in parallel: the panel *position* slide (300ms; tags 200ms) AND `blur_animation` (**500ms**, `app.py:556`). The 320ms timer only clears the *position* slide — at T+320ms the blur fade is still running, and `_any_panel_animating()` (`panels.py:544`) counts blur, so "all panels hidden" is NOT literally true at 320ms. The reopen works anyway because it only needs the panel off-screen (position done at 300ms); blur is cosmetic and the reopen re-drives it. **So the `all_panels_hidden` signal must choose:** (a) fire when the last *position* animation completes (≈ current 320ms behavior, ignore blur) — simplest, preserves today's timing; or (b) wait for blur too (~500ms) — "truly idle" but ~180ms slower to reopen, a deliberate behavior change. Recommend (a): exclude `blur_animation` from the count, because the reopen contract is "panel off-screen," not "no pixels moving." Whichever is chosen, document it at the signal definition so the next person doesn't re-derive this.

**Where to fix:** `panels.py` — `hide_all_panels` and each `_on_*_hidden` method (track a started-count, decrement per `_on_*_hidden`, emit at zero; decide blur per the caveat above). `app.py` — replace `singleShot(320, ...)` with a one-shot `all_panels_hidden` connection.

## `QStackedLayout` for mutually exclusive UI slots (2026-05-25)

When multiple widgets need to occupy the same fixed space with only one visible at a time, `QStackedLayout` inside a fixed-height container is the correct pattern. `.show()`/`.hide()` on siblings in a regular layout shifts surrounding content as each sibling collapses; `QStackedLayout` holds the reserved space constant regardless of which page is current. Pattern: create a `QWidget` with `setFixedHeight(N)`, assign a `QStackedLayout` to it, add all candidate pages (including a blank `QWidget` as the "empty" page), default to `setCurrentWidget(empty_page)`, and switch via `setCurrentWidget`. Store the layout reference on `self` for access from other methods.

**Concrete value (tag manager):** the reserved row in `tag_manager.py` is `self._reserved_row`, a `QWidget` with **`setFixedHeight(21)`** (`tag_manager.py:336`) wrapping the `QStackedLayout` whose three pages are `_reserved_empty` / `_color_picker_row` / `_confirm_delete_label`. The height is **21px, not 32** — REVIEW_PASS8 #2 flagged a checklist that said 32px; that figure was never in any project doc, and the code has correctly been 21 all along. Recording the real value here so future audits reference 21 and don't re-flag a non-issue. No call site overrides it.

## `_set_tag_color` — must not call `refresh()` or `_open_tag()` (2026-05-25)

Tag color change requires exactly three operations: DB write (`db.set_tag_color`), detail dot update (`_update_detail_dot`), list row dot update (`_update_list_dot`). `refresh()` rebuilds the entire tag list widget tree and reloads all cover images — correct for tag renames and deletions, but grossly unnecessary for a color change where no count, name, or book membership changes. `_open_tag()` would re-query books and rebuild the book grid. Any future change to `_set_tag_color` must preserve this constraint: patch in-place, do not rebuild.

## Deferred (low/UX): tag action button `check → delete` 2s timer can silently revert a slow edit (2026-06-12)

After a successful rename, `_on_rename` sets the action button to `check` then arms an **unguarded** `QTimer.singleShot(2000, lambda: self._set_action_mode("delete"))` (`tag_manager.py:622`). If the user starts a *new* rename within those 2s, `_on_tag_name_changed` moves the button to `save`, but the still-pending singleShot fires at T+2s and forces it back to `delete` — **silently reverting the in-progress edit's button state**. Phrased precisely: a user who types a single character and then pauses (entirely plausible for short tag names) will see their input's save-affordance disappear before the next keystroke restores it. It is NOT a correctness bug — the edit field text is untouched and the next keystroke re-sets `save` — but it is a real UX papercut, not a benign "self-heal." Deferred as low-priority debt. Fix when touched: capture the timer (or a generation token) and cancel/invalidate it in `_on_tag_name_changed` when the state moves to `save`. Was REVIEW_PASS8 finding #1.

## `terminate()` regression pattern — four-step sequence is atomic (2026-05-22)

`Player.terminate()` lost `wait_for_shutdown()` with no git trace — it was either never committed without it or dropped silently during a refactor. The four-step sequence must be treated as atomic: store the instance reference, clear `self.instance`, call `terminate()`, then call `wait_for_shutdown()`. Without `wait_for_shutdown()`, libmpv's internal threads outlive Qt's cleanup and crash in `avformat_close_input`. `wait_for_shutdown()` is a python-mpv API method — no custom implementation needed or appropriate. Any "simplification" that removes or reorders these steps will reintroduce the crash, possibly masked again by debug output.

## `_cover_cache` shared reference — tag thumbnails use library cache (2026-05-22)

`tag_manager.py` imports `_cover_cache` directly from `library.py` (`from .library import _cover_cache`). It is the same dict object the library panel populates — not a copy. `_TagBookThumb.__init__` checks this cache synchronously: a hit calls `_apply_cover` inline with no worker and no queued signal, so the pixmap is set before the widget is shown. This is why `_rebuild()` is safe to call on remove without cover flicker. If the cache strategy ever changes in `library.py` (eviction policy, key type, etc.), tag thumbnails are directly affected.

## `color:` QSS does not colorize QIcon pixmaps (2026-05-21)

Qt's `color:` CSS property affects text rendering only. It has no effect on `QIcon` pixels — the pixmap is painted as stored. To tint an SVG icon to a theme color, the color must be substituted directly into the SVG source before rendering, not applied via stylesheet.

## PySide6 does not honor `currentColor` in SVGs (2026-05-21)

`QSvgRenderer` does not resolve the CSS `currentColor` keyword against the widget's palette. SVGs that use `currentColor` for fill/stroke will render black (or transparent). Color must be baked into the SVG bytes at load time. The fix: read SVG as text, regex-substitute all `fill="..."` / `stroke="..."` attributes and `fill:` / `stroke:` inline style properties (Inkscape exports the latter), then render to a `QPixmap` sized to `renderer.defaultSize()`.

The `style="..."` pass is not optional — Inkscape SVGs exported with "plain SVG" or without explicit attribute export use inline CSS on the `<path>` element and the attribute-level regex will miss them entirely.

## `to_grayscale` and alpha channel (2026-05-20)

`Format_Grayscale8` drops the alpha channel — transparent pixels become black. Affects the placeholder logo cover when displayed for archived books. Fix: composite onto the themed background color before converting. Revisit when the app icon is finalized/vectorized. Lives in `to_grayscale()` in `cover_loader.py`.

## `_is_archived` ordering in `load_book()` (2026-05-20)

`_is_archived` and any flag that gates visual state must be set before any method that reads it is called in `load_book()`. Easy to regress as `load_book` grows — the cover block must always come after the archived detection block. The original implementation had it backwards; that was caught and fixed in session 2 of 05.20.

## `deleteLater()` and layout repaint (2026-05-20)

`deleteLater()` defers widget destruction to the next event loop iteration. If a layout doesn't visually update after a grid rebuild, a `refresh_current_tab()` or equivalent repaint trigger is needed to force Qt to process the deferred deletions and re-render.

## `AppInterface` is not the main `App` object (2026-05-20)

Attributes on the main app (e.g. `stats_panel`) are not accessible via `self.app` in `library_controller.py` — `self.app` is `AppInterface`, a thin proxy. Add a wrapper method to `AppInterface` for any new cross-panel call from the controller. Do not access `self.app.<main_attr>` directly.

## Stats panel cover loading — `_inject_active_covers` performance note (2026-05-20)

`_inject_active_covers` does one `get_active_cover_path` DB query per book, synchronously on the main thread. Acceptable for current list sizes. If the Month view with many books becomes perceptible, batch into a single `WHERE path IN (...)` query and return a dict keyed by path.

## `_iter_day_rows` — unrendered tab safety (2026-05-20)

`_iter_day_rows` uses `getattr(self, '_week_rows_layout', None)` and `getattr(self, '_month_rows_layout', None)`. These attributes may not exist if those tabs have never been rendered (Qt defers tab content until first visit). The method returns silently on `None` — this is intentional. Do not change to a direct attribute access.

## `active_cover_changed` signal widening — call site contract (2026-05-20)

`BookDetailPanel.active_cover_changed` was widened from `Signal(str)` to `Signal(str, str)` — `(book_path, cover_path)`. `CoverPanel.active_cover_changed` remains `Signal(str)`. The intermediate slot `_on_cover_panel_changed` in `BookDetailPanel` bridges them. Any future slot connected to `BookDetailPanel.active_cover_changed` must accept both positional args.

## Metadata lock feature (2026-05-19)

Four independent lock columns on `books`: `title_locked`, `author_locked`, `narrator_locked`, `year_locked` (all `INTEGER NOT NULL DEFAULT 0`). Locks are set per-field on save (`_commit_inline_save`), cleared all-at-once on unlock. Persisted to DB via `set_metadata_locks()` and read via `get_metadata_locks()`.

**Upsert protection:** The ON CONFLICT block in both `upsert_book` and `upsert_books_batch` uses `CASE WHEN books.X_locked = 1 THEN excluded.X ELSE updated.X END` for all four fields. This prevents rescans from overwriting user edits. Narrator and year preserve their existing `COALESCE(NULLIF(...), ...)` guards inside the ELSE branch (respecting existing empty-field behavior).

**Rescan resurrection:** Locks reset to 0 in the ON CONFLICT block alongside `is_deleted` and `is_excluded` — rescanning brings back locked metadata unchanged, but allows overwrite on the next rescan if locks aren't re-set.

**UI state machine:** `_MetaActionState` enum (HIDDEN, DIRTY, LOCKED, UNLOCKED) drives the metadata action button exclusively. DIRTY = save icon on keystroke, LOCKED = lock icon after save, UNLOCKED = lock-open icon after unlock click, HIDDEN = no button. Pre-edit state saved in `_enter_edit_mode`, restored on click-outside dismiss. UNLOCKED auto-transitions to HIDDEN after 2.5s via `self._unlock_timer` (QTimer, cancelled at the top of every `_set_meta_state()` call).

## SVG icon rendering caching (2026-05-19)

`_load_svg_icon()` in book_detail_panel.py is cached via `@functools.lru_cache(maxsize=32)` with cache key `(svg_path, color, size, opacity)`. Replaces both `stroke="#000000"` and `fill="#000000"` attributes with the provided color for compatibility. For SVGs with neither attribute (Font Awesome), injects a CSS `<style>path { fill: {color}; }</style>` rule — but only if no stroke replacements happened (to avoid interfering with stroke-only icons like trash).

Theme changes that call `_set_meta_state()` will hit the cache for previously seen (path, color, size, opacity) tuples. This is intentional — icon rendering is deterministic.

## Duration label cursor and toggle (2026-05-19)

Speed comparison uses tolerance `abs(speed - 1.0) < 1e-9` to handle floating-point rounding errors (values like 1.0000000000000053 or 0.9999999999999991 stored in config). When speed is effectively 1x, cursor shows arrow (not hand) and toggle is disabled (no-op on click). Speed sourced from `config.get_book_speed(self._book_path)` with fallback to `config.get_default_speed()` — prevents misleading UI when default speed hasn't been saved yet.

## Book removal — is_excluded vs is_deleted (2026-05-18)

Two independent soft-delete flags on the `books` table:

- `is_deleted = 1` — set by `remove_scan_location` when a folder is removed from the scan list. Means "this folder is no longer being monitored." Resurrected automatically when the folder is re-added and rescanned (`upsert_book` resets it to 0 in the ON CONFLICT block).
- `is_excluded = 1` — set by `set_book_excluded` when the user explicitly removes a book from the library via the trash button in BookDetailPanel. Resurrected the same way — rescanning the location resets it to 0.

Both are filtered by `get_all_books` (`WHERE is_deleted = 0 AND is_excluded = 0`). Stats queries are intentionally left unfenced — history, progress, and session data survive removal and are visible in the stats panel.

The `upsert` resurrection behavior (rescan brings a book back) is a deliberate design choice, not an oversight. If permanent exclusion is needed in the future, the upsert blocks would need a conditional reset: `is_excluded = CASE WHEN excluded.something THEN 0 ELSE books.is_excluded END`.

## Scanner progress invariant — never pass 0.0 (2026-05-18)

`upsert_book` and `upsert_books_batch` use `COALESCE(NULLIF(excluded.progress, 0.0), books.progress)` to avoid overwriting saved playback positions on rescan. The scanner does not know the user's position — it must pass `None`, not `0.0`. The `NULLIF` is a safety net for accidental zeros, not a contract callers can rely on. If a future DB engine or sqlite version changes `NULLIF` semantics, `0.0` would overwrite progress silently.

## CUE file support — architectural notes (2026-05-16)

- `_chapter_list` being non-`None` is the flag for cue mode. No separate `_cue_mode` boolean needed — the `chapter_list` property already abstracts over VT/cue/native.
- `_on_chapter_change` is fully suppressed (always returns immediately as of 2026-06-01). It was previously guarded per-mode; now it does nothing. `_on_time_pos_change` drives all chapter tracking universally.
- All chapter navigation must use position-based walks against `_chapter_list` when populated — never `self.chapter` directly.
- `_virtual_timeline` stays `None` for cue books — do not set it, VT file-switching machinery must not activate.
- CUE files from Windows rippers (EAC, dBpoweramp) almost always have a UTF-8 BOM — read with `utf-8-sig`, not `utf-8`.

## Player.terminate() must call wait_for_shutdown() (2026-05-16)

Without it, libmpv's internal threads outlive Qt's cleanup, causing a crash in `avformat_close_input`. Was masked for an unknown period by a debug print keeping the thread alive. Easy to regress — do not simplify the teardown sequence.

## Chapter boundary epsilon — named constant (2026-05-16)

`_CHAPTER_BOUNDARY_EPSILON = 0.35` appears in chapter walk, restore, and all boundary seeks. It compensates for mpv's "don't miss a frame" bias (undershoots boundaries by ~23ms) and for float drift in mpv's internal chapter boundary representation. Moving it to write time at save was considered and rejected — the saved position itself can already be on the wrong side of mpv's boundary. The epsilon must live at seek time.

---

## Multi-file MP3 virtual timeline — RESOLVED (2026-05-15)

**Problem:** Multi-file MP3 folders (N .mp3 files per book) could not be seeked globally, navigated by chapter, or advanced naturally across files. Two earlier implementations were reverted — concat:// blocked on backward seeks; partial VT without signal separation caused quadruple-advance feedback loops.

**Architecture:**
- `book_files` DB table stores per-file `{file_path, sort_order, duration_ms, cumulative_start_ms}`, populated by the scanner. Player reads this at load time (no mutagen re-scan).
- `_virtual_timeline` list on Player holds `{file_path, cumulative_start, duration}` entries. Player translates global positions into (file_index, local_offset) and issues `instance.play(target_file)` + `_pending_local_pos` for cross-file seeks.
- `book_ready` signal fires once per book (before any file for VT; after file-loaded for non-VT). `file_switched` fires per VT file load. This separation eliminates the feedback loop: `_on_file_ready` is not connected to `file_loaded` at all.

**Why book_ready fires from two different places:** VT books need it before any file loads (so position restore sets `_pending_local_pos` on the right file). Non-VT books need it after file-loaded (so `self.player.duration` is valid when the slider animation reads it). This asymmetry is intentional.

**Natural EOF advancement:** `keep_open='always'` means mpv never fires end-file with reason_int=0 (EOF) — it always fires RESTARTED (reason_int=2). All EOF detection goes through `_on_pause_test` near-EOF position check. `_is_vt_file_switch` gates `_on_pause_test` during file-load transient pauses to prevent quadruple-advance.

**Chapter tracking for VT:** `Player.chapter` getter walks `_chapter_list` by global `time_pos`. `_on_time_pos_change` emits `chapter_changed` whenever the global chapter index changes (compared to `_last_vt_chapter`). `ChapterList._activate_item` calls `seek_async(target_time)` for VT books instead of `self.player.chapter = idx`.

**What not to do:**
- Do not connect `_on_file_ready` to `file_loaded` — this was the root cause of the feedback loop in Round 2.
- Do not use `self.player.chapter` (mpv local) for VT books anywhere — it reflects per-file chapter index, not global.
- Do not read `self.progress_slider.value()` in `_on_file_ready` for switch animation — the slider may not have been updated yet (gated on `not slider_animating and not is_seeking`). Always compute from `new_progress / self.player.duration`.
- `keep_open='always'` makes `_on_end_file` reason_int=0 unreachable — do not add EOF logic there.

---

## MP3 seek blocks Qt main thread — RESOLVED (2026-05-14)

**Root cause:** `self.instance.time_pos = value` in python-mpv is synchronous — holds the GIL on the calling thread until libmpv acks the seek. For MP3 streams, libmpv scans backwards through the bitstream to find frame boundaries before acking. Called from slider release handlers on the Qt main thread → 10–30s freeze.

**Fix:**
- `Player.seek_async(pos)` uses `command_async('seek', pos, 'absolute+exact')` — non-blocking, returns immediately. `absolute+exact` preserves hr-seek precision.
- `seek_within_chapter` returns the computed `new_pos` so callers never need to read `time_pos` back after a seek.
- All four hot-path properties (`time_pos`, `duration`, `pause`, `speed`) cached via `observe_property` — reads no longer cross the IPC boundary.
- `is_seeking` clearance moved into `_on_time_pos_change` observer (fires when mpv delivers the settled position) — removed from the 200ms polling loop where it fired prematurely.

**What is intentionally left on sync path:** Skip buttons, book-load position restore. Not slider-driven, not the problem path. `apply_smart_rewind` was also left on sync initially but was unified to `seek_async` on 2026-05-28.

**`_seek_target = None` edge case:** If `seek_async` is called and `_seek_target` is `None` when the observer fires, `is_seeking` still clears (the `_seek_target is None` branch). This is safe — it means no target was set, so any position qualifies as settled. The edge case that previously caused 228% progress was from an earlier implementation that used `_seek_target` in the flow-animation path; that code was removed.

---

## Single VBR MP3 seek lag — RESOLVED (2026-05-28)

**Root cause:** `absolute+exact` seeks in VBR MP3 files require mpv to scan forward through the compressed bitstream to locate the target frame. For large files or long seeks, this scan takes 1–30 seconds. This is a libmpv/VBR constraint — no seek flag avoids it for stream-based seeking.

**Fix:** `seek_async` intercepts seeks above `_MP3_SEEK_THRESHOLD` (60s) on single `.mp3` files (`_play_target.endswith('.mp3')` and `_virtual_timeline is None`) and calls `_mp3_stop_and_load(target_pos)` instead. This issues `loadfile … start={target_pos}` which positions via the Xing/TOC header (byte offset from TOC fraction) — approximate but fast.

**State machine:**
1. `_mp3_stop_and_load`: sets `_mp3_seek_reload_pending`, `_mp3_seek_visual_lock`, pauses mpv, issues `loadfile`.
2. `_on_file_loaded` early-return block: clears `_mp3_seek_reload_pending`, clears `_is_seeking`, restores pause state, clears `_mp3_seek_visual_lock`, returns without emitting `book_ready`.
3. `_set_play_icon` in app.py: returns early while `mp3_seek_visual_lock` is True — prevents play/pause icon flicker during the reload window.

**Why not `loadfile start=` for all seeks?** Short seeks on VBR MP3 are fast (mpv's seek is a forward scan from a nearby keyframe). The 60s threshold avoids unnecessary file reloads on short seeks where `absolute+exact` is fine. The threshold is a module constant (`_MP3_SEEK_THRESHOLD`) for easy tuning.

**Invariant:** `book_ready` is never re-emitted during a reload seek. The early-return in `_on_file_loaded` skips all existing post-load logic. VT, M4B, CUE books: not `.mp3` or `_virtual_timeline is not None` — intercept never reached.

**Previously attempted (rejected):** `loadfile start=` from `_restore_position` — mpv reported `time_pos=0.0` after `file-loaded` regardless. That was a position-restore context; here we issue `loadfile` with a live player instance that has already loaded the file, which behaves differently.

---

## Stats Panel — First-visit flash on Day/Week/Month tabs — RESOLVED

### Fix
`setVisible(False)` before `insertWidget`, then `setVisible(True)` immediately after, for each `BookDayRow` in all three refresh methods. Forces Qt to fully realize the widget before it is first painted. Applied to `_refresh_daily`, `_refresh_weekly`, `_refresh_monthly`.

### Symptom (was)
On first visit to each of Day, Week, Month tabs after app start, content flashed garbled for a split second then rendered correctly. Happened exactly once per tab per session — second visit was clean. Overall tab (no `BookDayRow` widgets) unaffected.

### What was tried and failed
- **DPR fix on thumbnails** — wrong diagnosis, covers are not the cause
- **`setFixedHeight` on `BookDayRow`** — wrong diagnosis
- **`addStretch()` → `setAlignment(AlignTop)`** — wrong diagnosis; also changed `insertWidget`/clear loop as collateral
- **`setUpdatesEnabled(False)` + `QTimer.singleShot(0)` re-enable** — wrong diagnosis
- **Pre-populating all tabs before `show()`** — wrong diagnosis
- **`ElidedLabel.showEvent` override** — no change
- **Disabling elision entirely** — no change; elision is not the cause
- **`ensurePolished()` on each row after insert** — no change
- **`QTimer.singleShot(0, window().update() + processEvents())`** — no change
- **`setVisible(False)` → insert → `setVisible(True)` on each row** — **THIS WORKED** (see fix above)

### What is known
- The flash is the entire row content (text + layout), not just thumbnails
- It is not a DPR, cover loading, layout stretch, or stylesheet timing issue (all ruled out)
- Root cause undiagnosed. Do not re-attempt the above.

---

## Panel Animation — Deferred Fixes

### `library_panel_animation.finished` duplicate connection risk — `_start_library_entry` and `_close_library_flow`
`_start_library_entry` ([panels.py:86](src/fabulor/ui/panels.py#L86)) connects `finished` → `_on_library_shown` with no guard against the animation already running. `_close_library_flow` ([panels.py:223](src/fabulor/ui/panels.py#L223)) does the same for `_on_library_hidden`. If either is called twice before the animation completes, a second connection accumulates; the self-disconnect in `_on_library_shown`/`_on_library_hidden` only clears one copy per firing. Most paths are guarded (`_close_library_flow` checks `Running` at line 212; the sidebar path serialises through `_on_sidebar_closed_for_panel`), so the race is low frequency but real. Fix when panel animation code is next touched: add the disconnect-before-connect pattern matching the other animation handlers.

---

## Known Architectural Debt

### _cover_cache has no eviction — unbounded growth
`_cover_cache` ([library.py:43](src/fabulor/ui/library.py#L43)) is a module-level `dict` keyed by `book_id (int) → QPixmap`. It grows for the lifetime of the session and is never pruned. At ~226×344px JPEG-decoded to RGBA in memory, each entry is roughly 300 KB. 500 user-added covers (125+ books × 4 slots, all loaded in one session) would consume ~150 MB. Not a realistic v1 scenario given the 4-per-book cap. Revisit if the cap is raised or if memory pressure is reported. Fix when ready: LRU eviction keyed on last-visible timestamp, sized to ~200 entries.

### _sized_cover_cache has no eviction either — compounds the _cover_cache debt above (2026-06-24)
`_sized_cover_cache` (`BookDelegate`, [library.py:1085](src/fabulor/ui/library.py#L1085), added alongside the LANCZOS cover-quality fix — see "Library cover thumbnails..." entry above) is per-delegate-instance, keyed by `(book_id, device_w, device_h)`, and never pruned — same shape of problem as `_cover_cache`, but multiplied: every distinct cell size a book has been rendered at (one per view mode × DPR combination actually visited) gets its own cached pixmap on top of the one already held in `_cover_cache`. View-mode switches don't evict old-size entries (deliberate — see the `_get_sized_cover` CLAUDE.md rule), so a session that visits all 5 view modes holds up to 5 extra pre-scaled copies per book it has viewed, in addition to the native-resolution source. Not fixed now — eviction policy here is the same open decision as `_cover_cache`'s, and the two should be solved together (likely the same LRU/cap mechanism, or one driving the other's eviction) rather than inventing a second, independent policy. Do not implement a bound for one without considering the other.

### `_lanczos_scale`'s `cover.toImage()` readback cost (2026-06-24)
`_lanczos_scale` (`BookDelegate`, [library.py:1775](src/fabulor/ui/library.py#L1775)) calls `cover.toImage()` on a `QPixmap` to get pixel data for the PIL round-trip. `QPixmap` is typically stored server-side/GPU-backed in Qt; `toImage()` can force a readback to CPU memory, which is comparatively expensive versus operating on a `QImage` throughout. This runs once per `(book_id, cell-size)` (cached after, not on every paint), and only on a cache miss, so it's not a per-frame cost — but it is a real conversion cost on every new book/view-mode/DPR combination encountered. Not measured or fixed; flagging in case cover-loading or scroll-stutter complaints come up later and this round-trip is a plausible contributor. Possible mitigation if it ever matters: keep the decoded `QImage` from the original load path (before it becomes a `QPixmap` for `_cover_cache`) and feed `_lanczos_scale` from that instead, avoiding the round-trip entirely — not attempted, would touch `_on_cover_loaded`'s cache-write contract.

---

### Book switch state split on DB failure — `_on_book_selected_from_library`
`_on_book_selected_from_library` ([app.py:1449–1458](src/fabulor/app.py#L1449-L1458)) sets `current_file = path`, then fires `db.update_last_played`, `config.set_last_book`, and `player.load_book` as four sequential side effects with no rollback. If `db.update_last_played` raises (disk full, locked DB), `current_file` already points at the new book but mpv is still playing the old one. Subsequent `_update_ui_sync` ticks write position data for the new path keyed against the old mpv session. Fix requires either: (a) a transaction wrapper that rolls back `current_file` and config on failure, or (b) delaying `current_file` assignment until after all DB writes succeed. Not a common failure mode — DB operations would need to be failing for this to trigger.

### Stats page sluggishness on Weekly and Monthly tabs
RESOLVED: BookDayRow and FinishedBookThumb now load covers asynchronously via CoverLoaderWorker, with placeholder fallback and _cover_cache hit check.

---

## Book Switch Sequence — Known Remaining Issues

### cover_path can be an audio file path in edge case
Scanner sets `cover_path = str(af)` (audio file) when no external image exists but the file has embedded art. It then immediately extracts and saves a `.jpg` thumbnail, replacing `cover_path` with the thumbnail path. So the DB normally always stores a `.jpg` path. Exception: if `img.save()` fails (disk full, permissions), the audio file path is stored instead. `CoverLoaderWorker` calls `QImage.load()` on it, which returns a null image. `_on_cover_loaded` discards null images silently — result is a missing cover, not a crash. No fix applied; failure mode is acceptable.

---

### Cover cache — cold start still hits mutagen
`_load_cover_art` checks `_cover_cache.get(file_path)` before calling mutagen. Cache is keyed by audiobook path and populated by the library panel's `CoverLoaderWorker`. On a warm session (library opened at least once), cache hits are instant. On cold start (library never opened this session), cache is empty and mutagen runs as before. Resolving cold-start requires either: (a) storing cover thumbnails on disk during scan, or (b) populating the cache independently on first book load.

### library_controller must not hide metadata_label when a book is loaded
`apply_library_state` ([library_controller.py:126](src/fabulor/library_controller.py#L126)) previously called `update_metadata(None, show_metadata=False)` unconditionally when `has_book=True`. This hid the "author - title" fallback set by `_load_cover_art` for no-cover books. Fixed by removing `show_metadata=False` from that call — `_load_cover_art` is now the sole owner of `metadata_label` visibility when a book is playing. Do not restore the `show_metadata=False` there.

### `book_covers` pre-migration books — fallback behavior
Both the preloader and `_trigger_cover_load` now call `get_active_cover_path(book.path)` before constructing `CoverLoaderWorker`. For books with no `book_covers` entry, `get_active_cover_path` returns `None` and the worker falls back to `book.cover_path` (scanner thumbnail) — same visual result as before, consistently applied. The previous asymmetry (preloader ignoring `book_covers`) was a bug, not intentional. No further action needed; when all books are rescanned the fallback path becomes a no-op.

### Panel close delay on book switch — RESOLVED (2026-05-13)
The stutter on book selection was caused by mpv's audio pipeline initialisation (PulseAudio negotiation on background threads) competing with the Qt animation timer at the OS scheduler level — not a main-thread block. Confirmed by timing: every Python step was under 2ms, but the animation still stuttered. Back-button close (no mpv work) was always smooth; this was the diagnostic signal.

**The fix — three-part sequence:**

1. **`_playlist_resolved` worker thread** (`player.py`): `_resolve_playlist` (mutagen reads) moved to `QThreadPool` worker. Result is held in `_held_play` rather than calling `instance.play()` immediately.

2. **Gate/ungate pattern** (`player.py`): `load_book` sets `_play_gated = True`. `_on_playlist_resolved` stores the resolved target in `_held_play` if still gated, or plays immediately if gate already lifted. `ungate_play()` either drains `_held_play` or sets `_play_gated = False` for future resolution. This means `instance.play()` — the call that kicks off PulseAudio init — never fires until after the animation completes.

3. **`_mpv_ready` flag** (`app.py`): `_on_book_selected_from_library` sets `_mpv_ready = False`. The deadzone in `_update_ui_sync` ignores all `mpv_pos` values while `_mpv_ready` is False. `_mpv_ready = True` is set in `_on_library_hidden` (library path) or directly before `ungate_play()` (startup/EOF-restart paths). This prevents the 200ms UI timer from accepting the previous book's stale position during the animation window and writing it to the slider.

**`ungate_play()` call sites:** `_on_library_hidden` (library flow), startup book restore, EOF restart. Any new `load_book` call that bypasses the library panel must also call `_mpv_ready = True` then `ungate_play()` immediately after.

**`_on_file_ready` / `_on_file_loaded_populate_chapters` deferral:** Both check `library_panel._is_animating` and set deferred flags if True. `_on_library_hidden` drains them via `QTimer.singleShot(50, _drain_deferred_file_ready)`. The 50ms is intentional — avoids last-frame compositor hitch.

**What was tried and failed:**
- Deferring only `_load_cover_art` and `load_book` via `singleShot(0)` — not enough; `instance.play()` still fired one event loop cycle into the animation.
- `is_seeking` guard on `_sync_progress_sliders` — broke flow animation because `is_seeking` clears before mpv delivers real position.
- `_seek_target` proximity check — caused 228% progress when `target=None` or book had no saved position.
- Skipping `_update_ui_sync` when `is_seeking=True` in `_on_file_ready` — broke flow animation because slider value was 0 when `animate_to` was called.
- Deferred slider animation from deadzone `is_seeking` transition — fired on wrong tick, reading wrong slider value.

**Unobvious:** The stutter root cause is OS scheduler, not Python. Python profiling and timing showed nothing. The diagnostic was: back button (identical slide, no mpv work) was always smooth.

### Position restore fragility
`_restore_position` re-reads from DB after `config_pos` sync. If `_current_book` (set at the top of `_on_file_ready`) was read before the sync, its `progress` value may be stale. The current workaround is a fresh `db.get_book()` call inside `_restore_position`. This is a second DB read on the file-ready path. Could be eliminated by moving the config sync earlier (before `db.get_book` in `_on_file_ready`), but requires care — `_current_book` is used by the slider animation logic immediately after.

### mpv `loadfile start=` option does not work
Tested with `instance.loadfile(path, start=str(int(seconds)))` and `f"+{int(seconds)}"`. mpv reports `time_pos=0.0` after `file-loaded` fires regardless. python-mpv's `loadfile` encodes options correctly (`key=value` string) but the seek either doesn't apply or is overridden. If this ever works in a future python-mpv/mpv version, `time_pos` assignment in `_restore_position` can be replaced entirely.

---

## Library Panel — Open/Close Performance (RESOLVED — close stutter 2026-05-13, open performance since fixed)

Current state: both close slide and open performance are smooth. The attempt log below is kept as
historical record of what was tried during the close-stutter session; the open-side work that
finally resolved it landed later. Do not re-investigate the reverted attempts below as if open.

### What was attempted this session and reverted

**Attempt 1 — refresh() after animation (old behavior, worked but caused blank flash)**
`_on_library_shown` called `refresh()` after slide-in. `refresh()` does full DB read + model reset + cover load. Caused visible blank flash before content appeared. This was the original code.

**Attempt 2 — on_open() replacing refresh() (BROKE EVERYTHING)**
Added `LibraryPanel.on_open()` which only called `update_current_book_progress()`. Replaced `refresh()` call in `_on_library_shown` with `on_open()`. This broke: progress not saved correctly, Recent/Progress sorts not updating, dynamic time updates broken. Root cause: `refresh()` does more than populate books — it also updates all books' speed-adjusted durations and re-applies sort/filter. `on_open()` didn't replicate this. REVERTED.

**Attempt 3 — mpv callback deferral (partially correct, needs retesting)**
`_on_file_ready` and `_on_file_loaded_populate_chapters` deferred via `library_panel_animation.finished` signal when animation was running. This eliminated the burst-retry timer loop. Deferred flags `_file_ready_deferred` and `_chaps_deferred` prevented double-connecting. 50ms singleShot after `finished` to avoid last-frame compositor hitch. This was CORRECT and did not break anything — it was rolled back only because it was bundled with the broken on_open() commit.

**Attempt 4 — preload callback guard (correct)**
`_on_preload_cover_loaded` now checks `_is_animating` before `notify_cover_cached`. This was correct and did not break anything — rolled back only because bundled.

**Attempt 5 — List mode text layout cache (correct)**
`_list_row_layout()` caches `fm.horizontalAdvance()` and `fm.elidedText()` results per `(book.path, available_width)`. Cleared on theme change, view mode change, refresh(). This was correct and did not break anything — rolled back only because bundled.

**Attempt 6 — row pixmap cache (broke List hover effects)**
Pre-rendering list rows to QPixmap. Broke trailing hover fade effect and elision-on-hover because those are per-frame dynamic. Reverted. The right approach: cache only the static layer (bg + text + progress), paint hover effects live on top. Not implemented correctly.

**Attempt 7 — setUpdatesEnabled(False) during slide-in/out (caused ghost)**
Suppressing repaints on _list_view during animation caused transparent panel ghost in List and 1-per-row modes — the panel appeared as a skeleton sliding over the content. Root cause: suppressing updates prevented Qt from clearing the panel's painted content as it moved. REVERTED.

**Attempt 8 — opacity animation instead of pos (not a fair test)**
Replaced QPropertyAnimation on pos with opacity. Other panels slide fine, so this wasn't comparable. Reverted.

### What the debug output showed
- `[FILE_READY] animating=True` and `[POPULATE_CHAPS] animating=True` — mpv fires file-loaded during the 300ms animation on fast SSDs. These callbacks hit the main thread and compete with the compositor.
- `[UI_SYNC] fired during animation` — 200ms timer fires 1-2 times during animation. Tests showed this is NOT the cause — it fires during smooth animations too.

---

## ChapterList — Deferred Fixes (2026-05-15)

### `fade_out` signal accumulation — DEFERRED

`fade_out` ([chapter_list.py:179](src/fabulor/ui/chapter_list.py#L179)) calls `_disconnect_hide` before connecting `_on_fade_out_finished`, and sets `_hide_connected = True`. If `fade_out` is called twice before the animation completes, the second call disconnects the first connection (via `_disconnect_hide`) and creates a new one. The first animation's `finished` fires with no handler; the second fires correctly. The `_anim.stop()` call resets animation state so the two calls don't compound. **Safe in practice.** The `_hide_connected` flag is semantically stale between `_on_fade_out_finished` returning and the next `_disconnect_hide` call, but this window is never observable — `_disconnect_hide` is only called from `fade_out` and `show_above`, both of which immediately follow with a fresh connect. Defer until chapter list animation is next refactored.

### `_activate_item` accesses `player._virtual_timeline` directly — DEFERRED

`_activate_item` ([chapter_list.py:283](src/fabulor/ui/chapter_list.py#L283)) reads `self.player._virtual_timeline` to decide whether to call `seek_async` or set `self.player.chapter`. This is a coupling violation — `ChapterList` depends on a private Player attribute. The correct fix is a public `Player.is_virtual_timeline` property (or routing all chapter activation through a single Player method that handles both cases internally). Defer until a Player public API review pass. Do not access `_virtual_timeline` from any other UI file in the meantime.
- Skipping `_update_ui_sync` entirely during animation caused transparent ghost panel. Not viable.
- `valueChanged` on QPropertyAnimation fires only twice (start/end positions), not per frame — measuring frame gaps via valueChanged is meaningless.

### Confirmed facts
- Other panels (settings, speed, sleep, stats) slide perfectly — library-specific problem.
- Empty library slides in/out smoothly — book content weight causes the stutter.
- Back button close (no book load): smooth.
- Book load close: stutters near end — mpv file-loaded fires during last frames.
- Grid modes: open smooth, close mostly smooth.
- List mode open: stutter proportional to book count (~17 visible rows of heavy paint).
- GTX 1060 won't help — Qt animation driver is CPU-bound, GPU only does final composite.

### What to do next (correct order)

1. **Re-apply mpv callback deferral** (Attempt 3) — tested, correct, no side effects. Apply to app.py only. Test: load books, verify progress saves, sorts work, dynamic updates work BEFORE looking at animation.

2. **Re-apply preload callback guard** (Attempt 4) — one line change, correct. Test same.

3. **Re-apply List mode text layout cache** (Attempt 5) — correct, no side effects. Test same.

4. **Fix library open flash WITHOUT breaking refresh()** — the correct approach: call `refresh()` BEFORE `show()` while panel is at `-panel_w` (off-screen). The panel is populated before the first visible frame. The `_after_covers` retry loop in `refresh()` will wait for `visualRect` to be non-empty, which happens naturally after the animation ends. Do NOT replace `refresh()` with a lightweight alternative — it does too much.

5. **Row pixmap cache for List mode** — cache static layer (bg, alternating color, stripe for non-playing rows, text, progress bar, time) keyed on `(book.path, row_width, row_height, row_parity, is_playing_paused, pct_bucket, show_rem)`. Paint hover effects live on top in all cases. Skip cache for the actively pulsing playing row. This eliminates the paint-heavy slide-in for List mode without suppressing updates.

### CRITICAL TESTING CHECKLIST before committing any library changes
- [ ] Open library → verify books shown correctly
- [ ] Select a book → verify progress saves after listening
- [ ] Reopen library → verify Recent sort shows updated book at top
- [ ] Verify Progress sort orders by percentage correctly
- [ ] Verify dynamic time updates tick every ~1 second while playing
- [ ] Close with Back button → smooth slide
- [ ] Close by selecting a book → check for ghost/stutter
- [ ] Open in List mode → check for ghost/skeleton
- [ ] Open in Grid modes → check content visible during slide

--- 

## Theme Transition — Long-term Plan

### Current state (as of 2026-05-10)
Overlay fade works correctly when no panels are open. When panels are open, automatic theme changes (cover theme, rotation) snap instantly. Settings panel hover preview animates correctly via overlay. The `user_initiated` flag distinguishes automatic from user-driven theme changes.

### Known remaining limitation
The overlay approach is fundamentally incompatible with any panel being open during a theme change — a frozen pixmap over an actively changing UI produces ghosts and dissolution artifacts. The current workaround (snap when panels are open) is acceptable for normal use.

### Long-term correct solution: per-element Q_PROPERTY color animation
Replace the overlay entirely with `QPropertyAnimation` on color properties of each widget. All custom-painted widgets are already instrumented (see session 2026-05-10). The remaining work is the QSS-driven majority:

**Why QPalette won't work:** Theme dicts have up to 30 semantic color keys across 50 themes. QPalette has a fixed role set that does not map onto this structure cleanly.

**What's required:** Convert QSS-driven widgets to use programmatic color assignment (via palette or stored attributes + custom painting) for color only, keeping QSS for structural styling (geometry, borders, fonts, hover/pressed states). Scope is wide — every button, label, background across all panels and tabs.

**When to do it:** After the UI is feature-complete and stable. This is a polish-pass architectural change. Do it as a dedicated session with no feature work mixed in.

**Widgets still needing instrumentation (THEME_ANIM_TODO):**
- `app.py`: `MainWindow`, `TitleBar`, `ChapterList`, `SpeedControlsPanel`, `AudioSettingsTab`, `SleepTimerPanel`, `StatsPanel`, `BookDetailPanel`, `status_banner`, `sidebar`, `vol_container`
- `chapter_list.py`: `ChapterList`
- `library.py`: `LibraryPanel`
- `stats_panel.py`: `ElidedLabel`, `SessionListWidget`, `BookDayRow`, `FinishedBookThumb`, `FinishedScrollRow`, `StatsPanel`
- `book_detail_panel.py`: `BookDetailPanel`, `_ClickableLabel`

---

## Themes Tab — Excluded from Per-Element Animation (2026-05-10)

The Settings panel Themes tab was audited and ruled out for per-element color animation. All other tabs are tamed (no custom-painted widgets, overlay runs over them cleanly). The Themes tab is the permanent exception.

### Widget inventory and color sources

| Widget | Theme keys | State mechanism |
|---|---|---|
| `QTabBar::tab` | `bg_deep`, `accent`, `settings_tab_hover_*`, `accent_dark`, `button_text` | QSS pseudo-classes |
| `ThemeItem(QPushButton)` | `panel_theme_names_dimmed`, `accent`, `accent_light` | `[selected]`, `[active_display]` dynamic properties + unpolish/polish |
| Cover-mode / interval `QLabel` | `panel_theme_names_dimmed`, `accent` | `[selected]` dynamic property |
| `QLabel#settings_header` | `accent_light` | QSS only |
| `QLabel#theme_hint` | `accent` | QSS only |
| `QPushButton#theme_add/remove/change_now` | `text`, `accent_dark`, `accent`, `button_text` | QSS only |
| `QPushButton#pattern_button` | `panel_theme_names_dimmed`, `accent`, `accent_light`, `accent_dark`, `button_text` | `[selected]`, `[is_default]` dynamic properties |

### Why per-element animation is not viable

**Dynamic property state machine on ThemeItem**: Three visual states (dimmed / selected / active_display), six possible pairwise transitions. Each requires resolving both the source and target color from the current theme dict at the moment of the flip, then starting a `QPropertyAnimation`. The unpolish/polish mechanism would have to be suppressed and replaced entirely.

**QTabBar is not instrumentation-friendly**: Renders through `QStyle` internally. Animating tab colors requires subclassing `QTabBar`, overriding `paintTab`, and managing per-tab color state manually. Not feasible without a dedicated rewrite of the tab bar.

**N simultaneous instances**: Interval labels and ThemeItem pool buttons all flip state at once. Each instance needs its own animation with correct per-instance before/after colors computed at flip time.

**QPalette does not work when QSS is active**: Confirmed via `ThemedButton` canary test. Setting `QPalette.Button` is silently ignored when any QSS `background` rule applies to the widget — QSS takes full precedence. `background: transparent` in QSS causes the window background to show through rather than the palette color. The only working background path is a `paintEvent` override painting a rounded rect explicitly, which requires hardcoding `border-radius` to match QSS and loses QSS `:hover`/`:pressed` background states entirely.

### What works instead
`user_initiated` flag on `_on_theme_changed` + Themes-tab-active check: automatic theme changes (cover art, rotation) snap instantly when Themes tab is open. User-driven changes (hover preview, right-click, Change Now, mode buttons) animate normally. `snap_theme_forward()` on settings panel close prevents overlay dissolution during slide-out.

---

## Theme System — Known Bugs (2026-05-26)

### Spurious sidebar expand during theme hover — root cause unknown

**Symptom:** Occasionally during hover-preview over theme pool items, the sidebar briefly becomes
visible behind or alongside the settings panel. Visually this shows as sidebar button labels
(SETTINGS, STATS, etc.) bleeding through, giving a hodge-podge appearance.

**Root cause:** Sidebar expands when it shouldn't — suspected race between the right-click handler
and the panel animation guard, but not confirmed. The condition is sporadic and has not been
reliably reproduced.

**Mitigation (2026-05-26):** The overlay mask now unconditionally excludes the sidebar geometry
(previously only excluded when `sidebar_expanded` was already `True`). This limits visual damage
when the sidebar appears unexpectedly, but does not fix the underlying expand.

**Do not remove the `if pm.sidebar_expanded:` guard** — it controls the sidebar exclusion in other
code paths and is not the cause of the bug.

**Investigation notes:** The right-click flow in `_on_theme_right_clicked` calls
`_on_theme_changed` which checks `_any_panel_animating()` — if the panel guard fires while a
sidebar animation is in progress, the deferred retry may execute after the sidebar has already
closed, leaving `sidebar_expanded` stale. Check `_toggle_sidebar` / `_on_sidebar_hidden` timing
relative to `_panel_guard_timer` expiry.

---

## Player / VT — Deferred Bug Investigations (2026-05-16)

### Prev chapter while paused goes to N-1 instead of restarting N — RESOLVED (2026-05-16)

Two root causes:

1. `previous_chapter()` non-VT was reading `self.chapter or 0` (mpv's async property) to identify the current chapter. When paused this value can lag. Fixed: replace with a walk of `chapter_list` against `time_pos + 0.35`, same as VT and display paths.

2. The "restart current chapter" case used `self.time_pos = chap_start` (default seek). Default seek undershoots by one AAC frame (~23ms). When paused, playback never advances past the boundary to self-correct; mpv kept reporting N-1. When playing, forward playback masked the undershoot in one tick. Fixed: `seek_async(chap_start + 0.35)` — `absolute+exact` seek plus epsilon to clear the ~0.25s float drift window.

### Chapter slider position wrong after Prev/Next chapter — RESOLVED (2026-05-16)

Root cause: time labels in `_sync_chapter_ui` update without an `is_seeking` guard; slider `setValue` was gated on `not is_seeking`. For `self.chapter = N` seeks, `_seek_target` is never set, so `_is_seeking` clears on the first `_on_time_pos_change` callback. Race: timer fires with label showing correct "00:00" but slider retaining the stale near-full value from the previous chapter. A `setValue(0)` call in `handle_prev`/`handle_next` made it worse — it was overwritten before the seek settled.

Fixed: remove `setValue(0)` from both handlers; remove `not self.player.is_seeking` from the chapter slider's `setValue` condition in `_sync_chapter_ui`. Keep the `chap_animating` guard — that is the architecturally protected one. The slider now updates every 200ms unconditionally and self-corrects within one tick.

### M4B chapter label shows previous chapter on book load — RESOLVED (2026-05-16)

Root cause: `_restore_position` non-VT used `self.player.time_pos = book_data.progress` (default seek). One-frame undershoot (~23ms) lands before the chapter boundary when saved position is at chapter N's start. mpv correctly reports N-1 for that position.

Three signal-path approaches failed — **do not retry**:
- **Timer correction in `_sync_chapter_ui`**: `_update_chapter_label_from_index` (signal path) never updated the tracking index so the correction never fired. Adding tracking there caused N-1→N flash on every book load.
- **Walk in `_on_time_pos_change` for non-VT**: fires on every audio frame including intermediate seek values. Caused N+2 flashes on Next and a regression cascade (stuck slider, broken label on all seeks).
- **Walk in `_on_chapter_change` with direct `instance.time_pos` read**: could not reliably get the post-seek position before the chapter callback fired.

Fixed at the seek: `_restore_position` now uses `seek_async(book_data.progress + 0.35)`. Restores 0.35s past the saved position — accepted trade-off, consistent with what `previous_chapter` does for the same reason.

**Rule (superseded — see below):** Earlier rule said `chapter_changed` for non-VT must remain on `_on_chapter_change`. That rule is now wrong. See the 2026-06-01 session entry below.

### M4B chapter label drift after slider/right-click seek — RESOLVED (2026-05-16, session 2) — superseded by 2026-06-01

Root cause: mpv fires `time-pos` observer only once after a seek while paused. That single callback can arrive at an intermediate position and go silent before the seek fully lands — label stays wrong until the next natural `chapter_changed` emit.

Fix applied in 2026-05-16:
- `_on_time_pos_change` added non-VT branch walking `chapter_list` against `value + _CHAPTER_BOUNDARY_EPSILON`, emitting `chapter_changed` when index changes. Tracked via `_last_nonvt_chapter`.
- `seek_async` non-VT immediately set `_cached_time_pos = pos` and emitted `chapter_changed`.
- `_on_chapter_change` returned early if `_is_seeking` is True.

**This fix introduced a latent race** — see "Chapter snap-back on Prev/Next while paused" below.

### Chapter snap-back on Prev/Next while paused — RESOLVED (2026-06-01)

Root cause: `_on_time_pos_change` and `_on_chapter_change` were both emitting `chapter_changed` for embedded M4B books. The `_is_seeking` guard on `_on_chapter_change` was insufficient because `_on_time_pos_change` clears `_is_seeking` first (when the position settles within 1.0s of `_seek_target`). By the time `_on_chapter_change` fires, `_is_seeking` is already False — the guard cannot protect against the stale mpv native chapter value.

When **playing**, continuous `time_pos` events keep re-emitting the correct chapter within milliseconds, masking the snap-back. When **paused**, mpv fires no further events after settling — the stale `_on_chapter_change` value is the last word. Symptom: clicking Next while paused briefly shows the correct chapter title, then snaps back to the previous chapter. The actual seek did happen; only the label was wrong.

Fix: `_on_chapter_change` is now fully suppressed (immediate `return`). `_on_time_pos_change` handles chapter tracking universally for all three book types:
- **VT** (`_virtual_timeline is not None and _chapter_list`): walks `_chapter_list` against global position.
- **CUE** (`_chapter_list is not None, _virtual_timeline is None`): `self.chapter_list` returns `_chapter_list`, walks it.
- **Embedded M4B** (`_chapter_list is None, _virtual_timeline is None`): `self.chapter_list` returns `self.instance.chapter_list` (live from mpv), walks it.

All three paths track via `_last_nonvt_chapter` / `_last_vt_chapter` and emit only on change. No emission path remains in `_on_chapter_change`.

**Current rule:** `_on_chapter_change` is dead (always returns). Do not restore it. `_on_time_pos_change` is the sole driver of `chapter_changed` for all book types.

### M4B chapter stuck intermittently after a VT session — TRACED, not a Fabulor state-leak (2026-06-12, review/Review_260612_6.md #6)
Symptom (CLAUDE.md Known Debt): chapter display freezes at a chapter boundary in some embedded-M4B books, sometimes after a multi-file VT session.

**Trace conclusion (don't re-trace the reset path — it's clean):** The full VT-session-end → M4B-load → chapter-init path was walked. `load_book` (player.py ~343-360) **resets every relevant field synchronously before the async resolve worker is queued**: `_virtual_timeline=None`, `_chapter_list=None`, `_file_offset=0.0`, `_current_vt_index=0`, `_last_vt_chapter=-1`, `_last_nonvt_chapter=-1`, plus `_cached_time_pos/_cached_duration/_seek_target=None` and the `_mp3_seek_*` flags. **No VT/chapter-tracking state survives the VT→M4B transition.** `_last_nonvt_chapter=-1` forces the first `_on_time_pos_change` walk to emit. So the freeze is NOT a leaked `_virtual_timeline`/`_chapter_list`/`_last_nonvt_chapter`.

**Where the freeze actually originates (the real lead for next time):** the embedded-M4B branch of `_on_time_pos_change` walks `self.chapter_list`, which for M4B is `self.instance.chapter_list` (mpv-native). It is gated by `elif self.chapter_list and value is not None` — if mpv hasn't parsed the chapter table yet (or a particular M4B reports `time-pos` updates with a malformed/empty native chapter list), the branch is skipped and `_last_nonvt_chapter` never advances past its initial value → label sticks. Secondary contributor: the settle-reset (`_last_nonvt_chapter=-1`) only fires inside the seek-clear branch (`_seek_target is not None`), so on a normal play-through across a boundary the advance relies solely on `curr != _last_nonvt_chapter`; if two boundaries fall inside one `is_seeking`-gated window only the final chapter emits (coalescing, not a leak).

**Next investigation should instrument `self.instance.chapter_list` readiness at the first `_on_time_pos_change` for the affected M4Bs** — it is an mpv-data/timing property, not Fabulor reset-path state. Do not re-audit `load_book`'s reset block; it is comprehensive and correct.

### Progress slider race on book switch — TRACED, not a missing guard (2026-06-12, review/Review_260612_6.md #7)
Symptom: slider briefly shows 0% / wrong position before settling on book switch.

**Trace conclusion (don't re-derive):** The authoritative set in `_on_file_ready` — `animate_to(new_val, old_value=pre)` / `setValue(new_val)` at app.py ~1189/1192, where `new_val = int(new_progress/dur*1000)` and `pre = _switch.take_progress_target()` — is protected by **three composable guards** that hold through the switch window: `slider_animating` (flow `_flow_anim` Running), `player.is_seeking` (restore seek in flight), and `_switch.flow_pending_progress` (pre-switch capture not yet consumed). All three are checked together in `_sync_progress_sliders` (app.py ~1597) before the 200ms timer's `setValue`.

No second *unguarded synchronous* writer exists. The residual exposure is **purely a timing overlap**, not a missing guard: the resumed 200ms timer (`_resume_ui_timer` fires on `_flow_anim.finished`) can tick in the thin window where `slider_animating` has gone False (animation done) AND `is_seeking` has gone False (restore seek settled within 1.0s) but the live `pos` transiently differs from the animation's end value. It self-corrects on the very next tick (writes the now-converged live position). Matches the "intermittent, brief 0%/wrong-position" symptom.

The disconnect-before-connect fix in `load_book` addressed the *double-handler* variant (a real bug, fixed). This residual is the leftover guard-release-ordering overlap. **If determinism is ever wanted, the lever is ordering** — hold the timer resume until BOTH the flow animation finished AND the restore seek settled, rather than resuming on `_flow_anim.finished` alone. Not pursued; the self-correct makes it cosmetic and rare. Full writer list with file:line is in review/Review_260612_6.md §7.

### VT sessions not recorded correctly across file switches — believed FIXED (verify, 2026-06-25)
Original issue: `_close_session`/`_open_session` wiring did not account for mid-book VT file
transitions — when mpv emitted `file_switched`, the session layer treated it as a new play event
rather than continuation of the same book, breaking listening-time attribution across VT file
boundaries. Believed resolved as of 2026-06-25 (`file_switched` now threaded into the recorder), but
not independently re-confirmed here — left in NOTES as a root-cause record pending a verification
pass. If a VT book's listening time still fragments across its file boundaries, this is where to
start.

---

## Stats Panel — Timeline Tab Not Updated After Metadata Edit — RESOLVED (2026-05-16)

`get_hourly_heatmap` was reading `book_title` directly from `listening_sessions` (value snapshotted at recording time) instead of joining `books` to get the current title. Fixed: added `LEFT JOIN books b ON ls.book_path = b.path` and changed the select to `COALESCE(b.title, ls.book_title, ls.book_path)`, matching the pattern already used by all other stats queries in `db.py`. Updated title now appears in heatmap tooltips immediately after edit, with no restart needed.

### Deferred — chapter nav undo/restore near boundaries

- **Undo after Next:** Undo button does not appear. Root cause not yet isolated — may be `_undo_pos` not being set on the `seek_async` path.
- **Undo after Prev:** Undo fires but chapter slider drifts to far right. Undo target is at a chapter boundary; restore lands in wrong chapter for same boundary-drift reasons as the other nav bugs.
- **apply_smart_rewind and Undo restore:** Still use `time_pos =` assignment in some paths. Not yet audited for boundary drift. Needs testing near chapter starts.

---

## Cover Panel — Deferred Issues (2026-05-16)

### Duplicate cover detection not implemented
`_on_add_cover` ([cover_panel.py:497](src/fabulor/ui/cover_panel.py#L497)) copies the selected file into the book's cover directory without checking if an identical image already exists (by content hash or file size + dimensions). A user adding the same image twice creates redundant copies on disk and redundant DB rows. Implement before the cover panel slot limit (4) becomes a user-visible constraint — a duplicate wastes a slot.

### `upsert_cover` delete ordering — file before DB
On cover deletion, the current implementation deletes the file before the DB row. If the DB delete fails (locked, disk error), the file is gone but the DB still references it — the thumbnail shows a broken image on next open. The correct order is: delete DB row first, then delete file. If the file delete fails, the DB is clean and the orphaned file is harmless (not referenced). Address when cover panel is next touched.

### `_on_thumb_delete` does not check file delete return value
`_on_thumb_delete` ([cover_panel.py:444](src/fabulor/ui/cover_panel.py#L444)) calls the delete operation but does not inspect whether the file was successfully removed. A silent failure leaves an unreferenced file on disk. At minimum, log the failure. Address alongside the ordering fix above.

---

## Cleanup Deferrals — Pre-existing, Deliberate (2026-05-16)

These items exist in the codebase intentionally and should not be removed without a dedicated cleanup pass.

### Debug prints and timing instrumentation
`_close_session`, `_on_file_ready`, `_on_book_selected_from_library` contain `print()` calls and timing probes left from VT debugging. Remove in a dedicated cleanup commit — do not remove piecemeal during feature work.

### `KEY_Q` quote rotation shortcut — remove before release
`keyPressEvent` → `library_controller._rotate_quote()` when empty state active. Tagged `# TODO: remove before release` in `app.py`.

### Temp EOF flags
`_eof_event_written` and `_eof_dur_fetched` flags, and associated `#Temporary` comments, were added to guard double-write during EOF session close. Review whether they are still necessary after the session recording rewrite for VT. Do not remove blindly — check whether the guard condition is still reachable.

### Temp file accumulation for VT playlist resolution
`_resolve_playlist` writes `ffmetadata` and `concat` files with `delete=False` (or equivalent) for debugging. These accumulate in `/tmp` across sessions. Switch to `delete=True` or explicit cleanup in a `finally` block when VT is considered stable.

### Config — `balance` key has no bounds validation
`config.set_balance(value)` writes whatever it receives. The audio tab constrains input to `[-1.0, 1.0]` via the slider, but the config layer has no clamp. A manually edited or corrupted QSettings file can store an out-of-range value that passes silently to mpv's audio filter. Add `max(-1.0, min(1.0, value))` in `set_balance` when config is next touched.
---

## Library State Refactor + Cover Area Fix (2026-06-01)

### `apply_current_state()` vs `_check_library_status()` (LibraryController)

`apply_current_state()` computes library state, applies it to the UI, and returns the computed state object — no background-task or scan side effects. `_check_library_status()` delegates to `apply_current_state()` and feeds its returned state into `handle_background_tasks()`. All scan triggering lives in `_check_library_status` alone.

The book-selection path (`_on_book_selected_from_library`) calls `self.library_controller.apply_current_state()` inside its deferred `singleShot(0)` lambda, after `_load_cover_art` and `player.load_book`, so cover and chrome reveal in the same event-loop tick. `_check_library_status` is not used here because `handle_background_tasks` would fire a scan on every book pick.

`apply_library_state` is the sole chrome gate: it calls `set_visible(state["has_book"])` and manages `go_to_library_btn` visibility. Chrome only appears when this gate runs with `has_book=True`. The failure mode that prompted the refactor: in the empty → add folder → scan → pick book path, `current_file` was set but the gate never ran with `has_book=True`, so chrome stayed hidden until restart.

**Caller audit (2026-06-01):** Three `_check_library_status` call sites remain. All three legitimately want a scan trigger (`_on_remove_folder_clicked`, `_on_scan_now_clicked`) or fire during an active scan where `handle_background_tasks` guards on `mode != "scanning"` and is effectively a no-op (`_on_scan_progress` at `current == 1`). None need migration to `apply_current_state()` for correctness. `_on_scan_finished` does not call `_check_library_status` at all.

### `COVER_AREA_HEIGHT = 280` (`app.py` module constant)

Calibrated fixed height of the cover art box in pixels. `cover_art_label` is pinned with `setFixedHeight(COVER_AREA_HEIGHT)` and `setAlignment(Qt.AlignCenter)`. `_update_cover_art_scaling` uses this as `target_h`.

Value derived from the fixed-size window budget (564px total − title bar 32 − progress slider 24 = 508 content height; minus content margins 20, 5 spacing gaps 50, and six fixed-height rows below visual_area: speed 33, preview 21, controls 33, chapter_info 24, chapter_slider 13, book_info 24 = 148; 508 − 218 = 290 theoretical). Calibrated empirically to 280 after testing covers of various aspect ratios.

Do not derive `target_h` from `cover_art_label.height()` — that reflects transient layout allocation, which is wrong during any state transition. If the window layout ever changes, re-calibrate empirically.

---

## Empty-state and no-book-state layout — architecture notes (2026-06-02)

### `visual_layout` widget order and visibility contract

The `visual_layout` (inside `visual_area`) contains these widgets in order:

| Index | Widget | Empty state | No-book state | Player state |
|---|---|---|---|---|
| 0 | `cover_art_label` (fixed 280px) | hidden | hidden | shown |
| 1 | `scan_section` (stretch=1) | shown | hidden | hidden |
| 2 | `metadata_label` | hidden | shown ("No book selected.") | owner: `_load_cover_art` |
| 3 | `go_to_library_btn` | hidden | shown | hidden |
| 4 | `quote_section` (fixed 240px) | shown | hidden | hidden |

When the carousel is active, `_carousel_container` is inserted at index 0 (pushing everything else down by one). It is removed and `deleteLater()`'d on player-state and empty-state entry. The container wraps `CoverCarousel` with `addSpacing(30)` above and below.

### Status banner is a floating overlay, not a layout item

`status_banner` is a `QWidget(self)` child of `MainWindow`, positioned via `setGeometry(0, height-30, width, 30)` in `resizeEvent`. It is not in `visual_layout` or `content_layout`. Raising it above the fade overlay is suppressed while `_fade_overlay.isVisible()` — see session notes on the snap-back bug fix.

### `_suppress_fill` on `ClickSlider` — paint-only gate

`ClickSlider._suppress_fill = True` prevents the fill rect from being painted in `paintEvent` while still painting the background groove. The flag is toggled by `_set_interface_visible`. `setEnabled(False)` is also called alongside it to block mouse events; `ClickSlider.paintEvent` does not read `isEnabled()` so there is no visual side-effect from disabling.

### Cover carousel — sampling invariants

- Uses `books.cover_path` (scanner thumbnails), not user-selected active covers from `book_covers`. Intentional — fast, no joins, matches prompt scope.
- Pillow reads are header-only (`img.size` without `img.load()`) — reads only the image header, not the full pixel data.
- Static mode threshold is count-based (`n <= 3`), not width-based. Three covers at 96px/slot = 288px > 280px viewport, so they cannot scroll seamlessly (2x strip = 576px < threshold for gapless looping). Centered static layout is correct for 2–3 covers.
- `scroll_speed` default is 15 px/s (tuned from initial 30 — user preference).
- Carousel issues from visual inspection are pending resolution (commit tagged `wip`).

### Design decision — cancel scan keeps partial results

Cancelling a scan leaves already-scanned books in the library. This is intentional: for a large library mid-scan, removing the partial results would be destructive — the user would lose progress data and cover art for hundreds of books already processed. If a user adds the wrong folder, they remove it manually. Do not treat partial-scan residue as a bug.

### Intentional redundancy — `or not has_indexed_books` in `apply_library_state`

The condition `state["mode"] == "empty" or not state["has_indexed_books"]` contains a redundant clause. `compute_library_state` already sets `mode = "empty"` whenever `not has_indexed_books` (line: `if not has_locations or not has_indexed_books: mode = "empty"`), so the `or not has_indexed_books` branch can never be reached today. It is kept as a guard against future refactors that might introduce a state where `has_indexed_books=False` but `mode != "empty"` (e.g. a new `"no_books"` mode). Do not remove it for cleanup — the redundancy is load-bearing intent, not dead code.

### `_showing_placeholder` must be cleared on every path that hides the cover, not just the has-cover path

`_load_cover_art("")` hid `cover_art_label` but never reset `_showing_placeholder`, so a `_panel_guard_timer`-deferred `_reload_button_icons` (fired later, after a panel animation that was in flight at removal time finished) would see the stale `True` flag and unconditionally repaint the logo placeholder back onto the hidden label — the intermittent "logo cover survives location removal" bug. Verified via a forced race (toggle `panel_manager._any_panel_animating()` to `True` around `_on_book_removed()`, then flip it back and fire the single-shot guard timer once) rather than relying on wall-clock UI timing; see git log for the fix commit. Any boolean UI-state flag with more than one "clear" call site is a candidate for this same class of bug if one of those call sites is ever missed.
