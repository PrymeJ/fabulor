# Findings: the surgical cold-launch theme fix is SET ASIDE — what it bought, what it cost, and three post-fix findings

**Status: DOCUMENTATION ONLY. No code changed. The attempted fix lives in `stash@{0}` as a
reference artifact — it is NOT to be popped or re-run; it is kept so a future session can see
exactly what was tried and why it was set aside.** Working tree is pre-fix and probe-free; HEAD is
`af795d7` (docs only). Nothing from this fix attempt was ever committed.

Supersedes the "RESOLVED" framing in `plans/Findings_260714_coldlaunch_fix_interactions.md` (that
document's state table and sweep remain valid and useful; its verdict does not).
Companions: `plans/Plan_260714_surgical_coldlaunch_theme_fix.md`,
`review/Report_260714_theme_apply_safety_feasibility.md`,
`review/Report_260714_synchronous_main_thread_work.md`.

---

## 1. The honest verdict

**The surgical fix (Change A + redesigned Change B) is set aside, not shipped.** It produced a real
improvement and three new problems, at a complexity cost that was itself the signal it was the wrong
lever.

**What it bought (developer-confirmed, live):** the mid-flow freeze — Regime B, observed pre-fix as
*"stops at ~30%, then goes to 40%"* — **was genuinely solved by the fix.** This is a real result and
should not be lost: the mechanism (defer the cover-theme apply past the flow animation, and make the
post-scan reload stand down while an apply is pending) does close that specific freeze.

**What it did NOT fix:** the other hitches — app-start hitching, and the hitching the developer
continued to observe after the fix. These are NOT Regime B and were never closed by this work.

**What it broke:** three new findings (§3), all found by the developer *using* the app, none caught
by the verification matrix.

**Why the verification missed them — the methodology failure, stated plainly:** the matrix asked
*"does the theme eventually apply without freezing the animation?"* It never asked *"is what's on
screen correct for the whole time until it does?"* Every new finding lives in that gap. A green
matrix on the wrong question is worth less than ten seconds of a person using the app — a lesson this
codebase's own history (the settings-panel headless-verification rule) already records, re-learned
here the hard way.

**The deeper error — drift from the established root cause.** The parent report
(`Report_260714_synchronous_main_thread_work.md`) established the root cause precisely: it is
**`_apply_stylesheets`'s ~400ms synchronous cost** (median 318ms, pipeline median 442ms, max 759ms),
and explicitly NOT the cover-art extraction (~4ms, measured, cleared by name-suspicion). The
feasibility report then split the work into RANK-1 (reduce/reshape that cost) and RANK-2 (the
structural race). **This fix attempt did neither.** It rearranged *when* the expensive operation
fires, leaving the ~400ms cost fully intact. That was a legitimate thing to try (the plan said so),
but the escalating complexity — a 7-row state table, three interacting flags, two "interaction
surprises" from the same stale assumption, then a third bug in the fix's own flag timing — was the
signal to stop and reconsider the lever, not to keep patching. It kept going.

**Complexity accrued by the set-aside fix**, for the record: `_cover_theme_apply_pending`,
`_cover_apply_wait_inflight`, `_last_cover_source`, a `defer_theme` parameter threaded through two
functions, a re-entrancy guard, a rapid-switch stale-callback re-trigger, an apply-time DB re-read,
and a stand-down branch — to avoid making a ~400ms function cheaper.

## 2. What is genuinely known and still trustworthy (do not re-derive)

These survive the set-aside and should be carried forward:

- **The root cause is `_apply_stylesheets`'s synchronous cost**, not cover extraction. Measured, from
  a 70-run sample. (Parent report.)
- **`setStyleSheet` is GUI-thread-only** — "async" cannot mean threaded. The achievable shapes are
  deferral, chunking, or reducing the cost. (Feasibility report.)
- **The cover-theme dict is non-deterministic by design** (per-call jitter, 35 of 42 keys differ on
  the same pixmap) — any same-cover test must key on cover SOURCE identity, never dict equality.
  Verified by code + direct two-call test. (Plan's jitter caveat.)
- **`_any_panel_animating` is a deliberate, panel-scoped guard** (commit `a5cf753`) protecting panel
  slides from theme-apply; it was never about the flow animation. (Feasibility Phase 0.)
- **The state table and flag sweep** in `Findings_260714_coldlaunch_fix_interactions.md` — including
  that `_cover_theme_active` has many readers and cannot be overloaded — remain accurate and useful
  regardless of the verdict.
- **Regime A is real, separate, and low-rank**: a ~70–130ms hitch at animation start/decelerating
  tail, present with cover theme fully OFF (verified: VT75 cover-off, 0/8 Regime B, 77–127ms tail
  gaps). Not caused by this fix.
- **Position-dependence is a required test dimension**: the freeze's visible location tracks restore
  distance, because the competing apply fires at a ~fixed wall-clock time while the flow's position
  at that moment depends on how far it travels. A fixed-40% matrix under-reports. (Developer-found.)

**Explicitly NOT trustworthy — my own verification claims from this attempt.** The developer reverted
to pre-fix and still saw stutter + a VT reset; my "Race 3 = 0/8, Regime B = 0/8, closed" claim does
not survive that. Treat every number I produced for the *fixed* build as measuring the wrong
question, not as a baseline. One batch I nearly read as a "pre-fix baseline" collected **0 launches**
and was pure noise — caught only because the developer stopped it.

## 3. The three post-fix findings (documentation only — no fix proposed)

### Finding 1 — wrong theme shown on cold launch, then snaps (a direct, foreseeable cost of the fix)

With cover-art theme enabled (`exclusive` or `with_pool`), the fixed build launches showing a random
pool theme or a stale/default theme, then **snaps** to the correct cover-derived theme seconds later
when the deferred apply fires. Before the fix, the correct theme applied synchronously in `__init__`
— wrong in *timing* (that's what caused Race 3 / Regime B) but never visibly *wrong*. The fix made
the ordering correct and the screen wrong for the entire deferral window.

**This is the clearest evidence the fix traded one problem for another rather than removing a
problem.** It is a structural consequence of deferring, not a tuning issue — any fix that defers the
apply inherits it.

**Developer's proposed direction (leading candidate, NOT designed, NOT implemented):** persist the
last-applied cover theme (keyed to the book, or to "last exposure" generally) and have startup load
*that* as the starting theme, before any deferred apply runs — instead of a fixed default or a random
pool pick. The deferred apply then either **confirms** it (no visible change — the common case: same
book, same cover, same theme as last session) or **corrects** it (rare: cover changed since).

**Why this is structurally preferable to shrinking the window further:** it sidesteps the timing
window entirely for the common case rather than getting better at racing inside it — the same
"prevent the collision, don't get better at detecting it" principle that produced every durable fix
this session (guaranteed ordering over probabilistic timing; structural prevention over
detection-and-suppression). Shrinking a window on a *visible-wrongness* problem has the same weakness
as shrinking a window on a data-loss race: narrower is not closed.

### Finding 2 — a panel opened during the (now longer) pre-apply window is visually disrupted by the snap

Same root as Finding 1, different surface. The fix structurally lengthens the window between "book
starts loading" and "theme applies" (that lengthening *is* what fixed Regime B). Opening a panel
(including the sidebar) inside that window means the eventual theme snap visibly disrupts it.

**Hypothesis, explicitly NOT a conclusion — to verify, not assume:** this is likely resolved as a
side effect of whatever fixes Finding 1 (if the app starts already showing the correct theme, there
is no wrong-theme window to open a panel inside, for the common case). **Do not assume this** — the
"probably the same root cause / probably unrelated" assumption has already been wrong twice tonight
(the VT non-reproduction claim; the M4B-vs-VT regression claim). Check it.

### Finding 3 — HIGH PRIORITY: `T` during the deferral window strands slider colors — TRACED, and the premise needs correcting

**The trace (reading NOTES.md + git history, per instruction — the finding's framing was checked, not
assumed):**

**The original bug and its fix are real and identified:** NOTES.md 2026-06-19, *"Main-window theme
fade interrupt (sidebar mid-fade) FIXED; full color-animation rework DEFERRED."*
- **Symptom:** press `T` (theme rotate), then open the sidebar while the fade is still running → a
  slider (progress and/or chapter) stays painted in the **OLD theme's color** while everything else
  is the new theme.
- **Mechanism:** `_do_fade_with_slider_animation` excludes sliders from the overlay and instead
  animates their `bg_color`/`fill_color`/`notch_color` `@Property` values old→new, kicked off from a
  deferred `QTimer.singleShot(0, _start_color_anims)`. If a panel/sidebar opens between the fade
  starting and that deferred callback firing, the callback still runs, **re-resets the sliders to the
  OLD start colors**, and if the fade is then torn down they are **stranded** there.
- **Why sliders specifically:** `ClickSlider.paintEvent` paints from its `@Property` colors, NOT from
  QSS at paint time. New-theme colors reach those properties only via `_apply_stylesheets` → Qt
  `polish()` reading the `qproperty-*` declarations. Once a fade's color animation overrides the
  `@Property` and is stopped mid-flight, the slider keeps the stranded value until something
  re-polishes it. The rest of the UI reads colors from QSS at paint time and is correct the instant
  `_apply_stylesheets` runs.
- **The fix:** `ThemeManager.complete_main_fade()` — stops the fade + any running slider color
  animations, hides the overlay, unfreezes labels, then **re-applies the stylesheet for
  `_active_display_theme`**, re-polishing the slider `@Property` colors to correct values. Plus a
  `_fade_in_flight` flag guarding the deferred `_start_color_anims` so it returns early once the fade
  is completed/interrupted.
- **The invariant the fix relies on:** *every path that can interrupt an in-flight main-window fade
  must call `complete_main_fade()` first.* Verified still honored: `_toggle_sidebar` calls it, and
  `_complete_main_fade()` is called from every `_open_*_flow` direct-open branch and
  `open_book_detail` (`panels.py` — 9 call sites). The 2026-06-19 entry even predicted the hotkeys
  would need it; they got it.

**PREMISE CONFIRMED — this IS "a previously-fixed bug reopened." (This paragraph replaces an earlier
"PREMISE CORRECTION" that was WRONG — see the correction note below; it is left described, not
silently deleted, because how it went wrong matters more than that it did.)**

**The `T` + panel-open-SHORTCUT bug was fixed on 2026-07-10 by `8e65ddb`**, *"fix: complete in-flight
theme fade on keyboard-shortcut panel opens"*, whose commit message describes the exact symptom:
*"T followed immediately by a panel-opening shortcut (L/G/P/A/S/Z) left the transport sliders
stranded at the outgoing theme's colors while the rest of the UI had already moved to the new
theme."* Mechanism of that fix: the six keyboard shortcuts bypass `_toggle_sidebar` (which already
called `complete_main_fade()`) and instead called the weaker `abort_theme_fade()` (stops animations
but never re-polishes) — so `PanelManager._abort_theme_fade()` was renamed to `_complete_main_fade()`
and rewired to call `ThemeManager.complete_main_fade()`, shared by all five open-flow callers plus
`open_book_detail`.

**Why this record was briefly gotten wrong, and what it cost:** TODO.md's 2026-07-09 entry still
says this bug is *"not yet scoped or investigated... ask for the screenshot/repro steps at the start
of next session."* **That entry is STALE — the fix landed the next day (2026-07-10) and the entry was
never removed.** Reading TODO.md as authoritative produced a confident, wrong "correction" of the
finding's premise. The lesson is exactly the one this session applied everywhere else and skipped
here: **verify a claim against git history, don't trust a tracking document's status field.** TODO.md
records *intent at a point in time*; only git records *what was actually done*. (Two other
"hodge-podge"-named records DO exist and are genuinely different bugs — the 2026-06-19 sidebar-
mid-fade fix, and a root-cause-unknown sidebar bleed-through during hover-preview. The informal name
is shared across three records; that part of the earlier analysis was right and is why the stale
entry was believable.)

**So the correct statement of Finding 3 is:** pressing `T` during the deferral window reproduces
the stranded/mixed slider colors that `8e65ddb` fixed — **a fixed bug, reopened by a new trigger the
original fix's invariant does not cover.**

**The mechanism, now well-supported (still to be confirmed by trace before any fix):** `8e65ddb`'s
invariant is *"every path that can interrupt an in-flight main-window fade must call
`complete_main_fade()` first"* — and it enumerated those paths as **panel opens** (sidebar,
shortcuts, book detail). The set-aside fix introduces a **new kind of interrupt that is not a panel
open**: a *deferred cover-theme apply* firing while a `T`-initiated fade is in flight.
`apply_cover_theme` → `_on_theme_changed` starting a second fade over a running one is a shape the
invariant never anticipated, and no `_complete_main_fade()` call site covers it. Sliders strand for
the reason the 2026-06-19 entry documents: `ClickSlider` paints from `@Property` colors, not QSS, so
an interrupted color animation leaves them stranded until something re-polishes.

**Shared root with Findings 1/2? — Now clearer: Finding 3 is a REGRESSION INTRODUCED BY THE SET-ASIDE
FIX, not a pre-existing bug that merely surfaced.** It exists because the fix created a new
fade-interrupting path. That means: (a) with the fix set aside, Finding 3 should **not** reproduce on
current `main` — worth confirming, since it would independently validate this mechanism; and (b) **any
future fix that defers the theme apply will reintroduce it** unless the deferred apply also honors
`8e65ddb`'s invariant (i.e. completes an in-flight fade before starting its own). That makes Finding 3
a **design constraint on Findings 1/2's eventual fix**, not a separate bug to schedule — the opposite
of the earlier (wrong) conclusion that it might be fully independent.

## 4. The decision this document exists to inform (not made here)

The next investigation picks ONE of:
- **(A) RANK-1 properly** — reduce/reshape `_apply_stylesheets`'s ~400ms cost itself (deferral of the
  cost, chunking across event-loop iterations, or reducing what a theme change must restyle). This is
  what the parent report actually pointed at, and what this attempt substituted away from.
- **(B) Finding 1's persist-the-last-theme direction** — sidestep the window for the common case
  instead of shrinking or sequencing around it.

They are not mutually exclusive; (B) may make (A) less urgent, or vice versa. **This decision does
not need another matrix run on the set-aside design.**

## 5. Loose ends left in the tree (to resolve when the next step is decided)

- `stash@{0}` — the set-aside fix. Reference only. Do not pop/re-run.
- `tests/test_cover_theme_pending.py` (untracked) — 4 passing unit tests written for the set-aside
  design's contract. They test code that is no longer in the tree. Delete with the design, or keep if
  any of its mechanism is revived. **Not committed.**
- `plans/Findings_260714_coldlaunch_fix_interactions.md` (untracked) — its state table and flag sweep
  are still valid; its "RESOLVED" header is superseded by this document. Commit both together or
  neither.
- `[APPLY-ORIGIN]` / `[STUTTER-PROBE]` — both currently absent from `src/` (tree is pre-fix). If the
  next investigation needs apply-origin tracing, it is recoverable from `stash@{0}`.
