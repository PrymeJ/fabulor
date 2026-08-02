# Review_260802_CLAUDEMD.md — CLAUDE.md file-health audit

Audited against commit `bb4b23bf0fba73ebcba62621b212bc576cd370d7`, file version at that commit
(1874 lines). This is a file-health audit, not a code review — no CLAUDE.md content was edited as
part of this pass.

**Note on the premise:** the task brief stated CLAUDE.md was "trimmed to ~1500 lines last week."
Walking the file's line count at every commit that touched it found no such drop — growth from
~950 lines (2026-06-19) to 1874 lines today has been monotonic, with the closest thing to a
trim being the 2026-07-13 reorganization (which *merged* two duplicate passes into one, net +0
lines) documented in the note at line 233 and the changelog entry at line 1385. No dedicated
trim-pass commit matching "~1500 lines" was found. Flagging this as a factual correction rather
than proceeding on a false premise.

Six agents independently audited non-overlapping line ranges (1–425, 426–895, 896–1174,
1174–1386, 1385–1630, 1630–1874) against the six required categories, cross-checking NOTES.md,
SESSION.md, TODO.md, and DEBT_INVENTORY.md for narrative preservation, and spot-checking specific
claims against the live codebase. Findings below are organized by category across the whole file;
line ranges are cited per finding.

**Status: categories 3, 4, 5, and 6 have since been actioned** (see the "Actioned" note at the
end of each relevant section) — category 4's mechanical fixes and category 5's relocations are
applied to CLAUDE.md/TODO.md; category 3 was reviewed and accepted as-is (no edits, per explicit
direction); category 6 required no action by definition. Categories 1 and 2 remain as originally
filed pending separate decisions (see "Escalated"), except where an escalated item was
independently resolved by direct edits to CLAUDE.md after this report was first written — noted
inline where that happened.

**Correction to the original STALE §4e finding:** it labeled `352b72f` a "fabricated commit
hash" based on `git log --all --oneline | grep 352b72f` returning nothing. Re-verified during the
action pass via `git cat-file -e`/`git show`: the commit is real
(`352b72f3dcdb35f3b2416da33bc5fe0f848a51b6`, "fix: align 3-per-row margins with Square, widen
toolbar-to-grid gap," 2026-07-10) and its content matches exactly what CLAUDE.md cites it for.
It is reachable via reflog (`refs/heads/main@{214}`) but **not reachable from current `main`** —
`git log --all` only walks reachable history, which is why the original grep produced a false
negative. The citation in CLAUDE.md was left as-is (it's accurate); the branch-history gap that
produced an unreachable-but-real commit is a separate, standalone question tracked at the end of
this report, outside the scope of the CLAUDE.md content audit.

---

## Summary table

| Category | Count | Status | Notes |
|---|---|---|---|
| 1. SUPERSEDED | 2 | Both resolved independently, outside this report | One clean/marked (no defect), one genuine defect (line 1874, now carries an inline correction note) |
| 2. NARRATIVE VS. CONCLUSION | ~24 entries flagged | Not actioned (no compression applied) | All traced to NOTES.md/SESSION.md except 2 novel lessons stranded changelog-only |
| 3. DUPLICATION | 9 clusters | **Reviewed and accepted as-is — no edits** | All appear to be the deliberate rule↔reference-doc split, not accidental drift |
| 4. STALE | 10 confirmed mismatches (**all fixed**), 1 finding corrected/retracted, 3 unverifiable | **Actioned** | Includes 1 miscited hash (fixed), 1 factually-outdated performance claim (resolved independently), 1 hash finding that was itself wrong and has been corrected in this report |
| 5. SCOPE CREEP | 2 | **Both actioned** — relocated to TODO.md | Both were in the old changelog tail |
| 6. LOAD-BEARING, KEEP AS-IS | ~35 entries | No action required (by definition) | Majority of "Critical Architecture Rules" and all of "What's Built" |

**Estimated line reduction if all category-2 compressions were applied:** roughly **520–580
lines**, concentrated almost entirely in the changelog block (lines 1387–1874, currently 488
lines). Breakdown:
- Changelog entries older than 2026-07-13 (lines ~1630–1874, agent verdict: "fully mined, safe to
  archive/compress"): compressing each ~15–30-line entry to 2–4 lines saves an estimated
  **280–320 lines**.
- Changelog entries 2026-07-13 through 2026-08-02 (lines ~1387–1630): more selective compression
  (several entries are dense/multi-bug and already tight) saves an estimated **60–90 lines**.
- Narrative embedded in standing rules within "Critical Architecture Rules" (lines 1–1057):
  the ~10 flagged entries (swatch_box saga, blur-overlay-parent, theme_item padding, VT+Undo
  history retained per agent recommendation, keyboard-focus-ownership narrative clauses, etc.)
  save an estimated **150–170 lines**, largely offset by the VT+Undo section's narrative being
  judged load-bearing and NOT recommended for compression (see below) — net figure already
  accounts for that exclusion.
- Two minor prose trims in "What's Built" (lines 1182, 1294–1297): **~10 lines**.

This is an estimate only; no compression was applied.

---

## 1. SUPERSEDED

### 1a. Lines 472–481 vs. 483–503 — hover-preview restyle cost (handled correctly, not a defect)
The 2026-08-01 correction (472–481, ~460ms + ~215ms panel breakdown) is explicitly superseded by
the 2026-08-02 sharpening immediately below it (483–503, "Sharpened 2026-08-02, and this kills
every content-based fix"). The newer text clearly marks itself as superseding the older, and the
older isn't left standing as if still fully authoritative. **Not a finding requiring action** —
included here only because it's the clearest example of the pattern this category watches for,
and to distinguish it from 1b below, which is the same topic handled badly.

### 1b. Line 479 (and by extension 495) vs. current code — GENUINE, unmarked staleness (also filed under STALE §4a)
Line 479's "~215ms" panel-restyle figure, measured 2026-08-01, is contradicted by a visibility
gate added to `_apply_stylesheets` (`theme_manager.py:1622-1650`) the same day, per that code's
own comment: *"Restyling them cost ~2/3 of this step's ~215ms for something nobody can see."* The
gate means a typical hover (only `settings_panel` visible) now pays roughly ⅓ of the quoted
figure, not the full ~215ms — but CLAUDE.md's surviving text never mentions the gate exists, so a
reader takes away that every hover tick pays the full amount. Unlike 1a, this is NOT
explicitly marked as superseded anywhere in the file, and no NOTES.md entry documenting the gate
could be found (searched "isVisible.*panel", "only restyle a panel", "2/3 of this step" — no
hits). **This is a real, unflagged contradiction between a written performance claim and the code
that falsified it on the same day.** Line 495's "no `hover` gate on any of its work" is narrowly
still true (the gate is `isVisible()`-keyed, not `hover`-keyed) but compounds the same omission by
implying preview/snapback always do the same *expensive* work, when for the common case it's now
cheaper than lines 472–503 describe. **Escalating rather than resolving** — this needs a decision
about whether to update the figure, note the gate, or re-measure; not something to silently patch
into the report's compression text.

### 1c. Line 1874 vs. lines 1826 and 1861–1863 — GENUINE, confirmed by direct grep
Line 1874 (the oldest, last-read changelog entry, itself explaining the origin of "What's Built")
states as current fact: *"StreakGrid longest-run uses a derived `_longest_fill` color with
`streak_longest_fill`/`streak_finished_dot` per-theme overrides."* This is contradicted by two
later (chronologically newer, and positioned earlier in the file due to reverse-chronological
order) entries: the 2026-06-18 entry at ~1861–1863 states these keys were *replaced* by
`streak_grid_outline`/`streak_grid_dot`, and the standing rule content elsewhere in the file uses
only the new names. **Independently re-verified**: `grep -n "streak_longest_fill\|streak_finished_dot" src/fabulor/themes.py`
returns zero hits; `streak_grid_outline`/`streak_grid_dot` are present and populated for every
theme (themes.py:86-87, 176-177, 213, 266, 369, 413, 449, 548, ...). **Confirmed genuine
supersession, not just staleness** — line 1874 describes a state that was replaced by an entry
the reader encounters earlier in the same file. This is exactly the kind of thing this category
exists to catch and not silently resolve; flagging per instructions rather than fixing.

---

## 2. NARRATIVE VS. CONCLUSION

Organized by location. For each: line range, one-line description, proposed compression (where
given by the auditing agent), and whether the full narrative was confirmed to already exist in
NOTES.md/SESSION.md (BLOCKING if not).

### In "Do not comment on the time..." / "Never substitute a plausible explanation..." (lines 12–93)
- **Lines 30–36** (2026-07-28 context-exhaustion incident, direct Pryme quote). Preserved:
  SESSION.md ~1173. **Not blocking.** Proposed: *"Context exhaustion, not error rate, is the only
  valid reason to suggest stopping — conflating the two (2026-07-28) is the documented failure
  mode. See SESSION.md 2026-07-28."*
- **Lines 45–54** (three 2026-07-28 "Never substitute" incidents, with quotes). Preserved:
  SESSION.md 1165/1173, NOTES.md ~858. **Not blocking.** Proposed: *"Verify before explaining:
  three 2026-07-28 incidents (entr/restart misattribution, a grep read as showing incoherence
  that wasn't there, asking Pryme to redescribe a plainly-stated symptom) all had a checkable
  answer one query away. See NOTES.md 858, SESSION.md 1165/1173."*
- **Lines 60–91** (2026-07-30 "Colin Mace" phantom-filter incident, exact log excerpt). Preserved:
  NOTES.md 1098–1132 (exact `button=2` line confirmed present). **Not blocking.** Proposed: *"A
  report of what Pryme did/saw is data, not a hypothesis — don't defend an inference against it
  (2026-07-30: a stale filter target was wrongly attributed to a click Pryme said never happened;
  the real cause, a right-click armed via a code path that checked event type but not button, was
  two greps away). See NOTES.md 1098."*

### Debugging Discipline bullets (lines 101–167)
Individually checked by the agent covering this span; verdict for each:
- Lines 112–117 (stretch-participant, 2026-08-01): preserved (NOTES.md 294–317), already close to
  conclusion-shaped, minimal compression needed.
- Lines 118–126, 127–132, 133–136 (pre-screening, `_title_draw_width`, test-shares-assumption):
  already conclusion-shaped, **no compression needed**.
- Lines 137–142 (inferred-rationale/Stats 2px inset): preserved (SESSION.md 304). Not blocking.
- Lines 143–152 (chronological-timing, two 2026-08-02 instances): preserved exactly (NOTES.md 75,
  108, exact figures match). Not blocking. Proposed: *"Report timings chronologically, sort only
  once i.i.d. is established — sorting hid a first-call cold-start twice on 2026-08-02. See
  NOTES.md 75, 108."*
- Lines 153–160 (hit-rate-before-new-guard): preserved exactly (NOTES.md 248, 271, "44 of 120"
  confirmed). Not blocking. Proposed: *"Measure an existing guard's hit rate before adding a new
  one — a proposed root-restyle guard (2026-08-02) was written up as necessary before anyone
  counted; the existing guard was already catching 44/120 calls free. See NOTES.md 248."*
- Lines 161–167 (offscreen-harness 25% high): already tight, **no compression needed**.

### "Critical Architecture Rules" section (lines 223–1057)
- **Lines 341–360, "VT+Undo is the known-fragile zone"** — dense, narrative-heavy (four historical
  revert attempts with commit hashes). **Recommendation: do NOT compress.** The agent auditing
  this span makes a specific, reasoned case that the narrative here IS the load-bearing content —
  the section's own standing rule ("don't treat a green instrumentation run as a stopping point")
  is only credible *because* of the four-attempt history demonstrating clean-looking fixes that
  broke live. Collapsing the evidence would weaken the rule it supports. Flagging as an explicit
  exception to the general compression recommendation, per the agent's own reasoning — quoted
  rather than second-guessed, since compressing it would require judging whether the evidentiary
  function can survive summarization, which risks guessing at a conclusion not explicitly stated.
- **Lines 505–528, `_pending_fade_call` stash-tuple rule** — the generalization ("if the signature
  gains a parameter, widen the tuple at all three drain sites") is load-bearing and forward-looking,
  keep. But see STALE §4c: the line number and one variable name it cites are wrong.
- **Lines 614–679, swatch_box/`_on_themes_tab_left` saga** — dense investigation narrative (exact
  timing, two-pass fix history, 133-of-134-calls attribution). Preserved: NOTES.md 3152–3248 (full
  trace). Not blocking. Proposed: *"`swatch_box.leaveEvent` is the sole entry point into
  `_on_themes_tab_left`. Do not add a second bare unhover lambda anywhere in the Themes tab
  hierarchy — a blur-grab synthetic leave can silently kill an in-flight hover preview otherwise
  (root-caused 2026-07-22, full trace NOTES.md 3152)."*
- **Lines 636–665, visibility-check verification + two failed cursor-delta attempts** — same
  NOTES.md entry as above; SESSION.md 1323 also covers it. Not blocking. Proposed: *"The
  leave-suppression check anchors on `swatch_box.isVisible()`, not cursor position/delta — two
  delta-based replacements were tried and both regressed (verified live: 6/6 real mouse-outs
  visible, 12/12 hidden-leaves false positives). A `[SWATCH-LEAVE-SUSPECT]` probe exists to
  falsify this if wrong; grep count must stay 0."*
- **Lines 564–592, blur-overlay-parent rule** ("first attempt shipped invisible," "37 correct
  calls... nothing on screen"). Preserved: SESSION.md 123–199 (full three-attempt trace). Not
  blocking — note it lives in SESSION.md, not NOTES.md, which is the correct home per this file's
  own Conventions section. Proposed: *"A blur overlay can only cover what shares its parent
  (`raise_()` does not cross parent boundaries), and a `WA_StyledBackground` panel paints its wash
  before any child, so a child `lower()` can't sit beneath it either. Fix: parent the frost to the
  panel, composite the wash into the frost's pixmap. (Full three-attempt trace: SESSION.md,
  2026-08-01 Session 3.)"*
- **Lines 695–721, `theme_item` padding rule** ("tried live and failed," three named rejected
  fixes). Preserved: NOTES.md ~3178–3240 (same entry as the swatch_box saga, folded together —
  minor findability issue noted, not a preservation gap). Not blocking. Proposed: *"Padding must
  stay small enough that `theme_item`'s `sizeHint()` fits what `swatch_box` can give it —
  `settings_panel` has no slack to grant. Fixed by shrinking padding `4px 0px` → `1px 0px` (not by
  giving `swatch_box` more room — three room-growing variants were tried live and failed; see
  NOTES.md 2026-07-22)."*
- **Lines 919–996, "Keyboard focus ownership"** — the core invariant (919–927) and the two
  enforcement-mechanism bullets (928–948) are load-bearing; embedded narrative clauses (932–936,
  941–948, 994–996) are compressible. Preserved: NOTES.md 6863, SESSION.md 3119/3200/3010. Not
  blocking. Full proposed compressed replacement given by the auditing agent (see full agent
  output; compresses ~78 lines to ~12 while keeping all five sub-invariants as flat bullets).
- **Lines 1013–1032, "DO NOT use a bare QLineEdit"** — the "Andrew"→"And" anecdote is compressible;
  the distance+dwell mechanism and "distance alone was insufficient" clause must survive (filed
  under LOAD-BEARING). Preserved: NOTES.md 1007. Not blocking.
- **Lines 1034–1047, click-outside popup-allowlist rule** — the specific symptom trace is
  compressible; the general rule ("any Qt.Popup reads as 'outside' to containment checks") must
  survive. Preserved: NOTES.md 975. Not blocking.

### "What's Built" section (lines 1091–1386)
- **Line 1182** — embedded narrative clause ("this exact bug hit two separate pre-existing call
  sites the same day the guard was introduced") inside an otherwise-factual rule statement.
  Preserved: NOTES.md 7909. Not blocking. Proposed: drop the parenthetical; the invariant already
  stands without it.
- **Lines 1294–1297, "Pending / Known Debt" → VT open issues** — reads as an investigation trace
  (hypothesis-and-reasoning shaped) rather than the one-liner shape the rest of "Known Debt" uses.
  Preserved: review/Review_260612_6.md §6/§7, cited inline; also indexed in `DEBT_INVENTORY.md`.
  Not blocking, but shape-inconsistent with its own section — see SCOPE CREEP §5 for the related
  finding.

### Changelog block (lines 1387–1874)
This block is large enough (488 lines) that findings are summarized rather than fully
enumerated; see the two agents' full reports for line-by-line detail. Key points:
- **Lines 1397–1421, 1444–1457** (2026-08-02/08-01 entries): all confirmed preserved in
  NOTES.md/SESSION.md; proposed compressions given (see full agent output) trim each ~15-20 line
  entry to ~4-5 lines without losing the load-bearing conclusion.
- **Lines 1641–1874 (everything older than 2026-07-13, ~17 entries, ~234 lines)**: the agent
  auditing this range makes a structural case, backed by evidence, that this entire tail is now
  "fully mined" — every lesson-shaped entry checked traces to a standing rule that already exists
  elsewhere in the file, and every factual claim is already restated (often more accurately) in
  "What's Built." **Zero entries in this range were found to be the sole surviving record of a
  rule not already promoted.** This supports treating the pre-2026-07-13 changelog tail as an
  archival candidate — not a decision made here, but flagged with the supporting evidence per the
  task's own framing of the growth-vs-accretion question.

### Two lessons found stranded in changelog-only form — never promoted to a standing rule
Distinct from ordinary narrative-compression candidates: these are genuinely novel conclusions
that live ONLY in the changelog, were never stated as their own Debugging Discipline bullet or
architecture rule, and are NOT restated anywhere else in the file:
- **Lines 1530–1536** (2026-07-27): offscreen harnesses can be blind to compositing/paint-order
  defects entirely (returned byte-identical output for a bug plainly visible live) — categorically
  different from the existing "offscreen reads ~25% high on timing" rule (line 162), which is
  about *magnitude* bias, not correctness blindness.
- **Lines 1397–1400** (2026-08-02): "building stylesheet strings is 0.1ms while applying them is
  everything, so caching theme dicts cannot help" — a specific, reusable performance-intuition
  correction that killed three separate fix proposals per the text itself, but is stated nowhere
  as a standing rule.

Recommend considering promotion of both to the Debugging Discipline list — noted here since it's
the opposite failure of over-accretion: content that's too thin/buried rather than too verbose.

---

## 3. DUPLICATION

**Status: reviewed and accepted as-is — no edits made, per explicit direction.** All 9 clusters
below were judged deliberate rule↔reference-doc splits rather than accidental drift; the decision
was to close this category without merging or collapsing any of them.

All clusters found appear to be the file's own deliberate split between "Critical Architecture
Rules" (rule + rationale) and "What's Built" (compressed factual reference), or between a standing
rule and its origin-story changelog entry — not accidental copy-paste drift. Reporting per
instructions without merging.

1. **Soft-delete flags** (`is_deleted`/`is_excluded`/`is_missing`): full treatment at lines
   409–428; restated at lines 1242–1243 (Library state machine) and 1250–1251 (Database section);
   restated again in the 2026-06-27 Session 3 changelog entry (1775–1790, a strict subset of
   409–428, including the identical "Schrödinger's audiobook" framing). **4 locations total.**
2. **Chapter-seek constants** (`_CHAPTER_WALK_TOLERANCE` etc.): stated as rules at lines 296,
   356–358, 376; restated as "What's Built" fact at 1112–1116. **4 locations**, and per §4 below
   all four numeric values still agree — but a future recalibration must be applied in all four
   places, three of which carry their own prose justification.
3. **Keyboard focus ownership**: full invariant at 919–996 (+ sub-rules to 1057); compact
   cross-referenced restatement at 1222 (Panels "What's Built" section) — this one explicitly says
   "See the... CLAUDE.md rule for the full invariant," making it a deliberate pointer, not silent
   duplication.
4. **QComboBox popup pseudo-state bug**: standing rule at 911–912; restated in the 2026-07-09
   changelog entry at 1646–1652 — and the changelog copy carries a citation error the standing
   rule doesn't have (see STALE §4d).
5. **Library keyboard nav / click-to-filter / sort-shortcuts**: current mechanics stated in
   "What's Built" (1181–1184); origin-story changelog entries at 1641–1661 and 1731–1746 restate
   the same facts in past tense with added process narrative.
6. **`_sized_cover_cache`/`_get_sized_cover`**: full rule at 872–889; referenced in "What's Built"
   (1175, 1179) and three changelog entries (1748–1823) — consistent restatements/pointers, not
   competing statements.
7. **`_NO_BASE_INHERIT_KEYS`**: rule at 725–744; correctly cross-referenced (not restated) by
   TODO.md in two places, confirming CLAUDE.md as the authoritative home rather than duplication.
8. **Book Detail panel blur** (raise_()/WA_StyledBackground facts): standing rule (grep-confirmed
   to exist under "A blur overlay can only cover what shares its parent"); changelog entry at
   1404–1421 restates the general facts alongside a narrative unique to that entry (the
   three-failed-attempts trace) not found in the standing rule.
9. **"A report about what Pryme DID is data"**: standing principle at 61–92 (with the Colin Mace
   incident as its worked example); changelog entry at 1480–1488 references the same incident from
   the bug-fix angle (`editorEvent` checked type not button, `90bb36a`) — legitimate
   dual-purpose (process lesson vs. code-fix record), flagged as borderline rather than a clean
   duplicate.

**Not independently verifiable** beyond targeted greps: whether every topic keyword cluster
(`_claim_panel_focus`, `call_when_panels_settled`, and others adjacent to but outside each agent's
assigned span) has additional un-found duplicate locations. Flagged by the relevant agents for a
follow-up full-file duplicate scan if exhaustive coverage is wanted.

---

## 4. STALE

### Confirmed mismatches (verified against current codebase)

**4a. Line 479 — hover-preview restyle cost figure contradicted by same-day code change.**
Also filed under SUPERSEDED §1b. The quoted "~215ms" panel cost predates a visibility gate added
to `_apply_stylesheets` (`theme_manager.py:1622-1650`) the same day (2026-08-01) that the code's
own comment says cuts it to roughly ⅓ for the common case. No corresponding NOTES.md update found.

**4b. Line 903 (and 1137) — `COVER_AREA_HEIGHT` location.** ✅ **Actioned.**
Claimed "a module-level constant in `app.py`." Actual: `src/fabulor/ui/ui_helpers.py:25`;
`app.py` only imports it. The move predates even the "What's Built" section's stated audit date
(2026-06-13) — commit `3f29a66` moved it out of `app.py` on 2026-06-05 — meaning this claim was
already wrong when written and has stayed wrong through every later edit. No part of CLAUDE.md
currently states its real location correctly (the file tree at line 1348 doesn't mention this
constant either). Fixed: CLAUDE.md now reads "a module-level constant in `ui/ui_helpers.py`,
imported into `app.py`".

**4c. Lines 507, 528 — `_pending_fade_call` line number and variable name.** ✅ **Actioned.**
Claimed: `` `theme_manager.py`, ~line 768 ``, referencing a variable `_hover_interrupts_hover`.
Actual: the branch is at **line 995**, and the guard variable in code is
**`_hover_may_interrupt`**, not `_hover_interrupts_hover`. Two-part staleness: wrong line number
and a renamed identifier no longer matching the quoted name. (The `pending[3]` tuple-index claim
at line 528 does still check out positionally against the documented 6-tuple order — left
untouched.) Fixed: citation now reads `theme_manager.py:995` with the correct variable name.

**4d. Line 1650 — miscited commit hash for the QComboBox delegate fix.** ✅ **Actioned.**
`f6388d2` is cited as one of three commits implementing `_ComboItemDelegate`/`_ThemedComboBox`.
Its actual commit message is *"fix: return keyboard focus to book list after dropdown popup
closes"* — a real but unrelated fix. The two commits that actually implement the delegate/arrow
paint work are `3e8c241` and `8515605` (both independently confirmed via `git log`), already
cited alongside the wrong one. Fixed: `f6388d2` removed from the implementation-commits list and
re-cited with a one-clause note identifying what it actually is, so the reference isn't silently
dropped.

**4e. Line 1608 — commit hash re-investigated; NOT fabricated, correcting this finding.**
Original finding claimed `352b72f` "does not exist anywhere in git history," based on
`git log --all --oneline | grep 352b72f` returning nothing. **This was wrong.** Re-verified during
the action pass via `git cat-file -e 352b72f` (resolves to a real commit object) and
`git show 352b72f`: the commit is genuine
(`352b72f3dcdb35f3b2416da33bc5fe0f848a51b6`, "fix: align 3-per-row margins with Square, widen
toolbar-to-grid gap," 2026-07-10 09:28:27), and its content is exactly what CLAUDE.md cites it
for (the 3-per-row remainder-push margin work described in the same changelog entry). It shows up
in `git reflog --all` (`refs/heads/main@{214}`), confirming it really was on `main` at one point —
but `git merge-base --is-ancestor 352b72f HEAD` returns false: it is **not reachable from current
`main`**. `git log --all` only walks commits reachable from live refs, which is why the original
search produced a false negative on a genuine, unreachable-but-real commit rather than catching an
actual fabrication. **No change made to the CLAUDE.md citation** — it was accurate as written, per
explicit direction not to touch it. **Separate finding, tracked independently of this doc audit:**
something (a rebase, reset, or force-push) removed `352b72f` from `main`'s reachable history after
it landed — worth investigating as its own question, unrelated to CLAUDE.md's content, since the
same operation could have similarly orphaned other commits.

**4f. Line 1874 — stale streak-grid theme key names.** ✅ **Actioned independently, outside this
audit pass.** Already covered fully under SUPERSEDED §1c. CLAUDE.md line 1874's changelog entry
now carries an inline correction note (added directly, not via this report's compression
proposals) pointing out the old key names were replaced 2026-06-18 — see CLAUDE.md ~1797-1798.

**4g. Line 1293 — five `day_start_hour` inline-duplication line-number citations, all stale.**
✅ **Actioned.**
Claimed: `db.py:784`, `db.py:1031`, `app.py:320`, `stats_panel.py:2615`, `stats_panel.py:2628`.
Actual (verified via grep against current HEAD): `db.py:864`, `db.py:1119`, `app.py:430`,
`stats_panel.py:4007`, `stats_panel.py:4033`. All five have drifted; the underlying claim (five
near-identical inline copies, no shared helper) still appears structurally true. Fixed: all five
line numbers updated in place.

**4h. Lines 358–359 — two stale code-location citations in the `_logical_pos`/VT-restore FIXED
entry.** ✅ **Actioned.**
Claimed: `` `_on_vt_file_switched` (app.py:1430-1442) ``, `` `_on_end_file`'s ERROR branch
(player.py:620-645) ``. Actual: `_on_vt_file_switched` is now at `app.py:1703` (the `_seek_target
is None` gate itself at `app.py:1728`); `_on_end_file` is now at `player.py:708` (the reset block
at `player.py:727-734`). Both re-verified as content-accurate (the described guard logic matches
what's at the new locations) — only the line numbers were wrong. Fixed: citations now use the
precise current locations rather than reproducing the old span width.

**4i. Lines 172–190 — "TEMPORARY" conda-shadow section.** ✅ **Actioned — and this turned out to
be more than a citation staleness.**
Live-tested during the action pass, two findings: (1) the doc said "pytest fails collection on 8
files"; a live test found **7** — minor, likely drift from a test file being added/removed since
the 2026-07-30 date on this section. (2) More significant: the documented
`LD_PRELOAD=/usr/lib64/libstdc++.so.6 pytest tests/ -q` workaround, run exactly as written in a
fresh (unactivated) shell, **does not work** — it fails on an unrelated `libcaca.so.0`/`_nc_curscr`
symbol error instead of the GLIBCXX error this section exists to fix, because it silently depends
on `fabulorenv/bin/activate` having already been sourced in that shell (which sets the
`LD_LIBRARY_PATH` shim documented elsewhere in this file, under "Running the app"). The `python
main.py` line right above it already did this correctly; the `pytest` line did not. Verified the
fix works in a genuinely fresh shell (`bash -c 'source fabulorenv/bin/activate && LD_PRELOAD=...
pytest tests/ -q'`) before committing it. Fixed: file count corrected to 7; both workaround
commands now explicitly chain `source fabulorenv/bin/activate &&` first, with a note explaining
why `LD_PRELOAD` alone is insufficient.

### Confirmed accurate (no action needed — listed to show what was checked and passed)
- Window fixed size 300×564 (`app.py:643`).
- All four chapter-seek constants (`_CHAPTER_WALK_TOLERANCE=0.5`, `_CHAPTER_BOUNDARY_EPSILON=0.35`,
  `_EMBEDDED_CHAPTER_SEEK_OFFSET=-0.09`, `_PAUSED_SEEK_UNDERSHOOT_COMP=0.37`), exact matches in
  `player.py` lines 54/60/69/79.
- `_MP3_SEEK_THRESHOLD`/`_VT_MP3_SIZE_THRESHOLD` values, `player.py:80-81`.
- `_MetaActionState` enum, `book_detail_panel.py:28`.
- Cover panel preview label fixed 208×266, `cover_panel.py:363`.
- `ExcludedBooksPopup`/`ExcludedBooksSection`, both confirmed in `excluded_books.py`.
- `TAG_COLORS` (9 named + neutral, `tag_manager.py:113-122`) and `MAX_TAG_LENGTH=20`
  (`tag_manager.py:17`).
- All 8 stylesheet-architecture table functions exist in `themes.py` at the mapped widgets.
- Full file tree (lines 1301–1356) matches `src/fabulor/` and `src/fabulor/ui/` exactly — no
  missing or phantom entries.
- `_pending_fade_call` 6-tuple field order, `theme_manager.py:1070`.
- `pool_container.leaveEvent` confirmed removed; `swatch_box.leaveEvent` confirmed wired
  (`main_window_builders.py:692, 735`).
- `theme_item` padding `1px 0px`, `themes.py:3657`.
- `_close_settings_flow` → `_on_theme_unhovered()` → `snap_theme_forward()` ordering,
  `panels.py:1382-1383`.
- `requirements-dev.txt` contains pytest; `requirements.txt` does not.
- Roughly 30 additional commit hashes sampled across the file, all confirmed to exist and match
  their described change (only the two flagged above did not).

### Unverifiable without guessing (explicitly not resolved)
- Whether every constant/timing value in the "What's Built" section not specifically named for
  spot-check (e.g. `PRELOAD_BATCH_SIZE`, `_MIN_POOL`, `CELL 14`, etc.) still matches current code —
  out of scope for the targeted spot-checks performed; would need a full separate numeric-literal
  pass.
- Whether the "five current text inputs use DragSafeLineEdit, no bare QLineEdit remains" claim
  (line 1028) is still exhaustively true — would require a full-repo grep beyond what was run.
- Whether `hover` "skips the hidden stats/book-detail panels" (line ~1508 area) still holds after
  the 2026-08-02 `apply_panel_alpha_pass` addition — consistent with what was checked, but call
  sites weren't fully traced.
- Most git commit hashes in the pre-2026-07-13 changelog tail were spot-checked (a sample of 5-6),
  not exhaustively verified one-by-one; the two errors found (§4d, §4e) suggest a full sweep could
  surface more.

---

## 5. SCOPE CREEP

**Status: both items actioned.** Checked TODO.md/TODO_ARCHIVE.md for existing matching entries
first (per the original caveat that this wasn't done) — neither item had one; both were genuinely
missing, not just misfiled duplicates.

1. **Line 1682 — ✅ Actioned.** "Remaining letters (T onward) still pending" (2026-07-07 Session 3,
   per-theme library color pass). An open TODO sentence embedded in a changelog entry rather than
   recorded in TODO.md. Fixed: added `- [2026-07-07] Per-theme library color pass only covers A–S
   alphabetically (...) — letters T onward still need the same tuning pass (\`ae4441c\`)` under
   TODO.md's "Theme color/data" section (an existing, related-but-broader entry there — "Remove
   theme inheritance from The Color Purple" — did not already cover this specific, narrower fact).
   CLAUDE.md's changelog sentence trimmed to "Remaining letters (T onward) tracked in TODO.md."
2. **Lines 1636–1639 — ✅ Actioned.** "Deferred by the user ('Later'): 2-per-row still doesn't fully
   fill available whitespace... do not reuse this session's 469px measurement as a baseline." Same
   pattern — a deferred-work note sitting in a changelog entry instead of TODO.md. Fixed: added an
   entry under TODO.md's "Misc UI polish" section preserving the specific warning about the stale
   469px baseline (dated 2026-07-10, matching the session it came from — `d74ebee`). CLAUDE.md's
   changelog sentence trimmed to "Remaining 2-per-row whitespace tightening deferred by the user
   ('Later') — tracked in TODO.md."

**Not scope creep** (checked and ruled out): the "Pending / Known Debt" section itself (lines
1285–1297) is NOT scope creep — `DEBT_INVENTORY.md` explicitly names CLAUDE.md's "Pending / Known
Debt" section as its own source of truth, with DEBT_INVENTORY.md deliberately the thin index. This
section is correctly located per that file's own stated design, even though its VT-open-issues
sub-bullets are narrative-shaped rather than one-liner-shaped (see NARRATIVE §2 instead).

**Correction (this finding was wrong as originally filed):** the first draft of this report
flagged "two divergent `DEBT_INVENTORY.md` files" (`./DEBT_INVENTORY.md` and
`./review/Snapshot_260612_debt_inventory.md`) as an ambiguity affecting confidence in cross-references. That was
filed without reading `review/Snapshot_260612_debt_inventory.md`'s own header, which resolves the question
directly — its second line states: *"**STALE — frozen snapshot, not the current debt index.**
This file is part of the 2026-06-12 `review/Review_260612_1–8.md` audit batch and was
deliberately left untouched after that date (see SESSION.md, 2026-07-01 Session 3). The live,
actively-maintained debt index is..."* (pointing at the root `./DEBT_INVENTORY.md`). There is no
real ambiguity: the root file is canonical and current; the `review/` copy is an intentional,
self-declared historical snapshot, not accidental drift. Retracted — not a finding. (The
synthesizing pass should have opened both files and read past line 1 before writing this up;
noting the correction rather than silently removing it, per the standing rule against letting a
retracted claim quietly vanish.)

---

## 6. GENUINELY LOAD-BEARING, KEEP AS-IS

**Status: no action required by definition.** This category is the "leave alone" list — every
entry below was confirmed to need no edits during the action pass; none were touched.

A large majority of "Critical Architecture Rules" and effectively all of "What's Built" earned
this verdict. Listing explicitly per instructions, grouped by section:

**Lines 1–167 (opening sections):** the four sections here ("What this file is for," time/stopping
guidance, "Never substitute a plausible explanation," library-scale testing guidance) are each
doing real, non-narrative work in their core statements — only the embedded incident quotes
compress (see §2). "Design and test against library sizes an order of magnitude beyond what's on
hand" (96–98) is a single dense paragraph with zero narrative fat.

**Lines 223–1057 ("Critical Architecture Rules"):**
- MPV-init DO-NOT (285–293) — every clause names a still-current mechanism and consequence.
- Chapter-derivation-via-walk rule (295–296), book_ready/file_loaded connection + book-switch
  state machine (298–304), slider-staleness/duration-race/chapter-flow-target rules (305–311),
  the five seek-state guard rules (312–336) — all mechanism-level, no narrative fat, each maps to
  a distinct historical freeze bug.
- VT+Undo standing rule (341–360) — narrative retained deliberately, see §2 above.
- VT missing-file `os.path.exists` rule (362–363) — verified TODO.md pointer accurate.
- Chapter-slider-flash guard, `show_metadata=False`, native-chapter-nav ban, `_on_chapter_change`
  suppression, `_virtual_timeline`-for-CUE ban, `Player.terminate()` sequencing, checkpoint-unlink
  ordering, `session_recorder.close()` ordering (365–405) — each a specific, still-plausible
  invariant tied to a named method.
- Soft-delete-flags section in full (409–428), including all five numbered consequences.
- Metadata-preservation guards (432–439) — tight, test-pinned, no narrative fat.
- `book_events`/`listening_sessions` join rule, `books.finished_at` rule (455–459).
- `get_streaks()`/`StreakGrid` shared day-set invariant (463–469).
- `_pending_fade_call` stash-tuple rule's generalization (505–528, modulo the stale citation at
  §4c) — genuinely forward-looking.
- Panel-animation-wait/blur rule (530–563) — two non-obvious Qt facts stated tightly.
- Panel-dismiss-snapback ordering rule (594–613) — verified live against code, load-bearing
  precisely because nothing else enforces it.
- `_NO_BASE_INHERIT_KEYS` rule (725–744) — concrete, forward-looking, correctly cross-referenced
  by TODO.md.
- The six StreakGrid/HourlyHeatmap/TasselOverlay animation rules (746–826) — each a distinct,
  non-obvious gotcha, no redundancy between them.
- The six library-panel geometry/behavior rules (828–868) — tight, each testable, each with a real
  bug behind it.
- `_sized_cover_cache`/`_get_sized_cover` (872–889) — explicitly justified as load-bearing with a
  measured before/after; the three worker-thread invariants would silently regress if stated only
  informally.
- `is_overlay_open_or_committed()` gate (893–895) — concise, test-pinned.
- `get_book_count()` vs `get_visible_book_count()` (427–428).
- The keyboard-focus-ownership section's CORE invariant and mechanism bullets (919–948, 954–992,
  998–1011) — narrative clauses compress (§2), but the mechanism description itself (five distinct
  sub-rules: ownership, the hide()-before-clearFocus() gotcha, the NoFocus-sweep dependency, the
  widget-deletion generalization, the modal-dialog exception) is each independently load-bearing.
- DragSafeLineEdit's distance+dwell mechanism (1022–1026), specifically "both conditions required,
  distance alone was insufficient" — forecloses a plausible-looking simpler reimplementation.
- `beginResetModel()`/`finally`-guaranteed `endResetModel()` rule (1049–1057) — no narrative fat
  anywhere in it, even the incident reference is a single clause.

**Lines 1061–1386 ("Tech Stack" through "Stylesheet Architecture"):**
- Both Stylesheet Architecture rules (1375–1377, 1379–1381) — clean, mechanism-only Qt gotchas,
  no dates, no incident narrative.
- The "What's Built" reference sections as a whole (Player through Logging, ~1095–1282, plus the
  file tree and stylesheet table) — this is the file doing its own documented job ("what has been
  built... where are we now"), and aside from the two narrative asides flagged in §2 and the
  staleness findings in §4, this content is appropriately dense-but-not-bloated for a factual
  reference. Explicitly not a target for a future trim pass.

---

## Escalated / needs a decision (per task instructions, not resolved here)

**Both items below have since been resolved independently, by direct edits to CLAUDE.md outside
this report's own action pass.** Left in place as a record of what was originally escalated and
how it closed.

1. **SUPERSEDED §1b (line 479) — ✅ Resolved independently.** The hover-preview cost figure was
   contradicted by a same-day code change with no corresponding doc update found at the time this
   was written. CLAUDE.md's text has since been rewritten with a proper panel-open-state-dependent
   breakdown (~430-440ms with no panel/Themes-tab open vs ~590-620ms while open, re-measured
   2026-08-02), replacing the flat "~215ms" claim this finding was about. Confirmed via direct read
   of the current file — the stale claim is gone.
2. **SUPERSEDED §1c (line 1874) — ✅ Resolved independently.** Confirmed genuine (theme keys don't
   exist in current `themes.py`). Rather than being rewritten, the old changelog entry at line 1874
   now carries an inline correction note (visible at CLAUDE.md ~1797-1798) pointing out the old key
   names were replaced 2026-06-18, referencing the entry that supersedes it — preserving the
   original entry's text (per the file's "correct, don't silently delete" convention already
   established elsewhere in this document) while making the contradiction visible to a reader
   instead of leaving it silent.

(A third item, "two divergent DEBT_INVENTORY.md files," was listed here in the first draft and
has been retracted — see §5's correction note. `review/Snapshot_260612_debt_inventory.md`
self-declares as a frozen 2026-06-12 snapshot and names the root file as the live index; there was
nothing to decide. The file has since also been renamed away from `DEBT_INVENTORY.md` to
`Snapshot_260612_debt_inventory.md` specifically to prevent the name collision that caused this
mis-finding in the first place, per a separate `review/` naming-convention pass — see
`review/README.md`.)

---

## Follow-up: `352b72f` branch-history gap (identified during the action pass, not part of the
original audit)

While re-verifying STALE §4e, discovered that commit `352b72f3dcdb35f3b2416da33bc5fe0f848a51b6`
is real, content-accurate, and visible in `git reflog --all` as having once been on `main`
(`refs/heads/main@{214}`), but is **not reachable from current `main`**
(`git merge-base --is-ancestor 352b72f HEAD` → false). This means some history-rewriting operation
(rebase, reset, or force-push) removed it — and potentially other commits — from `main`'s
reachable history after it landed. This is unrelated to CLAUDE.md's content and is tracked here
only as a pointer; investigating it is a separate task from this document audit.
