# Investigation: depth provenance, re-derived (not re-quoted)

**Date:** 2026-08-03  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Complete. Part 1 of the original two-part task, executed fresh per explicit instruction — no
number below was carried over from the earlier same-branch run
(`review/Investigation_260802_restyle_cost_depth_and_narrowing.md`) without independent
re-verification live, today, against current HEAD and against freshly-created worktrees.

---

## Why re-run this at all

The original Part 1 already found depth flat at 11 across four checkpoints. This session's task
explicitly required treating that as unconfirmed rather than settled, because two commits have
landed on this branch since (`9a268c3`, a QSS-only theme tuning; `1a82c11`, the swatch-leave jitter
backstop fix shipped this session) — neither is a widget-tree structural change, but the instruction
was to verify that, not assume it. Re-running independently also let this pass add a checkpoint the
original never tested (`be208c0`, the Excluded Books popup rebuild) and cross-check the visibility-
cost connection against the CLAUDE.md figures directly rather than from memory.

## Step 1 — current-state ground truth, live, today

`tools/depth_probe.py` run against current HEAD (`e32ad52`), both offscreen (the script's own
default) and forced on-screen (`QT_QPA_PLATFORM=` cleared) — **identical results both ways**,
confirming this measurement class (Qt's object parent-chain, set at construction time) is unaffected
by on-screen vs. offscreen rendering, unlike paint/compositing measurements this codebase's own
rules (correctly) distrust offscreen for. This is checked, not assumed:

```
TOTAL_WIDGETS=632
OVERALL_MAX_DEPTH_FROM_MW=11
SUBTREE settings_panel       widgets=170  own_max_depth=6
SUBTREE stats_panel          widgets=177  own_max_depth=10
SUBTREE book_detail_panel    widgets=72   own_max_depth=6
SUBTREE library_panel        widgets=30   own_max_depth=6
SUBTREE sidebar              widgets=8    own_max_depth=2
```

## Step 2 — historical checkpoints, live-verified via `git worktree`, not interpolated

`git log --since="2 months ago" --oneline -- src/fabulor/ui/` returns 312 commits. Sorted by
insertion count (`git show --stat`) to find genuine widget/structure-adding candidates rather than
scanning commit messages alone — the single largest by insertions in the entire window is
`6002e4d` (StreakGrid, 474 insertions), already the original investigation's pick; this pass
independently re-confirms it holds that rank rather than assuming it still does after two months of
further commits.

Four checkpoints chosen and run, each in its own `git worktree`, each with `tools/depth_probe.py`
copied in as a standalone script (the file postdates all four checkpoints, so it cannot be reused
in place — copying it into each worktree's own `tools/` dir, unmodified, keeps its relative
`sys.path` insert correct and its logic untouched):

| checkpoint | date | commit message | total widgets | depth | `stats_panel` widgets | `stats_panel` depth |
|---|---|---|---|---|---|---|
| A | 06-03 | `645f460` fix: disable scan buttons during scan, fix stale chrome on book remove | 606 | 11 | 166 | 10 |
| B | 06-11 | `5ba3816` feat: add load_currentcolor_icon for fill="currentColor" SVGs (immediately pre-StreakGrid) | 606 | 11 | 169 | 10 |
| C | 06-11 | `6002e4d` feat: add StreakGrid timeline view with tassel toggle | 611 | 11 | 174 | 10 |
| D | 06-27 | `be208c0` refactor: rebuild excluded books list as a MainWindow-level popup | 627 | 11 | 177 | 10 |
| E (today) | 08-03 | `e32ad52` (current HEAD) | 632 | 11 | 177 | 10 |

All four historical runs launched cleanly against the current `fabulorenv` with no dependency
errors — no checkpoint had to be skipped or approximated. Every worktree was removed
(`git worktree remove --force`) after its run; the working tree is unmodified.

**Depth is 11 at every single checkpoint, with zero exceptions, across five data points spanning
the full 2-month window** — including both immediately before and immediately after the single
largest widget-adding commit in the window, and including a new checkpoint (D) the original pass
never tested.

## Step 3 — named commits responsible for the observed count jumps

- **`645f460` → `5ba3816` (06-03 → 06-11): +0 widgets.** No change in this window despite 8 days
  and many commits between them — the intervening commits in this stretch were not widget-adding.
- **`5ba3816` → `6002e4d` (same day, 06-11): +5 widgets, entirely inside `stats_panel` (169→174),
  depth unchanged (10→10).** This is `6002e4d`, "feat: add StreakGrid timeline view with tassel
  toggle" — the single largest insertion-count commit in the whole 2-month window (474 lines) —
  and it added only 5 widgets to the live tree and zero new depth. Checked directly against the
  commit: `StreakGrid` and `TasselOverlay` are each a single custom-painted `QWidget` subclass doing
  its own `paintEvent` (a 26×14 calendar grid; a bookmark-tab overlay) rather than a composed tree of
  child widgets — that is precisely why 474 lines of new feature code produced 5 new widgets and no
  new depth: the feature's own internal complexity lives in paint code, not in nested Qt widgets.
- **`6002e4d` → `be208c0` (06-11 → 06-27): +16 widgets (611→627), the largest jump in this dataset,
  split `settings_panel` +4 (156→160) and the rest elsewhere.** This is `be208c0`, "refactor:
  rebuild excluded books list as a MainWindow-level popup." Checked directly against the commit
  message and `excluded_books.py`: `ExcludedBooksPopup` is parented to `mw.library_tab` (a tab page
  inside `settings_panel`'s `QTabWidget`), NOT to `mw` directly despite being called a "MainWindow-
  level popup" in its own commit message (that phrase describes its *positioning/paint* behavior —
  `show()`/`raise_()`/`setGeometry()`, mirroring `ChapterList`'s architecture — not its Qt parentage
  for tree-walk purposes). So it IS counted inside the `settings_panel` subtree by this probe. Its
  row widgets (`_ExcludedRow`, built via `setItemWidget` per row) are constructed lazily inside
  `reload()` — called only when the popup is actually opened and populated, never during a fresh
  `MainWindow()` construction — so the probe's count here reflects only the popup's always-built
  shell (the `QListWidget` container and header controls), not its potentially-larger populated
  state. The commit's own message explains why this widget exists as a popup at all: the prior
  inline expand/collapse design (nested inside the fixed-height Settings panel, which has no scroll
  area) hit a structural dead end — "every attempt to animate the list's height... either silently
  failed to expand, fought sibling widgets for space, or rendered nothing at all" — so the popup
  form was the fix, not an arbitrary architecture choice.
- **`be208c0` → HEAD (06-27 → 08-03, ~5.5 weeks): +5 widgets (627→632).** Sorted the same window's
  commits by insertion count: the two largest are `ca492a8` (440 lines, transport-bar blur
  event-driven rework) and `b2e0eb0` (415 lines, the transport-bar blur overlay's original
  addition). Both are large in code but contribute almost nothing to the widget count — consistent
  with the same StreakGrid pattern: `TransportBarBlurOverlay` is a paint-effect overlay (a grabbed,
  blurred pixmap composited over a QLabel), not a composed tree of child widgets, so its
  considerable logic (event-driven refresh, feedback-loop fixes, diagnostic tracing) lives in code
  that runs, not in widgets that get counted or nested.

**Pattern across the whole window:** every commit in this dataset that was large by line count but
small by widget-count/depth impact shares the same shape — a custom-painted `QWidget` subclass
(`StreakGrid`, `TasselOverlay`, `TransportBarBlurOverlay`) or a widget parented at a shallow,
pre-existing point in the tree (`ExcludedBooksPopup`, inside `library_tab`'s already-existing
6-deep chain) rather than nested more deeply. None of the commits examined added a genuinely new
LEVEL of nesting anywhere in the app — which is the direct, mechanical reason depth stayed flat
across a window that added a real, substantial, user-visible feature (a full second Timeline view)
and a real architectural rebuild (the Excluded Books popup).

## Step 4 — does this connect to the visibility-cost finding, or is it separate?

**Separate, and necessarily so — not because the evidence happens to point that way, but because
the two measurements vary different axes by construction.**

The visibility finding (CLAUDE.md, 2026-08-02: "~22% higher with the four heavy panels shown, at
identical widget count") holds the tree's SHAPE constant (same 632-widget count, same commit, same
moment) and varies only whether panels are currently mapped/visible — closed (527ms) vs. shown
(643ms) vs. hidden again (516ms). This depth-provenance investigation holds visibility constant
(every checkpoint measured via a fresh `MainWindow()` construction, all panels closed/unmapped by
default) and varies only TIME — which historical commit. One experiment's constant is the other's
variable, and vice versa. Neither could explain the other even in principle: a finding that panel
visibility swings cost ~22% at fixed shape says nothing about whether shape itself has changed over
time, and a finding that shape hasn't changed over time says nothing about why toggling visibility
at any single point in time costs what it costs.

They are, however, **consistent** with each other in the sense that neither contradicts the other:
depth is a static property of the current tree (confirmed unchanged for 2 months by this
investigation), and visibility is a dynamic property of what's currently mapped (confirmed to swing
cost independently, by the earlier same-branch investigation). Both are real, both matter for
understanding `_apply_stylesheets` cost, and they compose additively rather than one subsuming the
other — this was already stated in the original Part 1 write-up and this re-verification does not
change that conclusion, only re-confirms the depth half of it independently with one more data
point (`be208c0`) than before.

**No tidy single-cause narrative is available, and none is manufactured here.** The investigation
still cannot explain why the restyle cost might feel worse now than remembered (if it does) purely
from tree shape, because tree shape hasn't moved. Whatever else might explain a felt slowdown —
run-to-run drift (documented elsewhere as real and unexplained), usage-pattern changes (more panels
open more often), or something else entirely — is outside what a depth-provenance check can settle.

## Step 5 — was the nesting avoidable? (Provenance only, no fix proposed)

Not evaluated as a design critique — out of scope per the task's own instruction, and no fix is
proposed here. Noted only as a factual observation directly relevant to why depth stayed flat: both
major widget-adding features in this window (StreakGrid/TasselOverlay, the Excluded Books popup)
were built using patterns (custom paint, popup-parented-at-a-shallow-point) that were each already
the SIMPLEST available option for what they needed, not a deliberately depth-conscious choice made
because of any performance concern at the time they were written — the Excluded Books popup's own
commit message describes it as the only design that worked at all after several inline nesting
attempts failed outright, not as a depth optimization. Whether Stats' own eventual delegate-model
conversion changes this picture is explicitly out of scope for this document, per the task.

---

## What this investigation is NOT

Not a fix, not a refactor proposal, not a claim that felt slowness is fully explained. A pure,
independently re-derived confirmation — with one new data point and a direct commit-level causal
trace the original investigation didn't have — that the real app's widget tree has not gotten
deeper in two months, regardless of how much code or how many widgets were added in that time, and
that this finding is orthogonal to (not competing with, not explaining) the separately-measured
visibility-cost effect.
