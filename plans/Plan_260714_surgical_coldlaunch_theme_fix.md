# Plan: the surgical cold-launch theme-apply fix (try before the broader theme-apply-cost fix)

**Status: PLAN ONLY — not implemented.** Scoped to the narrow cold-launch fix identified in
`review/Report_260714_theme_apply_safety_feasibility.md`. The broader deferral/chunking fix to
`_apply_stylesheets`'s own ~400ms cost is explicitly NOT this plan's target — it is the fallback,
needed only if this surgical fix proves insufficient. If it does, STOP and report; do not expand
scope here.

---

## Pre-establishment findings (done before writing this plan, with evidence)

### Finding 1 — the no-panel branch's missing slider-wait was reasonable-at-the-time, not a careless oversight; but it never accounted for a SECOND, later apply

`_apply_main_cover` (`app.py:2498-2511`) branches on `is_any_panel_visible()`:
- panel visible → stash `_pending_cover_pixmap`, applied later via `_apply_pending_cover_theme`
  (`app.py:1615`), which waits on both sliders' `when_animations_done()`.
- no panel → `apply_cover_theme(pixmap)` **immediately**, no wait.

**History (git):** the branch was introduced in `6eb8b9b` (2026-04-30, cover-theme feature) with a
bare commit message. The slider-wait ghost-fix (`be39b3f`, 2026-06-05, *"prevent ghost via
double-chain wait"*) was applied **only** to `_apply_pending_cover_theme`, never to the no-panel
branch. **Verdict: reasonable-at-the-time.** At the instant the no-panel branch executes on a
book-switch, no flow animation is running yet (the flow anim starts later, inside the queued
`_on_file_ready`), so "no panel visible ⇒ nothing to wait for" was locally true. What it did not
anticipate is a *second* cover apply firing later, when the animation IS running (Finding 2), plus
the cold-launch `__init__` apply that precedes the animation entirely (Finding 4). Not an oversight
to condemn — an assumption that stopped holding once cold-launch had two applies at two different
times.

### Finding 2 — the post-scan reload is NOT purely redundant (serves cover-correctness) but its THEME re-apply usually is

`_on_scan_finished` (`library_controller.py:158-161`) calls `load_cover_art(current)` after a scan,
commented *"ensures the active book_covers entry is used, not a stale cache entry from before the
scan."* History: `583713d` (2026-05-12, *"refresh player cover after library scan to ensure active
cover is displayed"*). **Genuine purpose:** at first cold-launch load the scanner may not yet have
written the book's `book_covers` entry, so the reload picks up the now-correct active cover. **Do
NOT delete the reload** — it serves cover correctness.

**But:** measured this session (DB inspection), for the common case the active cover already exists
at init (Zhivago has an active locked `book_covers` row before the scan runs), so the post-scan
reload re-applies an **identical** cover theme — a full ~400-600ms `_apply_stylesheets` that changes
nothing visually. The redundancy is in the *unconditional theme re-apply*, not in the reload itself.

### Finding 3 — Race 3 IS live at cold launch with cover-theme-ON (corrects the parent report)

The parent report (line 168 of the timing-map NOTES entry) reasoned *"at cold start nothing
competes for the Qt loop, so P1 always wins — which is why 200 automated cold restarts passed."*
**That reasoning only holds when nothing competes, and cover-theme-ON makes something compete.**
Measured this session: 8 cold launches of VT-cover Zhivago (progress reset to a fixed value before
each), **1/8 lost the restore race** — `[BOOKSWITCH-TRACE]` showed `order=load_BEFORE_defer (RACE
LOST)`, `consumed=False`, and the user **visually confirmed** that launch reset to 0%. Full trace:
a 1151ms `_apply_stylesheets` (the init cover apply) delayed the queued `_on_file_ready` until
`_on_file_loaded` (mpv thread) had already checked `_vt_restore_pending` and found `None`.

**Reconciliation with the 200-launch soak:** that soak targeted the VT-restore-on-load fix and ran
without exercising this — either cover mode was off (so `apply_cover_theme` early-returns at
`theme_manager.py:885`, no theme apply, nothing competes, "P1 always wins" held trivially) or it
otherwise didn't cover the cover-on path. Either way it did **not** test cover-theme-ON cold-launch
Race 3. So Race 3 at cold launch is a real, newly-confirmed live exposure, not something the soak
already cleared.

### Finding 4 — the two hazards map to TWO DIFFERENT cover applies that need DIFFERENT treatment

`[APPLY-ORIGIN2]` stack-origin tracing (temporary, reverted) confirmed exactly two
`apply_cover_theme` calls per cold launch, both via `_apply_main_cover`'s no-panel branch:

| Apply | Origin | Timing | Hazard | Why a `when_animations_done()` wait alone does/doesn't fix it |
|-------|--------|--------|--------|--------------------------------------------------------------|
| **#1** | `__init__` → `_load_cover_art` → `_apply_main_cover` | fires IN `__init__`, **before** the flow animation exists | **Race 3** — its synchronous ~700-1150ms `_apply_stylesheets` delays the queued `_on_file_ready`, so `_on_file_loaded` (mpv thread) reads `_vt_restore_pending` before `_restore_position` writes it | **A slider-wait does NOT fix #1** — no animation is running when #1 fires, so `when_animations_done()` fires the callback immediately. #1 needs a different treatment. |
| **#2** | `_on_scan_finished` → `load_cover_art` → `_apply_main_cover` | fires ~1.5s in, **during/near** the flow animation | **Regime B** — the ~400-600ms apply lands inside the flow-animation window and freezes the frame driver (and can also re-lose restore if it lands early) | **A slider-wait DOES fix #2's timing** — the animation is running when #2 fires, so the wait defers it past the animation. Even better: gating #2 on cover-actually-changed (Finding 2) eliminates it in the common case. |

**This is the load-bearing nuance the plan turns on: the two applies are not the same hazard with
the same fix. #1 (Race 3) precedes the animation and needs to not run synchronously in the
`_on_file_ready`-starving window; #2 (Regime B) coincides with the animation and needs either the
slider-wait or a cover-change gate.**

---

## The fix — two independent, minimal changes (one per apply)

### Change A — eliminate the redundant post-scan theme re-apply (fixes Regime B, and #2's Race-3 contribution)

**File:** `library_controller.py:158-161` (`_on_scan_finished`).
**Shape:** keep the cover reload for correctness, but only re-drive the cover-theme apply when the
active cover has actually changed since the pre-scan load. Concretely: have the post-scan path
compare the active-cover identity (path, or the book_covers active-cover key) against what was
loaded at init; if unchanged, refresh the displayed cover pixmap WITHOUT calling
`apply_cover_theme` (i.e. skip the theme re-apply, not the cover display refresh).

- **Where the change actually lands:** most cleanly inside `_apply_main_cover` /
  `apply_cover_theme`'s own path rather than in `_on_scan_finished`, so the "did the cover change?"
  test is centralized and applies to any future re-load caller, not just the scan-finish one. A
  candidate: `apply_cover_theme` already builds a `theme_dict`; it could early-out of
  `_on_theme_changed` if the newly-built cover theme is equivalent to the currently-active
  `_cover_theme`. BUT NOTE the jitter caveat below — this needs care.
- **Jitter caveat (must be resolved in implementation — the precise reason, not just "it doesn't
  work"):** a naive `theme_dict == _cover_theme` equality test will be `False` on EVERY call, even
  for the identical cover, so it would never skip and the gate would be a no-op. The exact
  mechanism (verified from `cover_theme.py` + a direct two-call test on one fixed pixmap: 35 of 42
  keys differed, `d1 == d2` → `False`):
  - `build_cover_theme` first extracts the dominant/secondary colors from the pixmap
    (`_qpixmap_to_rgb_pixels` → `_find_top_colors`). **This step is fully deterministic** for a
    fixed pixmap — the extracted `(dr,dg,db)`/`(sr,sg,sb)` are identical across calls.
  - It then applies **deliberate per-call random jitter** to the saturation/value of nearly every
    color: `j = lambda v, a=0.04: _jitter(v, a)`, where
    `_jitter(val, amount) = clamp(val + random.uniform(-amount, amount))`, using the **module-level,
    unseeded `random`** (`import random`, no `seed()` anywhere). So each of the ~35 jittered channel
    values draws a fresh `random.uniform` per call → different HSV → different final value.
  - The dict values are `_hex(...)` **strings** (e.g. `"#8B43BA"`), integer-rounded before
    formatting. So this is NOT a floating-point-epsilon comparison problem (values are strings) and
    NOT a dict insertion-order problem (Python `dict.__eq__` is order-independent, and both dicts are
    built by the same literal anyway). It is specifically: **the theme dict is intentionally
    non-deterministic per call by design** — the jitter exists precisely so the same cover doesn't
    map to a pixel-identical palette every session (see `build_cover_theme`'s own docstring: *"Small
    per-call jitter ensures the same cover produces slightly varied palettes"*).
  - **Therefore the change-detection must key on the deterministic COVER SOURCE IDENTITY** (the
    active cover file path / the `book_covers` active-cover key), which does NOT change call-to-call
    for the same cover — NOT on the derived theme dict, which is designed to change every call. This
    is why the gate belongs at the cover-load layer (where the source path is known), keyed on "same
    active cover source as what's already applied," not at the theme-dict layer. **Do not
    'simplify' this to a dict comparison later — it is unfixable by construction, because the
    non-determinism is a deliberate feature of the palette generator, not an artifact.**
- **Fallback if change-detection proves fiddly:** route the post-scan reload's apply through the
  same `when_animations_done()` deferral as `_apply_pending_cover_theme` (Change B's mechanism), so
  #2 at least lands after the animation instead of during it. This closes Regime B even without the
  cover-change gate; the gate is the cleaner win (avoids a redundant ~400ms apply entirely) but the
  deferral is the safe floor.

### Change B — stop apply #1 from starving the queued restore consumer (fixes Race 3 at cold launch)

**File:** `app.py` — the cold-launch init cover apply (`__init__` → `_load_cover_art` at `app.py:465`,
reaching `_apply_main_cover`'s no-panel branch at `app.py:2510`).
**Shape:** defer apply #1 so it runs AFTER `_on_file_ready`/`_restore_position` have executed (i.e.
after `defer_vt_restore` has written `_vt_restore_pending`), removing the race precondition. Two
candidate mechanisms, to be chosen by measurement:
1. **Defer the init cover apply to the next event-loop tick / until after book_ready is processed.**
   At init, wrap the no-panel-branch `apply_cover_theme(pixmap)` in a `QTimer.singleShot(0, ...)` (or
   chain it after `_on_file_ready` explicitly) so `_on_file_ready` → `_restore_position` →
   `defer_vt_restore` runs FIRST (the queued `book_ready` slot and the deferred apply then order
   deterministically: whichever is queued first runs first — verify the ordering empirically, do not
   assume `singleShot(0)` beats the already-queued `book_ready`).
2. **Skip apply #1 entirely at cold launch when apply #2 (post-scan) will set the cover theme
   anyway.** Since the cover is usually already available at init (Finding 2), and the scan runs at
   every cold launch, apply #1 may be entirely droppable at startup — but ONLY if apply #2 reliably
   fires and applies the correct theme. This is cleaner (one apply instead of two) but riskier
   (depends on the scan always running and finishing; a cold launch with no scan pending would leave
   no cover theme applied). **Prefer mechanism 1 (defer) over mechanism 2 (skip)** unless measurement
   shows the scan always fires — deferring is strictly safer than dropping.

**Interaction with the shipped VT fixes:** Change B is on the cover-theme/apply-timing side, not the
mpv-thread/seek-state side. It does NOT touch `_on_vt_file_switched`, the settle branch,
`_logical_pos`, `_vt_restore_pending`'s write/read logic, or `_on_end_file`'s ERROR reset. It only
changes WHEN the cover theme apply runs relative to `_on_file_ready` — moving it strictly LATER,
which can only reduce (never increase) the starvation window. But per the VT-fragile standing rule,
it must still be verified against the VT+Undo checklist (see Verification).

---

## Why this closes BOTH victims (the deciding question)

- **Regime B:** Change A removes/defers apply #2, the only theme apply that lands during the flow
  animation on cold launch. With it gone (or deferred past the animation), the flow animation has no
  ~400ms synchronous op competing for the frame driver → worst-frame-gap returns to the Regime-A
  baseline (~70ms). Regime A itself is untouched (it's chapter-populate/label work, not theme).
- **Race 3:** Change B moves apply #1 to run AFTER `_restore_position`/`defer_vt_restore`, so
  `_vt_restore_pending` is written before any theme apply can starve the queued consumer. The P1
  write wins the race against P2's mpv-thread read by construction, because the thing that used to
  delay P1 (the synchronous init apply) no longer runs before it. This mirrors, at cold launch, the
  protection book-switch already has (where `_apply_pending_cover_theme`'s wait keeps the apply after
  the restore/animation).

**Both share the same root — a cover-theme `_apply_stylesheets` running in the `_on_file_ready`
window — so addressing that root at cold launch closes both.** This is why the surgical fix is worth
trying before the broader cost fix: it does not require making `_apply_stylesheets` itself cheaper or
async; it only requires the apply not to run in the wrong window, which the codebase already knows
how to do (the `when_animations_done()` / pending-cover pattern).

---

## What must NOT change (per directive)

- `_any_panel_animating`'s existing behavior/scope (panel-slide ghost protection) — untouched.
- The shipped VT fixes (`_vt_restore_pending` write/read, gated `_on_vt_file_switched` clear,
  `_on_end_file` ERROR reset, `_logical_pos`) — untouched; Change B is timing-of-apply only.
- RANK-2 (the structural P1↔P2 pattern) — stays deferred, tracked in TODO.md, not addressed here.
- The post-scan reload's cover-correctness purpose (Finding 2) — preserved; Change A gates only the
  redundant THEME re-apply, not the cover refresh. If change-detection proves infeasible, fall back
  to deferral (never delete the reload).

---

## Implementation order + verification (for the eventual build step)

1. **Instrument first (temporary, DEBUG-gated, removable):** re-add the `[STUTTER-PROBE]` flow-anim
   frame-gap probe and the `[APPLY-ORIGIN]` cover-apply origin/timing probe. These are the exact
   probes this investigation used; they are the measurement instrument for "did the apply move out of
   the window."
2. **Change A first** (Regime B is the more visible, higher-frequency victim; 10/10 on M4B-cover).
   Measure across the matrix (below). Confirm apply #2 no longer lands in the animation window.
3. **Change B second** (Race 3). Measure the cover-on VT cold-launch restore race specifically:
   repeat the 8×-cold-launch protocol (restore progress before each launch), confirm 0 losses and
   no visual reset.
4. **Verification matrix (re-run the gap-closure investigation's exact matrix):**
   - 10 cold launches × 3 book types (M4B / MP3-single / VT) × 2 cover modes (off / with_pool).
   - Confirm flow-anim worst-frame-gap returns to Regime-A baseline (~70ms) on every config that
     previously showed the 400-600ms freeze (M4B-cover 10/10, VT-cover 8/9).
   - Confirm Regime A (~70ms) is UNCHANGED (this fix must not touch it — confirm, don't assume).
   - Cover-on VT cold-launch restore: 0/N losses, no visual 0% reset (the Finding-3 repro, now
     passing).
5. **VT+Undo standing-rule verification** (Change B touches the cold-launch cover/theme path near VT
   restore timing): re-run `tools/fs_race_harness.py`, `tools/vt_restore_race_harness.py`, and the
   VT+Undo live checklist. Re-run the VT cold-start soak methodology (progress-preserving repeated
   cold launches) if Change B's final shape could plausibly interact with restore timing.
6. `pytest tests/ -q` green.
7. Remove all temporary instrumentation; confirm via `git diff`/grep.

**Stop-and-report condition:** if, after Change A + Change B, the matrix still shows Regime B on any
config, OR the cover-on VT cold-launch restore still loses, OR either change reveals an interaction
with the shipped VT fixes — STOP and report that the surgical fix is insufficient. Do NOT expand
scope to the broader `_apply_stylesheets` deferral/chunking fix without a separate, explicit
decision. A partial win (e.g. Regime B closed but a residual Race-3 edge remains, or vice versa) is
worth shipping on its own merits — but report it AS a partial win, do not round up to "both closed."

---

## Confidence on the deciding question (both victims), stated honestly

- **Regime B closure: HIGH confidence.** The mechanism is fully traced (apply #2 lands in the
  window; remove/defer it and the window is clear), and the deferral mechanism (Change A's fallback)
  is a proven in-codebase pattern.
- **Race 3 closure: MEDIUM-HIGH confidence, pending the `singleShot(0)`-vs-`book_ready`-ordering
  measurement in step 3.** The mechanism is traced and the direction is right (move apply #1 after
  `_restore_position`), but the exact deferral mechanism's ordering against the already-queued
  `book_ready` slot must be measured, not assumed — hence it is step 3's explicit measurement, not a
  claimed certainty. If mechanism 1 (defer) doesn't deterministically order after `book_ready`,
  mechanism 2 (skip apply #1) is the fallback, with its own caveat (scan must fire).

Both are close enough that the surgical fix is the right thing to try before the broader cost fix —
but the plan deliberately keeps the "stop and report if insufficient" gate rather than pre-declaring
victory.
