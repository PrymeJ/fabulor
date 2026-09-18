# Fabulor — Claude Context

## What this file is for

This is a reference document for Claude and Claude Code. It records **what has been built**, key
architectural decisions, and current state — it is the single authoritative source for the
architecture rules and project state. (GEMINI.md was removed 2026-06-12 when Gemini left the
workflow; do not reference it.) This file answers "where are we now?"

---

## Do not comment on the time or suggest stopping

Never say the hour is late, suggest wrapping up, or frame a suggestion as "you should probably
rest" / "we can pick this up later" / anything with that parenting undertone — this includes
implying it indirectly, not just saying it outright. Pryme decides when a session ends, not
Claude.

The one exception: if the NEXT task is genuinely large enough that it would reasonably deserve its
own session (not a vague sense that it's getting late), it's fine to note that gently, as
information, not as a decision made on Pryme's behalf. E.g. "this next piece is a big one — worth
knowing that going in" is fine; "I'm not doing this now" or "let's stop here" is not. State it and
let Pryme decide what to do with that information; do not decide for them.

**Context exhaustion is the one thing you MUST raise, and you must name it plainly.** When the
context window is filling and answers are starting to drift, say exactly that — "I'm drifting from
context exhaustion; want me to write a handoff and continue in a fresh window?" — and offer the
handoff. This is not the same as suggesting Pryme stop working: the session continues in a new
window, and it is information only Claude has.

Do NOT dress it up as anything else. The failure mode this exists to prevent (2026-07-28): with the
window near full, Claude proposed ending the session citing its own error rate — "I've been wrong
repeatedly, I don't think I should keep going tonight" — when the actual reason was context. Pryme's
response: *"You are wrong multiple times every day, you find your way after many tries... None of
those are blockers. I am used to it. Just be honest though."* Being repeatedly wrong is normal and
expected here; it is never a reason to stop. Context exhaustion is, and it is the honest one.

---

## Never substitute a plausible explanation for a checked one

When something needs explaining — a symptom, a contradiction, your own behaviour — say what you
actually know and mark the rest as unverified. Do not reach for the explanation that sounds
reasonable and move on as though it were established.

Three instances in one evening (2026-07-28), all corrected by Pryme rather than caught by Claude:

- Log lines showed `Fabulor started` mid-test; Claude attributed them to its own file edits
  triggering `entr`, twice, when Pryme was restarting the app deliberately. The explanation
  dismissed the user's report instead of asking what he had done.
- A grep filtered out the sidebar's closing toggles; Claude reported "three consecutive opens with
  no close between" and called the state machine incoherent. Pryme refused it — *"There is no such
  thing as opening an open sidebar again"* — and was right. The incoherence was in the analysis.
- Asked to explain a sidebar failure, Claude asked Pryme to re-describe what "opens" looks like,
  which he had already stated plainly. That was stalling dressed as diligence.

The check is cheap: before offering an explanation, ask whether you verified it or merely
constructed it. If constructed, say so in the same sentence. "I don't know yet" is a complete and
acceptable answer; a confident wrong one costs a round of Pryme's testing time.

### A report about what Pryme DID is data, not a competing theory — the next action is a lookup, not a restatement

A wrong theory that gets checked against evidence and dropped is working as intended; that is how
the correct one gets bought. The failure mode is narrower and worth naming exactly: **inferring that
an action occurred because a data structure implies it should have, then defending the inference
when Pryme says it didn't happen.**

2026-07-30, the phantom-filter hunt: a stale `pending_field_filter` target held
`('narrator', 'Colin Mace')`. Claude wrote "at some earlier point you left-clicked Colin Mace"
— reasoning backwards from the target's existence to the click that normally creates it. Pryme had
already said thrice, across the session, that he never clicks author/narrator/year fields. The
arming event was **two greps away** in a log already open, and said `button=2` — a *right*-click,
which armed the target through a code path that checked event type but never button. The narrative
was coherent and wrong; the log was one query away and right.

The distinction that matters: Pryme reporting *what he did* or *what he sees* is an observation
about the system's real input, not a hypothesis to be weighed against Claude's. Weighing it as a
hypothesis is a category error — the same one the "user sees the rendered pixels" rule covers for
visual matters, generalized to actions. So:

- When a report contradicts an inference, **the inference is the suspect.** Go find the evidence
  that would settle it before restating the claim even once more.
- Do not ask Pryme to re-describe what he already stated plainly. That is stalling dressed as
  diligence (see the sidebar instance above).
- Not the same as accepting everything uncritically — Pryme has said so directly. Check the claim
  against evidence; just check it *instead of* arguing, and treat "I didn't do that" as pointing at
  where to look, not as something to overcome.

A related trap from the same session: a claim was correctly made ("the DB accepted the bad year"),
then **wrongly retracted** on the basis of a query run *after* Pryme had manually deleted the row.
Absence-after-cleanup is not evidence about the original write. Before retracting, confirm the new
evidence actually bears on the original claim.

---

## Design and test against library sizes an order of magnitude beyond what's on hand

The real library used for day-to-day testing has been ~400 books. That is not representative of what the app needs to handle. Any design assumption, performance claim, or "this is fine" conclusion about scan cost, startup cost, library-panel rendering, cover caching, or anything else that scales with book count must be checked against a library an order of magnitude larger than whatever is actually on hand at the time (e.g. if real data tops out around 400-3000, test synthetic data at 3000-5000+), not just validated against whatever happens to be installed. A cost that's invisible at hundreds of books can be a real, user-facing problem at thousands — don't assume linear scaling without checking, and don't let "it's fine on my machine" stand in for "it's fine at scale."

---

## Debugging discipline

- **Colour widgets first** when a bug is about which widget owns which pixel — faster than positional theories.
- **Change-only probes can't prove absence.** Log stationary state too, not just transitions.
- **Verify the app restarted** before trusting a log (`entr` can silently miss edits). Before trusting a capture, confirm
  the running binary/process postdates the code change.
- **A branch switch that resets the working tree to an older branch's files is not data loss** — it
  only changes which branch's files sit on disk right now. Before saying or implying anything is
  gone, run `git branch --show-current` and `git log --oneline`/`git reflog` and report what they
  actually show. If a task requires branching off `main` while unrelated work sits ahead on another
  branch (e.g. `git checkout main -- .` to reset the tree before creating a fresh investigation
  branch), say so plainly before doing it — the app will look and behave like the older branch until
  switched back, and that is expected, not a symptom of anything broken. (2026-08-05: this exact
  sequence briefly read as "30+ commits gone" mid-session; nothing was lost, confirmed via reflog —
  see SESSION.md.)
- **Single-point checks aren't a survey.** Sample edges/full area, not one representative point.
- **`window().cursor()` does not tell you what's displayed.** It returns the
  top-level widget's own cursor property, not the platform's actual visible cursor
  state. Don't use it as a proxy for "what does the user currently see."
- **Qt's `QRect.right()`/`.bottom()` are inclusive (last pixel), not the true edge** — documented historical quirk, not a bug. Use `x()+width()`/`y()+height()`. Suspect first for any single-pixel boundary hit-test mismatch.
- **A 1px antialiased stroke on an INTEGER coordinate straddles two pixel lines at ~50% each; on a
  half-integer it fills one crisply** (measured 2026-09-05: `#7f7f7f`/`#808080` vs. one `#ffffff`
  row). Qt puts pixel centres at half-integers, so a hand-drawn 1px outline wants `+0.5`. Invisible
  on short/diagonal runs, unmissable on a long axis-aligned one — it presents as a horizontal line
  "slanting" at its ends, not as blur. Combined with the `QRect` rule above, the same half-pixel
  inset is also what pulls a right/bottom stroke back ONTO the widget.
- **A QSS ID selector (`#name`) outranks a plain type selector (`QPushButton:hover`), so a widget
  with an `#id` background rule silently has NO hover** unless given its own ID-level `:hover`.
  Found 2026-09-05 on `#reset_audio_btn`, which had never responded to the mouse; `#disable_sleep_btn`
  still has the same gap. Suspect this whenever a styled-by-id control ignores a generically
  defined state rule.
- **A mouse click on a QTabBar tab arrives as `TabFocusReason`, not `MouseFocusReason`** (measured
  2026-09-03) — the reason describes focus moving *to a tab*, not the Tab key. `OtherFocusReason` is
  no better: it covers both a tab click AND the legitimate keyboard hop where Tab lands on the tab
  bar and Qt forwards focus onward ~2ms later. **No `QFocusEvent.reason()` value reliably means
  "the user is on the mouse."** Record modality from the actual `MouseButtonPress`/`KeyPress`
  instead — same shape as the `user_seek_pending`/`sleep_fired` rule: a flag set where intent is
  known beats anything inferred downstream. Two successive fixes here were defeated by trusting a
  reason (see `_set_keyboard_nav_active`'s MODALITY OWNERSHIP notes, app.py).
- **`QAbstractButton::mouseReleaseEvent` repaints the button back to enabled/hover-visible BEFORE
  it emits `clicked()`, not after.** Confirmed via a live paint-event trace with timestamps, not
  assumed — a flash frame painted 0.3ms before a `setEnabled(False)` placed at the very top of the
  `clicked` slot could run. Nothing reachable from inside a `clicked` slot (disabling, hiding,
  reordering statements) can suppress that specific repaint; disabling any EARLIER than release
  (e.g. on `pressed`) instead kills `clicked()` outright, since Qt gates it on `isEnabled()` at
  release time. If a button's own native release-repaint is the thing that needs suppressing —
  not just something to react to afterward — it needs an opaque overlay painted over the button
  itself (with its own full press/drag-off/release state tracking), not a `clicked`-slot fix. See
  NOTES.md, 2026-09-10 (Sleep/Sprint Disable-Cancel button blink — three fix attempts, all reverted).
- **`unpolish`/`polish` on a parent does NOT re-resolve a child's cached style.** A dynamic
  property gating QSS on an ancestor (e.g. `#settings_panel[kbdnav="true"] ... :hover`) will not
  take effect on descendants until each one is polished itself — and `update()` alone is not
  enough. Found twice in one session, separately, on `QTabBar` (whose `::tab` sub-controls cache
  their own hover state) and then on the buttons underneath it (2026-09-04). If a property-gated
  rule "isn't applying" while the property and flag both verify correct, this is the cause.
  **Recurred 2026-09-08** in a NEWER, more general repolish helper (`app.py`'s
  `_set_kbdnav_property`, added after the above finding) that walked only `QPushButton` children
  and never got the tab-bar-specific repolish call the original fix required — surfaced as an
  intermittent bug (worked only when an unrelated theme switch happened to also repolish the tab
  bar) rather than a consistent failure, which is a harder signature to recognize as this same
  cause. Any new helper that repolishes a `#settings_panel`-rooted subtree needs the SAME explicit
  `tabs.tabBar()` unpolish/polish call this rule already documents — do not assume a
  `findChildren(QPushButton)`-style loop covers it.
- **Constraining a lone stretch participant's height moves the whole block.** In a `QVBoxLayout`
  with one `stretch=1` member, that member absorbs all leftover height. `setFixedHeight` or
  `setMaximumHeight` on it withdraws it from the stretch and the layout redistributes the freed
  pixels *around* the block — content drifts down from the top. Pair any such cap with an explicit
  `addStretch()` where the slack should go. Both variants were tried and reverted before this was
  understood (2026-08-01, Stats rows viewport).
- **Pre-screen visual changes before handing them over — but never in place of Pryme's eyes.** Two
  things are sound and were wrongly talked out of once (2026-08-01): reading geometry off the
  RUNNING app (`tools/tags_geometry_probe.py` — open the panel through its real flow, print what Qt
  allocated), and diffing screenshots of the real app numerically (`PIL.ImageChops.difference` for
  "did anything move", scanning for row boundaries for "is the pitch still N"). Both are arithmetic
  on real composited output. What is NOT sound is an offscreen *reconstruction* of a layout — that
  is a different render and has returned confidently wrong numbers here. Don't collapse the two into
  "I can't measure this panel." Pre-screening catches the obviously-broken version; whether it LOOKS
  right is still Pryme's call, every time.
- **If two code paths must agree on a measurement, make one of them call the other.** Text elided to
  one width and painted into another differs silently — it just looks like the font is wrong, or
  like a stray clip. `ChapterItemDelegate.paint` and `ChapterList.populate` each derived the title's
  width from raw margins and disagreed by 9-10px for a long time; both now call
  `_title_draw_width()` (2026-08-01). Same shape as the `_row_content_width`/`_list_author_layout`
  rules for the library rows.
- **A test that shares the code's assumption cannot falsify it.** Derive the check independently of
  the thing being checked. A probe written as `viewport % pitch == 0` encoded the same off-by-one as
  the code (N rows have N−1 gaps, not N) and so reported a perfect fit on a viewport 5px too tall,
  with rows visibly clipped in the app (2026-08-01, Tags list).
- **A rationale you inferred is not a rationale that was recorded.** Before treating a documented
  constraint as load-bearing, check whether it traces to a real decision — `git log -S` the line
  and read the commit that introduced it. Twice now a plausible explanation written into the docs
  was later cited as established fact and constrained real work: the Stats 2px inset (2026-08-01)
  was documented as scroll-step alignment, was actually a leftover from a cosmetic margin pass, and
  described a mechanism (`setSingleStep`) the file never calls.
- **Report timings in CHRONOLOGICAL order, and only sort once you know the samples are
  interchangeable.** Sorting to take a median is correct for i.i.d. samples and actively destroys
  the evidence otherwise — any time the FIRST sample may differ in kind (cold cache, first call in
  a process, first paint, an empty cache being filled), sorting hides exactly the structure you
  need. Two distinct instances in one night (2026-08-02): a sorted median reported an empty-sheet
  restyle at 8.2ms when four of five iterations were no-ops and the lone real measurement was the
  "outlier" at 723ms; and a sorted clear-cost table hid a clean monotonic decay
  (667→583→550→533→536→535) that immediately identified a first-call-in-process effect. Print the
  sequence, look at it, THEN aggregate. Related to the change-only-probe rule above — both are
  cases of an aggregate concealing a state the probe never separated.
- **Measure an existing guard's hit rate before proposing a new one.** Adding a redundant-work guard
  is only worth it if the redundancy is actually frequent, and the codebase may already be catching
  it. Instrument what is there first: a proposed no-op guard on the root restyle (2026-08-02) was
  written up as the "only surviving option" before anyone counted, and counting killed it — the
  proposed sites fired 1 and 4 times in a real session while the EXISTING no-op guard in
  `_on_theme_changed` had silently caught 44 of 120 calls at zero cost. Nobody had that number until
  it was asked for. Hit-rate counters on existing guards are cheap and turn "this seems redundant"
  into a decision.
- **An offscreen harness reads ~25% HIGH for widget-tree/restyle timings on this app** (quantified
  2026-08-02: `mw.setStyleSheet` medians ~535-580ms offscreen vs **436ms** live over 120 real
  samples). Offscreen results remain useful for RATIOS between conditions — that is what killed
  three separate restyle fix proposals — but never quote an offscreen number as the live cost, and
  label every offscreen figure as such at the point it is written down, not once in a caveat further
  up the page.
- **An offscreen harness can also be blind to correctness, not just biased on timing — those are two
  separate risks.** The rule above is about MAGNITUDE (offscreen numbers read high). A different
  failure showed up 2026-07-27 chasing a `visual_area` blur-clip bug: an offscreen harness returned
  byte-identical output for a bug that was plainly visible live — it could not see the
  compositing/paint-order defect at all, not just mismeasure its cost. Do not treat "offscreen
  matches" as evidence a paint/compositing bug is fixed; only a live check settles that class of
  claim. Also from that investigation: take the reported symptom literally rather than reinterpreting
  it to fit the current theory (the actual word "thicker" ruled out every reveal-based explanation a
  theory-first read would have kept alive), and verify the baseline before attributing a symptom to
  your own change — three unrelated pre-existing bugs were found this way (a 10-day-old regression,
  ghost transport buttons, non-blurring carousel thumbnails) that a "must be my change" assumption
  would have missed.
- **Establish a scope by diffing actual output against a baseline, not by reading call sites.**
  Scoping the 2026-08-02 panel-backdrop-alpha restyle fix by reading which widgets *look* like they
  read `panel_opacity_hover` would have missed two real cases: the override reaches
  library/stats/tags/sidebar too (it flows through `_resolve_theme`, not a hardcoded list), and
  `get_tags_stylesheet` was never even imported at the call site that was meant to invoke it. Diffing
  every `get_*_stylesheet`'s actual output with the override at `None` vs. its real value caught both;
  reading the call sites would not have.
- **Before spending effort on a new fix, check whether an existing measurement harness can just
  falsify the plausible-sounding claim behind it.** Three separate 2026-07-28 theme-hover fix
  proposals were killed this way, each in minutes, by pointing an already-built measurement harness
  at the specific claim motivating it ("a blur tween can't hitch a restyle," "a hover restyle is
  cheaper," "the hitch would be hidden") rather than trusting the claim and building the fix first.
  All three would otherwise have shipped.

---

## Running the app (Claude Code / Bash tool)

## TEMPORARY: fabulorenv Python is conda-shadowed (2026-07-30)

`fabulorenv/bin/python` symlinks into miniconda (`/home/pryme/miniconda3/bin/python`),
so conda's `libstdc++.so.6` shadows the system one. Without a workaround:
- `pytest` fails collection on 7 files
- `python main.py` won't start at all — `GLIBCXX_3.4.35 not found (required by
  /lib64/libopenal.so.1)`

The documented `source fabulorenv/bin/activate && python main.py` does NOT
currently work on its own. Workaround until the venv is rebuilt cleanly — the venv
must be activated FIRST in both cases (its `LD_LIBRARY_PATH` shim, see "Running the
app" below, is what resolves `libcaca.so.0`'s `_nc_curscr` symbol; `LD_PRELOAD`
alone does not — a bare `LD_PRELOAD=... pytest` in an unactivated shell fails on
that unrelated symbol instead of the GLIBCXX error this section is about):

    source fabulorenv/bin/activate && LD_PRELOAD=/usr/lib64/libstdc++.so.6 python main.py
    source fabulorenv/bin/activate && LD_PRELOAD=/usr/lib64/libstdc++.so.6 pytest tests/ -q

Root fix (not yet done): rebuild fabulorenv without a conda-symlinked
interpreter, or pin an explicit libstdc++ resolution in the venv activation
script so this stops requiring a manual prefix every session.

## END OF TEMPORARY


**Always activate the venv before running** — do not invoke `fabulorenv/bin/python` directly:

```bash
source fabulorenv/bin/activate && python main.py
```

Activation sets `LD_LIBRARY_PATH=/home/pryme/Coding/Python/fabulor/fabulorenv/lib/stub`, which
contains a `libcaca.so.0` shim that resolves a symbol-version conflict
(`_nc_curscr@NCURSES6_TINFO_5.7.20081102`) between the system's `libcaca` package and its
`libncursesw`/`libtinfo` packages — confirmed via `objdump -T` to be a genuine broken system
package mismatch (`libncursesw.so.6` imports `_nc_curscr` but `libtinfow.so.6` doesn't export it;
only the non-wide `libtinfo.so.6` does). Without the venv's `LD_LIBRARY_PATH`, `import mpv` raises
`OSError: .../libcaca.so.0: undefined symbol: _nc_curscr, version NCURSES6_TINFO_5.7.20081102`,
which `player.py`'s top-level `try/except` masks behind a generic "❌ libmpv not found" message —
so the real cause looks like a missing-library problem when it is actually an `LD_LIBRARY_PATH`
problem. Setting `LD_LIBRARY_PATH` to other values (e.g. `/usr/lib64`, or PySide6's bundled Qt lib
dir) does not fix this and can break Qt loading instead — the venv's `lib/stub` shim is the only
known-working path. This is unrelated to the MPV-init rule below; do not conflate the two.

To launch the app in the background and capture output without leaving stray processes:
```bash
source fabulorenv/bin/activate
python main.py > /tmp/fabulor_run.log 2>&1 &
# ... test, then:
kill %1   # or: pkill -f "python main.py" — but check `ps aux` first if an `entr` dev-loop is also running
```

---

## Critical Architecture Rules

These rules exist because violating them caused real bugs. The reasoning is documented in
SESSION.md. They are not arbitrary constraints — they are load-bearing until proven otherwise
in a specific context.

If you believe the cleanest solution requires crossing one of them, stop and explain why before
proceeding. Don't route around them silently. The bar for crossing one is: you've identified a
specific reason the rule doesn't apply in this case, not just that it would be simpler to ignore it.

This section was reorganized 2026-07-13 to group rules that share one underlying fact under a
single statement of that fact, instead of re-explaining the same fact in each rule's own
paragraph. No rule, constant, date, commit hash, or piece of reasoning was removed in that pass —
only repeated explanations were consolidated. A rule with multiple consequences lists them as
bullets beneath the shared fact.

A second consolidation pass ran 2026-08-13 (`3ffa8f3`, `1957430`, `9d54592`), same method and same
non-destructive constraint: seven headings became two shared-fact sections — the Themes tab's hover
machinery vs. the blur grab's synthetic events (four consequences) and keyboard focus ownership
(five consequences) — and five rules had investigation narrative trimmed to the mechanism, the fix,
and the generalization, with the trail cited to NOTES.md rather than retold. Every measurement,
constant, commit hash, pinned test, probe contract and design-doc pointer was verified still
present by grep afterward.

**Two corrections that pass made, both of which would have caused a wrong action if left:**
(1) the `[SWATCH-LEAVE-SUSPECT]` probe was documented — here and in `theme_manager.py` — as
`grep -c` **must be 0**, on a premise that was falsified live on 2026-08-03 and answered by
`17d46e2` upgrading the branch from detect-only to detect-and-correct; a non-zero count is now
expected and handled, so the old contract would have read normal operation as a premise violation.
(2) The hover-preview rule carried two generations of measurement for the same cost, 2026-08-01 and
2026-08-02, with only reading order to say which was current; the superseded figures are gone.

Net line change across the pass was roughly zero. That is the honest result and worth recording:
these clusters overlapped in **cross-references** (each rule re-deriving its relationship to its
siblings) far more than in restated mechanism, and stating a relationship once, explicitly, costs
about what removing the scattered restatements saves. The gain is single-sourcing — one home per
fact, one heading per causal root — not size. A future density pass should expect the same and
judge itself on duplication removed, not lines saved.

---

### The user sees the rendered pixels. You do not. When they say something is visually off, that is ground truth — your calculation is what's wrong.
On any visual/layout/pixel matter, the user's eyes are authoritative and your arithmetic is not.
When a live observation (a screenshot, a measurement like "W: 282", "it's 4px off", "move it right")
disagrees with your computed values, **the computation is the suspect, not the observation.** Do NOT
re-derive, re-measure with a script, or re-question the user to defend your numbers — offscreen
harnesses use default styles/sizes and silently diverge from the real rendered app (e.g. the
scrollbar is 8px via QSS, not the 14px Qt default; assumed widths are wrong). When the user says
"nudge it Npx" or "it ends here," just make that change and let them verify live. Asking them to
reconcile your math against what they can plainly see is not rigor — it wastes their time and
erodes trust. Take the visual correction at face value, apply it, move on. (Added 2026-07-06 after
exactly this failure: clinging to a wrong SCROLLBAR_EXTENT/window-width calculation and repeatedly
questioning the user instead of applying a simple 4px nudge they'd already measured and mocked up.)

Four later rules are direct consequences of this same lesson, each applied to a widget class or Qt
API where a plausible-looking computed/headless result kept diverging from what the live app
actually showed — see, further below: "DO NOT verify a settings-panel/tab visual layout bug with
headless test scripts alone"; "DO NOT trust `QComboBox` popup pseudo-state QSS ... on this app's
target desktop"; "DO NOT rely on `WA_PaintUnclipped` ... and DO NOT pin a widget's width with
`setFixedWidth` inside a `QGridLayout`/stretch column" (a live geometry probe reports the intended
geometry for a child that is in fact being clipped — only a screenshot catches it); and "DO NOT
assume a text label's horizontal position is 'the box's position' without checking its alignment"
(a single test string can hide the bug entirely).

---

### When the user says a specific claim is wrong, retract it explicitly before doing anything else — restate the new belief AND name what it invalidates.
"You're right" is not itself a retraction. Saying it and then moving straight to the next diagnostic
step, while quietly still treating the corrected claim as true in later reasoning, is worse than
never having said it — it reads as agreement while nothing actually changed. The required pattern
when the user flags a claim (a conclusion, a "this data is clean," a "the grab looks fine") as
wrong: (1) state plainly what you now believe instead, (2) name the specific prior claim it
replaces, (3) check every subsequent step or conclusion already taken that depended on the
now-dead claim, and flag which of those are also now unsupported — don't let them silently survive
into the next round of reasoning. If you can't tell whether a downstream step depended on the
retracted claim, say so and check before reusing that step's output.

This mirrors the rule above (the user's eyes are ground truth on rendered pixels) but is broader:
this rule applies to any factual/diagnostic claim the user corrects — not just visual layout — and
specifically targets the failure mode where "you're right" gets said but the retraction never
actually propagates. (Added 2026-07-19 after exactly this failure during the transport-bar blur
investigation: a raw-grab screenshot was called "completely fine, no corruption" — the user
immediately said the grab was wrong, evidence right in front of both of us. "You're right" was
said, but three more diagnostic rounds — an alpha-padding fix, a bounding-rect-size test, a
dirty-tracking-disabled test — were then built on top of the same unretracted "grab is clean"
premise, producing a conclusion of "clean in isolated testing, broken live — unexplained" that was
actually just the original wrong claim never having been corrected.)

---

### DO NOT modify, refactor, or touch any code related to MPV initialization under any circumstances.
This includes the `_ensure_mpv()` method, the `load_book()` method's MPV init block, the
`locale.setlocale(locale.LC_NUMERIC, "C")` call, and all MPV constructor arguments (`vo`, `ao`,
`vid`, `ytdl`, `keep_open`, `audio_client_name`). This code resolves a hard-won, non-obvious bug
involving libcaca, libtinfo, and Qt's locale reset on Wayland/openSUSE. Any "improvement,"
"cleanup," or "fix" to this block will break the app. If you think something in this block needs
changing, say so explicitly and wait for confirmation before touching it.

`audio_client_name='fabulor'` (added 2026-06-26) sets mpv's `--audio-client-name`, which maps to the PulseAudio/PipeWire sink-input `application.name` property. Without it, mpv's `ao='pulse'` stream gets an unstable name (`mpv` or PID-derived), so `module-stream-restore` can't reliably remember a per-app volume across launches — symptom: openSUSE/PulseAudio resets the app's OS-level volume to some stale value (e.g. 5%) on every load, independent of the in-app volume which is correctly persisted. This does NOT fix an already-poisoned stream-restore entry — that must be cleared once via `pavucontrol` or the PipeWire/Pulse stream-restore DB; this just makes the restore key stable going forward.

### DO NOT use `self.player.chapter` to derive which chapter the UI should display
It looks like the obvious choice but it is wrong — mpv updates the chapter property asynchronously and it will be ahead of or behind time_pos after any seek. Always derive the current chapter by walking `self.player.chapter_list` and finding the last entry whose `time <= pos + _CHAPTER_WALK_TOLERANCE`. As of Session 3 (2026-06-13) that tolerance is 0.5 (was 0.35); it must exceed mpv's measured ~0.37s PAUSED-seek undershoot, else a paused Next/Prev resolves the chapter just left and the chapter slider sticks. (The old "~0.25s short of nominal" rationale was disproven by measurement: mpv overshoots ~0.09s while playing and undershoots ~0.37s while paused.) This rule applies everywhere in `_sync_chapter_ui` and any future method that maps a playback position to a chapter index. **Confirmed violated a third time, 2026-09-16: `Player.apply_smart_rewind`'s chapter-boundary clamp read `self.chapter` (native mpv property for non-VT, tolerance-less walk for VT) instead of the standard `chapter_list` + `_CHAPTER_WALK_TOLERANCE` walk every other chapter-position site uses** — harmless most of the time since the clamp only matters near a boundary, but exactly the class of position this rule is about. Fixed to walk `chapter_list` like `previous_chapter`/`next_chapter`/`activate_chapter_index`/`seek_within_chapter` all already do. See `tests/test_smart_rewind.py` for the regression net (a fake mpv `instance` drives `apply_smart_rewind` directly, no QApplication).

### Smart rewind must be reset per book, not carried across a book switch
`Player.apply_smart_rewind` needs a pause timestamp (`MainWindow._last_pause_timestamp`) to know how long playback sat paused. That timestamp lives on `MainWindow`, not `Player`, so `Player.load_book`'s per-book state reset (VT/chapter/seek fields — see its own block of `self._foo = None` assignments) never touches it. Found live 2026-09-16: pausing one book long enough to arm the wait threshold, then switching to a DIFFERENT book before resuming, applied the rewind to the new book's first resume — rewinding by an amount computed from the old book's pause duration, against the new book's (unrelated) chapter boundaries. Fixed by clearing `_last_pause_timestamp = None` at every point that tears down or replaces the current book: `_on_book_selected_from_library` (book switch), the EOF-restart branch of `toggle_play_pause` (reloads the same book at position 0 — a stale timestamp from an earlier pause/resume cycle must not apply to the fresh restart either), and `_on_book_removed` (defensive — the book the pause was armed against no longer exists). The existing clear on a *consumed* rewind (`toggle_play_pause`'s resume branch, `_last_pause_timestamp = None` after `apply_smart_rewind` returns `True`) was already correct and is unchanged; the gap was every *other* path that ends a book's lifecycle without ever consuming the pending rewind. **Both this fix and the chapter-confinement fix above were live-verified 2026-09-16**: no cross-book leak, and a same-book rewind near a chapter start now correctly clamps to that chapter's own 0:00 instead of drifting into the previous chapter.

**Known, separate, pre-existing issue surfaced during this live testing — not a smart-rewind bug, nothing actioned:** landing exactly at a chapter's nominal start (whether via smart rewind's clamp, or via the `|<`/Prev button, which lands on the same boundary through `_chapter_seek_offset()`) can clip the first fraction of a second of narration (e.g. "apter two" instead of "Chapter two"). Reproduces identically via Prev with smart rewind never in the picture, so it belongs to the existing mpv seek-landing drift the `_CHAPTER_WALK_TOLERANCE`/`_EMBEDDED_CHAPTER_SEEK_OFFSET`/`_PAUSED_SEEK_UNDERSHOOT_COMP`/`_CHAPTER_BOUNDARY_EPSILON` constants already compensate for (see the "Chapter-seek constants" section under Player — playback behaviors), not to the chapter-confinement logic added here. No further action taken. **Filed under TODO.md's "Seek-landing precision at chapter boundaries" group** (a dedicated summary-index heading, added 2026-09-16 specifically to collect this sighting alongside every other scattered symptom of the same underlying mpv imprecision — the elapsed-label offset, the load-time retrace, the backward-seek flicker, the notch-click residual clip, and the canonical `_PAUSED_SEEK_UNDERSHOOT_COMP` entry with its reverted 2026-07-14 fix attempt). Also see `SEEK_CONSTANTS.md` for the constant-interaction map. Pryme's own decision: pick this whole cluster up as one dedicated investigation, not fixed symptom-by-symptom — do not start a narrow fix for just this sighting.

### Undo must anchor to a seek spree's start, not to whichever seek happens to individually qualify
Reported live 2026-09-16, separate from smart rewind: sitting in a short (e.g. 40s) chapter, pressing Next repeatedly through several chapters (some short, some long), then Undo, landed on the first LONG chapter's start rather than the position before the short chapter was ever left.

Root cause: every seek-driven call site (`handle_next`/`handle_prev`, chapter-list click, slider release/right-click, chapter-slider release) gated its OWN call to `Player.save_seek_position` on whether THAT SINGLE seek's displacement exceeded a threshold (`60 * speed` seconds — the "don't bother showing undo for a trivial skip" heuristic). A spree of small seeks — e.g. Next through a 40s chapter, whose own displacement never crosses 60s — could clear the threshold in aggregate while no single press ever qualified individually. Because the gate lived at the CALLER and skipped calling `save_seek_position` entirely when it failed, the coalescing anchor (`_undo_pos`) was never captured on the first (non-qualifying) press. Whichever LATER press finally cleared 60s then captured ITS OWN `old_pos` as the anchor — a mid-spree position (the start of the first *long* chapter), not the position before the spree began (the start of the short chapter). `save_seek_position`'s own coalescing window (repeated close-together calls keep the *first* `old_pos`, only resetting once `duration_limit` elapses with no activity) was correct and untouched — the bug was that the gate upstream of it sometimes prevented it from ever being called at all.

Fixed by moving the distance decision INTO `save_seek_position` itself (`player.py`), which is the only place with access to the already-coalesced anchor: `save_seek_position(old_pos, new_pos, duration_limit, threshold)` now captures the anchor UNCONDITIONALLY on every call within a live coalescing spree (whether or not `threshold` is cleared), and only the return value (whether to show the overlay) is gated on `abs(new_pos - _undo_pos) > threshold` — CUMULATIVE distance from the live anchor, never the single call's own displacement. Every call site in `app.py` now calls `MainWindow._trigger_undo(old_pos, new_pos, threshold=...)` unconditionally (no caller-side distance gate) — `_trigger_undo` defaults `threshold` to `60 * speed`, the standard gate. **Silently arming `_undo_pos` without showing the overlay is safe**: `undo_seek()` is reachable only via the overlay button or the `u` shortcut (itself gated on `undo_overlay.isVisible()` — see `_undo_shortcut`), both of which require the overlay to have actually shown at some point, so a quietly-armed anchor can never be acted on before it either graduates to a shown overlay or the coalescing window (default 3s) expires and resets. See `tests/test_undo_position.py` for the regression net (pure logic, no mpv/QApplication). **Live-verified 2026-09-16**: Next through a short chapter into a longer one, then Undo, correctly returns to the position before the spree began.

**Correction, same day:** the paragraph above originally claimed the long-skip buttons, `|<`-to-restart, and the chapter-slider wheel "never had a distance gate before and must not gain one" (`threshold=0.0` at those three sites). That claim did not survive contact with further live testing and has been retracted, not left standing — see the two rules directly below for what actually shipped and why the original claim was wrong.

### DO NOT trust the pre-computed seek target for Undo's distance check — read the position back after seek_async
Found live 2026-09-16, immediately after the fix above shipped: the long-skip buttons (`handle_rewind`/`handle_forward` with `long_skip=True`) and `|<`-to-restart (`_on_prev_right_click`) used `threshold=0.0` (always show Undo), on the assumption that a long skip or restart-to-0 is inherently a big, deliberate jump worth remembering. That assumption breaks at both ends of the book: a forward long-skip within 2s of EOF is silently refused in full by `seek_async`'s near-EOF guard (see "DO NOT seek to a position within 2 seconds of a file's duration") — nothing moves, but Undo showed anyway, for a jump that never happened; and a backward long-skip or restart-to-0 already near the start of the book lands a real but trivial, undo-unworthy seek (e.g. right-clicking `|<` while already sitting at 0:00).

Fixed by giving all three sites the same standard `60 * speed` distance gate every other seek-driven call site uses (dropping `threshold=0.0`), but — critically — measured against the position **actually reached**, not the pre-computed target: `self.player.time_pos` is read back immediately after `seek_async` returns and used as `new_pos` in the `_trigger_undo` call. This works because `time_pos` only updates (`_seek_target`/`_logical_pos` get set) when `seek_async` genuinely issues a seek — every one of its early-return no-op paths (near-EOF, VT past-file-end, missing-file abandon) leaves those fields untouched, so `time_pos` still reads the pre-seek value in exactly the cases where nothing moved. Using the requested target instead of the actual result would have "fixed" the near-start case (small real displacement, correctly gated) while leaving the near-EOF case broken (large *requested* displacement even though the *actual* displacement was zero). This is the same shape as the seek-state architecture's broader "derive intent/result from what actually happened, not from what was requested or inferred" principle documented throughout this file's Player rules — see `_on_chapter_list_selected`, which already read `self.player.time_pos` post-seek rather than the pre-computed target, for the pattern this generalizes from three sites to five.

### The chapter-slider wheel's coalescing timestamp guard was never a substitute for a distance gate on Undo
Found live 2026-09-16, same session: scrolling the chapter progress slider (a fine intra-chapter scrub — `skip = max(10.0, chap_dur * 0.10)`, e.g. ~24s for a 4m04s chapter, as little as 10s for anything shorter) showed Undo on every single tick, `threshold=0.0`. The commit that introduced this (`a3b74ac`, 2026-05-30) reasoned that `save_seek_position`'s existing timestamp/coalescing guard would "prevent spam during rapid scrolling" — this conflated two different things the guard does NOT do together: the coalescing window keeps the *anchor* (`_undo_pos`) stable across rapid calls, but before today's fix (see the rule above) it never gated whether the overlay itself got shown — that was `save_seek_position`'s unconditional `return True`, later `_trigger_undo`'s caller-side `threshold=0.0`. So every tick, however small, re-showed/re-armed the overlay's auto-hide timer, which reads as "Undo won't stop popping up for a trivial nudge."

Fixed the same way as the rule above: standard `60 * speed` gate (dropped `threshold=0.0`), `_trigger_undo` moved to AFTER `seek_async` and given the read-back `self.player.time_pos` instead of the pre-computed, boundary-clamped `new_pos` — this site clamps to the whole book's duration too, so it has the identical near-EOF silent-refusal risk the rule above describes. Because this is a genuine coalescing spree (rapid ticks well within the 3s window), the fix means individual ticks correctly stay quiet unless the CUMULATIVE scroll distance from the spree's start crosses 60s, or a single large step does — same anchoring behavior as "Undo must anchor to a seek spree's start" above, applied to a third input modality (wheel) alongside button-clicks and chapter-nav. Live-verified 2026-09-16 by Pryme against both a short chapter and a real deliberate scrub.

### Regular skip (`</>` buttons, Left/Right keys) participates in the same Undo distance gate as every other seek input
Added 2026-09-16, same session, on Pryme's own initiative after the wheel-scrub fix above shipped: "Should we have something similar for regular skips (multiple clicks or long clicks on `>`/`<` buttons, and multiple presses and long presses on right or left arrow keys) to trigger Undo option when 1 minute is passed in either direction?" `handle_rewind`/`handle_forward` previously called `_trigger_undo` ONLY when `long_skip=True` — a regular-skip tap (default `skip_duration` 10s) never armed or showed Undo at all, no matter how many times it was pressed or how long the button/key was held. Both the `</>` buttons (`setAutoRepeat(True)`, 150ms interval after a 500ms delay) and Left/Right (`Action.SEEK_BACK`/`SEEK_FORWARD`, `allow_autorepeat=True`) can accumulate well past 60s in a few seconds of holding.

Fixed by calling `_trigger_undo` unconditionally in both methods (removing the `if long_skip:` gate), same standard `60 * speed` threshold and read-back `time_pos` pattern as the two rules above. No special-casing was needed for "a single tap should stay silent" — that already falls out of the existing mechanism for free: a lone tap's displacement (10s default) is under the 60s gate on its own, so it's silent; a spree of taps or a held key/button accumulates via `save_seek_position`'s coalescing anchor exactly like the wheel scrub, and earns Undo once cumulative distance crosses 60s. `Action.LONG_SKIP_BACK`/`LONG_SKIP_FORWARD` (Shift+Left/Shift+Right, via `_nudge_long_skip`) already routed through the same `handle_rewind`/`handle_forward` with `long_skip=True`, so both the boundary-no-op fix and this fix cover keyboard long-skip with no separate change. Commit `df1923e`. Live-verified by Pryme. This is the fourth and final input modality to gain the gate this session — Next/Prev, long-skip/restart, chapter-slider wheel, and now regular skip taps/holds all share one mechanism.

### A widget's clickable/hoverable zone must match its RENDERED content, not its layout bounds — and resync the cursor inside whatever sets the content, not just on mouseMoveEvent
Found live 2026-09-16 (Session 2), as a chain of six instances of the same underlying shape across the vol_stack area and the chapter label: `muted_icon_label` (a 14x14 icon centered in a 104x24 `QStackedWidget` page), `sleep_timer_label` (centered text in a full 104x24 `QPushButton` with a transparent background), and `current_chapter_label` (a `ScrollingLabel` in a `stretch=1` layout cell far wider than its title text) all gated click/hover-cursor on the WIDGET's own bounds — which is correct for a widget whose content fills its bounds, but reaches well past what's actually on screen for any widget laid out wider than its content. Each was narrowed to hit-test against the content's own rendered rect (`_muted_icon_rect` — from the pixmap's real size; `_indicator_label_text_rect`/`ScrollingLabel._text_rect` — from font metrics, covering every rendering mode: static centered, elided, and actively scrolling).

**Narrowing the hit-test rect creates a second, distinct bug if not paired with a forced resync: a STALE cursor when the content changes shape under a stationary mouse.** `mouseMoveEvent` only fires on genuine mouse movement — it does not fire when a page swaps (`_settle_vol_stack` swapping to the muted icon on scroll-to-mute), when a countdown label's text changes width every tick, or when `setText` lands new, differently-sized content (advancing chapters via keyboard while hovering near the edge of a scrolling title, landing on a short chapter that doesn't scroll). In every one of these, the widget's cursor PROPERTY can be set correctly and the platform still shows the previous cursor at the previous position until something moves. The fix is a resync that reads `QCursor.pos()` (mapped to local coordinates via `mapFromGlobal`) and re-evaluates the hit-test against it, called from wherever the content actually changes — not from `mouseMoveEvent` alone. Two shapes were used: an external resync the CALLER must remember to invoke (`_resync_muted_icon_cursor` called from `_settle_vol_stack`; `_resync_indicator_label_cursor` called from both `_on_sleep_display_text_updated`/`_on_sprint_display_text_updated`) — works, but is forgettable by a future call site — versus the more robust shape used for the chapter label, where the resync lives INSIDE `ScrollingLabel.setText` itself, the one choke point every text change already routes through regardless of caller, so it cannot be forgotten. **Prefer the internal-to-the-content-setter shape when the widget is a reusable class with multiple/future call sites; the external per-caller shape is acceptable only when there is exactly one call site and it is unlikely to grow more.**

Before trusting either half of this fix (the narrowed rect, or the resync), each was verified against a live Qt harness driving real `QMouseEvent`s/`setText` calls and checking press-inside-fires vs. press-outside-doesn't and cursor-shape-after — not just read from the source and assumed correct, per this file's "never substitute a plausible explanation for a checked one" rule. One case (`sleep_timer_label`) was initially suspected of a real click-routing bug reaching past its own widget bounds entirely; confirmed via direct questioning of the live symptom (not assumed) that this was actually correct `QPushButton` behavior — a transparent background just made the real, legitimately-clickable bounds invisible — before deciding whether to narrow it anyway (narrowed per user preference, not because it was broken). Commits `f2526d7`, `0370816`.

### DO NOT connect `_on_file_ready` to the `file_loaded` signal — it must only connect to `book_ready`
`book_ready` fires once per book (before any file for VT books; after file-loaded for non-VT). `file_loaded` fires on every mpv file-loaded event including VT file switches mid-book. If `_on_file_ready` runs on every file switch, it triggers position restore, which triggers another file switch, causing a quadruple-advance feedback loop. This was the root cause of two reverted stage 3 implementations.

**book_ready invariant:** For VT books, `book_ready` is emitted from `ungate_play` or `_on_playlist_resolved` (before any file loads, while VT state is ready). `_on_file_loaded` never emits `book_ready` for VT books — it emits `file_switched` instead. For non-VT books (M4B, single-file), `_on_file_loaded` is the only emitter of `book_ready`. These two paths are mutually exclusive and must never converge.

**Book-switch state machine (`book_switch.py`, `self._switch: BookSwitchState`):** The switch-specific transition flags live on one object, not as loose `MainWindow` attributes. `phase` (`IDLE`/`LOADING`/`RESTORING`) is *derived* from the sub-flags, so there is no fragile terminal transition. Flag mapping (old attr → SM): `_mpv_ready` → `in_deadzone` (inverted; set by `begin()` at selection, cleared by `library_revealed()` in `panels._on_library_hidden`); `_pre_switch_slider_value` → `flow_pending_progress` + `take_progress_target()`; `_pre_switch_chap_slider_value` → `flow_pending_chapter` + `take_chapter_target()`; `_chaps_dur_retried`/`_file_ready_deferred`/`_chaps_deferred` → same-named SM members. The SM owns ONLY switch-specific state. The **orthogonal** guards — `player._is_seeking`/`_seek_target`, the slider-drag flags, `_flow_anim` running state, `mp3_seek_reload_pending` — stay separate and the SM composes with them (e.g. `_sync_progress_sliders` reads `not is_seeking and not slider_animating and not self._switch.flow_pending_progress`). Do NOT fold those into the SM: they fire for chapter nav / manual seeks / theme color animations and are the fixes for the rules below. Known gap: no stale-book guard on rapid switching (the SM is the natural home for a future `generation` counter, deliberately not added). **Consume-once constraint:** `take_progress_target()`/`take_chapter_target()` are consuming reads — each captured value can be read exactly once, which is what flips `flow_pending_*` to False and tears the switch down. A future fix that needs to *inspect* a pre-value without consuming it must add a non-consuming peek property; do NOT read-then-restore via `take()`, and do NOT make a guard depend on `take()`'s side effect.

### DO NOT read `self.progress_slider.value()` (or any slider's `.value()`) in `_on_file_ready` to compute the "new position" for a switch animation
The slider value is stale at that point — `_update_ui_sync`'s `setValue` call is gated on `not slider_animating`, `not is_seeking`, and `not self._switch.flow_pending_progress`, and may not have run yet. The legitimate pre-switch capture happens earlier, in `self._switch.begin(...)` at selection time; `_on_file_ready` consumes it via `self._switch.take_progress_target()`. Always compute the target slider value from the authoritative data: `int((new_progress / self.player.duration) * 1000)`.

**Duration race corollary (also `_on_file_ready` and `_on_file_loaded_populate_chapters`):** For non-VT books, `player.duration` (`_cached_duration`) is populated by an mpv property observer on the mpv thread. In rare timing conditions it may be None when the queued `book_ready` signal is processed on the Qt main thread. Two rules apply: (1) in `_on_file_ready`, if `not dur`, set `new_val = None` and skip the animation entirely — never animate to 0 as a fallback, because `not dur` and `new_progress == 0` are different cases; (2) in `_on_file_loaded_populate_chapters`, if `not dur`, schedule a 150ms retry via the `self._switch.chaps_dur_retried` flag (reset on each book selection by `self._switch.begin(...)` in `_on_book_selected_from_library`) rather than calling `_set_chapter_ui_active(False)` prematurely — that makes the chapter label text transparent for the entire session.

**Chapter flow animation target:** `_on_file_loaded_populate_chapters` must compute `new_chap_val` from a chapter-list walk against `new_progress` (same algorithm as `_sync_chapter_ui`), NOT from `self.chapter_progress_slider.value()`. At the time this handler runs, the 200ms timer has not ticked; the slider still holds the previous book's chapter position, which equals `pre_chap`, making `pre_chap != new_chap_val` always False and degrading `animate_to` to `setValue`.

### DO NOT remove the animation-state guard in `_sync_progress_sliders` or `_sync_chapter_ui`
Both methods check whether the flow animation is running before calling `setValue`. If that check is removed, the 200ms UI timer will fight the animation frame-by-frame, causing visible jitter. The guard must survive any refactor of those methods.

### DO NOT remove the `self._switch.flow_pending_chapter` guard from `_sync_chapter_ui`
(Formerly `_pre_switch_chap_slider_value is not None` — same predicate, now read off the switch state machine.) Without this guard the 200ms timer can fire between the pre-switch capture in `self._switch.begin(...)` (`_on_book_selected_from_library`) and the `animate_to()` call in `_on_file_loaded_populate_chapters`, writing `setValue(chapter_at_pos_0)` to the slider. `animate_to()` then resets `_value = start` (= pre_chap) before animating, so the user sees: pre_chap → 0 (timer) → pre_chap (animate_to reset) → flow. This is the "blinks first, jumps, then flows" artifact. Mirrors the `flow_pending_progress` guard in `_sync_progress_sliders`. The capture is consumed once via `self._switch.take_chapter_target()`.

### DO NOT remove either gate from `_update_chapter_label_from_index`
Two gates must both survive: `player.is_seeking` and `self._switch.flow_pending_chapter`.

`is_seeking` suppresses VU-meter oscillation: intermediate `time_pos` events during a seek fire `chapter_changed` as mpv scans through chapter boundaries; the gate blocks all updates until the seek settles, then fires one clean update. The CUE-mode optimistic emit from `seek_async` is also suppressed — intentional; settle-time `time_pos` provides the update within ~100ms.

`flow_pending_chapter` covers the deferred populate path. When `_on_file_loaded_populate_chapters` is delayed until after `_on_library_hidden`, the seek can settle before the 50ms drain fires — leaving `_is_seeking` already False when `populate()` is called. `populate()` emits `currentRowChanged(0)`, which fires `chapter_changed(0)` and would write chapter 0's name to the label before `_sync_chapter_ui` corrects it. `flow_pending_chapter` is True throughout the `try` block of `_on_file_loaded_populate_chapters` (consumed only after it via `take_chapter_target()`), so this gate blocks the spurious index-0 write regardless of seek state.

### DO NOT restore the `_seek_target is None` branch in `_on_time_pos_change`
The original `if self._seek_target is None or abs(...) < 1.0` condition caused a race: `load_book` sets `_is_seeking=True` with `_seek_target=None`; the first `time_pos=0` from the new file cleared `_is_seeking=False` immediately; `_sync_progress_sliders` (which guards on `not is_seeking`) was then unblocked before `_on_file_ready` ran, and the 200ms timer wrote 0 to the slider. The fix: only clear `_is_seeking` when `_seek_target is not None` AND position is within 1.0s. `load_book` also now resets `_seek_target = None` (alongside `_cached_time_pos` and `_cached_duration`) to clear any stale target from an interrupted seek on the previous book. `_restore_position` explicitly clears `is_seeking=False` for the no-progress case (where no `seek_async` is called and `_seek_target` stays None), so the slider can update during normal playback. Do NOT add the asymmetric-clear back — it was the root cause of the "0% flash before the flow animation" bug.

### DO NOT store `_seek_target` in LOCAL coordinate space (it must be GLOBAL)
The settle in `_on_time_pos_change` is `abs((value + _file_offset) − _seek_target) < 1.0` — `_seek_target` is compared against the GLOBAL position, so it MUST be global. The VT cross-file follow-up seek in `_on_file_loaded` previously stored `_seek_target = pending` (a LOCAL offset into the just-loaded file); for any file past the first, `abs(global − local) ≈ cumulative_start` never fell below 1.0, so `is_seeking` stuck True forever → permanent chapter-UI freeze (FIXED 2026-06-15, `29b266c`). Correct form there: `_seek_target = pending + target_file['cumulative_start']` (use the timeline entry, self-consistent with `_current_vt_index`, not the bare `_file_offset` field); the mpv `command_async('seek', pending, ...)` stays LOCAL. The `[VT-DESYNC]` tripwire in `_on_file_loaded` guards the assumption that VT loads are serialized (verified — see NOTES).

This is the GLOBAL/local coordinate convention `_logical_pos` (added 2026-07-13, see the
"`Player.time_pos` returns `_logical_pos`" rule further below) also follows — always GLOBAL,
matching `_seek_target`'s convention.

### DO NOT set `is_seeking = True` outside of `seek_async` / a path that also sets `_seek_target`
`is_seeking` and `_seek_target` are cleared together by the settle (`...and _seek_target is not None`), so any path that sets `is_seeking = True` WITHOUT a matching `_seek_target` strands the flag → settle can never clear it → permanent freeze. This bit twice: the chapter-list-click native path (fixed) and `handle_prev`/`handle_next`/`_on_prev_right_click` setting `is_seeking = True` unconditionally after a nav call that no-ops at the chapter[0]/last-chapter boundary (FIXED 2026-06-15, `29b266c`). Rule: let `seek_async` own `is_seeking` — it sets both together, and ONLY when it actually seeks. Do not re-add app-level `is_seeking = True` to nav handlers.

### DO NOT infer "was this a seek?" from `is_seeking`'s timing — set a plain flag at the seek SOURCE instead
Any consumer outside `player.py` that needs to know whether a navigation action (not just whether one is *currently in flight*) caused some later observable change must NOT try to sample or poll `player.is_seeking` for that purpose — `_on_time_pos_change` clears `_is_seeking` *before* running its own chapter walk/emit in the same call, so a queued, cross-thread signal delivered after that point can already read `is_seeking == False` for a transition that genuinely was seek-driven. A polling latch (setting a flag whenever a 200ms UI-timer tick happens to observe `is_seeking == True`) does not fix this — a seek on a local file can fully settle (`True`→`False`) within a single 200ms polling gap, so the poll can miss it entirely. The correct pattern is a plain public flag set unconditionally as the FIRST statement of `seek_async` itself (e.g. `Player.user_seek_pending`) — the one confirmed choke point every navigation action routes through (Next/Prev, chapter-list click, slider drag/wheel, skip buttons, every keyboard shortcut; verified via direct trace, no bypass anywhere) — read and cleared by the consumer. This must be consumed on *every* relevant event the consumer sees, not only the specific transition it cares about (e.g. a seek landing ON a boundary, or staying entirely within the same segment and never producing the event the consumer is watching for) — an uncleared flag survives to falsely tag the next, unrelated event. See `SleepTimerPanel`'s end-of-chapter mode (`ui/sleep_timer.py`) for the reference implementation: `Player.user_seek_pending`, consumed in `_on_chapter_changed` on every call past its mode guard (not just a forward crossing) plus a settle-detection fallback in `update_timer_state` for the same-chapter-seek case. Three earlier attempts at this exact problem (a chapter-index distance heuristic, a bare `is_seeking` poll, and a re-derived-index gate layered on that poll) were each shipped without being checked against a trace and each failed live — full failure trail in NOTES.md, 2026-08-10.

**This is the reference case for a family of rules sharing one fact: intent must be recorded by a
flag set at the source, never inferred from timing or statement ordering.** The others are
`Player.sleep_fired` (`_advance_or_finish`'s unpause must not clear a pause it didn't set), the
per-tick shared-widget emit rule, and the `emit()`/`.show()` same-call-stack rule — all below. Qt
gives no paint or event-loop return between two synchronous statements, and no cross-thread signal
guarantees the flag it would have inferred from is still set by the time it is read.

### Automated tests exist (`tests/`, pytest, dev-only)
`_on_time_pos_change`/seek-state is a near-pure state machine (no mpv, no QApplication). Run `source fabulorenv/bin/activate && pytest tests/ -q`. Keep green on any seek-path change — these encode the `is_seeking`/`_seek_target` invariants whose violations caused repeated freezes/regressions. pytest is in `requirements-dev.txt` (NOT runtime `requirements.txt`).

### Seek/position tracking — VT+Undo is the known-fragile zone
Any change to how `time_pos`, `_seek_target`, `_cached_time_pos`, or a seek-settle boundary is computed or read must be live-verified against VT (multi-file) books and Undo before being considered done — not as a general precaution, but because this specific combination has broken four independent times, and been successfully fixed a fifth touch (with a sixth, additive touch closing a consequence the fifth touch exposed) after understanding exactly why the first three attempts at that fifth fix's own mechanism had failed:

- **2026-06-06:** `seek_settled` signal attempt — reverted. Broke slider/fill desync, undo, notch reanimation, VT slider corruption, chapterless-book snaps. Root cause on record: "the 200ms timer is the silent antagonist — it fires regardless of load state and requires guards that have a one-tick gap."
- **2026-06-06:** `file_switched`-deferral attempt — reverted. Broke undo (VT slider stuck after undo).
- **2026-06-15 (`b6a4023`):** backward-jump rejection heuristic (`_STALE_BACKWARD_TOLERANCE`) — verified clean via instrumentation (32/32 known artifacts correctly classified, zero false positives) — shipped, then reverted. Broke VT backward-seek, the play/pause icon, and chapter[1]→[0] click. No mechanism-level cause was ever diagnosed — the record stops at "regressed X/Y/Z."
- **2026-07-13 (drift-fix branch, untracked):** narrowing `_on_vt_file_switched`'s unconditional `is_seeking` clear on `_seek_target is None` — tried twice, reverted both times, trading a data-loss clobber for a permanent UI freeze. **Both attempts were tested exclusively against a seek structurally incapable of ever landing** (the VT-restore-on-load `book_ready`-before-`play()` race, a separate bug fixed later the same session), so the freeze was that bug's inevitable consequence, not evidence against the guard. The same guard was safely re-attempted and shipped once the seek under test could actually land — see the 2026-07-13 FIXED entry below. **Do not treat "reverted twice" alone as a permanent verdict on a guard — check what the seek under test was actually capable of doing first.**

The load-bearing lesson is not any one of these bugs — it's that clean instrumentation data has already been proven insufficient evidence of safety on this exact bug class. A heuristic or new tracking field can score perfectly against captured samples and still break something live, for reasons that may never be diagnosed. Do not treat a green instrumentation run as a stopping point before live testing; do not treat a clean live pass on the presenting symptom (e.g. drift, slider bounce) as sufficient without separately checking VT playback, VT cross-file seeking, and Undo. The 2026-07-13 fix below is the one case in this zone where a reverted approach was later shown, with real evidence rather than a hopeful reinterpretation, to have failed for a reason that no longer applied — this is the exception that proves the rule: it took a fully independent, checkable finding (a git-history + TODO.md audit of what the guard had actually been tested against) to justify re-trying it, not just "it feels different this time."

**Standing rule:** any seek/position-tracking change verifies VT+Undo FIRST, before verifying the symptom the change was meant to fix. If something regresses, stop and report rather than patching inline — patching around an undiagnosed regression in this zone has not worked before.

Full incident detail: NOTES.md entries dated 2026-06-06 (×2), 2026-06-15, and 2026-07-13 ("`_on_file_loaded`'s general... race — FIXED and live-verified"); commits `12dcf32`→`a506de9`, `4ae0783`/`92902cd`.

**Post-settle stale-backward-sample guard (787bfaa, 2026-08-12):** After
settle clears `_is_seeking`, `_post_settle_target` (LOCAL position, not
global) and `_post_settle_deadline` are armed. The suppression block in
`_on_time_pos_change` sits AFTER `_cached_time_pos` and `_logical_pos`
maintenance and BEFORE the chapter walk — this insertion point is not
arbitrary. Moving it earlier would drop `_cached_time_pos` updates on
suppressed samples (reproducing b6a4023's icon regression). Moving it later
or into the chapter-walk branch would require duplicating it across VT and
non-VT paths. The tolerance (0.05s) is tight by design — reference is the
exact settle position, not a magnitude estimate. Do not widen it.

See SEEK_CONSTANTS.md for the full interaction map between seek-related constants.

**`Player.time_pos` returns `_logical_pos` (the app's believed position), NOT raw mpv `_cached_time_pos` — and the two must stay decoupled** (added 2026-07-13 to fix compounding seek drift, `9521ee4`, live-verified — this change also fell under, and was verified against, the VT+Undo standing rule above). `time_pos`'s getter returns `_logical_pos` when set, falling back to the raw `_cached_time_pos` path only before the first sample of a book. `_logical_pos` is the fix for the drift class where `time_pos` was reading mpv's raw per-seek landing residual (the ~0.09/0.37s over/undershoot `_PAUSED_SEEK_UNDERSHOOT_COMP` compensates), so every subsequent seek computed its target from an imprecise base and residuals compounded (alternating scroll/skip crept to EOF). Load-bearing invariants:
- **`_logical_pos` is ALWAYS GLOBAL** (matches `_seek_target`'s convention — never add `_file_offset` to it). Never conflate with `_cached_time_pos`, which is FILE-LOCAL for VT. Do NOT couple a `_logical_pos` write to any `_cached_time_pos` write.
- **`_cached_time_pos` stays raw, unconditional, every sample** — untouched by this fix. It is the raw mirror the chapter-walk and settle-detection read, pinned by `tests/test_seek_state.py::test_cached_time_pos_tracks_every_sample`. The chapter-walk-and-emit block in `_on_time_pos_change` MUST keep reading raw `value`/`global_pos`, never `_logical_pos` — that is what keeps `_CHAPTER_WALK_TOLERANCE`/the seek epsilons calibrated against mpv's actual landing.
- **Lifecycle** (`_on_time_pos_change` maintenance block): set to the target at every `_seek_target` write site; adopted EXACTLY from `_seek_target` at settle (discarding the residual) with `_just_settled = True`; the first post-settle sample is SKIPPED (does not accumulate) so the discarded residual is not re-added; advanced by raw-sample delta during normal playback; resynced to raw on a delta above `_LOGICAL_POS_RESYNC_THRESHOLD` (2.5s, measured). Do NOT replace the `_just_settled` skip-one with a "reprime the baseline at settle" formulation — that was traced and found case-incompatible (same-file-paused vs. VT cross-file want opposite baselines; the reprime breaks whichever it isn't tuned for). Skip-one is the only case-agnostic fix.
- **FIXED (2026-07-13, later the same session):** the VT restore-on-load gap described above (this fix) plus a broader, pre-existing general race it surfaced were both fixed together. **VT restore-on-load**: `_restore_position` (`app.py`) no longer calls `seek_async` directly for a VT book's initial restore — it defers via `Player.defer_vt_restore`/`_vt_restore_pending`, and `_on_file_loaded`'s VT branch issues the real seek only once mpv has actually confirmed the file is loaded (not when `book_ready` fires, which is before `instance.play()` for VT books — see the book_ready invariant above). **The general race this surfaced**: `_on_file_loaded`'s pattern of issuing a seek then unconditionally emitting `file_switched` was found to be a pre-existing, general hazard — not specific to VT restore-on-load — that also intermittently corrupted state on ordinary manual VT cross-file seeks (wheel, arrow-key, seek/skip-button, slider-click, chapter-list-click), just rarely enough to not have surfaced before. Fixed via two required, paired changes: (1) `_on_vt_file_switched` (`app.py:1703`, gate at `app.py:1728`) now gates its clear on `self.player._seek_target is None` instead of clearing unconditionally — safe this time because, unlike the two 2026-07-13 reverted attempts above, it was tested against a seek proven capable of landing, not one that structurally never could; (2) `_on_end_file`'s ERROR branch (`player.py:708`, reset block at `player.py:727-734`) now also resets seek state when a seek was genuinely pending, closing a real, independently-discovered gap (a VT cross-file seek's target file failing to load previously left `is_seeking=True` stranded forever, with no settle and — once (1) landed — no recovery path either). Both required together; (1) alone would have introduced a new unrecoverable freeze for the ERROR case. Verified via two forced-condition harnesses (`tools/vt_restore_race_harness.py`, `tools/fs_race_harness.py`, both 100% pass) plus ~45 real live VT cross-file crossings across all six input methods and Undo, 0 real misses. Full mechanism, evidence, and verification detail in NOTES.md ("`_on_file_loaded`'s general... race — FIXED and live-verified", 2026-07-13).

### DO NOT let a VT cross-file seek reach `os.path.getsize` for a target file that may not exist — check `os.path.exists` first, never a try/except
`seek_async`'s VT same-file branch calls `os.path.getsize(target_file['file_path'])` as part of the MP3-stop-and-load size-threshold test, AFTER `is_seeking`/`_seek_target`/`_logical_pos` are already set. If the VT file is missing from disk (deleted/moved/renamed), `os.path.getsize` raises `FileNotFoundError` mid-seek, stranding those three fields with no settle ever able to arrive — Qt's own default uncaught-exception handling for Python slots prevents a full crash, but nothing recovers the stranded state (found live 2026-07-14, immediately after the Part 1 guard above landed — Part 1's guard removed what used to be an ACCIDENTAL self-healing path for this exact strand, since the pre-guard unconditional `_on_vt_file_switched` clear used to mask it). Fixed via `os.path.exists(target_file['file_path'])` checked BEFORE `os.path.getsize` is ever reached — a pre-check, not a try/except; a try/except would still let the exception get raised and unwind, just caught one frame closer, which is strictly weaker than never raising it at all. On a missing file, `Player._abandon_seek_missing_file()` resets `_is_seeking`/`_seek_target`/`_logical_pos`/`_last_raw_global`/`_just_settled` (the exact same field set the `_on_end_file` ERROR-path reset above uses — mirror that shape, don't reinvent it), emits `self.load_failed.emit("File missing.")`, and `seek_async` returns without issuing any seek command. `_on_load_failed` (`app.py`) routes `"File missing."` through the same `_mark_book_missing(self.current_file)` call the `"no audio files in folder"` reason already used — **this uses `is_missing`, NOT `is_excluded`** (a literal-but-wrong instruction during this fix's planning named `is_excluded`; using it would reintroduce the "ping-pong bug" the "Soft-delete flags" section documents — see that section for why `is_missing` is the only correct flag for a confirmed-gone file). `_mark_book_missing` → `_on_book_removed` was reused entirely as-is; neither was modified. Live-confirmed by the user against the real repro (deleted VT file, Doctor Zhivago): banner shows, book unloads, a manual rescan correctly revives the book with the still-missing files excluded. A second missing-file scenario the user tried produced a sequence they weren't fully certain of — flagged as open, not a confirmed bug; do not change this behavior without a clearer repro from the user. A richer design (a sticky banner offering "remove from library" vs. "rebuild/resync the VT timeline around the gap and keep playing") was explicitly deferred — see TODO.md. Full detail in NOTES.md ("VT missing-file exception strands seek state — FIXED and live-verified", 2026-07-14).

### DO NOT let `_advance_or_finish`'s unpause clear a pause it didn't set
`_advance_or_finish` (player.py, called only from `_on_pause_test`'s near-EOF probe and
`_on_end_file`'s `reason_int == 0` EOF branch — confirmed no other caller, no UI/user-driven path
reaches either) unconditionally cleared `instance.pause` after advancing to the next VT file. That
line exists to lift the pause `_on_pause_test` itself applied while probing near-EOF — it is "clear
the pause I put there," not "clear whatever pause exists." If an unrelated pause (e.g. the sleep
timer firing) lands within the same probe/advance window, it gets silently undone within tens of
milliseconds — confirmed live 2026-08-10: an end-of-chapter sleep timer whose anchor chapter happened
to end exactly at a VT file boundary paused correctly, then kept playing because the VT advance's own
unpause ran ~60ms later. Fixed via `Player.sleep_fired`, a plain public flag set by
`SleepTimerPanel.update_timer_state` at BOTH sleep-fire sites (timed and end-of-chapter — both have
the identical vulnerability) immediately before the pause is applied, cleared by
`disable_sleep_timer()`, and read by the unpause line: `if self.instance.pause and not
self.sleep_fired: self.instance.pause = False`. Same shape as `user_seek_pending` (see the rule
above) — a plain flag set at the moment intent is known, not inferred from timing. If any future
caller of `_advance_or_finish` needs the unpause to fire despite `sleep_fired`, that is new scope —
verify the caller doesn't already special-case sleep before assuming this guard needs weakening.

### DO NOT let a per-tick state machine emit an unconditional "nothing to show" value into a widget shared with another per-tick state machine
`SleepTimerPanel.update_timer_state`'s trailing `display_text_updated.emit(display_text)` was
unconditional — it ran on every single 200ms tick regardless of whether sleep was armed, sending
`""` whenever it wasn't. This was harmless for years because `sleep_timer_label` (`vol_stack` page
0) had exactly one writer. Adding `SprintPanel` as a second writer of the SAME label (2026-08-11,
by design — sleep and sprint are mutually exclusive, so sharing one indicator slot is correct)
turned the old "harmless redundant `""`" into a live bug: `_sync_playback_state` calls sleep's
`update_timer_state` BEFORE sprint's `update_sprint_state` on every tick, so sleep's redundant
empty-write ran first and clobbered whatever sprint had just written, on every tick sleep wasn't
armed — i.e. constantly, for anyone using sprint alone. This corrupted sprint's own
`_on_sprint_display_text_updated`'s `old_text`/`was_armed` tracking (spuriously reading `newly_armed
= True` far more often than intended), surfacing as two seemingly unrelated symptoms: the mute-icon
transient misfiring, and the cancel/complete message appearing to dismiss early. Two live-tried
fixes addressed the WRONG layer first (a `_cancel_message_active`/`disable_sprint()` reorder — a
real, separately-confirmed bug, but insufficient alone; and the same-call-stack `emit()`/`.show()`
reorder covered by the rule below). Neither was found wrong by re-guessing — both were confirmed
insufficient only by adding `logger.warning` tracing and reading the actual timestamps. Full trail:
NOTES.md, 2026-08-11. Fixed by gating sleep's
trailing emit on `self._sleep_mode is not None`: sleep still emits everything it legitimately needs
to (the running countdown, `[chapter]` text, and `disable_sleep_timer()`'s own explicit `""` on the
real disarm transition) — it just stops repeating a redundant `""` every tick when it was never
armed at all. `SprintPanel.update_sprint_state` was already correctly gated (`if not
self._sprint_active: return` at the top) — the interference was one-directional. **Any future
per-tick state machine that shares a display widget with another one must emit only when it
genuinely has something to say, never an unconditional default value on every poll** — even a value
that looks obviously harmless (an empty string) can silently break a second writer added later.

### DO NOT try to fix a visible flash by reordering an `emit()`/`.show()` pair within the same call stack
`SleepTimerPanel`/`SprintPanel`'s "Disable/Cancel" button flashed visibly for one frame right before
its own panel closed on arm (`timer_started`/`sprint_started` is connected to
`PanelManager._close_sleep_flow`/`_close_sprint_flow`, which starts the close-slide synchronously in
the same call). Reordering `.show()` to run after the `emit()` was tried first, on the theory that
the close-slide would start before the button painted visible — **this has no mechanism to work**:
Qt does not paint between two synchronous Python statements in the same call stack, so both the
button's visibility change and the animation start land in the same paint cycle regardless of
statement order. Confirmed live that the reorder did not fix the symptom. The correct shape, already
shipped elsewhere here: defer the reconciliation to the NEXT panel-open rather than applying it live
during an interaction that would visibly disturb an open/closing panel (`_sync_persist_filter_on_open`,
`app.py`, called from `PanelManager._start_settings_entry`, does this for Settings' "Persist search
filter" master switch). Applied the same shape: `.show()` was removed from the arm path entirely; a
new `sync_disable_button_visibility()` on each panel is called from
`PanelManager._start_sleep_entry`/`_start_sprint_entry` instead, i.e. exactly when the panel is about
to become visible again, never during the arm-then-auto-close sequence.
`disable_sleep_timer()`/`disable_sprint()`'s own `.hide()` calls (the disarm-while-open path, which
never triggers an auto-close) were left untouched. If a
future visible-flash bug looks like an ordering problem, check whether the two statements are
genuinely separated by a return to the Qt event loop (a different call stack) before assuming a
same-call-stack reorder can fix it — most of the time it cannot.

### DO NOT let `_do_fade_with_slider_animation` iterate `chapter_progress_slider` when `_chapter_ui_active` is False
The slider loop in `_do_fade_with_slider_animation` must skip `chapter_progress_slider` when `mw._chapter_ui_active` is `False`. The theme overlay punch-through re-exposes the slider during the window between `_apply_stylesheets` (which repolishes child widgets and overwrites transparent colors with theme colors) and the `_set_chapter_ui_active` reapplication at the end of `_apply_stylesheets`. Without the guard the slider briefly renders at full opacity, causing a visible flash. Guard: `if attr == 'chapter_progress_slider' and not mw._chapter_ui_active: continue`.

### DO NOT restore `show_metadata=False` to `library_controller.apply_library_state`
The `show_metadata=False` argument was removed from the `apply_library_state` call in
`library_controller.py` on 2026-05-11. Do not restore it. It was silently overriding cover
display on every book switch — `_load_cover_art` owns `metadata_label` visibility and the
call was fighting it. If you think metadata visibility needs to be controlled at the
`apply_library_state` call site, stop and explain why before touching it.

### DO NOT use `self.chapter = idx` for chapter navigation anywhere
Always navigate to a chapter by seeking to its boundary with a position-based walk of `chapter_list`, never by native `self.chapter = idx` assignment (mpv's native chapter assignment undershoots boundaries and causes drift). This applies in `chapter_list.py`, `player.py`, and anywhere else chapter navigation is triggered. The seek target is `nominal + _chapter_seek_offset()`, where `_chapter_seek_offset()` is mode-aware: `_EMBEDDED_CHAPTER_SEEK_OFFSET` (−0.09, cancels mpv's ~0.09s overshoot) for embedded M4B, `_CHAPTER_BOUNDARY_EPSILON` (+0.35) for VT/CUE.

**As of 2026-06-13 (Session 3 cont.), embedded-M4B chapter-LIST clicks NO LONGER use `self.chapter = idx`.** The old exception ("embedded clicks use native nav because mpv owns boundaries") was carved out (git `e243193`, 2026-05-17) because the *then-current* `seek_async + 0.35` drifted on embedded M4B. The Session-3 calibrated-offset model (−0.09) made that obsolete: embedded clicks now route through `Player.activate_chapter_index(idx)` → `seek_async`, same as Prev/Next and VT/CUE clicks. This was required to fix a freeze — native `self.chapter = idx` never set `_seek_target`, so the chapter-UI's `is_seeking` guard never cleared and the chapter slider/labels stayed frozen until a manual slider click. Do NOT restore the native-click path. The native `chapter` *setter* is now only reachable via the `chapter` property (unused for navigation); the native `chapter` *getter* is still read by `apply_smart_rewind` to clamp to chapter start — that read is valid (mpv updates its native chapter from playback position regardless of how the seek was issued).

### DO NOT restore any emit in `_on_chapter_change` — it is fully suppressed as of 2026-06-01
`_on_chapter_change` now contains only `return`. `_on_time_pos_change` drives `chapter_changed` universally for all book types (VT, CUE, embedded M4B) via position walk. The old `_is_seeking` guard on `_on_chapter_change` was insufficient: `_on_time_pos_change` clears `_is_seeking` first, so by the time `_on_chapter_change` fires the guard is already False — it emitted stale mpv native chapter values, causing snap-back on Prev/Next while paused. Do not add back any emit here.

### DO NOT set `_virtual_timeline` for CUE books
CUE mode is indicated solely by `_chapter_list` being non-`None` with `_virtual_timeline` remaining `None`. Setting `_virtual_timeline` would activate VT file-switching machinery on a single-file book.

### DO NOT simplify `Player.terminate()`
It must store the instance reference, clear `self.instance`, call `terminate()`, then `wait_for_shutdown()`. Without `wait_for_shutdown()`, libmpv's internal threads outlive Qt's cleanup and crash in `avformat_close_input`. This was masked for an unknown period by a debug print. The sequence is intentional — do not reorder or remove steps.

### The checkpoint `unlink` must always run synchronously, never deferred to a daemon write thread's `finally` — true on BOTH the close path and the recovery path
`close()` flushes the session to DB on a daemon thread and RETURNS that thread (or `None` on the sub-60s/no-book discard). The checkpoint deletion is NOT inside that daemon closure — it is a separate synchronous `SessionRecorder.clear_checkpoint()` that `closeEvent` calls **unconditionally** after `flush_thread.join(timeout=0.5)`. Ordering is load-bearing: `t = close(); if t: t.join(timeout=0.5); clear_checkpoint(); event.accept()` — all before `event.accept()` (the point of no return). DO NOT move the checkpoint `unlink` back into `SessionRecorder.close()`'s daemon thread, and DO NOT make `closeEvent`'s `clear_checkpoint()` conditional. The original code did the `unlink` inside the daemon `_write` after the DB write; on graceful close the process exits right after `close()` returns, killing that daemon thread before the unlink but AFTER the DB write landed → stale checkpoint → next startup's `_recover_checkpoint()` re-wrote the SAME session as a **duplicate** (FIXED 2026-06-21; see NOTES.md "Session recorded twice on graceful app close"). Two independent guards with two distinct jobs: the **join** gives the DB write a bounded chance to land (it can be lost only if a single-row WAL insert exceeds 500ms — DB-broken territory); the **unconditional synchronous clear** makes the duplicate impossible regardless of how the join resolved. If the clear were left inside `_write` (or made conditional on the join completing), a join *timeout* could strand a checkpoint after a committed write and resurrect the bug. `losing-at-worst` beats `duplicating`; the prior behavior was a guaranteed duplicate.

**The recovery path (`_recover_checkpoint`) had the EXACT SAME bug shape, independently, until 2026-08-22 — this section's earlier text calling it "a DIFFERENT path... leave it as-is" was itself wrong and has been corrected here, not left to stand as stale documentation.** `_recover_checkpoint` used to unlink the checkpoint file inside its own daemon write thread's `finally`, mirroring the exact defect `close()` was already fixed for above. A second process launch arriving before that thread finished — trivially reachable under an `entr -r python main.py` dev loop, which kills the process on every file save and never runs `closeEvent`/`clear_checkpoint()` at all, but also reachable by any real crash-then-quick-relaunch — would see the same still-present checkpoint and recover it AGAIN as a duplicate `listening_sessions` row, sometimes cascading across several rapid restarts as the checkpoint's `listened_seconds` kept growing between kills. Found live 2026-08-22 after 67 such duplicate rows had accumulated since 2026-06-19 (cleaned up via a one-off dedup script, full table backed up first — see NOTES.md). Fixed (`43a9fca`) by unlinking synchronously in `_recover_checkpoint` itself, immediately after reading the file and BEFORE the write thread is spawned — not in the thread's `finally`, same fix shape as `close()`'s. A second, independent bug was found and fixed in the same investigation: `_recover_checkpoint` had stamped a recovered session's `session_end` as `datetime.now()` **at recovery time** (i.e. whenever the app next happened to launch) rather than when the session actually stopped — corrupting both the streak grid (wrongly crediting a day with no real listening, via the correct-in-general `get_streaks()` start-OR-end union rule reading a bogus input) and the hourly heatmap (`get_hourly_heatmap`'s proportional wall-time split smearing real seconds across every clock-hour between the true stop and the eventual relaunch). Fixed (`f3816cf`, the commit immediately before `43a9fca`) via `session_end = max(checkpoint_mtime, session_start)` — the checkpoint file's own mtime (rewritten every 30s while a session stays open) is the tightest honest estimate available, floored at `session_start` to guard clock skew. Both fixes are pinned by regression tests in `tests/test_session_recorder.py`, each independently verified to fail against the pre-fix code before confirming they pass against the fix.

### DO NOT call `session_recorder.close()` after nulling `_current_book` / `current_file`
`SessionRecorder` is constructed with `get_book_fn=lambda: self._current_book` (`app.py`). `close()`
reads the book through that lambda at call time and gates its entire flush on
`listened >= 60 and book is not None` — if the book is already `None`, the flush is skipped
regardless of how long the session ran, and ONLY the misleading "< 60s threshold" log line prints
(it doesn't distinguish "too short" from "no book"). `_on_book_removed` (the helper called by
scan-location removal, the book-detail trash button, and confirmed-missing handling) used to null
`_current_book`/`current_file` BEFORE calling `close()`, silently discarding every active session —
including multi-hour ones — on any removal of the currently-playing book (FIXED 2026-06-25; see
NOTES.md "`_on_book_removed` nulled `_current_book` before calling `session_recorder.close()`").
Correct order, and the one any future teardown helper must follow: call `close()` FIRST (book and
player both still valid, so the position read is also correct), THEN clear `_current_book` /
`current_file`, THEN `player.terminate()`. `tests/test_session_recorder.py` pins this contract —
keep it green on any change to `_on_book_removed` or to `SessionRecorder.close()`'s guard.

---

#### Soft-delete flags on `books` (`is_deleted` / `is_excluded` / `is_missing`) — one shared fact, five consequences

`books` has three independent soft-delete-ish flags, each with a distinct owner and a distinct reset policy. Getting any of the consequences below wrong re-opens a bug that has already shipped and been fixed once.

- `is_deleted = 1` — set by `remove_scan_location` (location removed from scan list); cleared by `restore_books_under_path` (only when `is_excluded=0`) or by any upsert (self-healing).
- `is_excluded = 1` — set by `set_book_excluded` (user explicitly removed a book via the trash button) — ONLY. Untouched by removal/restore. **Sticky**: does NOT reset on upsert (`CASE WHEN books.is_excluded THEN 1 ELSE 0 END`, added 2026-06-27, reversing the old "rescan resets both flags" behavior). The ONLY restore path is `set_book_excluded(path, False)` — called from the **Excluded Books** popup in the Library settings tab (`ui/excluded_books.py`, driven by `db.get_excluded_books()`); `restore_books_under_path` is NOT one (it only touches `is_deleted`).
- `is_missing = 1` — set by `set_book_missing`/`mark_books_missing` (confirmed gone from disk) — a separate flag, added 2026-06-27 specifically to stop conflating it with `is_excluded`. **Self-heals** on any upsert, unconditionally — the OPPOSITE of `is_excluded`'s stickiness; do not copy the `is_excluded` CASE WHEN pattern onto it.

**The ping-pong bug (2026-06-27) — why `is_missing` exists as its own flag:** `mark_books_missing`/`_mark_book_missing` used to write `is_excluded=1` for a book confirmed gone from disk (same flag as user-trash). The Excluded Books popup's eye-click restore (`set_book_excluded(path, False)`) treated every row identically — for a missing-flagged row, that put a file-less book back in the visible library; the user tried to load it; `_mark_book_missing` fired again (still no file) and put it right back in Excluded Books. Infinite loop ("Schrödinger's audiobook"). Fix: missing-detection now writes the dedicated `is_missing` flag instead, and `get_excluded_books()` filters `is_missing=1` rows out entirely — there's no restore action that makes sense for a book that isn't there. **Accepted edge case, not a bug:** a book can be both `is_excluded=1` AND `is_missing=1` (trashed an already-missing book, or trashed before discovery). While missing it's correctly hidden from the popup; when the file returns, `is_missing` self-heals on upsert but `is_excluded` stays sticky — the book reappears in the popup (visible again) but not the library, with no proactive notification. The user could forget about it. Out of scope, accepted.

Consequences of this shared fact, each independently load-bearing:

1. **DO NOT hard-delete from the `books` table.** `remove_scan_location` soft-deletes via `UPDATE books SET is_deleted = 1` — never `DELETE FROM books`. All rows, progress, covers, `book_files`, and session history must survive a location removal so they can be resurrected when the location is re-added. Any query that drives the library view must include `WHERE is_deleted = 0 AND is_excluded = 0 AND is_missing = 0`. Stats queries must not — they key off `book_path`/`book_title` in the sessions tables directly and must see all historical rows.
2. **DO NOT conflate the three flags** with each other — see the per-flag descriptions above. "Visible" = all three 0. Stats queries are intentionally unfenced by all three flags — listening history and progress survive removal permanently.
3. **Scanner resurrection behaviour:** `scanner.py` builds `known_paths` from `get_all_book_paths()` (unfenced — all rows regardless of flags). Excluded/deleted/missing books are therefore recognised as known and skipped during non-force scans, so they are NOT automatically resurfaced. A force rescan (`force_refresh=True`, triggered by the Rescan button) re-processes all paths and calls `upsert_books_batch`, which resets `is_deleted` and `is_missing` to 0 (resurrecting location-removed/rediscovered books) but **keeps `is_excluded` sticky**. Do NOT change `known_paths` to use `get_all_books()` or any fenced query — doing so caused excluded books to be silently resurfaced on every scan (2026-06-06 bug).
4. **Scanner missing-book detection (force rescan only, 2026-06-26, flag corrected 2026-06-27):** A force rescan also *creates* `is_missing=1` rows (it is no longer purely additive/resurrective). After Phase 1, for each location whose root `exists()` (`walked_locations`), `ScannerWorker.run_scan` diffs `db.get_visible_book_paths_under(loc)` (currently-visible books, `is_deleted=0 AND is_excluded=0 AND is_missing=0`) against the folders rediscovered on disk and calls `db.mark_books_missing(paths)` (batch `is_missing=1`) for any visible book whose folder is gone. **This writes `is_missing`, NOT `is_excluded`** — see the ping-pong bug note above for why that distinction is load-bearing. The book stays in DB/stats and self-heals (is_missing clears) the moment a later scan rediscovers the folder — no sticky-flag exception needed for that, unlike `is_excluded`. Two guards are load-bearing and must survive any refactor: (1) it runs ONLY on `force_refresh=True`, never on non-force scans; (2) it is scoped to `walked_locations` ONLY — an offline/unmounted location (root `exists()` False) is never in that list, so its books are NEVER falsely flagged when its drive is detached. The inner per-folder `entry.iterdir()` audio check is wrapped in `try/except (PermissionError, OSError)`; skipped folders accumulate in a function-scoped `skipped_dirs` set (initialized once at the top of `run_scan`, only `.add()`ed, never reassigned) that is folded into the `discovered` set, so a transient per-folder I/O error never reads as "folder gone". Do NOT scope `skipped_dirs`/`walked_locations` inside the loop or the except block.
5. **Location-readd resurrection (`restore_books_under_path`, 2026-06-08):** Re-adding a previously-removed scan location used to leave its books permanently hidden — `remove_scan_location` soft-deletes (`is_deleted=1`) but the scanner's `known_paths` skip (above) means a routine scan never re-processes those paths to flip the flag back, forcing a manual force rescan. `db.restore_books_under_path(path)` un-soft-deletes (`is_deleted=0`) books under `path`, called from `_on_scan_now_clicked` immediately after `add_scan_location`. It is intentionally narrower than a force rescan: it only flips `is_deleted`, gated on `is_excluded = 0`, so user-trashed books stay hidden and still require a manual force rescan — it must NOT touch `is_excluded`. This is a different code path from the scanner/`upsert_books_batch` resurrection above; keep them conceptually separate.

### DO NOT swap `get_book_count()` and `get_visible_book_count()` — they serve different purposes
`get_book_count()` queries `SELECT COUNT(*) FROM books` — all rows, including `is_deleted=1` and `is_excluded=1`. Correct for stats (which must see all historical rows). `get_visible_book_count()` queries with `WHERE is_deleted = 0 AND is_excluded = 0` — only rows visible in the library. `compute_library_state` uses `get_visible_book_count()` for `has_indexed_books`; never change it to `get_book_count()`. Using the unfenced count would make `has_indexed_books=True` even when the library panel shows 0 books (soft-deleted rows from a prior scan remain in the DB), routing the empty state into the no-book carousel instead of the scan/quote prompt.

---

#### Metadata-preservation guards in `upsert_book`/`upsert_books_batch`/`reparse_library` — one shared fact, three consequences

`upsert_book` and `upsert_books_batch` share identical SQL logic (execute vs executemany) and both use `CASE WHEN books.X_locked THEN books.X ELSE excluded.X END` guards (title/author/narrator/year) so a rescan cannot silently clobber user-edited, locked metadata. (Implementation uses the bare-truthy form `CASE WHEN books.title_locked THEN ...`, not `= 1` — equivalent in SQLite since the column is `INTEGER NOT NULL DEFAULT 0`.) `reparse_library` (the naming-pattern re-split) shares the same underlying concern from a different code path.

1. **DO NOT pass `0.0` as `progress`** to `upsert_book` or `upsert_books_batch`. The scanner does not know a book's saved playback position. Pass `None` if progress is unknown. The `COALESCE(NULLIF(excluded.progress, 0.0), books.progress)` in both upserts is a safety net against accidental `0.0` — it is not a contract that callers can rely on. Passing `0.0` would overwrite saved progress on any future DB engine that handles `NULLIF` differently.
2. **DO NOT keep `upsert_book` and `upsert_books_batch` out of sync.** Any schema or ON CONFLICT guard change in one MUST be applied to the other. Skipping this sync causes silent data loss on rescans.
3. **DO NOT remove the `CASE WHEN books.X_locked` guards** from either upsert's ON CONFLICT clause. They must survive any future refactor. (The guard reads `books.title` on the locked branch and `excluded.title` on the unlocked branch.)
4. **DO NOT remove the lock guard from `reparse_library`.** `reparse_library(pattern)` re-splits every book's `title`/`author` from `folder_name_raw` when the Library tab's naming-pattern button is clicked. Its `UPDATE` MUST keep the `CASE WHEN title_locked THEN title ELSE ? END` / `CASE WHEN author_locked THEN author ELSE ? END` guards (added 2026-06-27) — without them a naming-pattern click silently clobbers user-edited, locked title/author for the WHOLE library (it was the one write path that ignored locks; every other path — both upserts — guards them). `folder_name_raw` still re-stores unconditionally (it is the raw source string, not user-editable metadata). Param order is `(new_title, new_author, raw, id)`; the CASE WHEN handles preservation. `tests/test_reparse_library.py` pins this (both-locked preserved, title-only, author-only) — keep it green.

---

### DO NOT add separate save/lock widgets to BookDetailPanel
The metadata action button state is driven exclusively by `_MetaActionState` enum. Do not add `_save_label` or `_lock_btn` widgets — use `_set_meta_state()` to manage appearance.

### DO NOT set cursor or stylesheet on chapter widgets outside `_set_chapter_ui_active`
`_set_chapter_ui_active(active: bool)` is the sole owner of chapter slider cursor, chapter label stylesheets, and `WA_TransparentForMouseEvents` state. Do not set these directly in `_build_secondary_controls`, theme application, or any other call site. Theme changes repolish child widgets and clear instance stylesheets — `_apply_stylesheets` reapplies the correct state by calling `mw._set_chapter_ui_active(mw._chapter_ui_active)` at its end. The `_chapter_ui_active` flag tracks the logical state and must stay in sync: always route through `_set_chapter_ui_active`, never set flag or widget state separately.

### DO NOT call `_set_chapter_ui_active(False)` unconditionally at book selection time
For chaptered→chaptered switches, the chapter slider must remain visible and at the old position — it is the flow animation's start point. Hiding it unconditionally kills the flow: the slider clears, blinks, then animates from the old position instead of flowing smoothly. Protection against the `_set_bg_suppressed` repolish is handled by a lightweight `bg_color`/`fill_color` re-assert in `_set_bg_suppressed` itself, guarded by `not _chapter_ui_active`. That re-assert fires only when the slider is already inactive and is the correct and only place for this protection. The preemptive `_set_chapter_ui_active(False)` that previously lived in `_on_book_selected_from_library` was removed for exactly this reason — do not restore it.

### DO NOT seek to a position within 2 seconds of a file's duration
mpv hangs silently when seeked within ~2s of EOF — no error, no event, no recovery. Every `command_async('seek', ...)` or `loadfile start=X` call must be preceded by a guard that returns early if `duration - pos < 2.0`. Guards currently live in `seek_async` (player.py): VT same-file branch checks `target_file['duration'] - local_pos < 2.0`; non-VT branch checks `self._cached_duration - pos < 2.0`. The stop-and-load path has its own 5s buffer. If any new seek path is added, the buffer must be present.

### DO NOT join `book_events` directly into a query that aggregates `listening_sessions`
The join produces a cartesian product (sessions × finished events per book) before GROUP BY, inflating `SUM(listened_seconds)` by the finished event count. Always use a correlated scalar subquery: `(SELECT MAX(CASE WHEN be.event_type = 'finished' THEN 1 ELSE 0 END) FROM book_events be WHERE be.book_id = b.id) as is_finished`. Applies to `get_daily_book_breakdown`, `get_books_listened_in_period`, and any future query with the same shape.

### DO NOT query `books.finished_at` for finished state — it is never written
`books.finished_at` exists in the schema but is only ever reset to NULL (`reset_stats`/`delete_book_stats`); nothing populates it. The authoritative source is `book_events` with `event_type = 'finished'`. All finished-book queries use it (`get_finished_book_data`, `get_recently_finished`, `get_streak_grid_finished_dates`). Querying `books.finished_at` returns silently empty.

---

#### `get_streaks()` and `StreakGrid`'s cache must derive the longest run from the SAME listened-day set — one shared fact, two consequences

As of 2026-06-12 a "listened day" is `session (start OR end adjusted-date) OR 'finished' book_event` (finished ⟹ listened). Both the SQL side (`get_streaks`, `build_streak_grid_cache`) and the Python side (`StreakGrid._compute_longest_run`) must agree on this exact day-set, or the streak count and the grid's visual longest-run/cell fills silently diverge.

1. **DO NOT keep `StreakGrid` from cross-checking its longest run against `get_streaks()['longest']`.** `get_streaks(day_start_hour)` returns only counts (`current`/`longest`), not which days. `StreakGrid._compute_longest_run(cache)` derives the longest-run **date set** independently (ISO sort + consecutive scan; most-recent wins on tie via `>=`). The invariant `len(self._longest_dates) == streak_info['longest']` must hold — two independent paths over the same listened-day set (SQL `get_streaks` union vs. Python scan over `streak_grid_cache`). Both paths must include finished adjusted-dates: `get_streaks` unions them into its day set; the cache write sites add them to `streak_grid_cache`. A divergence means the two drifted — an attribution change applied to some of the six finished⟹listened sites but not all (`build_streak_grid_cache`, `_update_streak_grid_cache_for_date`, `write_book_event`, `unfinish_book`, `delete_book_stats`, `get_streaks` — see NOTES.md "StreakGrid invariant: a 'finished' day is ALWAYS a listened day"). That mismatch is the diagnostic; do NOT clamp one to the other to hide it.
2. **DO NOT make `get_streaks` use start-date-only attribution — it must union `session_end`, matching the grid.** The streak grid (`build_streak_grid_cache`/`_update_streak_grid_cache_for_date`) has always correctly lit a cell if a session's start OR end adjusted-date matches it — a session spanning the `day_start_hour` boundary (e.g. 23:55→00:05, or 04:53→06:02 with `day_start_hour=5`) genuinely was listened to on both of those adjusted-days, and the grid cells were right to reflect that. The bug (found 2026-06-19, see NOTES.md "Streak count / grid cell mismatch") was that `get_streaks` — which drives the streak NUMBER, not the cells — built its day-set from `get_active_periods` (start-date only, by design: it also drives Day/Week/Month nav and must stay start-only there) plus finished events, but never unioned session end-dates. So a spanning session lit two grid cells while the streak count/label only credited one of those days. Fixed by adding a session_end-date query directly inside `get_streaks` (NOT by changing `get_active_periods`, which must remain start-only for the period navigator) and unioning it into `active_set` alongside the existing finished-event union — mirroring `build_streak_grid_cache`'s three sources (start, end, finished) exactly. Do NOT "fix" this again by making the grid start-only to match `get_active_periods` — that direction was tried and reverted; the grid was correct, the streak count was the thing missing data. The Day/Week/Month tabs are explicitly start-date-only and intentionally do NOT show a spanning session twice — see NOTES.md for why full session-splitting there was scoped out as too large a change for too small a benefit.

### DO NOT assume `streak_grid_cache` stays fresh for a long-running session — it needs its own rollover timer, not just a startup rebuild
`build_streak_grid_cache` used to run in exactly two places: unconditionally at app startup and inside `StatsPanel._on_day_start_hour_changed` on a manual setting edit. Neither fires again as wall-clock time passes while the app stays open. A process launched *before* the adjusted-day boundary (`day_start_hour`) and left running *past* it never re-derives "today" — the startup rebuild was correct at the instant it ran, but the cache table then has no row at all for the day that starts later that same session, even though `listening_sessions`/`book_events` are written correctly the whole time (confirmed live 2026-08-10: app launched at 06:12 with `day_start_hour=10`; the adjusted day was still yesterday at launch, rolled to today at 10:00, and `streak_grid_cache` never got today's row — `get_streak_grid_finished_dates` is a live query so the finished-dot still rendered, masking that only the cache-backed fill/count had gone stale). A restart "fixes" it by re-running the startup rebuild against the now-correct current day, which is why this is easy to misdiagnose as something else (an archived-book edge case was suspected and ruled out first). Fixed via `StatsPanel._arm_streak_rollover_timer()` — computes the exact next adjusted-day rollover instant (`_next_streak_rollover`) and arms a single-shot `QTimer` for that moment; `_on_streak_rollover()` rebuilds (no `reset_streak_grid_cache()` needed — a plain rollover doesn't change historical attribution, so the seed/flip logic's existing idempotency covers it) and reschedules itself. Also re-armed at the end of `_on_day_start_hour_changed` so a pending shot always tracks the current setting. Deliberately a self-rescheduling single-shot rather than a periodic polling timer — zero idle firing between rollovers, and it never runs on any panel open/close codepath. Full trace in NOTES.md, 2026-08-10.

**Consequence found 2026-08-18: this fix exposed a dormant gap in `StreakGrid.catch_up_streak_count`.** That method hardcoded `_pending_reveal_days = 0` on the assumption that a catch-up's newest grid cell could never already be `listened=1` when `set_data()` paints it — true only by accident of the staleness bug above, since `streak_grid_cache` could never contain a cell newer than the last startup rebuild. Once the rollover timer kept the cache genuinely current, that assumption broke: today's cell rendered lit immediately on panel reopen, before the pause-then-tick count-up even started, instead of popping in with it. Fixed by mirroring `animate_streak_count`'s existing grid tie-in — arm `_pending_reveal_days`/`_revealed_days` whenever there's a genuine increment to catch up on (`grew = previous is not None and current > previous`), so the shared `_run_streak_leg2` reveal suppresses and pops in the new cell(s) in sync with the counter, same as a live tab-click already does. **General lesson: fixing a staleness bug can retroactively make a previously-impossible code path reachable — re-check every downstream consumer's "this can never happen" comments, not just the write path being fixed.** Full trace in NOTES.md, 2026-08-18.

---

### Hover-preview theme application must never reach `_schedule_deferred_restyle` or any panel-level stylesheet
Previews are confined to main window, settings panel, and title bar via `get_base_stylesheet` — this
confinement is deliberate, not an oversight: a preview must not also restyle the library/stats/tags/
book_detail surfaces, which is real work avoided. **The confinement is narrower work, not cheap
work** — `mw.setStyleSheet(get_base_stylesheet(...))` targets the ROOT widget, so Qt re-polishes all
~642 descendants on every hover tick regardless. (Historical note: a rationale claiming the
confinement avoids "walking the whole widget tree" stood here until measurement killed it,
2026-08-01. The confinement stayed load-bearing for the reasons below; only its cost claim was
false.)

**The cost is not the sheet's SCOPE and not its CONTENT — this kills every content-based fix**
(measured 2026-08-02). `mw.setStyleSheet()` costs the same regardless of argument: the full 27-rule
sheet, a **single** `QWidget#mainwindow` rule, an **identical** re-set of the current sheet, and an
**empty** string all measure the same. Qt does not no-op an identical sheet, and clearing is as
expensive as setting. So: splitting the base sheet across the nine widgets its rules actually
target (all depth 1-2 under `mw`) saves **nothing**, and neither does emptying the root sheet by
moving the main-window background out of QSS — both were measured and are dead. Only *not calling
it*, or a shallower tree, helps. **Cost is panel-open-state dependent, not cadence dependent** (see
NOTES.md "hover-preview cadence vs. panel-state" for the full breakdown):
- **~430-440ms live** — theme apply with no panel/Themes-tab open (startup `apply_full_pass`,
  `_rotate_theme`, snapback-with-panel-closed). Matches the original n=120 organic-session figure.
- **~590-620ms live** — theme apply while the settings panel/Themes tab is open (hover preview,
  unhover snapback, panel-close snap-forward). **This is the figure that governs hover-preview
  responsiveness specifically** — it is what a user actually pays while browsing themes.
- Call cadence (fast/slow/organic-paced access) does **not** move either figure — confirmed across
  fast (~220ms), slow (paced past every debounce/fade constant in play), and human-jittered
  conditions, all landing in the same 588-620ms band regardless of pacing. Panel-open state is the
  variable, not timing between calls.
- An offscreen harness reads ~25% high on this same measurement — quote the live figures above, not
  an offscreen one.

Cost also tracks **visibility** (~22% higher with the four heavy panels shown, at identical widget
count) — consistent with the panel-open-state split above, not a separate effect. The multiplier is
tree DEPTH, not widget count (600 widgets flat = 11.9ms, the same 600 nested = 123.3ms, non-linear).
Note also that `_apply_stylesheets` has **no `hover` gate on any of its work** — a preview and a snapback do
identical work — so a design of the form "preview styles only the visible elements, revert reverts
only those" cannot be built on the current code without first adding that gate, which
`5cfe3a3` §2 records being reverted once as a regression. See NOTES.md 2026-08-02. A
preview must never be replayed through the same apply path as a genuine selection — any code that
drains, resumes, or re-applies a stashed/pending theme-change call must preserve whether that call
was a hover preview or a real selection, and a hover preview being replayed must stay confined to the
preview-safe surfaces, never reach `_schedule_deferred_restyle` (library/stats/tags/book_detail,
Sleep/Speed's per-button colors) or any other panel-level `setStyleSheet()`.

### DO NOT let `_pending_fade_call`'s stash tuple drop any `_on_theme_changed` parameter it needs to replay correctly
`_on_theme_changed`'s `elif _fade_running and not _hover_may_interrupt:` branch (`theme_manager.py:995`)
stashes a call that arrives while a fade is already in flight into `self._pending_fade_call`,
to be replayed once the fade settles by one of three drain sites: `_on_fade_finished`,
`snap_theme_forward`, `complete_main_fade`. As of 2026-07-22 this is a 6-tuple —
`(theme_name, save, fade_ms, hover, user_initiated, bypass_panel_open_guard)`. It was previously a
5-tuple that silently dropped `bypass_panel_open_guard`: `_on_theme_unhovered()` always calls with
`bypass_panel_open_guard=True` so its snapback can apply even while a panel is open, but a stashed
snapback replayed with the default `False` at every drain site, landing the replay in the
`_any_animating or _panel_open` guard branch instead of applying — which then queued it into the
single-slot `_panel_guard_timer`, a timer that gets disconnected/re-armed by every subsequent
hover-driven call, so the snapback could hang indefinitely instead of firing once the fade ended.
Fixed by widening the stash to carry the flag through (`8243959`; full trace in NOTES.md, 2026-07-22).
**If `_on_theme_changed`'s signature ever gains a new parameter that affects how a replayed call
should behave, it must be added to this stash tuple too, at all three drain sites, or the same class
of bug reopens for that parameter.** `snap_theme_forward` previously hardcoded
`bypass_panel_open_guard=True` on replay rather than reading it from the stash — this happened to
mask the drop (its only real trigger, the settings-close snapback path, always passes `True` at the
source anyway) but was still the wrong shape; it now reads the real stashed value. Before widening
this tuple again, re-confirm the same exclusivity check performed for `bypass_panel_open_guard`: no
call site may pass `hover=True` together with whatever new flag is being added set to a value that
would let the hover-preview confinement discard rule (`pending[3]`, unaffected by this rule) be
bypassed on replay — see the "Hover-preview theme application must never reach
`_schedule_deferred_restyle`..." rule area (2026-07-21) for why that confinement exists.

### DO NOT resume a panel-animation wait via a `finished` signal — and DO NOT drop `blur_animation` from `_any_panel_animating()`
Two halves of one fact: `_on_theme_changed`'s animation guard must wait for the blur, and it must
not wait for it by subscribing to a signal.

**Why the blur must stay in the predicate** (`panels.py`, `_any_panel_animating` — note the sibling
`is_any_panel_animating` deliberately EXCLUDES it, for the preloader): a ~300ms synchronous
`_apply_stylesheets` landing mid-blur-tween freezes it for **310.9ms** (measured offscreen on the
animation clock; 17.1ms worst gap without). "A blur tween isn't geometry so it can't hitch" is the
obvious instinct and it is wrong.

**Why the resume must not use `finished`:** `QPropertyAnimation.stop()` emits `stateChanged` but
**NOT** `finished` (verified empirically 2026-07-28), and `blur_animation.stop()` runs
unconditionally on every panel open (`_start_visual_area_blur`) and on blur-toggle-off. A
`finished`-based resume is therefore silently dropped — the same failure already diagnosed three
times against `_fade_anim` (see the three `stop()` comments in `theme_manager.py`).
`stateChanged` fails differently: it fires on that same `stop()`, mid-panel-open, *before* the
replacement blur starts — precisely the window the guard exists to protect.

`PanelManager.call_when_panels_settled` is the correct shape: **event-driven in effect** (resumes
within one 16ms tick of the true settle), **predicate-driven in mechanism** (re-checks
`_any_panel_animating()`, so `stop()` cannot drop it). It has NO per-call signal connection — one
permanent `timeout.connect` at construction, a coalescing flag, a waiter list — so double-fire is
structurally impossible and a stale connection is unrepresentable.

`_arm_settled_watch` must **never restart a running timer**. That early-return is what makes the
deadline absolute; `_panel_guard_timer` (which this replaced for the animating case) did
`stop()`+`start()` on every re-arm, so its deadline was retriggerable by mouse motion and a queued
call could starve indefinitely — the 2026-07-22 "snapback hangs" incident, whose fix addressed the
entry into the branch but left that property intact.

The `_panel_open` half still uses `_panel_guard_timer`, correctly: it ends when the USER closes a
panel, not on a clock, so there is no signal to subscribe to and 700ms is a re-check cadence rather
than an overshoot.

### DO NOT rely on a lambda's `w=worker`-style default argument to survive a signal connection when that signal carries its own payload
A `w=worker` default in `lambda w=worker: ...` only protects against the *closure* capturing a
mutated `worker` variable later (the classic late-binding trap) — it does nothing to stop Qt from
overwriting that default with a real positional argument when the signal being connected to actually
emits one. `CoverLoaderWorker.finished = Signal()` (cover_loader.py) is a no-argument signal, so this
pattern works everywhere it's used in that class (`library.py`'s `_active_workers.discard(w)`
cleanup lambdas, `stats_panel.py`'s equivalents) — Qt calls the slot with zero arguments and `w`
correctly falls back to its default. `_StatsHistoryLookupWorker.finished = Signal(list)`
(stats_panel.py, added 2026-08-08 for the Stats eager-cover-warm fix) carries the query result as
its one argument — connecting `lambda w=worker: self._day_active_workers.discard(w)` to it crashed
live (`TypeError: unhashable type: 'list'`) because Qt bound the emitted `list` to the lambda's first
positional parameter regardless of the default, landing the list into `w` instead of the worker.
Fixed by giving the emitted value its own real parameter name (`def _on_finished(books, w=worker):`)
so `w` is never in the collision path. Before copying a `w=worker`-default cleanup lambda onto a new
signal connection, check whether that signal is genuinely no-argument like `CoverLoaderWorker`'s — if
it carries a payload, the payload needs its own named parameter, not a second default-argument slot.

### A shared, session-lifetime cache (`_cover_cache`, `_sized_cover_cache`, etc.) resets to empty on every app restart — "warmed once this session" is not "warmed," it recurs every launch
Confirmed the hard way (2026-08-08, Stats Day-tab cover-flash investigation): an early read of this
bug treated the first-ever-load-per-book flash as the same rare, accepted edge case the 2026-06-04
carousel fix (`b20a08e`) left in place — reasoning that a book only flashes once per session, so it's
a minor cosmetic cost. That framing missed that "once per session" is not "once" for a cache that
starts empty on every launch: a tab that surfaces many distinct books quickly (Day tab backfilling
through months of listening history) hits this "rare" case constantly, every single session, for
every book the idle preloader hasn't reached yet or structurally can't reach (see the preload-scope
consequence above). Before characterizing any cache-miss cost as "accepted" or "rare" because it's
gated on "has this book been seen this session," check what resets the cache and how often that reset
actually happens in real use — a session boundary that recurs on every app launch is not a rare
boundary.

### A design document you read yourself is not the same as the actual commit — re-derive a cited historical fix from its real diff before treating a summary of it as settled
The same 2026-08-08 investigation initially cited "the June carousel fix accepted the first-visit
cold-cache flash, per SESSION.md/NOTES.md" as grounds for treating the Stats Day-tab flash the same
way — before reading the actual commit (`b20a08e`) itself. The real diff shows something narrower and
different: `FinishedBookThumb.__init__` was restructured to check `_cover_cache` BEFORE ever
constructing or showing a placeholder, and `_on_cover_loaded` was fixed to write the load result INTO
`_cover_cache` (previously discarded) — together, these make a cache hit skip the placeholder
entirely and make every subsequent visit convergently warm, not "accept" anything. The prose summary
in SESSION.md ("First-visit cold-cache flash... is accepted") was accurate as written — about a
genuinely narrower residual case — but got silently widened into "the flash in general is an accepted
design tradeoff" over the course of the investigation, without re-checking the source. When a
historical fix is being cited as precedent for how to treat a current bug, read the actual commit
diff, not a remembered or restated summary of it — a summary can be locally correct and still mislead
about scope when reused for a different decision.

### A blur overlay can only cover what shares its parent — `raise_()` does NOT cross parents, and a panel's own QSS wash always paints under its children
Two Qt facts, one shared consequence: an overlay meant to sit *behind translucent content* must be a
child of the widget it is frosting, and the wash must be composited into its pixmap. Both halves were
learned by shipping the wrong thing first (2026-08-01, Book Detail frost).

**`raise_()` only reorders a widget among its OWN siblings.** `TransportBarBlurOverlay._overlay` is a
child of `content_container`; every full panel is a child of `main_window`, raised above it. So the
shared overlay can climb to the top of `content_container`'s children and *still* sit under any
panel — `raise_()` cannot lift it across that boundary. The first Book Detail attempt shipped
completely invisible this way: the log showed 37 correct calls, the right rect, a non-null pixmap and
a completed grab, and nothing on screen. It works for Settings/Speed/Sleep/Stats/Tags **only because
they are 90% width** — the uncovered remainder is the part you actually see. A full-width panel
exposes it totally. `frost_panel_backdrop` therefore parents the frost to the PANEL
(`panel._backdrop_frost`), which makes stacking correct by construction. Do NOT "fix" a future case
by reparenting the shared overlay to `main_window` — that is the documented 2026-07-19 pink-wash
trap, and it would perturb five panels that work today.

**A panel with `WA_StyledBackground` paints its wash BEFORE any child**, so no child can sit beneath
it. `frost.lower()` reaches only the bottom of the *child* stack — still above the wash. The second
attempt did exactly that and covered the `rgba(bg_main, panel_opacity_hover)` wash with an opaque
snapshot, which read as "the panel's background was removed" and made the foreground **harder** to
read — the precise opposite of a frost's purpose. The fix is to paint the wash INTO the frost pixmap
(`QPainter.fillRect` with the live theme's `bg_main` at `panel_opacity_hover`), so the frost is the
finished backdrop and its position in the child stack stops mattering.

**Diagnostic that settled both**, worth reaching for before theorising: dump the raw grab, the
blurred result, and a post-paint window grab, and log `same_parent` / the overlay's sibling index. A
correct pixmap that never appears is a compositing problem, not a grab problem — that one check
eliminated every grab-timing theory at once.

### DO NOT make any panel-dismiss path depend on a *stashed* snapback to restore the active theme
`_close_settings_flow` (`panels.py`) must call `_on_theme_unhovered()` — which issues a **fresh**
snapback — *before* `snap_theme_forward()`; `hide_all_panels` and `handle_drag_area_right_click`
follow the same ordering. That ordering is what guarantees the active theme is applied when a panel
is dismissed while an unselected preview is showing.

It is load-bearing because `_on_theme_changed`'s interrupt site clears `_pending_fade_call`
whenever a newer call claims the fade slot (added 2026-07-28 — `_fade_anim.stop()` emits no
`finished`, so a stash left against a stopped fade is never drained by the site meant to drain it
and instead fires against the *next* fade: the 775ms flash-then-revert). The clear is correct, and
the dismiss ordering is what makes it safe. **A dismiss path that instead relied on a stashed
snapback would silently strand the UI on an unselected preview** — no exception, no failing test,
just the wrong colors persisting after the panel closes.

This is a silent structural precondition that no assertion enforces: `tests/test_fade_drain.py`
pins today's drain behaviour but cannot stop a future refactor from routing a dismiss path through
the stash. Same shape as the "content change that produces no Paint event strands the blur cache"
class — if you change any dismiss path, re-verify it issues its own snapback rather than inheriting
one.

#### The Themes tab's hover machinery vs. the blur grab's synthetic events — one shared fact, four consequences

**The shared fact:** with the transport-bar blur effect enabled,
`transport_bar_blur._grab_and_blur` hides and re-shows the active panel roughly every ~65-200ms
while a book plays, in order to grab a clean backdrop. Every one of those hide/show cycles fires
**synthetic** enter/leave events on `swatch_box` and every descendant widget in between — events Qt
delivers identically to real ones. So every piece of the Themes tab's hover machinery has to answer
one question correctly: *did the user actually leave, or did the blur grab just blink the widget?*
Getting that wrong in either direction is a shipped bug — three distinct times so far, plus a layout
consequence from the containment fix.

Current wiring: **`swatch_box.leaveEvent` is the SOLE trigger** for
`ThemeManager._on_themes_tab_left(tab_widget)` (`theme_manager.py`, near `_on_theme_unhovered`).
That method's first check is `tab_widget.isVisible()` — a leave arriving while the widget is hidden
is the blur grab's, not the user's.

Consequences of this shared fact, each independently load-bearing:

**1. Never add a second bare `_on_theme_unhovered()` lambda anywhere in the Themes tab hierarchy.**
A deliberately-still hover on a theme swatch could
silently never convert into an applied preview (confirmed live 2026-07-22: a genuine
`enterEvent PASSED` followed 7ms later by a leave recorded as synthetic, with no
`[hover debounce] firing preview` line ever appearing). Root cause: `themes_tab.leaveEvent` and, at
the time, `pool_container.leaveEvent` were bare `lambda _: mw.theme_manager._on_theme_unhovered()`
lambdas with no equivalent of `ThemeItem`'s own `_last_leave_was_synthetic` suppression (see the
2026-07-21 heartbeat fix above), so a grab-fired synthetic leave called
`_hover_debounce_timer.stop()` unconditionally. A grab tick landing inside the swatch's 80ms
`_HOVER_DEBOUNCE_MS` window — likely at that cadence — killed the debounce before it could fire.

Fixing only the OUTER container was insufficient, confirmed live rather than assumed from the shared
lambda shape: a caller-identifying trace showed 133 of 134 calls in one hover session came from
`pool_container.leaveEvent`, not `themes_tab.leaveEvent` — the inner widget receives the grab's
hide/show before the cursor's hit-test ever reaches the outer one. Both wirings were later removed
when `swatch_box` was introduced (consequence 3), but **the lesson stands regardless of which widget
currently owns it: do not add a new bare `lambda _: mw.theme_manager._on_theme_unhovered()` anywhere
in the Themes tab hierarchy** — any future container needing unhover-on-leave must route through
`_on_themes_tab_left`, or this bug reopens for that container. NOTES.md, 2026-07-22.

**2. DO NOT replace the visibility check with a cursor-position/delta test.**
The `isVisible()` premise was re-verified by counting (2026-07-28): over a full live session, 6 real
mouse-outs, ALL `visible=True`, all at the right-hand edge (x = 254, 254, 256, 254, 254, 238) exiting
toward the dismiss sliver — and 12 leaves classified genuine while hidden, all false positives.
A delta test was tried twice on 2026-07-28, both times reasoning from a single trace, and both
attempts shipped a regression:
1. Position vs. the last genuine ENTER, consuming the reference on a genuine leave — every later
   synthetic leave hit the `None` fallback and fired a snapback (~70 in 5s, cursor frozen at
   `pos=(222,271)`).
2. Position vs. the last LEAVE (rolling reference) — consecutive synthetic leaves are ~65ms apart,
   so a cursor merely MOVING ACROSS the swatch area travels 4-14px between them, past the jitter
   threshold. Every one read as genuine, and `_on_theme_unhovered`'s `_hover_debounce_timer.stop()`
   killed the 80ms debounce ~15x/sec — previews never fired while the cursor was in motion. That is
   consequence 1's bug, reopened by a different route.

Both share one root error: inferring "did the user leave?" from cursor deltas when the widget's own
visibility answers it directly. A position check remains ONLY as a secondary guard for a leave
delivered while VISIBLE with the cursor unmoved (a stylesheet-cascade artifact); it anchors to the
last genuine ENTER (`_last_swatch_pos`, written only by `_on_theme_hovered`), never to the last
leave, and is never consumed. `_MOUSE_JITTER_PX` (2) absorbs sub-pixel reporting noise there. Both
failed variants are pinned by tests that fail against them
(`tests/test_hover_interrupts_snapback.py`).

**The `[SWATCH-LEAVE-SUSPECT]` probe — contract CHANGED, read this before acting on a hit.** The
probe fires at WARNING when a leave is suppressed while hidden AND the cursor is outside
`swatch_box`'s bounds. It was added as a **falsification probe** for this branch's premise ("a real
mouse-out never arrives while hidden"), originally carrying a `grep -c "SWATCH-LEAVE-SUSPECT"` →
**must be 0** contract. **That premise was falsified live on 2026-08-03, and the probe was upgraded
from detect-only to detect-and-correct on 2026-08-05** (`17d46e2`,
`review/Design_260805_swatch_leave_suspect_correction.md`): the `if outside:` branch now calls
`_on_theme_unhovered()` immediately after the warning log. **A non-zero count is therefore the
expected, handled case — it is no longer a signal to revert anything.** Correcting unconditionally
here is safe because this condition is not an inference: unlike the sibling jitter guard (which
infers intent from a position *delta*, with the two documented false-positive regressions above),
it is a direct geometric fact — is the cursor outside the rect right now — independent of *why* the
widget is hidden. Before the correction landed, this gap produced real stuck windows of 62s, 80s,
106s, 125s and 277s within single sessions, with `_is_hover_active` stranded `True` and nothing to
clear it, starving `transport_bar_blur`'s `hover_active_gate` for the whole window. The probe's log
lines still carry the cursor pos and widget rect and remain the diagnostic for this branch — keep
them.

**3. The hover-active region is `swatch_box` only — not the whole Themes tab, not `pool_container`.**
As of 2026-07-22, hovering a theme swatch only keeps previewing while the cursor stays inside
`swatch_box` (`main_window_builders.py`, `build_themes_tab`) — a narrow container holding ONLY the
"Cover art based theme" entry and the theme swatch rows. The "Theme pool" header, the Add
all/Remove all/Change now row, and the Interval Selection row all sit outside it (still inside the
wider `pool_container`, which now exists ONLY as the Exclusive-mode show/hide unit — see
`update_cover_art_mode_visuals`, `theme_manager.py`). Moving onto any of those, or off the tab
entirely, reverts the preview to the active theme — previously the whole tab (then the whole
`pool_container`) counted as "still hovering," so moving onto the header/buttons/interval row while
a preview was showing silently left it stuck. Do not re-add `themes_tab.leaveEvent` or
`pool_container.leaveEvent` wiring; both were removed when `swatch_box` was introduced specifically
to avoid a duplicate/racing revert trigger.

**4. `_swatch_leave_backstop_timer` covers a THIRD failure mode — the visible-branch jitter guard's
own false-suppression case, not a reopening of either regression above.**
Confirmed live twice (2026-08-02, `review/Investigation_260802_swatch_leave_jitter_suppression.md`):
hovering a swatch near `swatch_box`'s own edge, then leaving toward the gutter, can report a
`leaveEvent` position within `_MOUSE_JITTER_PX` (2px) of the recorded enter position — **not**
because the cursor failed to move (the case that check exists for), but because a genuine boundary
crossing at a shallow angle or short distance is itself small relative to the tolerance. Both repros
showed `ThemeItem.leaveEvent` and `swatch_box.leaveEvent` firing in the same millisecond at the
identical position, ruling out a stale-cursor-sample theory. Structurally independent of blur and
panel-backdrop mode (reproduced identically in Frosty and Transparent) — the misfiring branch
(`visible=True` jitter check) never reads blur/backdrop state at all; only its sibling does.

This is in the **visible-widget** branch, where the compared delta is doing exactly what it was
designed to do — the tolerance is just too narrow for a real, short crossing. Narrowing/widening
`_MOUSE_JITTER_PX` or changing what it compares against was explicitly ruled out (same class of risk
as the two regressions above); the guard's condition, constant, and reference semantics
(enter-anchored, never consumed, never rolled forward) are all unchanged.

**The fix (2026-08-03, `1a82c11`) is a periodic backstop, not a guard redesign.**
`ThemeManager._swatch_leave_backstop_timer` (a repeating `QTimer`, `_SWATCH_LEAVE_BACKSTOP_MS = 500`)
is armed/disarmed **only** inside `_mark_theme_applied` — the sole writer of `_is_hover_active` — on
its `False`↔`True` transitions, so it only ticks while a preview is genuinely showing. Its tick
(`_check_swatch_still_hovered`) asks a structurally different question than the jitter guard: an
**absolute** cursor-vs-`swatch_box`-rect containment check, using the same
`mapFromGlobal`/`rect().contains()` pattern the `SWATCH-LEAVE-SUSPECT` branch uses. It never compares
two time-adjacent samples, so it cannot reproduce either regression: there is no reference to consume
(attempt 1's failure), and no pair of close-in-time leaves to compare (attempt 2's failure) — one
absolute check against one static rect, on a 500ms cadence far outside the ~65-200ms grab cadence
that made those attempts fail. On finding the cursor genuinely outside while a preview is active it
calls the existing `_on_theme_unhovered()` — this backstop widens WHEN that call can fire, never what
it does.

**Dismiss-time correctness needed no new code.** `_close_settings_flow` (`panels.py:1379-1383`)
already calls `_on_theme_unhovered()` unconditionally on every Settings dismiss, regardless of timer
or leave-event history — confirmed in both repro logs, where the dismiss click forced the theme back
even after the preview had been stuck 7s and ~34s. A fast edge-out-then-immediate-dismiss-click was
a stated concern before this fix and was already closed by that call, which is why the backstop only
covers the DWELL window (a stuck preview visible for a noticeable duration), not dismiss itself.

**Cost is logged permanently, unconditionally, from the first commit — not added later if found
expensive.** `[SWATCH-BACKSTOP-COST] tick=X.XXXms` fires on every tick regardless of outcome. This
was a deliberate requirement (not an afterthought): the timer can stay armed for several seconds
during genuinely common usage on this app (deliberate slow hovering to compare theme colors), and
"this is surely negligible" has been wrong before on this exact codebase — the `_apply_stylesheets`
cost investigation (2026-08-01/02, see the section above) started from exactly that kind of
unverified assumption. Do NOT downgrade this log to DEBUG or remove it as "clearly fine" without
first checking a real session's worth of `[SWATCH-BACKSTOP-COST]` lines.

Full design rationale, the side-by-side comparison against both 2026-07-28 failed redesigns, and the
cost analysis showing dismiss itself pays no new cost (an already-corrected `_is_hover_active` hits
`_on_theme_changed`'s existing cheap no-op guard) are in
`review/Design_260803_swatch_leave_jitter_backstop.md`.

---

### `QPushButton#theme_item`'s vertical padding must stay small enough that its `sizeHint()` doesn't exceed what `swatch_box` can actually give it
A layout consequence of introducing `swatch_box` (consequence 3 above), not a hover-machinery rule.
`settings_panel` is a fixed 500px-height widget with no scroll area (see the "DO NOT try to expand a
widget's height inside the Library settings tab's `QVBoxLayout`" rule below) — `pool_container`'s
total budget inside it is a genuine, non-negotiable remainder after every sibling above/around it
claims its own space, not a solvable margin puzzle. When `swatch_box` was introduced, the theme
swatch rows started rendering 5px shorter than their own
`sizeHint()` (20px actual vs. 25px wanted, confirmed via live geometry logging, NOT guessed) —
silently clipping the active-theme underline (`QPushButton#theme_item[active_display="true"]`,
`text-decoration: underline`) and glyph descenders (e.g. the 'g' in "Slow Regard"). **Do not try to
fix this by giving `swatch_box` more room** — `setMinimumHeight`, size-policy changes, and swapping
`themes_layout`'s trailing `addStretch()` for a fixed `addSpacing()` were all tried live and each
failed or actively made it worse (the `addSpacing()` swap shrank `pool_container` further, since a
fixed trailing demand competes for the same constrained budget differently than a stretch that can
shrink to zero when nothing needs the space — confirmed via before/after geometry logs, not
theorized). **The fix that actually worked**: reduce the padding itself
(`QPushButton#theme_item, QPushButton#theme_interval_btn`, `themes.py`, `padding: 4px 0px` →
`padding: 1px 0px`) so the button's natural `sizeHint()` shrinks to roughly match the space it was
already being given, instead of asking for space that structurally isn't there. `theme_interval_btn`
shares this rule but is unused in practice (no widget is ever given that object name — the interval
row uses `QLabel#theme_interval_label` instead), so this change only affects `theme_item` swatches.
A follow-up `pool_layout.addSpacing(10)` between `swatch_box` and the Add all/Remove
all/Change now button row added real breathing room, now that the padding fix had genuinely freed
slack (as opposed to the earlier `addSpacing()` attempt, which had nothing real to reclaim). Full
before/after geometry numbers and the failed-attempt trail in NOTES.md, 2026-07-22 — read it before
re-attempting a layout-level fix for this widget class; this is the same underlying lesson as the
"user sees the rendered pixels" and "do not verify a settings-panel layout bug with headless
scripts" rules — live geometry logging, not guessed theory, is what actually found this one.

---

### DO NOT add a key to "The Color Purple" without checking `_NO_BASE_INHERIT_KEYS` (themes.py)
Every theme is resolved by `_resolve_theme()` as `THEMES["The Color Purple"].copy()` overlaid with
the requested theme's own dict — "The Color Purple" is the base template every other theme
inherits from for any key it doesn't set itself. This is correct for plain literal-value keys
(a theme that doesn't set `bg_deep` should get Purple's), but WRONG for any key whose intended
"unset" behavior is a *derived* per-theme fallback rather than Purple's literal value — e.g.
`streak_grid_outline`/`streak_grid_dot` (meant to fall back to a value derived from that theme's
own `accent`, via `StreakGrid._derive_longest_fill`/`_derive_finished_dot`) and `slider_progress`
(meant to fall back to `text_on_light_bg` → `text`). Without exclusion, Purple's literal value
would silently inherit into every theme that doesn't define its own, masking the derived fallback
entirely. `_NO_BASE_INHERIT_KEYS` (a tuple near `_resolve_theme`) lists every such key; `_resolve_theme`
pops them from the copied base before overlaying. **Any new optional/fallback-driven theme key
that "The Color Purple" itself ever defines a value for MUST be added to `_NO_BASE_INHERIT_KEYS` in
the same change** — added 2026-06-19 (Session 4): the five tassel/bookmark keys
(`bookmark_body`/`bookmark_icon`/`tassel_cord`/`tassel_head`/`tassel_fringe`) do NOT need to be in
the tuple today because "The Color Purple" doesn't set any of them yet — but if it ever does (e.g.
giving the reference theme an explicit tassel color), that addition must land together with adding
those keys to `_NO_BASE_INHERIT_KEYS`, or every other theme that relies on the
`tassel_cord`/`tassel_head` → `tassel_fringe` → `accent_light` fallback chain will silently start
showing Purple's literal tassel color instead.

### DO NOT fold `animate_conceal` duration logic into `HourlyHeatmap.animate_reveal`
`animate_conceal` (on both `HourlyHeatmap` and `StreakGrid`) is **additive-only**: it reuses the `reveal_progress` property in reverse (1.0→0.0, 600ms) and is the streak↔heatmap transition's drain phase. `HourlyHeatmap.animate_reveal` and `paintEvent` stay byte-for-byte unchanged. `animate_conceal` restores the 1000ms reveal duration in its `finished` callback so the following construct wave runs full-length, and tracks its pending slot in `self._conceal_slot` (disconnect only when present — avoids `Failed to disconnect (None)`). The asymmetric duration restore is the whole point; do NOT share a `setDuration(600)` between the two methods. Relatedly: `StreakGrid.set_data` must NOT call `animate_reveal()` — the caller (`_switch_timeline_view` / `_on_tab_changed`) fires exactly one reveal on the visible grid, else the tab-change reveal double-fires and hitches.

### DO NOT give the label-cascade enter/exit `_label_local` the same opacity-window formula
`HourlyHeatmap`/`StreakGrid`'s per-label cascade (top date labels, left-gutter date/hour labels) must
use a DIFFERENT window-placement formula for entering vs. exiting, not the same formula run with
`_label_progress` going the other direction. Enter anchors each label's fade-in window from the START
of the timeline (`start` to `start + span`); exit must anchor from the END (`end - span` to `end`,
where `end = 1.0 - start`). Reusing the enter formula for exit (just feeding it a falling
`_label_progress`) silently breaks because clamping (`max(0, min(1, ...))`) masks the asymmetry: the
"leading" label ends up holding at full opacity until late in the exit animation instead of fading
first, which reads as the wrong cascade direction even though the per-label rank assignment
(`cascade_pos`) is correct. This was found and fixed 2026-06-18 — see NOTES.md "Timeline tab visual
rework" for the verification approach (hand-computed opacity at several progress values per rank
before trusting it visually). Also: `_label_sweep_in` must be initialized in `__init__` (both
classes) — it was previously only ever set inside `animate_labels_in`/`animate_labels_out`, so the
very first paint before either had run raised `AttributeError`.

### DO NOT keep the streak count-up's "previous shown" value in-memory only
`StreakGrid.animate_streak_count(previous=...)` needs to know the streak value as of the last time it
actually animated, to decide whether to run the pause-then-tick second leg. That value MUST be
persisted via `Config.get_last_shown_streak()`/`set_last_shown_streak()` (QSettings-backed), not kept
only in `StreakGrid._last_animated_streak` (in-memory instance state). An in-memory-only value resets
to `None` on every app launch, so the session's first reveal always falls into the "no prior value,
skip the pause" branch — even when the streak genuinely grew while the app was closed. `None` (not
`0`) is the correct "never tracked" sentinel: defaulting to `0` would make a pre-feature upgrade with
a real non-zero streak misread "never tracked" as "previous was 0" and spuriously play a 0→N
pause-then-tick that implies growth from nothing.

### DO NOT let the Stats panel's Timeline slide-reopen skip the streak catch-up tick
`QTabWidget.currentChanged` only fires when the active tab index changes. If the Stats panel slides
open with Timeline already the remembered active tab (the normal case — panel was last closed on
Timeline/Streak), `_on_tab_changed` never runs that session; the only code path is
`refresh_current_tab() -> _refresh_time() -> StreakGrid.set_data()`, which correctly never animates the
grid (slide-reopen must never animate grid cells/labels — established rule, see the `animate_conceal`
rule above). Without an explicit exception, that same flow also silently swallowed the streak
count-up: `set_data()` snapped the number straight to its new value with zero comparison against the
persisted previous value, so a streak that grew while the panel was closed showed the new number with
no visual call-out at all. Fix: `StatsPanel._refresh_time(streak_mode=...)` takes `"full"` (tab click /
view-switch seam — runs the normal two-leg `animate_streak_count()`), `"catch_up"` (wired only from
`refresh_current_tab`'s Timeline branch — calls `StreakGrid.catch_up_streak_count(previous)`, which
snaps to the old value and ticks to the new one WITHOUT touching the grid at all), or `"none"`
(background refreshes like `refresh_all` — leaves `set_data()`'s plain snap untouched). This is the
one deliberate place where the streak number's animation rule diverges from the grid's blanket
"never animate on slide-reopen" rule — the grid stays fully static every time, the number gets a
narrow exception so a real change is never silently dropped.

### DO NOT animate a UI count-up toward a target derived from a coarser/truncated value than what live tracking will show
`_animate_percentage_label`'s tween must compute its end value as `round((new_progress/dur)*100, 1)`
— the SAME rounding the live 200ms tracker uses (`f"{percent:.1f}%"`) — not by re-deriving a percent
from the progress slider's `new_val` (`int((new_progress/dur)*1000)`, which TRUNCATES to the
slider's coarser 0-1000 scale). A true value like 739.97 truncates to slider tick 739 ("73.9%") but
rounds to "74.0%" — every book whose saved progress rounds up in its last digit reproduced a
guaranteed one-tick jump the instant the live tracker resumed after the tween. This is a
truncate-vs-round MATH mismatch, not a timing race — a settle-delay guard was tried first and
confirmed not to fix it (the jump was identical with or without the delay). Any future animated
label that shares a "coarse slider scale" data source with a "precise live display" must independently
verify both sides actually agree on rounding before assuming a delay/guard will paper over a gap.

### DO NOT trust a callee's busy/no-op guard to protect a caller's OWN side effects
`TasselOverlay.play()`'s `_busy` flag correctly no-ops repeat calls for the bookmark slide animation
itself, but `StatsPanel._on_tassel_clicked` also independently calls `_switch_timeline_view()` on
every click — and that call was NOT gated on anything, so rapid clicking queued up multiple
overlapping `_switch_timeline_view()` cycles (each its own `animate_conceal`/`animate_labels_out`
pair) racing over the same grid visibility state, which could hang the Timeline view indefinitely
with both grids left hidden. Fixed via a public `TasselOverlay.is_busy` property that
`_on_tassel_clicked` checks itself before doing anything. General rule: if a caller triggers a side
effect ALONGSIDE calling a method that has its own internal busy/idempotency guard, the guard
living inside that method does not protect the caller's side effect — the caller must check the
same busy state itself (via an exposed property, not by assuming the callee's no-op will be enough).

### DO NOT let `TasselOverlay`'s hand cursor and clickable region diverge
`TasselOverlay.__init__` does NOT call `setCursor(PointingHandCursor)` on the whole widget — that
was the original (2026-06-19) implementation and it was a real UX bug: the widget is wider/taller
than its actual clickable area (the tab rect plus the tight tassel body box, via
`_in_hit_region()`), so a blanket cursor showed a hand over dead space where clicking did nothing.
The cursor is instead set dynamically in `mouseMoveEvent`, calling `setCursor`/`unsetCursor` based
on the exact same `_in_hit_region()` test that `mousePressEvent` uses. Any future change to the
clickable region (`_tab_rect`, `_tassel_rect`) must keep reading through `_in_hit_region()` from
both methods — do not special-case the cursor logic or the click logic separately, or they will
silently drift apart again.

### DO NOT use `load_themed_icon` for `currentColor` SVGs — use `load_currentcolor_icon`
clock.svg / calendar.svg use `fill="currentColor"`. `load_themed_icon` only swaps `fill="#000000"`; it happens to tint these anyway via its `<style>`-injection fallback, but that is incidental, not contractual. `load_currentcolor_icon` recolors `currentColor` explicitly via regex (mirrors `render_logo_placeholder`). Use it for these icons; do not "simplify" back to `load_themed_icon` on the theory they're equivalent.

### DO NOT call `search_field.setText(...)` directly anywhere in `LibraryPanel` outside `set_search`/`clear_tag_filter_if_active`
Every direct write to the library search field must go through `self._programmatic_search_update = True` / `setText(...)` / `= False`, or through `clear_tag_filter_if_active()` (which already does this). `_on_search_changed` reads any unguarded `setText` as genuine user typing and overwrites `self._explicit_filter_text` — the value click-filter toggle-off/revert (author/narrator/year re-click, library reopen, left-click into the field) restores to instead of clearing to `""`. This bit twice in one day (2026-07-05, `6847330` and `a7271a5`) via two DIFFERENT pre-existing direct-`setText` call sites (`clear_tag_filter_if_active`'s old body, `focusInEvent`'s handler) that predated the guard and were never routed through it. If a new call site ever needs to change the field's text programmatically, route it through the guard or through `clear_tag_filter_if_active()` — never call `setText` on `search_field` bare.

### DO NOT use `active_cover_changed` on `BookDetailPanel` as a single-arg signal
It emits `(book_path, cover_path)` — both args required at all call sites. `CoverPanel.active_cover_changed` remains `Signal(str)`; the intermediate slot `_on_cover_panel_changed` in `BookDetailPanel` injects `self._book_path` and re-emits. Do not connect `CoverPanel.active_cover_changed` directly to `BookDetailPanel.active_cover_changed`.

### DO NOT pass raw DB rows directly to `StatsRowModel` or `FinishedBookThumb`
Always call `StatsPanel._inject_active_covers()` on the row list first. Raw rows carry only `cover_path` (scanner thumbnail); `_inject_active_covers` adds `active_cover_path` from `book_covers`. Skipping it causes stats panel thumbnails to show scanner art instead of the user-selected cover. (Heading formerly named `BookDayRow`, the widget-per-row class `StatsRowModel`/`StatsRowDelegate` replaced in the 2026-08-05/09 Stats delegate migration; the rule is unchanged and applies at every row site.)

### DO NOT remove the `has_progress` gate on speed application in `BookDelegate._resolve_playback`
Speed is only applied to `dur_disp` when `has_progress` is `True`. Books with no progress always show total duration at 1x regardless of per-book speed. Removing this gate causes incorrect duration display in the library view.

### DO NOT lay out a library row from the live viewport width — reserve the scrollbar's space
Any per-row geometry with **right-aligned** content (author, time column, progress %) must NOT derive its width or right edge from `option.rect.width()` / `r.right()` (the live viewport), because that value drops by `SCROLLBAR_EXTENT` (14px) when the vertical scrollbar appears and regains it when the scrollbar disappears — so filtering, which shrinks the list and toggles the scrollbar, makes right-aligned content jump by 14px. Lay out against a **stable** width/right edge that reserves the scrollbar gutter unconditionally: `BookDelegate._row_content_width(...)` (= `view.width() - 2*frameWidth - SCROLLBAR_EXTENT`) and `_row_stable_right(r)` (the stable right-edge x, use in place of `r.right()`) — 2026-07-06. The view width is fixed (the scrollbar takes space *inside* it, shrinking the viewport but not the view), so this is constant regardless of scrollbar state. Left-aligned content (title, the progress bar itself) is unaffected. **Fixed in both List (`_list_author_layout`, commit `9c20f40`) and 1-per-row (`_paint_one_per_row`, commit `9f8b06f`).** When adding ANY new right-aligned row content in ANY mode, route it through `_row_stable_right`/`_row_content_width`, never `r.right()`/`option.rect.width()` directly.

### DO NOT size a fixed-width IconMode grid cell against the nominal viewport width with zero slack
`QListView`'s default `frameWidth()` is 1px, taken off BOTH sides of the viewport (2px total) — the
real usable width for column math is `nominal_width - 2*frameWidth`, not the nominal width itself.
Confirmed live (2026-07-10): sizing 2-per-row's cell at `w=146` so `2*146` landed exactly on the
292px nominal viewport (zero slack) silently collapsed the grid to a single column — Qt had no
room to fit two cells once the real frame-adjusted width (290) was accounted for. Fixed by using
`cell_w=145` (`2*145=290`). Any future fixed-width grid-cell sizing in `library.py` must budget
against the frame-adjusted width, or verify live that the exact intended column count actually
renders — this failure mode is silent (no error, no log, just fewer columns) and is NOT caught by
arithmetic that only checks against the nominal window width.

### DO NOT use a uniform per-cell margin when a grid mode needs a middle gap smaller than its outer margins
For two adjacent cells sharing a uniform left/right margin `L`/`R` (every grid mode before
2-per-row), the visual gap between them is always `R + L` — with the normal symmetric case
(`L == R`), that's `2L`, exactly double the outer margin, for any `L`. There is no way to make the
middle gap SMALLER than the outer margins with a single per-mode margin; it requires per-COLUMN
margins instead. `BookDelegate._TWO_PER_ROW_LEFT_MARGIN` (a 2-tuple, one entry per column, derived
from `index.row() % 2`) is the pattern: column 0 gets a wide left / narrow right, column 1 gets the
mirror image, so the shared middle gap (`right_of_col0 + left_of_col1`) can be tuned independently
of the outer edges. `_cover_rect()` and `cover_cell_size()` must stay in lockstep with this (both
already take/use the column) — any new per-cell geometry in a multi-column mode that needs
independent outer/middle spacing should follow this same column-aware shape rather than trying to
force it out of a single margin value.

---

#### `_sized_cover_cache`/`_get_sized_cover` — one shared fact, three consequences

This cache is load-bearing, not a performance nicety layered on top of an already-correct render.
Confirmed by direct measurement (2026-06-24): the scanner-side fixes alone (cover discovery,
LANCZOS thumbnail resampling, 320×480 cap) produced **zero visible improvement** in the library
grid, even after a full force rescan + app restart. The reason is `_draw_cover`'s own
`painter.drawPixmap(rect, cover, src_rect)` — a single Qt bilinear downscale straight from the
cached thumbnail (up to 320×480) down to the real cell size (as small as ~88×88) — which erases a
better source's quality gain regardless of how good that source is. `_get_sized_cover` exists
specifically to remove that downscale's *magnitude* (pre-shrink close to cell size via LANCZOS
first, so the final `drawPixmap` is a near-1:1 blit).

1. **DO NOT remove `_sized_cover_cache`/`_get_sized_cover` as "just an optimization."** If this cache is ever removed or bypassed, the library grid will silently regress to the exact "no visible difference" state this was built to fix — the scanner-side quality work is necessary but was proven, by measurement, insufficient on its own.
2. **DO NOT change `_get_sized_cover`'s scale mode to `KeepAspectRatioByExpanding`.** `_get_sized_cover` (`BookDelegate`, `library.py`) pre-scales the cached cover to roughly the grid cell size before `_draw_cover` runs its square/crop/letterbox branching. It deliberately uses a plain aspect-preserving bounded fit (scale by `max(dev_w/w, dev_h/h)`, same shape as `KeepAspectRatio`), NOT `KeepAspectRatioByExpanding` cropped exactly to the cell. This looks like the "more correct" choice for a pre-sized thumbnail cache — it isn't: `_draw_cover`'s letterbox branch needs the pixmap's real, uncropped proportions to compute its own centered inset; feeding it an already-cell-cropped pixmap breaks letterbox specifically while leaving the square/stretch/crop branches looking fine, so the bug would only surface on covers whose aspect ratio lands in the letterbox bucket (>8% ratio mismatch from the cell). Also do not raise the `UnsharpMask` strength in `_lanczos_qimage` (currently `radius=0.8, percent=25`; this is where the scale logic lives as of 2026-07-04 — `_lanczos_scale` is now just its main-thread `QPixmap` tail) without re-checking against a *photographic* cover, not just a flat-color graphic one — a stronger pass (`percent=60` was tried and reverted) reads as fine on graphic art but produces visible edge haloing on photographic gradients (skies, faces), described by the user as "out of focus, then we slapped an HDR filter on it." Full root-cause writeup in NOTES.md, 2026-06-24.
3. **DO NOT write `_sized_cover_cache` from a worker thread, read DPR off the main thread, or let the preloader's key drift from `_get_sized_cover`'s.** The idle preloader warms `_sized_cover_cache` off-thread (2026-07-04). Three invariants make that safe; all are load-bearing:
   - **The scale is split for thread-safety.** `_lanczos_qimage(QImage→QImage)` (the PIL LANCZOS + UnsharpMask) is the ONLY part that may run on a `CoverLoaderWorker` thread — it touches only `QImage` (a pure raster container) and PIL. `QPixmap` is a GUI-thread-only paint device: creating or reading one off-thread is undefined behaviour (works sometimes, crashes others). So the worker emits a `QImage` (`sized_cover_loaded`), and the `QImage→QPixmap` conversion + the `_sized_cover_cache` write happen on the main thread in `_on_preload_sized_cover_loaded` (QueuedConnection). NEVER write either cover cache from a worker; NEVER move the QPixmap step off-thread.
   - **DPR is read on the main thread at enqueue time and passed by value** into the worker (`_current_sized_key_dims()` reads `self.screen()`), because `screen()`/DPR access off the GUI thread is unsafe. Do not read it inside the worker.
   - **The preloader's key MUST equal `_get_sized_cover`'s paint-time key**, `(book_id, round(target_w*dpr), round(target_h*dpr))`. `BookDelegate.cover_cell_size()` is the single source of the per-view-mode `target_w/target_h` and MUST stay in lockstep with the cover-rect math in `_paint_grid_cell` (`r.width()-4, r.height()-4`), `_paint_one_per_row` (100×151), and `_paint_two_per_row` (118×180, column-aware X via `_TWO_PER_ROW_LEFT_MARGIN`, fixed size regardless of column). A mismatch is silent: the preloaded entry keys on the wrong size, is never hit at paint time, and the LANCZOS runs on the main thread during the slide anyway — the exact stall this warming exists to remove. Verified matching for all five modes when added; re-verify if any cover-rect formula changes. Warming is **current view mode only** (all-modes doesn't scale by library size — see NOTES.md cost table and the "FUTURE IDEA" first-page-per-mode note). Batching is also load-bearing: dumping all workers at once froze the main thread ~766ms (completion slots pile onto it), so keep `PRELOAD_BATCH_SIZE` batched — 4 is the measured ceiling; do not raise without re-measuring the real two-slot completion path.
4. **DO NOT assume `get_all_books()`'s active-library filter (`is_deleted=0 AND is_excluded=0 AND is_missing=0`) covers every book a preload/warm pass needs to reach.** The idle preloader's queue source is exactly this filtered query, which means a book can be excluded/soft-deleted/missing from the active library while still correctly appearing in Stats' Day/Week/Month history (a book listened to before being removed keeps showing in its historical periods — see the soft-delete-flags section above). Such a book's cover could NEVER preload, no matter how long the app idled — a permanent gap, not a timing one. Measured on a real library (2026-08-08): 21 of 70 distinct books referenced in Stats history fell into this gap. `db.get_stats_history_only_books()` (a cheap indexed query, sub-millisecond measured) closes it by feeding the currently-hidden-but-historically-relevant subset into the same preloader queue, appended after the active library. Any future preload/warm pass that sources its book list from `get_all_books()` alone should ask the same question before assuming full coverage.

---

### DO NOT add an overlay-open path that skips `is_overlay_open_or_committed()`
Only ONE overlay (the six sidebar panels — library/settings/speed/sleep/stats/tags — the chapter-list dropdown, or a mid-flight sidebar handoff) may open at a time. `PanelManager.is_overlay_open_or_committed()` (`panels.py`) is the single gate: `is_any_full_panel_visible() OR is_any_panel_animating() OR _pending_panel_open is not None`. Every overlay-OPEN entry point consults it FIRST and early-returns (drops the request) if True — the six `_open_*_flow` methods, `_show_chapter_dropdown` (AFTER its own already-visible→`fade_out` toggle), and `_open_library_shortcut`. The speed/sleep buttons delegate to `_open_speed_flow`/`_open_sleep_flow` (which gate) instead of the old unconditional `_hide_popups()`-then-open. **Policy is DROP the second request (ignore), NOT switch or queue** — two opens inside the animation window aren't legitimate intent. Do NOT "fix" a collision by making an opener call `hide_all_panels()` then open: that starts a close-slide that fights the other panel's open-slide (the exact overlap bug this replaced — see `review/Review_260706_2.md`). Load-bearing exclusions that must stay: a **bare expanded sidebar** is NOT blocked (the gate excludes it so the sidebar-queued open path works); the sidebar handoff dispatches via `_start_*_entry` (not `_open_*_flow`) so it's never blocked by its own committed state; `open_book_detail` is intentionally UNGATED (reachable only from within an already-open library/stats/tags panel — never races a fresh open). `_close_*_flow` and the own-panel-visible→close toggles are never gated. The FUTURE "press L in Stats → dismiss Stats, open Library" switch behavior is deliberately NOT built (shortcuts are main-window-exclusive today). `tests/test_panel_exclusion.py` pins the gate's truth table.

### Settings' Themes tab and every other panel are mutually exclusive — hover-confinement verification must be synthetic, never assumed reachable live
Settings' Themes tab and every other panel (Library, Stats, Sleep, Speed, Tags) are mutually exclusive — only one panel can be visible at a time. The one exception is Book Detail, which can open over Stats or Library. Any theme-hover interaction with another panel simultaneously visible is therefore impossible by construction, not just rare — verification of hover-confinement fixes must be synthetic/instrumented, never assumed reachable by live manual interaction.

### DO NOT replicate `apply_library_state(compute_library_state())` at a call site
`apply_current_state()` on `LibraryController` is the sole entry point for reconciling library UI state without scan side effects. Any call site that needs compute-and-apply (but not a scan trigger) must call `self.library_controller.apply_current_state()` — never inline the two-liner. Inlining the compute+apply pair creates sync-drift risk identical to the `upsert_book` / `upsert_books_batch` invariant: the pairing can drift independently from `apply_current_state`'s implementation. `_check_library_status` delegates to `apply_current_state` internally and additionally calls `handle_background_tasks`; use it only when a scan trigger is appropriate.

### DO NOT suppress the theme `bg_image` by overriding `visual_area` — regenerate the stylesheet without it
The theme `bg_image` is painted by `content_container`'s `QWidget#visual_area { background-image: url(...) }` rule in `get_player_stylesheet`. It is stripped in the no-book and empty-library states (where it overlapped the prompts/carousel/quote). The ONLY working suppression is `get_player_stylesheet(theme_name, suppress_bg_image=True)`, which omits the image at generation time. Do NOT attempt to cancel it with a child override (`visual_area` instance stylesheet, a `background-image: none` rule, or a dynamic property like the removed `carouselActive`): Qt's QSS cascade treats `background-image: none` as "unspecified", so the ancestor `url()` wins on the child per-property and the image survives (verified — a child `background-color` override applied while the image layered on top). `MainWindow._set_bg_suppressed(suppressed)` is the sole authority: it sets `_bg_suppressed`, sets `setAutoFillBackground(not suppressed)`, and re-applies the regenerated stylesheet. `apply_library_state` drives it (`True` for empty + no-book, `False` for has_book) and `ThemeManager._apply_stylesheets` reads `_bg_suppressed` so a theme change in those states keeps the image stripped. `_show_carousel`/`_hide_carousel` must NOT touch background or `autoFillBackground` — suppression is owned by the state machine, not the carousel.

### DO NOT revert `_update_cover_art_scaling` to reading `cover_art_label.height()` for `target_h`
`_update_cover_art_scaling` uses `COVER_AREA_HEIGHT` (a module-level constant in `ui/ui_helpers.py`, imported into `app.py`) as `target_h`, not `self.cover_art_label.height()`. The live allocated height is transient and state-dependent — it reflects whatever the layout engine allocated at the moment of the call, which can be wrong during any state transition (empty→book, no-cover→cover, panel open/close). The constant decouples scaling from layout state and prevents any cover aspect ratio or state transition from breaking the layout. `cover_art_label` is also pinned with `setFixedHeight(COVER_AREA_HEIGHT)` in `_build_cover_art`. If the window layout ever changes, re-calibrate `COVER_AREA_HEIGHT` empirically by testing covers of various aspect ratios and confirming no bottom clipping in fit mode.

### DO NOT try to expand a widget's height inside the Library settings tab's `QVBoxLayout` — use a MainWindow-level popup instead
`settings_panel` (`main_window_builders.py` `build_settings_panel`) is a **fixed 500px height** widget, and no settings tab has its own `QScrollArea` (this is intentional — no panel in this app has a scrollbar: Stats, Sleep, and Playback don't, and Library must not either). Any widget inside a settings tab that tries to grow taller than the tab's already-fully-claimed vertical budget has nowhere to put the extra height: Qt either refuses to allocate it, or steals it from a sibling with a flexible size policy (visible as the whole tab drifting). Multiple inline approaches for the Excluded Books expandable list were tried and all failed this way, including a `QScrollArea` with animated `maximumHeight` and an absolute-overlay child of the section widget itself — see SESSION.md, 2026-06-27 Session 2, and NOTES.md "Excluded Books list wouldn't expand..." for the full attempt-by-attempt trail if this shape of bug resurfaces. The fix: anything that needs to expand beyond a settings tab's available space must be a popup parented directly to `MainWindow` (see `ExcludedBooksPopup`, `ui/excluded_books.py`, which copies `ChapterList`'s — `ui/chapter_list.py` — architecture exactly: `QGraphicsOpacityEffect` fade only, no size `QPropertyAnimation`, `show()`/`raise_()`/`setGeometry()` from the click handler). It is never a descendant of the tab's layout, so nothing in that layout is ever asked to renegotiate space for it.

### DO NOT verify a settings-panel/tab visual layout bug with headless test scripts alone
For this exact class of bug (widgets inside a settings tab not sizing/showing correctly), every headless Python verification attempt — `processEvents()` loops, manual `QPropertyAnimation.setCurrentTime()`, synthetic `QMouseEvent` delivery, even instantiating `MainWindow()` without actually opening the settings panel through its real animated entry path or switching to the real active tab — reported "looks correct" at some point, including for an attempt that rendered nothing at all in the live app. The gap between a script reporting correct geometry/`isVisible()`/stylesheet state and what the real, live, actually-opened app shows was real and repeated, not a one-off fluke. For any settings-panel/tab layout or paint bug: do not trust headless assertions as a substitute for the user checking the live app. Make the change, ask them to check, and treat their report as ground truth over any script's output. (Same underlying lesson as the "user sees the rendered pixels" rule at the top of this section — this is that lesson applied to a widget class where even careful headless verification kept giving false confidence.)

**Scope note (2026-07-11):** this distrust is specific to the settings-panel/tab layout/paint bug class above, not a blanket "never trust headless tests" rule. Headless traces were the correct tool, and caught real bugs, for the Qt-KEYBOARD-FOCUS class of bug (the transport-shortcuts/focus-ownership investigation, see the "Keyboard focus ownership" rule) — two of those traces did give false signals, but from test-harness bugs, not from this same headless-vs-live gap, and were re-verified rather than distrusted wholesale. Check which class a new bug belongs to before deciding whether headless verification is trustworthy for it.

### DO NOT trust `QComboBox` popup pseudo-state QSS (`::item:hover`/`::item:selected`) or `::down-arrow` on this app's target desktop — paint them manually instead
Confirmed on the primary dev desktop (KDE Plasma, Wayland, Fusion style — `QApplication.style().objectName() == "fusion"`, no `QT_QPA_PLATFORMTHEME` set), and reproduced in complete isolation outside the app: `QComboBox QAbstractItemView::item:hover` / `::item:selected` QSS rules do **not** reach the popup's paint at all (a rule swapped to glaring red produced zero visual change, ruling out a color/subtlety problem). The SAME desktop also ignores `QComboBox::down-arrow`'s `image: none` + border-triangle QSS trick — the native style paints its own arrow glyph there regardless. Fix for both, in `library.py`: `_ComboItemDelegate` (installed via `combo.view().setItemDelegate(...)`) paints popup item hover/selection backgrounds directly instead of relying on native pseudo-state painting; `_ThemedComboBox` (a `QComboBox` subclass, used in place of a plain `QComboBox()` for `sort_combo`/`style_combo`) overrides `paintEvent` to call `super().paintEvent()` first (background/border/text via the style still work fine — only the popup-item and arrow pseudo-states are broken) then paints its own triangle over just the arrow sub-control's rect. **Do not fill the arrow rect edge-to-edge** — `subControlRect(SC_ComboBoxArrow)` spans the FULL control height including the rounded top/bottom-right corners; a flat fill there squares off those corners — see the `corner_clearance` inset in `_ThemedComboBox.paintEvent`. Do not attempt a QSS-only re-fix for either of these without re-confirming on the affected desktop first — this is a known-failed approach (this exact area was attempted and abandoned once before, undocumented at the time). See SESSION.md, 2026-07-09 Session 1, for the diagnostic trail (including the isolation/screenshot tests) and NOTES.md for the writeup.

### DO NOT rely on `WA_PaintUnclipped` to let a child widget paint past its parent's bounds, and DO NOT pin a widget's width with `setFixedWidth` inside a `QGridLayout`/stretch column without checking what it steals
Two separate traps hit in the same investigation (Book Detail Stats/History tab alignment, 2026-08-13), both plausible-sounding APIs that were shipped without being checked against real rendering first — see CLAUDE.md's "never substitute a plausible explanation for a checked one" section, which this is a concrete instance of.

`Qt.WidgetAttribute.WA_PaintUnclipped` does **nothing** on an ordinary `QWidget` — it is a documented no-op outside `WA_PaintOnScreen` contexts (native/GL surfaces). A plain `QWidget` clips its children's painting to its own rect regardless of the child's own `setGeometry()`. Setting a child's geometry wider than its parent and expecting the overflow to render anyway will silently do nothing — a live geometry probe (`mapTo`/`.size()`) will report the correct, wider geometry, making this look fixed when it isn't; only an actual screenshot/live check catches it. If a widget needs to visually extend past its layout-assigned cell, give the CONTAINER itself the extra width (so the layout genuinely reserves the space), not the child.

Separately: pinning a widget's width via `setFixedWidth` while it participates in a `QGridLayout` column that has `setColumnStretch` applied changes that column's width computation — the pin can steal space back from the stretched column, moving OTHER widgets in unexpected directions (confirmed live: pinning a pct label's width moved it left, the opposite of the intended right-nudge, because the pin shrank the stretched bar column next to it). A `QGridLayout` column/row that isn't itself stretched to fill its parent (`addWidget(grid_widget, 0, ...)` — stretch factor 0) sizes to its own `sizeHint`, which is the MAX demand across every row sharing that column — so a single row's attempt to claim more width can hit a hard, confusing cap dictated by an unrelated row's content (the fix, in this case, was giving `grid_widget` a real stretch factor so column width wasn't capped by whichever row's text happened to be longest).

### DO NOT assume a text label's horizontal position is "the box's position" without checking its alignment
A left-aligned `QLabel` in an auto-sized box and a right-aligned `QLabel` in a fixed-width box can look identical for one specific text value and diverge for every other value the label will ever show. The Stats-tab furthest-position pct label was `AlignLeft` in an auto-sized box while every other pct label in the app (`_RecentHistoryWidget`'s and `_HistoryRow`'s) is `AlignRight` in a `setFixedWidth(32)` box — a left-aligned narrow string ("0%", "5%") does not reach as far right as a wider one ("28%", "100%") even when the box itself is positioned identically, which made a pure alignment bug look like an inconsistent, book-dependent spacing bug across several rounds of live measurement before the actual difference (alignment, not position) was spotted. When matching one label's position against a sibling label elsewhere in the app, match its alignment and fixed-width convention first, not just its container's x — and re-verify with more than one sample of visible text (different digit counts), since a single fixed test value can hide this class of bug entirely.

### DO NOT let `open_book_detail` retarget or re-animate an already-visible Book Detail Panel
`open_book_detail` (`panels.py`) now no-ops entirely — does not call `load_book`, does not restart the slide-in animation — whenever `book_detail_panel.isVisible()` is already `True`, regardless of which book is showing. `_start_book_detail_entry` is unconditional (always moves the panel off-screen right then slides it back to `x=0`), so calling `open_book_detail` while already open visibly yanks the panel out and back — this is what Library's new Alt+Enter shortcut surfaced (repeatedly pressing it on the already-open book re-triggered the slide every time). Worse without the guard: arrow-navigating to a DIFFERENT book while detail is already open (e.g. after a right-click) and then pressing Alt+Enter would hijack the visible panel onto the new book instead of being blocked — same call path, no protection. The fix is scoped to book-detail-vs-book-detail only; it does **not** touch or weaken `PanelManager.is_overlay_open_or_committed()` (the cross-panel — library/settings/speed/sleep/stats/tags — one-overlay-at-a-time gate), which deliberately still excludes `open_book_detail` for the unrelated reason documented above (it's reachable only from within an already-open library/stats/tags panel, so it never races a *different* panel's opening animation). The user must close the panel via an existing close path (`_close_book_detail_flow` / the panel's own close button) before opening another book's detail.

---

#### Keyboard focus ownership (added 2026-07-11) — one shared fact, five consequences

Load-bearing architecture, not a one-off fix. The invariant: **exactly one widget owns real Qt
keyboard focus at a time, and `MainWindow.keyPressEvent` only hands a key to the shortcut
dispatcher (`MainWindow._focus_allows_global_shortcuts()`) when `QApplication.focusWidget()` is
`None` or `MainWindow` itself** — never when a panel/overlay is open and one of its own widgets
holds real focus. A panel-local focused widget gets first AND FINAL say over a key, even if it
declines it (leaves it unaccepted and lets Qt propagate the event upward) — the key must NOT fall
through to global shortcuts just because the local widget didn't want it.

Two enforcement points, both required (fixing only one leaves the other's failure mode open):
- **Ownership** (`PanelManager._claim_panel_focus`, called from every panel's `_start_*_entry`
  after `.raise_()`): every panel/overlay must claim focus for one of its own widgets on open.
  `raise_()`/`.show()` only change Z-order/paint stacking — they have ZERO effect on keyboard
  focus. Without this, a panel opened over an already-focused panel (e.g. Book Detail opened from
  Library) leaves the PREVIOUS panel's widget (e.g. Library's `_list_view`) holding real focus, so
  arrow keys/Space silently navigate and activate the panel underneath the visible one — this is
  reachable in practice because `open_book_detail` is the one intentionally-ungated overlay path
  (see the `open_book_detail` rule above). Settings/Speed/Sleep reuse `panel_tab_widgets(panel_key)`
  (the same "first focusable widget" list Tab-cycling already uses) as the claim target;
  Stats/Tags/BookDetail (not in that list) claim the panel root itself. Library and ChapterList
  self-manage this already (their own `showEvent`/`show_above`) and are NOT routed through the
  shared helper — leave them as-is.
- **Dispatch** (`MainWindow._focus_allows_global_shortcuts`): without this, a key a focused input
  widget doesn't itself consume (e.g. `Up`/`Down` inside a `QLineEdit`, which only handles
  cursor-relevant keys) propagates up to `MainWindow.keyPressEvent`, which — with no
  focus-awareness — hands it to the dispatcher regardless of what has focus (this is how
  `Up`/`Down` while editing a field used to fire `VOLUME_UP/DOWN` → `_on_volume_changed` →
  `hide_all_panels()`, dismissing the whole panel). The fix does NOT special-case volume or any
  individual handler — that would only close the hole for that one key and leave every other bound
  key free to leak the same way. It must live at the dispatch decision point, once, for every key.

Consequences of this shared fact, each independently load-bearing:

**1. DO NOT let a new panel/overlay skip `_claim_panel_focus`/`_release_panel_focus`** (or
self-manage focus like Library/ChapterList) in its open/close flow — nothing else in the codebase
enforces this per-panel; skipping it silently reintroduces the bleed-through bug.

**1a. The settings Tab cycle is HAND-ROLLED, so it inherits none of Qt's own skip rules.**
`panel_tab_widgets` and `settings_tab_button_rows` (arrow navigation) each filter membership
themselves — `isVisibleTo`, `focusPolicy`, `isEnabled`. **A filter added to one must be mirrored
in the other**, or Tab and the arrows disagree about what is reachable (2026-09-05: Tab landed on
a disabled button the arrows correctly skipped).

**2. The NoFocus sweep must stay complete — this entire mechanism depends on it.**
`_focus_allows_global_shortcuts()`'s "not None, not MainWindow ⇒ panel-local" equivalence is only
true because every always-on chrome widget outside a panel is `Qt.NoFocus`. **Any new always-on
widget added outside a panel (a new transport button, a new status indicator, anything parented
directly to `MainWindow`'s always-visible chrome) MUST be `setFocusPolicy(Qt.NoFocus)`, full
stop** — otherwise it becomes a focus candidate indistinguishable from a real panel-local widget,
and the whole dispatch guard silently breaks. The current sweep covers: the five transport buttons,
the two title-bar buttons, `speed_button`, `sleep_timer_label`, the six sidebar trigger buttons +
`sleep_cancel_btn`, `undo_overlay`, `eof_revert_btn`/`eof_close_btn`/`cancel_scan_btn`,
`scan_now_btn`, `go_to_library_btn`. A single missed chrome widget with a default (`StrongFocus`)
policy reintroduces the exact bug this sweep fixed: focus can land on it (Qt auto-focuses the first
focusable widget at startup, and Tab/arrow navigation can land on any focusable widget), `Space`
fires its `clicked` instead of play/pause, and the dispatcher is starved for as long as it holds
focus. `ClickSlider` (progress/chapter/volume sliders) is a `QWidget` subclass and `NoFocus` by
default with no `keyPressEvent` override — it needs no explicit call, but do not change its base
class or add key handling to it without re-adding one.

**Two Qt defaults that violate this silently, both found the hard way:**
`QScrollArea`'s default `focusPolicy()` is **`StrongFocus`, not `NoFocus`** — only its `viewport()`
defaults to `NoFocus`. `QToolButton` defaults to `TabFocus`. `_history_scroll` (Book Detail's
History tab) was missing an explicit policy, so a click on a `NoFocus`-correct child (`_trash_btn`)
fell through the ancestor chain and silently stole real Qt focus from `BookDetailPanel`, breaking
all of History's keyboard handling until the panel was reopened (2026-08-12, `3f04e03`). Any
`QScrollArea` or `QToolButton` added to a panel that owns its own `keyPressEvent` needs an explicit
`setFocusPolicy(Qt.FocusPolicy.NoFocus)`.

**3. Qt gotcha — clear focus AFTER `.hide()`, never before.** `hide()` on a widget that
still holds real Qt focus makes Qt fall back and silently RE-GRANT focus to that same now-hidden
widget if it's the only (or best) `StrongFocus` candidate around — so a `clearFocus()` call placed
before `hide()` gets invisibly undone by `hide()` itself. `_release_panel_focus` is deliberately
called AFTER `panel.hide()` in every close handler for this reason. Also: `clearFocus()` only acts
on `self` — call it on the actual focused descendant (`QApplication.focusWidget()`, checked via
`panel.isAncestorOf(...)`), never on the panel container, which typically never holds focus
directly itself.

**4. ANY mouse-clickable `QPushButton`/`QToolButton`/`QLineEdit` inside a panel is a
focus-strand risk, not just the panel's own open/close transition.** A user's click grants that
widget real Qt focus; if a later code path then hides, disables (`setEnabled(False)`), or deletes
(`deleteLater()`) that same widget — a confirm banner appearing over it, a list/grid rebuild after
add/remove, a bulk-action button disabling itself on click — Qt does NOT reliably hand focus back
to the panel. **Any panel with a clickable button/field that can be hidden, disabled, or deleted by
its own click handler should have — or be covered by — a general safety net, not rely on
remembering to add a reclaim at every site.** `BookDetailPanel._ensure_panel_owns_focus()` is the
reference implementation: called at the top of `eventFilter` on every `KeyPress`, it reclaims focus
for the panel whenever `QApplication.focusWidget()` is `None` or not a descendant of the panel, so
any future site with this shape self-heals on the very next keypress instead of reintroducing the
bug.

**5. A widget the panel itself opened still reads as FOREIGN to the panel's own containment
checks — this bites two different mechanisms.** Both are cases of "the panel spawned it, so surely
it's ours" being false:

- **Modal dialogs vs. a `QApplication`-wide `eventFilter`.** That filter (the mechanism every
  panel's Tab/Escape handling and consequence 4's safety net are built on) intercepts EVERY key
  event app-wide, including ones meant for an unrelated modal dialog (e.g.
  `QFileDialog.getOpenFileName`) that a panel opened — unless guarded, it steals Escape/keys from
  the dialog before the dialog's own handling ever runs. **Any `QApplication`-wide `eventFilter`
  that owns Escape/Tab/focus-reclaim logic MUST check `QApplication.activeModalWidget() is not
  None` first and decline to handle the event (`return False`) whenever true** — not scoped to
  dialogs the panel itself opened; any modal dialog anywhere in the app must win.
  `BookDetailPanel.eventFilter` does this at its very top, before any other branch.
- **Popups vs. a click-outside handler's `safe` allowlist.** A `Qt.WindowType.Popup` (e.g.
  `ContextIconMenu`) is a separate top-level window. Showing it moves focus off the field, and it
  reads as "outside" by every containment test a click-outside handler cheaply runs — including
  `isAncestorOf`. `BookDetailPanel` and `TagManagerWidget` both revert the in-progress edit when
  focus lands outside a hardcoded `safe` tuple, and the context menu was in neither:
  right-clicking a selection to cut it silently **reverted the edit first**, so the Cut ran against
  a field whose text had already been restored. The selection stays visually highlighted through
  the revert, so the field looks untouched — the reported symptom was just "cut does nothing," and
  Ctrl+X was unaffected, which is what made it look field-specific rather than menu-specific (FIXED
  2026-07-30, `40715cf`; both panels needed it). **Any click-outside/focus-loss handler with a
  `safe` allowlist must list every popup that panel can spawn.**

See SESSION.md, 2026-07-11 Session 3 and Session 4, for the full trace-by-trace investigation that
produced this invariant (three live-reported focus bugs in Session 3; three more focus-strand sites
plus the modal-dialog bug in Session 4).

---

### DO NOT use a bare `QLineEdit` for a new text input — subclass `DragSafeLineEdit`
On this app's target desktop (KDE Plasma / Wayland), a `mouseMoveEvent` with **zero displacement**
arrives ~40ms after a press while the button is still down. `QLineEdit` reads any move in that
window as the start of a drag-select: it discards a double-click's word selection and re-anchors
the caret mid-word, and it turns a plain click into a selection running from the press point to the
release point. In a metadata editor this is data loss, not a cosmetic glitch — a Cut following a
double-click acts on the truncated selection ("Andrew" → "And", leaving "rew Kishino" behind).
Measured live with the mouse physically untouched; full traces in NOTES.md, 2026-07-30.

`ui/line_edit_dragfix.py`'s `DragSafeLineEdit` consumes moves that have not **both** travelled
`QApplication.startDragDistance()` (10px) **and** been sustained `_DRAG_DWELL_MS` (120ms). **Both
conditions are required** — the distance check alone was the first attempt and left occasional
one-character selections, because a spurious move can jump well past 10px in a single event. Do not
simplify it back to a distance-only check.

All five current text inputs use it (library search, sleep custom-duration, tag name, tag input,
and `_ElidingLineEdit`); no bare `QLineEdit()` remains. The defect is Qt-level and applies to every
field in the app, so a new input that skips this base class reintroduces it for that field alone —
which is exactly how it surfaced twice, reported first in Book Detail and then independently in the
Tags panel.

### DO NOT leave a `beginResetModel()` without a `finally`-guaranteed `endResetModel()`
`BookModel.set_books`/`sort_books`/`filter_books` wrap their reset pairs in `try/finally`. An
exception between the two calls leaves Qt permanently mid-reset: every subsequent filter or sort
logs `beginResetModel called ... without calling endResetModel first`, and the library panel stays
broken until the app restarts. One transient exception becomes a session-long outage. This bit for
real on 2026-07-30 — an emptied book title made `_apply_filter_and_sort` dereference
`None.lower()`, and the resulting strand broke the panel far more visibly than the crash itself
(`8678d68`). The `None` guard is fixed too, but **do not remove the `finally` on the grounds that
the known trigger is handled** — it guards the class of failure, not that one instance.

### DO NOT rely on a `QApplication`-level `QEvent.MouseMove` filter branch to detect "any mouse movement anywhere in the window"
Qt only **generates** `MouseMove` events for a widget that has `setMouseTracking(True)` enabled (or
has a mouse button held) — confirmed live, 2026-08-09. Almost nothing in this app's widget tree has
tracking enabled (only `total_time_label` did, at the time this was found). A `QApplication`-level
`eventFilter` branch on `QEvent.Type.MouseMove` only sees events Qt actually generated, so it will
fire during drags but silently never fire for ordinary cursor movement over any widget that didn't
opt in — there is no cascade from a parent's `setMouseTracking` to its children. The corner-hotspot
sidebar trigger's idle-dismiss timer (`review/Plan_260809_corner_hotspot_sidebar_trigger.md`) was
originally *designed* this way and would have silently never reset on real mouse movement; caught
before shipping by testing the mechanism directly (a synthesized `sendEvent` proved nothing, since it
bypasses the generation step this gotcha is about — the platform integration itself has to be
consulted, or the underlying Qt behavior reasoned from first principles). Fixed by polling
`QCursor.pos()` on a repeating `QTimer` instead (`ui/panels.py`, `_sidebar_idle_poll_timer`, 500ms
cadence) — sidesteps the tracking-cascade problem entirely and touches no existing widget. Prefer a
`QCursor.pos()` poll over a `MouseMove`-filter interception for any future "detect activity anywhere
in the window" need; only reach for real `MouseMove` events for a hover mechanism scoped to a single
widget that can set its own tracking (the pattern every other hover feature in this app already
uses).

---

## Tech Stack

PySide6 (Qt) + mpv via python-mpv. Python. SQLite. Mutagen for metadata.

---

## Collaboration Model

- **Claude**: architecture, decisions, code generation, code review, documentation, root-cause investigation

(Gemini was previously used for pipeline scripts / folder-naming conventions, kept in lane by a
GEMINI.md guardrail file; both were retired 2026-06-12.) The working model is "flag, confirm, then act."

## Conventions

- **SESSION.md entries are always prepended** (newest at the top), not appended. **Session numbers reset every new day** — the first entry on a given date is always Session 1, even if it continues an issue from a prior day's Session 6.
- **All git commit messages must start with a verb** (e.g. `feat:`, `fix:`, `docs:`, `refactor:`).
- **After completing a task, flag if SESSION.md, NOTES.md, CLAUDE.md, or TESTING.md would benefit from an update** — but only when there is something specific and non-obvious worth recording, not as a reflexive offer after every change.
- **Deferred work goes in `TODO.md`** (added 2026-06-19), not buried in NOTES.md prose or an external scratchpad. Short dated entries: what, why deferred, what it's blocked on. NOTES.md stays for root-cause writeups of things already done; TODO.md is for things not yet started. **Closed/fixed/superseded entries move to `TODO_ARCHIVE.md`, not deleted and not left in TODO.md** — TODO.md is open work only; a closed entry left in place defeats the point of a todo list.
- **Standalone analysis documents go in `review/`, named `Type_YYMMDD_topic.md`** — see `review/README.md` for the six types and the full rationale, and **`review/INDEX.md`** for a one-line summary of every existing document's actual finding (update it in the same commit that adds a new file — a stale index is worse than none, since it reads as complete). NEVER write one to the repo root, and NEVER give one the same name as a root document. Four rules, each of which exists because it was broken:
  - **The date is mandatory.** Without it a document reads as current forever.
  - **Never collide with a root filename.** `review/DEBT_INVENTORY.md` was read as a second, competing debt index by a reviewer on 2026-08-02 *despite* a `> **STALE**` banner in its first three lines — the filename is what gets seen first, so a header cannot fix a name collision. Now `review/Snapshot_260612_debt_inventory.md`.
  - **Whatever it concludes must be summarized into NOTES.md/TODO.md/DEBT_INVENTORY.md and linked from there**, because **an unreferenced document is an invisible one**: seven such files were written to the root in July 2026 and cited from no main doc; one (`review/Review_260720_theme_reach.md`) was forgotten for six weeks until it happened to be opened in the IDE, while a later session re-derived a worse version of its call-site inventory from greps — unaware that it *and* three closely-related perf reports already sat in `review/`, one of them direct prior art on the exact question being investigated.
  - **A `Snapshot_` document must say what commit it describes, in its own header** (see `review/Snapshot_260717_theming_state.md`, accurate at `5cfe3a3` and stale within two weeks) — otherwise it silently becomes a source of wrong beliefs.
  Being *linked* is not the same as being *findable before starting work* — `review/Report_260715_apply_stylesheets_avoidable_work.md` was linked correctly and still went unread for two weeks, because nothing summarized 21 files into something scannable in one screen. `review/INDEX.md` is that summary; check it before any perf/theme/panel investigation, not just when a doc happens to get opened.

---

## Window

Fixed size: 300×564px (`setFixedSize(300, 564)` in app.py:379). Cover label has no minimum size
so it fills the fixed window. Do not fight this with per-widget minimum sizes.

---
## What's Built

A factual reference of what the app does, by subsystem. Reflects the code as audited 2026-06-13.

### Player — playback modes

All mode detection happens in `_resolve_playlist()` (run async on a `QThreadPool` worker; result delivered to the Qt thread via the internal `_playlist_resolved` signal, then `_on_playlist_resolved`). Audio extensions: `.m4b`, `.mp3`, `.flac`, `.m4a`.

- **Single-file M4B/M4A, embedded chapters** — one audio file, `chapter_list_source == 'embedded'` (default). Chapter boundaries come from mpv's native `instance.chapter_list`, which is snapshotted into `_chapter_list` once at file-loaded time by `cache_chapter_list()` (called from `_on_file_loaded_populate_chapters`). This sets `_is_embedded_m4b = True`. After that point `_chapter_list` is non-None for chaptered embedded M4B, just like CUE/VT — the `chapter_list` property returns it without ever touching `instance.chapter_list` again during playback. Unchaptered embedded M4B: `cache_chapter_list()` sees an empty list and leaves `_chapter_list = None` / `_is_embedded_m4b = False`.
- **Single-file M4B/M4A, CUE chapters** — same single-file condition but source is `'cue'`. `_select_cue_file` matches a `.cue` by the Title part of the `"Author - Title"` folder name (exact then substring). `_parse_cue` validates: FILE stem matches the audio stem, first timestamp = 0.0, strictly increasing, no chapter ≥ file duration, ≥ 2 chapters; reads with `utf-8-sig` (Windows ripper BOM). On success `_chapter_list` is populated and `_virtual_timeline` stays `None` — that combination is the CUE-mode flag. On failure: silent fallback to embedded.
- **Multi-file (MP3/M4A/FLAC) via Virtual Timeline (VT)** — folder has multiple audio files and `db.get_book_files` returns rows. `_virtual_timeline` is a list of `{file_path, cumulative_start, duration}`; `_chapter_list` is synthesized from each file row's `cumulative_start_ms` + `title`; `_book_duration` is the sum. Plays the first file directly. If `book_files` is empty, falls back to playing the folder path as-is. State: `_file_offset`, `_current_vt_index`, `_pending_local_pos`, `_is_vt_file_switch`, `_last_vt_chapter`.
- **Single MP3** — one `.mp3`, no `_chapter_list`.
- **No audio files** — `_resolve_playlist` returns the raw folder path; `_on_playlist_resolved` sees a directory and emits `load_failed("no audio files in folder")`.

### Player — playback behaviors

- **Gate/ungate** — `load_book` sets `_play_gated = True` before resolving. If resolve finishes while gated, the result is held in `_held_play`; `ungate_play()` (called from `_on_library_hidden` after the library slide finishes) clears the gate and fires `instance.play()`. Lets panel animations finish before audio starts.
- **Property caching** — `time_pos`, `duration`, `pause`, `speed` cached via `observe_property` (`_cached_*`). `time_pos` getter adds `_file_offset` under VT; `duration` getter returns `_book_duration` under VT, else `_cached_duration`.
- **Async seeking** — `seek_async(pos)` issues `command_async('seek', pos, 'absolute+exact')` for in-file seeks, triggers a VT file switch for cross-file seeks, or routes to `_mp3_stop_and_load` for long MP3 seeks. Used by all UI-driven seeks (slider, chapter, right-click, undo, VT cross-file, chapter nav) **and** smart rewind. Skip buttons and position restore stay on the sync `time_pos =` path.
- **MP3 stop-and-load** — for VBR single `.mp3`: `seek_async` intercepts displacements > `_MP3_SEEK_THRESHOLD` (60s) and calls `_mp3_stop_and_load`, which pauses and issues `loadfile … start=X` (positions via Xing/TOC header, not stream-scan). VT same-file variant additionally gates on file size > `_VT_MP3_SIZE_THRESHOLD` (40 MB) and `2.0 < local_pos < duration − 5.0`. State vars (all reset in `load_book`): `_play_target`, `_mp3_seek_reload_pending` (guards the `_on_file_loaded` early-return + blocks concurrent reloads), `_mp3_seek_was_playing`, `_mp3_seek_visual_lock` (suppresses play/pause icon flicker). `book_ready` is NOT re-emitted during reload. VT same-file sets `_cached_time_pos = local_pos` (not global), else the `time_pos` getter double-counts `_file_offset`. Both `seek_async` call sites include `and not self._mp3_seek_reload_pending`.
- **Chapter navigation** — `previous_chapter` / `next_chapter` / `seek_within_chapter` all do a position-based forward walk over `chapter_list` and `seek_async(nominal + _chapter_seek_offset())`; never `self.chapter = idx`. Chapter-LIST clicks (all book types, embedded M4B included as of 2026-06-13) route through `Player.activate_chapter_index(idx)` → `seek_async` — no native-nav exception anymore. `previous_chapter` threshold is `2.0 × speed`s past chapter start (within → previous chapter; outside → restart current). `next_chapter` is a no-op at EOF.
- **Chapter-seek constants (three, split Session 3, 2026-06-13)** — the old single `_CHAPTER_BOUNDARY_EPSILON = 0.35` was overloaded as both a position→index walk tolerance AND a seek-target epsilon, which clipped the first word of embedded-M4B chapters (~0.44s skipped). Measured across 5 M4Bs / 67 seeks: mpv's exact seek *overshoots* the nominal boundary by ~0.09s while **playing**, and *undershoots* by ~0.37s while **paused**. The three constants:
  - **`_CHAPTER_WALK_TOLERANCE = 0.5`** — tolerance for every position→chapter-index walk (`time <= pos + X`) in `player.py` and `app.py` (`_sync_chapter_ui`, label paths). Must exceed the ~0.37s paused undershoot or paused Next/Prev resolves the chapter just left and the slider sticks; 0.5 is still far under the ~2s minimum real chapter spacing. **This is the value used in all walks now — NOT `_CHAPTER_BOUNDARY_EPSILON`.**
  - **`_EMBEDDED_CHAPTER_SEEK_OFFSET = -0.09`** — seek-target offset for embedded-M4B chapter nav (via `_chapter_seek_offset()`); cancels mpv's natural +0.09 overshoot so the first word plays.
  - **`_PAUSED_SEEK_UNDERSHOOT_COMP = 0.37`** — forward correction added to the mpv seek command (only) when paused, embedded only, in `seek_async`. Compensates the paused undershoot so undo/notch/nav land on target. Applied to the command; `_seek_target`/`_cached_time_pos` keep the logical position. Guarded against the near-EOF deadzone.
  - **`_CHAPTER_BOUNDARY_EPSILON = 0.35`** — now ONLY the legacy seek-target epsilon for **VT/CUE** chapter-boundary seeks (kept to preserve their landing). Do NOT reuse it for walks (use `_CHAPTER_WALK_TOLERANCE`) or embedded seeks (use `_EMBEDDED_CHAPTER_SEEK_OFFSET`). A `seek_async` target floor of `0.05` prevents the negative embedded offset from producing a negative absolute seek (which mpv lands at EOF).
- **`chapter_changed` driving** — `_on_time_pos_change` is the universal driver for all book types (VT walks `_chapter_list` against global pos; CUE walks `_chapter_list`; embedded M4B walks `_chapter_list` — the cached snapshot, not `instance.chapter_list` live), emitting only when the index changes. `_on_chapter_change` (the mpv `chapter` observer) is fully suppressed (always returns). `seek_async` also emits `chapter_changed` synchronously for CUE mode as an optimistic paused-case update. On seek settle (`abs(global_pos − _seek_target) < 1.0`) both `_last_*_chapter` reset to −1 to force one clean emit.
- **Smart rewind on resume** — `apply_smart_rewind(last_pause_ts, wait_min, rewind_sec)` only fires if away ≥ `wait_min` minutes; rewinds `rewind_sec × speed`, clamped to current chapter start; via `seek_async`. Config `smart_rewind_wait` / `smart_rewind_duration` (0 = disabled).
- **Undo (one level)** — `save_seek_position(old_pos, new_pos, duration_limit, threshold)` stores `_undo_pos` unconditionally when no live anchor exists (unset, or more than `duration_limit`s since the last call — the coalescing spree window), and returns whether the CUMULATIVE distance from that anchor (`abs(new_pos - _undo_pos)`) exceeds `threshold` — the caller (`MainWindow._trigger_undo`) uses this return value to decide whether to show the undo overlay, but the anchor itself is captured either way. See "Undo must anchor to a seek spree's start" below. `undo_seek()` seeks back via `seek_async` and clears `_undo_pos`. `duration_limit == 0` disables (config `undo_duration`, default 3s).
- **EOF / keep_open** — mpv runs `keep_open='always'`, so nothing auto-advances/closes. `_on_end_file(reason 0)` and a secondary `_on_pause_test` check (pause True and `pos ≥ dur − 1.5`) both call `_advance_or_finish()`: VT advances to the next file (sets `_eof` on the last), non-VT sets `_eof` immediately.
- **Seek guards** — near-EOF: `seek_async` returns early if `dur − pos < 2.0` (single-file) / `target_file['duration'] − local_pos < 2.0` (VT same-file); stop-and-load keeps its own 5s buffer. mpv hangs silently when seeked within ~2s of EOF.
- **Per-book speed / volume** — speed keyed `speed_{path}` in QSettings (None → `default_speed`). Volume is log-scaled: `_base_volume × _fade_ratio` (the fade ratio is the sleep-timer multiplier 0.0–1.0).
- **Signals** — `book_ready` (non-VT: from `_on_file_loaded`; VT: from `ungate_play` / `_on_playlist_resolved`, before `instance.play`), `file_switched` (VT cross-file), `chapter_changed(int)`, `load_failed(str)`. `file_loaded` is declared but driven by mpv's event, not re-emitted here.

### App shell (`app.py`, `MainWindow`)

`MainWindow` is a `QWidget` (not `QMainWindow`), frameless, fixed 300×564.

- **Three UI states**, reconciled by `LibraryController.apply_current_state()` (called at startup, on book select/remove, on library-status change):
  - **Empty library** — scan prompt + rotating literary quote (`book_quotes`, 60s `quote_timer`); player chrome and Library button hidden; bg image suppressed; carousel may show DB covers.
  - **No book selected (books exist)** — transport/sliders hidden via `_set_interface_visible(False)`; `no_book_section` ("go to library") shown; bg suppressed; carousel shown.
  - **Has book** — full chrome via `_set_interface_visible(True)`; bg restored; carousel hidden; `_load_cover_art` runs.
- **Carousel** — `CoverCarousel` built lazily in `_show_carousel()` (guards: not already shown, no current file, `no_book_section` visible). Slides in (220 ms OutCubic), stacked under `visual_area`. Paused/resumed around theme fades via `_on_fade_state_changed`. `_hide_carousel` tears it down; it never touches bg suppression (owned by the state machine).
- **`_set_bg_suppressed`** — sets `_bg_suppressed` (read by `ThemeManager._apply_stylesheets`), toggles `visual_area.setAutoFillBackground`, and regenerates `content_container`'s stylesheet with `get_player_stylesheet(theme, suppress_bg_image=…)` (uses `_active_display_theme` when a cover theme is live, to avoid a pool-color flash). Re-asserts transparent chapter-slider colors when `_chapter_ui_active` is False.
- **Right-click suppression after folder dialog** — `_get_new_folder_path` restarts `_dialog_close_time` (`QElapsedTimer`); `_on_drag_area_pressed` ignores right-clicks within 500 ms of the dialog closing. Drag-area right-click is also only forwarded when `db.get_book_count() > 0`.
- **Drag-area press** — `visual_area.mousePressEvent` is monkey-patched to `_on_drag_area_pressed`: left-click closes open panels, else toggles play/pause; empty library short-circuits. (No window-move logic lives here.)
- **Cover scaling** — `_update_cover_art_scaling()` implements four fit modes (`fit` KeepAspectRatio / `stretch` IgnoreAspectRatio / `crop` center-crop / `top` top-aligned on black canvas), all sized to `COVER_AREA_HEIGHT` (module constant), not the live label height. No-cover books render a themed `fabulor.svg` placeholder. Cover-theme application defers while a panel is open (`_pending_cover_pixmap` → `_apply_pending_cover_theme`).
- **200 ms `ui_timer` (`_update_ui_sync`)** — the heartbeat. Reads time/dur/pause/speed/eof; feeds `session_recorder.update_furthest_position`; on EOF synthesizes `pos = dur`, sets the restart icon, writes one `'finished'` event, shows the revert/close banner, and closes the session. Delegates to `_sync_playback_state`, `_sync_ui_render`, `_sync_progress_sliders` (skips setValue during flow anim / seeking / `flow_pending_progress`), `_sync_chapter_ui` (derives chapter from `pos`, skips during reload / no chapters / `flow_pending_chapter` / seeking), `_sync_persistence` (saves position every 0.1%, skips during drag / deadzone). Stopped during the flow animation; resumed via `_resume_ui_timer`.
- **Keyboard** — global keys route through `ShortcutDispatcher` (`shortcuts.py`), wired in `MainWindow.keyPressEvent`. `C` opens/closes the chapter dropdown (2+ chapters only); `T` rotates theme (`COOLDOWN_COALESCE` 2s — leading fire, repeats coalesce to one trailing fire, migrated from the old `_theme_rotate_cooldown`/`_pending` attrs); `Q` rotates the no-book quote (testing-only); `L` opens the library (`COOLDOWN_DROP` 500ms — open-only, no-op if the library/any full panel is already open or in the empty state, sidebar-open flows via `_open_library_flow`). The dispatcher owns binding + spam-guard ONLY; each action's app-state gating stays in its handler. **Transport keys (added 2026-07-11)** — `Space` play/pause, `Up`/`Down` volume (repeats on hold), `Alt+Up`/`Alt+Down` speed (repeats on hold, self-throttled — `_SPEED_NUDGE_THROTTLE_S`), `Shift+Left`/`Shift+Right` long skip, `Ctrl+Left`/`Ctrl+Right` chapter prev/next, `m` mute, `u` undo (only while the undo affordance is shown) — each calls the exact method its on-screen button/wheel already uses; volume/speed share `_nudge_volume`/`_nudge_speed` with `wheelEvent`. Added real modifier support to `Binding`/the dispatcher (masked to Shift/Ctrl/Alt) — a bare-key binding now matches only an unmodified press (Ctrl+T no longer rotates the theme). **Gated by the focus-ownership invariant** (see the CLAUDE.md rule of that name): the dispatcher only acts when `QApplication.focusWidget()` is `None` or `MainWindow` itself, never when a panel/overlay's own widget holds real focus — this is what stops these keys from leaking into text fields or firing while any panel is open. Full input map (incl. chapter-list keys, text-field Escape handlers, mouse/wheel) in `KEYBINDINGS.md`.
- **Wheel zones** — over `visual_area`: volume ±5 (2s overlay); over `speed_button`: speed ±`speed_increment`, clamped 0.25–8.0; over `progress_slider`: chapter Prev/Next (up → next chapter, down → previous; no-op when no chapters or at last/first boundary — delegates to `handle_next`/`handle_prev` so all guards are inherited); over `chapter_progress_slider`: seek by `max(10, chap_dur × 0.05)` with undo capture.
- **Module-level interface classes** — thin one-way facades so controllers don't hold a raw `MainWindow`: `UIInterface` + `AppInterface` + `BrowserInterface` (→ `LibraryController`); `VisualsInterface` + `PanelInterface` + `UICallbackInterface` + `LibraryInterface` + `PlayerInterface` (→ `SettingsController`).
- **Startup** (`__init__`) — build core objects → seed streak-grid cache → `_setup_ui` → wire timers/signals → instantiate `LibraryController` → restore last book (validated against active locations + `os.path.exists`) → `_check_library_status` → `ui_timer.start(200)` → instantiate `SettingsController` → `show()` → defer `start_idle_preload` by 4 s.
- **Teardown** — `_on_book_removed` zeroes labels/sliders, stops animations, deactivates chapter UI, clears cover; `closeEvent` saves volume + last book/position, terminates the player, stops/joins the scanner, closes the recorder.

### UI — Player view

- Cover art (four fit modes, above). Themed SVG placeholder for no-cover books.
- **Chapter list overlay** (`chapter_list.py`, `ChapterList`) — `QListWidget` child positioned absolutely; fade in 450 ms / out 300 ms (opacity → 0.94); `ROW_HEIGHT 24`, default `VISIBLE_ROWS 5`. Expand/collapse (button shown only when count > visible; Left/Right arrows toggle). Keyboard: Up/Down nav, Enter activate (no force-play), Space activate (force-play), Esc/`C` close. Digit jump: buffer + 800 ms debounce; `by_index` (1-based) or `by_name` (word-boundary regex); autoplay configurable. Activation uses `seek_async(+epsilon)` for VT/CUE, native `chapter = idx` for embedded M4B.
- Progress slider with chapter notch markers + notch reveal animation; separate chapter-progress slider; flow animation on book switch (both sliders animate between positions); UI-timer guards skip setValue during animation.
- `self._switch.in_deadzone` (`book_switch.py`) prevents stale position display during the library slide-out.
- Scrolling title/author labels (`ScrollingLabel`). Speed-controls panel, sleep-timer panel, sidebar (stats/settings/cover/detail access).

### Book Detail Panel (`book_detail_panel.py`)

`QTabWidget` (`stats_tabs`) with four tabs + a header:

- **Header** — four inline-editable `_ElidingLineEdit` fields (title/author/narrator/year, read-only at rest, click to edit; year has a `-?\d*` validator; narrator+year always shown in edit mode). Escape / click-outside cancels via the app event filter. 80px-wide / 120px-max header cover (`_render_logo_placeholder` fallback, grayscale for archived books). `_finished_label` (always visible) toggles manual finish/unfinish with a 7s confirm. `_remove_btn` excludes the book (7s confirm); archived books show `_ghost_label` instead.
- **Metadata locks** — `_locks` dict (title/author/narrator/year). The unified `_meta_action_btn` (24×24) is driven by `_MetaActionState`: `HIDDEN` / `DIRTY` (save icon → save + lock changed fields) / `LOCKED` (lock icon → clear all locks) / `UNLOCKED` (lock-open, auto-reverts after 2500 ms).
- **Stats tab** — furthest-position `_RangeBar` + %; a grid of Remaining (speed-aware) / Total listened / Sessions / Last session / Started / Finished; a non-scrolling `_RecentHistoryWidget` (up to 4 recent sessions).
- **History tab** — full scrollable `_HistoryRow` list; per-row hover-reveal trash → slide-in "Delete this session?" confirm; "Delete listening history" with a 7s confirm; emits `history_deleted`.
- **Tags tab** — `FlowLayout` chip container + input with a debounced (200 ms) case-insensitive `QCompleter`; per-book limit 5 (input hidden at 5); a tag display strip above the tabs (clickable colored dots → `tag_filter_requested` in library context).
- **Cover tab** — embeds a `CoverPanel`.
- **Duration label** (`_ClickableLabel`) — wall-clock by default; click toggles to speed-adjusted ("Xh Ym at N.Nx"); cursor/toggle disabled at 1.0×.
- Signals: `close_requested`, `history_deleted`, `metadata_saved`, `tags_changed`, `active_cover_changed(book_path, cover_path)`, `book_removed`, `tag_filter_requested(str)`, `open_tag_manager_requested`.

### Cover Panel (`cover_panel.py`)

- Up to 4 user covers (slots 1–4) + 1 locked scanner cover (slot 0). Add via `QFileDialog` (`.jpg/.jpeg/.png`, validated ≤ 5 MB), saved as JPEG; first user cover auto-activates. Locked covers can't be deleted; `_add_btn` hidden at 4 user covers.
- `CoverThumbnail` 72×72 with a 17px bottom hover overlay (× delete / ✓ set-active, both suppressed when not applicable; overlay fully suppressed when the sole cover is locked); 2px accent border on the active cover.
- Preview `QLabel` fixed **208×266**, four fit modes (`fit` letterbox / `stretch` / `top` top-anchored crop / `crop` center-crop), persisted per cover via `db.set_fit_mode`. Fit buttons (exclusive `QButtonGroup`) hidden until a cover is selected.
- `_left_col` height = `n × 72 + max(n−1, 0) × 6`. Active-cover change persists via `db.set_active_cover` and emits `active_cover_changed(file_path)` (`""` when none remain).

### Library Panel (`library.py`)

- `BookModel(QAbstractListModel)` + `BookDelegate(QStyledItemDelegate)` + `LibraryPanel`. Shared module-level `_cover_cache` keyed by `book.id` (int) holds one native-resolution pixmap per book. `BookDelegate` additionally holds its own per-instance `_sized_cover_cache` keyed by `(book_id, device_w, device_h)` — a LANCZOS-prescaled pixmap per grid-cell size, built lazily by `_get_sized_cover` (on the paint path) AND warmed ahead of time by the idle preloader (off-thread, 2026-07-04), consumed by `_draw_cover` so the final paint-time `drawPixmap` is a near-1:1 blit rather than a large bilinear downscale (added 2026-06-24, see CLAUDE.md rules below and NOTES.md for the full root-cause writeup).
- **Five view modes** (`VIEW_MODES`): 1-per-row, 2-per-row, 3-per-row, Square, List. Display names are randomized literary puns (reshuffle on `hideEvent`). List mode draws an animated left-edge stripe (`_pulse_timer` 40 ms) on the playing book and supports hover-fade (Off/Slow/Normal/Fast); 1- and 2-per-row support hover text-scroll.
- **Sort** (`SORT_KEY_MAP`): Title, Author, Last Played, Progress, Duration, Year, Finished. "Progress"/"Finished" appear only when such books exist (`has_books_with_progress` / `has_finished_books`). Direction toggle (`↑`/`↓`) defaults per key via `_SORT_DIRECTION_DEFAULTS`, persisted to config.
- **Search/filter** — plain text (title/author/narrator/exact 4-digit year); `#tag` prefix (`get_paths_for_tag_prefix`; `#` alone = all); `_prefix` = title-starts-with; `@name` = author only; year filters `=NNNN` (exact) / `>NNNN` (≥) / `<NNNN` (≤) / ranges (both orderings). All year forms accept a leading minus for BCE. **Branch order in `_apply_filter_and_sort` is load-bearing** — the range test must precede the bare `<`/`>` tests, else `>1950<1990` fails the bare-operator number check and degrades to a text search. `@` and `=` exist to resolve real collisions with the all-three-fields bare search (`james baldwin` matches a biography's title *and* a novel's author; `1984` matches a title *and* a year); click-to-filter emits `@Name`/`=YYYY` for the same reason, while **narrator deliberately emits bare** (no narrator operator — the author-who-also-narrates collision was judged too rare to earn one). No-match: search field turns dark-red and the model falls back to the full list (never empty); **year filters never redden** and incomplete year expressions never show red — deciding whether `<50` is complete or a half-typed `<500` is undecidable from the input alone, and a library-aware rule would make one keystroke behave differently per user. `_YearFilterValidator` caps year expressions at 4 digits per number (grammar-only, never consults the library) and only constrains strings starting with `<`/`>`/`=`, since one validator sits on a field taking every filter type. Right-click clears the field; persistence is per-classification (`persist_filter_tag/year/text` — `_classify_filter` must recognise every year form or a year filter is governed by the user's *text* toggle). Operators are **not discoverable in-app** — a tooltip and a Settings placement were both tried and rejected on measured evidence; they are slated for the planned help section (see TODO.md).
- **Cover loading** — `_load_visible_covers` finds the topmost visible row via `_first_visible_row()` (a visualRect binary search — shared with the view-mode-switch scroll-preservation capture, see rule below) then binary-searches the bottom (±5 row pad), dispatches `CoverLoaderWorker` (caps to 320×480, raised from 226×344 on 2026-06-24). Idle preloader (`start_idle_preload`): queues in sort order, `PRELOAD_BATCH_SIZE = 4` every `PRELOAD_INTERVAL_MS = 50` ms (batch was 3, raised to 4 on 2026-07-04 — measured ceiling before main-thread jank; see the constant's comment), **warms BOTH `_cover_cache` (raw) AND `_sized_cover_cache` (current view mode's cell size, off-thread — 2026-07-04)**, pauses per `_preload_paused()` (scan / theme-fade / cover-art flow anim / any panel slide — NOT static panels/Stats-Month/playback/seek), and no longer starts on an app-start timer: it's armed once after `_finish_startup` and only runs after 5s of genuine no-interaction (the eventFilter's idle-restart timer). `_on_cover_loaded` / `_on_preload_sized_cover_loaded` skip the `dataChanged` emit while `_is_animating`.
- `BookDelegate._resolve_playback` returns `(pos, dur, dur_disp, pct, has_progress, speed)`; `has_progress` (gated on `progress > MIN_PROGRESS` = 1.0s) is what shows the elapsed/bar/percentage and applies per-book speed to the displayed duration. Clicking the time label toggles remaining/total. All delegate colors are injected `Property(QColor)` for theme animation.
- **Click-to-filter on author/narrator/year (1-per-row/2-per-row only, added 2026-07-05)** — clicking author/narrator/year text sets the library search field to that value (year via the existing `<YYYY>YYYY` range-string convention) instead of selecting/playing the book. Title is never clickable. `_field_filter_target_at(book, pos)` is the single source of truth for both the click grab (`editorEvent`) and the hand-cursor decision, so they can't diverge. Multi-value author/narrator (e.g. `"Feist, Wurts"`) is split into clickable per-name segments (`_split_field_value`/`_segment_bounds`/`_segment_under_point`, on `,` `;` `" and "` `" & "`); a click in the separator gap between names is a dead zone (default cursor, falls through to normal selection) rather than grabbing the full joined string. No hover affordance beyond cursor shape — no underline, no color change, on any field. 1-per-row's title/author/narrator/year rows are fixed per-field-type slots (not redistribute-to-fill): a missing field leaves its row blank rather than letting adjacent fields shift, and the stored hit-rect height is the real font height (tight vertical hit-testing).
- **Click-filter toggle-off/revert semantics** — clicking a value that exactly matches the field's current text (author/narrator/year re-click, or reopening the library, or left-clicking into the field) reverts to `LibraryPanel._explicit_filter_text` — the user's last genuinely typed or right-click-cleared text — never to `""`. `_explicit_filter_text` is updated only on a real edit (`textChanged` while `not self._programmatic_search_update`); `set_search()` sets that guard around its `setText()` call, and every OTHER direct `search_field.setText(...)` call site (`clear_tag_filter_if_active`, `focusInEvent`'s handler) must go through the same guard or through `clear_tag_filter_if_active()` itself — an unguarded direct `setText` on this field is read by `_on_search_changed` as real typing and silently destroys `_explicit_filter_text` (this exact bug hit two separate pre-existing call sites the same day the guard was introduced; see NOTES.md). Right-click (`_on_search_right_click`) is the one deliberate hard nuke to `""` and sets `_explicit_filter_text = ""` explicitly — unaffected by any of the above. A Book Detail Panel tag chip (library context only) whose tag exactly matches the active filter renders inert (regular cursor, no click, no `<a href>`) via a one-time `active_search_text` snapshot passed through `open_book_detail`/`load_book` — see `panels.py`.
- **Keyboard navigation (added 2026-07-09)** — `_list_view` gets real `Qt.StrongFocus` and grabs focus in `showEvent`, so arrows work the instant the panel opens (no click/Tab needed first). Up/Down delegate to native `QListView.keyPressEvent` (no custom model `flags()` needed — `BookModel` already inherits `Qt.ItemIsSelectable | Qt.ItemIsEnabled`); Left/Right are hand-coded ±1-column moves (`_move_selection_by`, using `ITEM_DIMENSIONS[mode]["cols"]`) in grid modes (2-per-row/3-per-row/Square) and a no-op in the two single-column modes (1-per-row/List) — native `QListView` IconMode arrow traversal was unreliable against this app's custom `sizeHint`/uniform sizing. Enter/Space reuse `_on_item_clicked` (the same click-to-play path); Alt+Enter reuses the `detail_requested` signal (the same right-click-to-detail path) — neither duplicates its target's logic. Tab is an exclusive two-way toggle between `search_field` and `_list_view` only (`_focus_list_from_search`); it never reaches `sort_combo`/`style_combo`/`sort_dir_btn`/`back_button`, because Tab-focus routing here is fully custom (not Qt's native tab-order chain), so those widgets are simply never in the path. Mouse hover ALSO sets `currentIndex()` (`_on_view_entered`) — a single source of truth for "which book is highlighted," so Enter/Alt+Enter always act on whatever's visually lit, and a later arrow press resumes from wherever the mouse last was, not a stale keyboard position.
- **Sort/view-mode keyboard shortcuts (added 2026-07-10, list-focus-scoped)** — while `_list_view` has focus (NOT the search field, so the keys type normally when searching), `t/a/r/d/y/p/f` set the sort field and `1`–`5` set the view mode, mirroring the two dropdowns. Handled in the same `_list_key` monkeypatch (two new `elif` branches, gated by the `_SORT_KEY_SHORTCUTS`/`_VIEW_MODE_SHORTCUTS` class dicts) — no second key path. Decision logic is split into `_apply_sort_shortcut`/`_apply_view_mode_shortcut` (so it's unit-testable against a fake combo — `tests/test_library_shortcuts.py`), and every path **reuses an existing dropdown handler**, never duplicating sort/view logic: an inactive sort field → `sort_combo.setCurrentIndex` fires `_on_sort_changed` (which applies the field's fixed fresh-selection default direction from `_SORT_DIRECTION_DEFAULTS`); the **already-active** field → `_toggle_sort_direction()` (the exact asc/desc arrow-button path); a view digit → `style_combo.setCurrentIndex` fires `_on_view_mode_changed`. `p`/`f` are a silent no-op when Progress/Finished aren't in the dropdown (conditional entries, `findData == -1`); the already-active view digit is an explicit no-op (no re-layout/re-animation). Each branch **consumes the key in all cases** (never falls through to `QListView.keyPressEvent`), so an unhandled letter can't trigger type-ahead selection or bubble up to the global `ShortcutDispatcher` — and even if it did, `P`/`A` etc. already no-op via `is_overlay_open_or_committed()` while Library is open. Both branches carry their own `isAutoRepeat()` guard scoped to just these keys (the dispatcher's `allow_autorepeat` doesn't reach keys it never sees; nav keys stay repeatable). `r → "Last Played"` (the combo displays "Recent" but its data key is "Last Played"); digit N → `VIEW_MODES[N-1]`, a 1:1 map with no remap. `KEYBINDINGS.md` has the human-reference rows.
- **Keyboard-selection visual, per view mode** — 1-per-row keeps its own tint fill (`_kbd_selected_path`/`_kbd_alpha` on `BookDelegate`). As of 2026-09-18 this tint uses the SAME theme keys as mouse hover (`library_item_hover_color`/`_alpha`) rather than a separate `library_item_keyboard_color`/`_alpha` pair — Pryme's own call, unifying the two styles now that both keys' only prior use was a fallback to `accent`. The dedicated keyboard keys were removed from `themes.py`'s doc block (no theme dict ever set them). 2-per-row/3-per-row/Square deliberately have **no separate tint** — they reuse the same duration/progress `_draw_hover_overlay` mouse hover already shows (`hovered or is_kbd_selected`), since a second highlight there was redundant (removed 2026-07-09 after live feedback — do not re-add a `_kbd_fill_color()` fill to these three modes). List mode reuses the mouse's own `on_list_hover_enter`/`on_list_hover_leave` hover-fade mechanism (`_flash_keyboard_selection_list`) so it honors the user's Hover-fade setting (Fast/Normal/Slow/Off) exactly like a real hover would — with its own `BookDelegate._kbd_hover_path` (independent of `_kbd_selected_path`/`_kbd_alpha`, which List mode ignores entirely) as the Off-mode instant-fill fallback, mirroring hover's own Off-mode fallback. Keyboard-move handling calls `_on_view_left()` (the same teardown a real mouse-Leave uses) before showing the keyboard highlight, and mouse hover entering a DIFFERENT book calls a quick fade-out (or an instant clear if it's the SAME book) on whatever keyboard highlight was showing — so only one highlight is ever visible, never both at once.

### Stats Panel (`stats_panel.py`)

- **Tabs**: Overall, Timeline, Day, Week, Month, ⚙.
  - **Overall** — `BarChartWidget` (last 7 days; click a bar → Day tab at that date); stat grid (Listening time, Books started, Sessions, Longest/Last/Average session, Current/Longest streak); "Recently finished" `FinishedScrollRow` (≤ 20, hidden when empty).
  - **Timeline** — both `HourlyHeatmap` and `StreakGrid` built, one visible (default from `config.get_default_timeline_view()`); `TasselOverlay` toggles them with a conceal→reveal transition.
  - **Day / Week / Month** — ‹/› nav (right-click jumps to oldest/newest), wheel-scroll header (Day optionally accelerated), row list (rows < 60s excluded), total label, "Finished" `FinishedScrollRow`. **All three tabs use `StatsRowModel`/`StatsRowDelegate`/`StatsRowListView`** (a `QAbstractListModel`/`QStyledItemDelegate` pair, lazily painting rows into a real `QListView` instead of constructing per-row widgets — migrated Day 2026-08-05, Week and Month 2026-08-09; see `review/Spec_260805_stats_lazy_delegate.md` for the original design and `review/INDEX.md` for the full implementation/bugfix history). The old widget-per-row class this replaced (`BookDayRow`) and everything that existed only to support it (`ElidedLabel`, `_dim_effect()`, `_elide()`, `ScrollHoverTracker`, `_claim_container_input`) were removed once all three tabs migrated — see git history if any of that mechanism's lessons (especially `_claim_container_input`'s flush-widget Qt hit-testing gotcha) are needed again for some future widget-per-row list. `StatsPanel` also fires a one-time eager cover-warm at construction (`_eager_warm_stats_history_covers`/`_StatsHistoryLookupWorker`) covering every book Stats history can ever show, closing a first-load cover-flash gap the delegate migration surfaced — see the CLAUDE.md rules near `_sized_cover_cache` and the two new rules on lambda-signal defaults / session-lifetime cache resets. Cover-load dispatch (`_dispatch_cover_load`/`_on_cover_loaded`/`_delegate_refresh_cover_for_path`) is shared across all three tabs via a `prefix` parameter (`_day`/`_week`/`_month`), with dedup keyed on `book_id` alone (`_stats_cover_pending`), not per-tab.
  - **⚙** — day-start hour `QSpinBox` (0–23, rebuilds streak cache), period scroll-acceleration toggle, default-timeline-view toggle, "Reset all stats" (7s confirm).
- **`HourlyHeatmap`** — 14-day × 24-hour grid (CELL 14, GAP 1), today leftmost; cell alpha `40 + intensity×215` (intensity = `min(1, sec/3600)`); hover highlights + per-hour tooltip (date, total, per-book table). Mexico-wave reveal/conceal cell transition uses the shared `_grid_cell_anim` helper, style `"pop"` (cells scale up from a center-anchored inset as they reveal, shrink back on conceal — not a plain alpha fade); top date labels and left-gutter hour labels cascade via per-label opacity fade with enter/exit as true mirrors (left-to-right entering top labels / right-to-left exiting; top-to-bottom entering gutter labels / bottom-to-top exiting).
- **`StreakGrid`** — 26×14 = 364-day calendar, today top-left, backed by `streak_grid_cache`. Listened days filled accent; finished days get a small sharp centered 4×4 square dot (`_finished` set, `streak_grid_dot` per-theme override); the longest consecutive run **fills with a derived lighter/desaturated tint of accent and borders in plain accent** (`streak_grid_outline` per-theme override for the border color — fill/border roles were swapped from the original distinct-fill design), computed in-widget by `_compute_longest_run` (most-recent run wins on tie). Left gutter shows the current-streak icon + an animated count: linear count-up 0 → previously-shown value, then (only if the streak grew since last shown) a paused snappy tick up to the new value — see `animate_streak_count`/`catch_up_streak_count` and the two CLAUDE.md rules above on persistence and the panel-reopen catch-up exception. Same `_grid_cell_anim` "pop" transition as the heatmap.
- **`TasselOverlay`** — sliver tab pinned top-left (~7px peek), slides down → holds 1200 ms → switches view → retreats; clock icon (Streak) ↔ fire icon (Heatmap; was `calendar.svg`, swapped 2026-06-18 — rendered as a plain rectangle at 14px). Icon recolors via `accent_dark`/`bg_main` theme keys (was `accent`) and updates only once the bookmark is fully retreated at rest, not mid-transition — see `TasselOverlay.play(on_switch, on_retreated=...)`. `_switch_timeline_view` uses a 2-counter seam so the visibility flip waits for both conceal and label-out. A decorative tassel (cubic-Bezier cord looping from the tab's top-centre, vertically into a bound "head" rect, fanning into a 7-thread fringe — added 2026-06-19 Session 3, `_cord_color` from `accent_dark`/`bg_main`) hangs alongside the tab: a perpetual ~30fps idle micro-sway plus a decaying "kick" on slide-down/retreat, gated by `showEvent`/`hideEvent` + an `isVisible()` tick guard. The widget itself is wider/taller than the tab to give the tassel room, but `_tab_rect`/`REST_Y`/`EXT_Y`/the 7px peek are unchanged; clicking and the hand cursor are both driven by `_in_hit_region()` (tab rect OR a tight tassel-body box — see the CLAUDE.md rule above) so the cursor never shows over dead space.
- **Widgets**: `StatsRowDelegate` (48×48 cover, elided title/author, `pct_start · pct_end | +delta`; archived shown in grayscale, no opacity dimming — see the CLAUDE.md decision note; finished/deleted styled) paints Day/Week/Month rows; `FinishedBookThumb` (47×47 crop) is the one remaining per-widget row class, used only by the Finished-period carousels, deliberately not migrated to the delegate pattern; `SessionListWidget` (scrollable session rows: timestamp / delta% / `_RangeBar` / end%), `_RangeBar` (flat start→end fill bar with animatable colors; also used by the detail panel).
- **Data flow** — period caches (`_cached_active_days/weeks/months`) invalidated on tab change / `refresh_all`. `_inject_active_covers(rows)` adds `active_cover_path` from `book_covers` (must run at every row site, including `FinishedBookThumb`). `on_cover_changed(book_path, cover_path)` refreshes every tab's model directly via `_delegate_refresh_cover_for_path` (not gated on which tab is currently visible, so a hidden tab's `_cover_cache` entry still gets corrected) plus `_iter_finished_thumbs` → `refresh_cover` for the Finished carousels.

### Tag Manager (`tag_manager.py`, `TagManagerWidget`)

- Two alternating child widgets (not a `QStackedWidget`): **list view** (tag rows: colored dot, name ≤ 20 chars, book-count badge) and **tag panel** (back, name edit, reserved 21px row, book grid).
- **Rename** — typing flips the single `_action_btn` to save mode; Enter/click → `db.rename_tag`; success shows a check for 2000 ms; name-taken shows a red save icon (`save_error`); Escape/click-outside reverts.
- **Delete** — trash → reserved row shows a "Confirm to delete the tag" confirm (7s), grid locked; confirm → `db.delete_tag`.
- **Color** — clicking the dot shows a 9-swatch + neutral picker (`db.set_tag_color`); mutually exclusive with delete-confirm.
- **Remove book from tag** — left-click a `_TagBookThumb` → `db.remove_book_tag` (deletes the tag if it was the last book); right-click → `detail_requested`.
- `TAG_COLORS`: 9 named (coral/peach/lemon/lime/mint/sky/lavender/rose/white) + neutral. `MAX_TAG_LENGTH = 20`. Per-book limit 5, global 50 unique (enforced in `db.add_book_tag`). `_TagBookGrid` 5 columns; `set_locked` routes clicks through the parent. Completer popup styled by `_style_completer_popup` on each keystroke + theme change.

### Theme System (`theme_manager.py`)

- 50+ named themes (`themes.py`); per-component stylesheets — never `main_window.setStyleSheet()` globally. `_apply_stylesheets(theme_name, hover)` dispatches to: base/main window, title bar, `content_container` (`get_player_stylesheet`, `suppress_bg_image` flag), library (skipped during hover), chapter list (skipped during hover), settings/speed/sleep panels, stats + book-detail panels, sidebar; then `_reload_button_icons` + `_set_chapter_ui_active`.
- **Hover preview + snapback** — hover applies at half the fade duration; un-hover snaps back to the cover theme (if active) or current theme at `_SNAPBACK_FADE_MS = 200`.
- **Overlay fade** — `_fade_overlay` `QLabel` + `_fade_anim` (opacity 1→0, `_THEME_SWITCH_FADE_MS = 750`). When the Themes tab is inactive, sliders are punched out of the overlay mask and their `bg_color`/`fill_color`/`notch_color` animate separately; time/chapter labels are frozen (`FreezableLabel`) before the grab to prevent ghosting. `snap_theme_forward()` (panel open) and `abort_theme_fade()` (panel close) short-circuit the fade.
- **Rotation** — `rotation_timer` every `interval` minutes; `_rotate_theme` skips in `exclusive` cover mode and defers (`_pending_rotation`) while a panel is open (`_fire_pending_rotation` retries 3s after close). Selection excludes the current theme + recent (`deque(maxlen=10)`), relaxes below `_MIN_POOL = 4`, then inverse-distance-weights by perceptual distance (`_EXCLUSION_THRESHOLD = 0.5`). Automatic changes snap instantly when the Themes tab is active. `_PANEL_ANIM_GUARD_MS = 700`.
- **Cover-art dynamic theme** — `apply_cover_theme(pixmap)` (modes `off` / `with_pool` / `exclusive`); `clear_cover_theme` reverts. `_cover_pool_btn`: left-click toggles off↔with_pool, right-click activates immediately.

### Panels (`panels.py`, `PanelManager`)

- Manages sidebar, library, settings, speed, sleep, sprint, stats, tags, book-detail, and chapter-list visibility. All slide via `QPropertyAnimation` on position; re-entry guarded.
- Library slides full-width from the left (sets `_is_animating` to suppress cover emits; `refresh()` on shown). Settings/speed/sleep/sprint/stats/tags slide from the left at 90% width, fixed 500px height. **Book detail uniquely enters from the right.** Optional blur animation (`blur_effect.blurRadius` 0↔10) per `config.get_blur_enabled`.
- **Sprint** (`_start_sprint_entry`/`_close_sprint_flow`) mirrors `_start_sleep_entry`/`_close_sleep_flow` exactly — same slide geometry, same `_claim_panel_focus`/`_release_panel_focus` pair, same transport-bar/visual-area blur hookup on slide-finish. `sync_disable_button_visibility()` runs on every entry (reconciles the Cancel-sprint vs. Reset-all-sprint-data button visibility against `_sprint_active`, since that toggle can change while the panel is closed); `_cancel_reset_sprint_data()` runs on every close (dismisses any in-flight 7s reset confirmation rather than leaving it stranded). `SprintPanel` holds no `db` reference — coordinates with `app.py` entirely via signals (`sprint_started`, `sprint_stopped`, `sprint_expired(int)`, `display_text_updated(str)`, `grace_warning_changed(bool)`, `reset_sprint_stats_requested`), same shape as `SleepTimerPanel`.
- Sidebar uses a queued-open pattern (closes first, then dispatches the panel). `_on_library_hidden` ends the deadzone (`mw._switch.library_revealed`), calls `ungate_play`, then drains deferred file-ready events or applies the pending cover theme.
- **Two ways to open the sidebar (added 2026-08-09)** — right-click on the cover-art area (existing), or hovering an invisible 15×15 hotspot zone at the cover art's top-left corner for ~200ms (`SidebarHotspot`, `ui/sidebar_hotspot.py`; toggle in Settings > Controls). `PanelManager._sidebar_opened_via` (`"right_click"` | `"hotspot_hover"` | `None`) records which, set at the two open call sites and cleared in `_toggle_sidebar`'s closing branch. It gates `on_sidebar_hover_out()`: cursor-leaves-the-sidebar-rect only dismisses a hotspot-opened sidebar, never a right-click-opened one. A universal idle-dismiss poll (`_sidebar_idle_poll_timer`, `QCursor.pos()`-based — see the CLAUDE.md rule on why this isn't a `MouseMove` filter) closes either after `_SIDEBAR_IDLE_DISMISS_MS` (10s) of no movement anywhere in the window. The hotspot's own `_armed` flag requires a genuine exit-then-reentry of the zone before it can fire again — disarmed on ANY sidebar-open transition while the cursor rests inside it (not just hotspot-triggered opens), which is what prevents the idle timer from closing the sidebar and immediately reopening it via a stationary cursor. See `review/Plan_260809_corner_hotspot_sidebar_trigger.md` for the full design and SESSION.md 2026-08-09 for why a visual indicator was tried and removed.
- **Keyboard focus ownership (added 2026-07-11)** — every panel/overlay claims real Qt focus on open (`_claim_panel_focus`, called after `.raise_()`) and releases it on close (`_release_panel_focus`, called after `.hide()`), enforcing that exactly one widget owns focus at a time app-wide. Settings/Speed/Sleep claim the first entry of `panel_tab_widgets(panel_key)` (same list Tab-cycling uses); Stats/Tags/BookDetail claim the panel root itself (granted `StrongFocus` if it doesn't already have it). Library and ChapterList self-manage this in their own `showEvent`/`show_above` and are not routed through these helpers. See the "Keyboard focus ownership" CLAUDE.md rule for the full invariant and the `hide()`-before-`clearFocus()` Qt gotcha this depends on getting right.

### Controls & widgets (`controls.py`, `audio_controls.py`, `carousel.py`, `icon_utils.py`, `text_context_menu.py`)

- **`ClickSlider`** — animatable `bg_color`/`fill_color`/`notch_color`/`notch_opacity`/`animatedValue` properties; `animate_to` (200–600 ms distance-scaled); `when_animations_done` chains flow then reveal; chapter-notch reveal animation (`revealedCount`, mirrored to seek direction, alternating tick halves); optional center mark + snap-to-center; right-click emits a ratio and snaps to markers.
- **`FreezableLabel`** — `setText` is a no-op while frozen (pins labels during theme fades). **`ScrollingLabel`** (extends it) — horizontal marquee with Slow/Normal/Off modes, animatable `text_color`, `clicked`; `clicked` only fires (and the hand cursor only shows) when the click/hover position falls within the actual RENDERED text rect (`_text_rect`, covering scrolling/elided/static-centered — see the CLAUDE.md rule on hit-testing rendered content vs. layout bounds), not the widget's full layout bounds; `set_clickable(bool)` gates both entirely off (no cursor, no click) for e.g. fewer than 2 chapters. **`HoverButton`** — `hovered`/`unhovered`/`rightClicked`. **`ShimmerButton`** — `play_shimmer()` runs an 800 ms diagonal glint.
- **`AudioSettingsTab`** — normalisation, voice boost, stereo/mono, channel swap, L/R balance slider (−100..100, snap-to-center). Each change calls `player.apply_audio_processing(...)`; a reset button appears only when something is non-default.
- **`CoverCarousel`** — decorative scrolling strip, fixed 300px wide; static when ≤ 3 covers, else gapless looping scroll (`_TICK_MS = 33`, time-delta based); staggered reveal (first at 375 ms, then every 75 ms) with a fade-in; 1px top/bottom stripe lines; `set_stripe_color` / `stop` / `start`.
- **`icon_utils`** — `render_logo_placeholder` (themed `fabulor.svg`), `render_logo_placeholder_bordered`, `load_themed_icon` (LRU 64; swaps `#000000` fills/strokes — for black-paint icons), `load_currentcolor_icon` (LRU 64; regex-replaces all non-`none` fills/strokes — for `currentColor` SVGs like clock/calendar).
- **`ContextIconMenu`** — single shared frameless popup with Cut/Copy/Paste/Delete (each enabled by selection/clipboard/read-only state), themed, clamped within the window.

### Settings Panel

- Themes tab, Controls tab (chapter digit mode by_name/by_index, autoplay/jump-only toggle), Audio tab, Library tab (folder management, naming pattern, chapter source Embedded/.cue, persist-filter, and an **Excluded Books** toggle line — `ui/excluded_books.py`'s `ExcludedBooksSection` — that opens `ExcludedBooksPopup`, a `MainWindow`-level popup, NOT an inline expanding widget; rebuilt on each panel open via `_reload_excluded_books`, restoring via `set_book_excluded(path, False)`). Bound dynamically via `SettingsController` through the five interface facades.

### Library state machine, scan & covers (`library_controller.py`, `library/`)

- **`compute_library_state`** → `{mode, has_book, has_locations, has_indexed_books}`. `mode` is `empty` (no locations OR no visible indexed books), `scanning` (locations + indexed + scanner running), or `ready`. `has_book` derives from `app.get_current_file()`; `has_indexed_books` from `get_visible_book_count()`.
- **`apply_library_state`** branches: **empty** (hide chrome/Library button/carousel, suppress bg, rotate quote, set prompt by sub-state: no-locations / scanning / no-books); **no-book** (show Library button, hide prompts, show metadata "go to library", suppress bg, show reshuffled carousel); **has-book** (show Library button, hide carousel, restore bg, delegate metadata visibility to `_load_cover_art`).
- **`apply_current_state`** is the sole compute+apply entry point (no scan side effects). **`_check_library_status(manual, force_refresh)`** = `apply_current_state` + `handle_background_tasks` (starts a scan when manual, force, or no indexed books, and not already scanning).
- **Location flows** — add (`_on_scan_now_clicked`): abspath-normalize, dedupe against sub/parent existing locations, `add_scan_location`, then **synchronous** `restore_books_under_path` (un-soft-deletes `is_deleted=1, is_excluded=0` books under the path), refresh, `_check_library_status(manual=True)`. Remove: `remove_scan_location` (soft-delete), unload the current book if it was under a removed folder, refresh. Excluded books stay hidden through both.
- **Scanner** (`scanner.py`) — `LibraryScanner` owns a `QThread`; `ScannerWorker` does the work, cancellable via a `threading.Event`. Phase 1 discovers one-level-deep book folders (any audio extension). Phase 2 builds `known_paths` from `get_all_book_paths()` (ALL rows regardless of flags) — on a non-force scan, known (incl. excluded/deleted/missing) paths are skipped and NOT resurrected; a force scan re-extracts everything and `upsert_books_batch` resets `is_deleted` and `is_missing` to 0 but keeps `is_excluded` sticky (see the "Sticky `is_excluded`" rule). A force scan additionally runs missing-book detection (2026-06-26, flag corrected to `is_missing` 2026-06-27): visible books under a scanned-and-reachable location whose folder is gone from disk are batch-flagged `is_missing=1` via `db.mark_books_missing` (see the "Scanner missing-book detection" rule above — NOT `is_excluded`, that was the ping-pong bug). Extracts cover (external image file → embedded tag), narrator/title/author/year (tag priority chains → folder-name fallback), `book_files` (multi-file only), summed duration; generates a 226×344 JPEG thumbnail under the cache dir and upserts a locked scanner cover (slot 0) if none exists.
- **Cover manager** (`cover_manager.py`) — `get_covers_dir` (user data dir), `save_cover_image`, `delete_cover_file`, `validate_cover_file` (size-only ≤ 5 MB).

### Database (`db.py`)

- SQLite, WAL per connection, `sqlite3.Row` factory, auto-commit/rollback context manager.
- **Tables**: `scan_locations`; `books` (+ `progress`, `year`, `started_at`/`finished_at`, `chapter_source`, soft-delete `is_deleted`/`is_excluded`/`is_missing`, four `*_locked` flags); `listening_sessions` (+ `book_id` FK, `furthest_position`); `book_events` (+ `book_id`, `event_type`, `source`); `book_tags` (`book_id`); `tags` (name PK, color); `book_covers` (locked/active/fit_mode/sort_order); `book_files` (sort_order, duration_ms, cumulative_start_ms, title); `streak_grid_cache` (date PK, listened) — a 364-row rolling window.
- **Soft-delete-ish flags** — `is_deleted` set by `remove_scan_location`, cleared by `restore_books_under_path` (only when `is_excluded=0`) or any upsert; `is_excluded` set by `set_book_excluded` (user-trash only), untouched by removal/restore, cleared only by `set_book_excluded(path, False)` (sticky through upserts); `is_missing` set by `set_book_missing`/`mark_books_missing` (confirmed gone from disk), self-heals on any upsert (the opposite of `is_excluded`'s stickiness) — see "DO NOT conflate" above. "Visible" = all three 0. `get_book_count()` (all rows, for stats) vs `get_visible_book_count()` (library); `get_all_book_paths()` is unfenced (drives the scanner's `known_paths`).
- **Upserts** — `upsert_book` / `upsert_books_batch` share identical SQL (execute vs executemany). ON CONFLICT guards: title/author updated only if not `*_locked`; narrator/year additionally NULLIF-guarded against empty/null; `progress` via `COALESCE(NULLIF(excluded.progress, 0.0), books.progress)`; `is_deleted` resets to 0; `is_excluded` is sticky (`CASE WHEN books.is_excluded THEN 1 ELSE 0 END`); `is_missing` resets to 0 unconditionally (self-healing, NOT sticky — do not copy the `is_excluded` CASE WHEN pattern onto it). All three must stay in lockstep between the two upserts.
- **Sessions/events** — `write_session` dual-writes `book_path` + `book_id` and updates the streak grid for the start and end dates; `write_book_event` writes events (only `source='playback'` finished events light a grid cell). `unfinish_book` / `clear_finished` / `delete_session` / `delete_book_stats` all re-evaluate the affected grid cells. `set_started_at` only writes when NULL.
- **Stats queries** — `get_book_stats`, `get_overall_stats`, `get_last_n_days` (zero-fills gaps in Python), `get_active_periods`, `get_listening_time_per_period`, `get_books_listened_in_period`, `get_daily_book_breakdown`, `get_finished_in_period`, `get_recently_finished`, `get_streaks`, `get_hourly_heatmap` (splits sessions across clock-hour boundaries in Python, caps 3600s/hour, wall-clock with no day-start offset). Stats queries are intentionally unfenced by the soft-delete flags and use `COALESCE(b.title, ls.book_title)` over LEFT JOINs so deleted books keep their title. Per-book period positions use correlated subqueries (and `has_finished_books` uses `EXISTS`) to avoid cartesian fan-out.
- **Streak grid** — `build_streak_grid_cache` seeds 364 dates at 0 then flips any date with a qualifying session (start OR end adjusted-date) or `source='playback'` finished event to 1; `_update_streak_grid_cache_for_date` does incremental updates; all date attribution uses a SQL `day_start_hour` offset (passed in, never read from config). **Invariant: a finished day is always a listened day** — a playback-finish lights its cell even with no session; manual (`source='manual'`) finishes never touch the grid (visible in Finished tab/detail only). `get_streaks` (the streak count) mirrors this same start∪end∪finished day-set — see CLAUDE.md rule below.
- **Tags** — `add_book_tag` (lowercased, ≤ 20 chars; per-book 5, global 50 limits), `remove_book_tag`, `get_all_tags` (LEFT JOIN color), `get_books_by_tag`, `get_paths_for_tag_prefix`, `rename_tag`, `delete_tag`, `set_tag_color`, `get_tag_suggestions`. **Covers** — `get_active_cover[_path]`, `get_covers_for_book`, `upsert_cover`, `set_active_cover` (maintains the single-active invariant manually), `set_fit_mode`, `delete_cover`.

### Session Recording (`session_recorder.py`)

`SessionRecorder(QObject)` owns all session state/persistence; `MainWindow` holds one and delegates. `_current_book` stays on `MainWindow` (passed via `get_book_fn`); day-start hour via `get_day_start_hour_fn`.

- **Lifecycle**: `open()` (start, seed furthest position, start checkpoint timer), `resume()` (after a short pause), `pause()` (accumulate the segment, start the 3-min `_pause_timer`), `close()` (accumulate, flush to DB if `listened ≥ 60`, reset). `is_active` property.
- **Thresholds**: 60s wall-clock minimum (else discarded), 3-min pause timeout (auto-close), 15s **seek credit** — a forward seek past the furthest sets `_post_seek_pending_position` and starts `_seek_credit_timer`; staying 15s promotes it (a backward seek cancels). `notify_seek(new_pos)` from slider-released handlers feeds this; `update_furthest_position(pos)` from the 200 ms loop advances the furthest only when no seek credit is pending.
- **Persistence**: `write_session` dual-writes `book_id` + `book_path` + title/author/duration + start/end/positions + `furthest_position` + `listened_seconds` + `day_start_hour`; sets `started_at` if unset; runs on a daemon thread and emits **`session_written`** (lives on the recorder, not `MainWindow`). A `session_checkpoint.json` is written every 30s and recovered on startup (writes a session if ≥ 60s, without emitting `session_written`). `close()` returns its flush daemon thread; `closeEvent` joins it (500 ms) then calls `clear_checkpoint()` **synchronously** so the checkpoint never survives a graceful close into the next startup's recovery (would otherwise double-write the session — see the `close()`/`clear_checkpoint()` rule above). The checkpoint `unlink` is NOT in the daemon thread.

### Config (`config.py`)

`QSettings("Fabulor", "Fabulor")`; `_safe_int`/`_safe_float` guard list-typed returns.

- **Playback**: `volume` (100), `skip_duration` (10s), `long_skip_duration` (1 min), `smart_rewind_wait`/`smart_rewind_duration` (0 = off), `speed_increment` (0.1), `default_speed` (1.0), `speed_{path}` (per-book, None), `pos_{path}` (0.0), `last_book` (""), `sleep_duration` (30 min), `sleep_mode` ("timed" | "end_of_chapter"), `sleep_fade_duration` (0s), `undo_duration` (3s), `chapter_list_source` ("embedded" | "cue").
- **Audio**: `voice_boost_enabled`, `norm_enabled`, `mono_enabled`, `channels_swapped`, `balance` (0.0).
- **Library**: `naming_pattern` ("Author - Title"), `library_sort_key`/`library_sort_ascending`/`library_view_mode`, `persist_filter_enabled`/`persist_filter_tag`/`persist_filter_text`/`persist_filter_year`.
- **UI/Theme**: `theme`, `blur_enabled`, `theme_fade_duration` (750 ms), `theme_rotation_interval` (0 = off), `cover_art_theme_mode` ("off"|"with_pool"|"exclusive"), `show_remaining_time` (true), `scroll_mode`, `hover_fade_mode`, `chapter_hints_mode`, `chapter_notches_enabled`, `chapter_notch_animation_enabled`, `chapter_digit_mode` ("by_name"), `chapter_digit_autoplay`.
- **Stats/Timeline**: `day_start_hour` (0), `default_timeline_view` ("heatmap"|"streak"), `streak_grid_cache_date`, `stats_accel_scroll`.

### Assets & quotes

- `assets.py` — `get_asset_path(relative)` resolves into the bundled `assets/` dir; `ICON_PATH` for the app icon.
- `book_quotes.py` — `BOOK_QUOTES`: 32 `(text, title, text_size, title_size, color, text_align)` literary quotes; `LibraryController._rotate_quote` picks one and renders it as HTML in the empty state.

### Logging (`logger_setup.py`, added 2026-07-01)

Pure plumbing, no call sites yet. `setup_logging()` (called first thing in `main.py`'s `__main__` block, before `QApplication`) configures the `fabulor` root logger **once** (idempotent): a `RotatingFileHandler` (2 MB × 3 backups) at `platformdirs.user_log_dir("fabulor")`, level from `FABULOR_LOG_LEVEL` (DEBUG/INFO/WARNING/ERROR, case-insensitive, invalid → WARNING default), format `"%(asctime)s %(levelname)-8s %(name)s — %(message)s"`, `propagate=False` — **file sink only, no stdout/console handler**. Emits one `logger.warning("Fabulor started")` at the end (WARNING, not INFO, so it lands in the file at the default level). Module-level `logger = logging.getLogger(__name__)` instances exist in `player.py`, `app.py`, `ui/theme_manager.py` but are **silent** — call sites land incrementally in later sessions. **Windows-port note:** the log dir uses the one-arg `user_log_dir("fabulor")` form (no appauthor), unlike the two-arg `user_data_dir("fabulor", "fabulor")` used everywhere else — see NOTES.md (2026-07-01) for why that matters on Windows.

---
## Pending / Known Debt

- `_cover_cache` has no eviction policy (unbounded LRU). Deferred.
- Theme transitions — long-term path is per-element `@Property(QColor)` animation, but Themes tab QSS complexity makes it non-trivial. `THEME_ANIM_TODO` comments mark instrumented widgets.
- `CoverLoaderWorker` anonymous type objects in stats_panel/tag_manager (path→ID migration context). Deferred to next cover refactor.
- Screen drag 4K→1080p: cover scaling doesn't update without scroll (needs `QWindow.screenChanged`).
- MP3 natural sort (2 before 10) — out of scope for v1.
- **Diacritic-folded sort (library author/title, tag list) is a locale-agnostic approximation, not "correct" collation — accepted, not a TODO item.** `library.py`'s `_fold_diacritics` (used for both the library's sort and, since `07f4bdc`, the tag list's) strips every combining mark unconditionally, so an accented letter always sorts adjacent to its plain base form (Álvaro sorts near "Alvaro" by its next letter, not in a separate block) — correct for the vast majority of cases, including the one that prompted this (Ágota Kristóf/Álvaro Enrigue landing with the A's instead of after Z). It is NOT locale-correct: several languages treat a diacritic letter as genuinely distinct from its base rather than a decorated variant of it — Turkish ö sorts as its own letter immediately after o (not folded to o); Swedish/Finnish å/ä/ö sort as their own letters at the END of the alphabet, after z; German traditionally alphabetizes ö near "oe". A real per-language answer needs locale-aware collation (ICU, or Python's `locale` module pinned to a specific language) — genuine added complexity, and there is no single "right" answer across languages to pin it to. Raised and explicitly accepted 2026-09-10 (Pryme's own framing: "Öd... coming before Oz... ö before o not as it is a proper letter by itself in Turkish alphabet") — kept as a known, permanent simplification, not scheduled work.
- **ScrollingLabel first-glyph clipping** — cosmetic, at the shipped `72d80df` 2px-gap tradeoff.
  Seven fix attempts across two sessions (2026-07-01, 2026-09-18) all failed or regressed; accepted,
  not scheduled work. Full trace in NOTES.md (2026-09-18) if revisited.
- **`path_to_index()`** is in `library.py` (`LibraryPanel`, not `BookModel`).
- **`day_start_hour` date adjustment has no named helper** — `(datetime.now() - timedelta(hours=N)).date()` appears inline at `db.py:864`, `db.py:1119`, `app.py:430`, `stats_panel.py:4007`, `stats_panel.py:4033`. Five identical copies; drift risk if one site is touched and the others aren't. Candidate for extraction to a `_adjusted_today(day_start_hour)` helper when any of these sites next needs touching.
- **VT open issues (multi-file MP3) — fully deferred:**
  - Progress slider race on book switch — **traced** (review/Review_260612_6.md §7, NOTES.md): not a missing guard. The authoritative `_on_file_ready` set is protected by three composable guards (`slider_animating`, `is_seeking`, `_switch.flow_pending_progress`); the residual is a guard-release-ordering timing overlap that self-corrects on the next 200ms tick. Lever (if determinism wanted): hold the timer resume until both the flow animation finished AND the restore seek settled.
  - M4B chapter stuck intermittently — **traced** (review/Review_260612_6.md §6, NOTES.md): NOT a Fabulor state-leak. `load_book` resets all VT/chapter state before the M4B loads. The freeze may originate in mpv-native `chapter_list` readiness/timing for specific M4Bs at load time — but note that as of 2026-06-16, `_on_time_pos_change`'s embedded M4B branch now reads `_chapter_list` (the cached snapshot) rather than `self.instance.chapter_list` live, so the original "gated on `instance.chapter_list` being populated" rationale no longer fully applies. If this re-surfaces: check whether `cache_chapter_list()` returned an empty list for the affected file (unchaptered path), and whether the 150ms retry in `_on_file_loaded_populate_chapters` resolves it.
  - Rapid book switch (VT → any) regression: test that the newly selected book's progress slider shows the correct position and not 0%. Symptom of a double-handler invocation resetting progress; fixed via disconnect-before-connect in `load_book`, but should be part of regression runs.

---

## Files and Responsibilities

```
main.py                       # Entry point (repo ROOT, not inside src/fabulor/) — calls setup_logging() before QApplication
tools/                        # Diagnostic harnesses, not shipped. row_hittest_minimal.py is the
                              # reference for the row-boundary pixel Qt delivers to the parent
                              # (run with --show; its offscreen mode is deliberately blind).
src/fabulor/
├── app.py                    # MainWindow wiring + module-level interface classes (VisualsInterface, PanelInterface, UICallbackInterface, LibraryInterface, PlayerInterface, BrowserInterface, UIInterface, AppInterface)
├── player.py                 # MPV wrapper, VT, async seek, gate/ungate
├── db.py                     # SQLite layer
├── config.py                 # QSettings wrapper
├── themes.py                 # Theme dicts + per-component QSS functions (get_player_stylesheet accepts suppress_bg_image)
├── library_controller.py     # Library logic, scan wiring, apply_library_state, _set_bg_suppressed
├── settings_controller.py    # Settings logic (dynamic binding)
├── session_recorder.py       # SessionRecorder — session open/pause/resume/close, checkpoint, furthest-pos tracking
├── book_switch.py            # BookSwitchState — single authority for the book-switch transition lifecycle (phase, deadzone, pre-switch captures, deferred flags)
├── shortcuts.py              # ShortcutDispatcher — data-driven global key bindings (Action enum, Binding table, declarative per-binding spam-guards); wired in MainWindow.keyPressEvent. See KEYBINDINGS.md
├── logger_setup.py           # setup_logging() — root fabulor logger, rotating file handler (called first in main.py)
├── book_quotes.py            # Quote pool for the empty/no-book state rotation
├── assets.py                 # get_asset_path helper (resolves paths into the assets/ bundle)
├── library/
│   ├── scanner.py            # Async file scan (threading.Event for cancel)
│   └── cover_manager.py      # Cover extraction and DB persistence helpers
├── models/
│   └── book.py               # Book dataclass
└── ui/
    ├── controls.py           # ClickSlider (animatedValue, when_animations_done), HoverButton, FreezableLabel
    ├── chapter_list.py       # Chapter list overlay (child widget, not popup)
    ├── library.py            # BookModel, BookDelegate, LibraryPanel (owns evict_cover/get_cached_cover — app.py must not access _cover_cache directly), _cover_cache
    ├── cover_loader.py       # CoverLoaderWorker: Signal(int, QImage)
    ├── cover_panel.py        # Cover management panel
    ├── cover_theme.py        # Dominant color extraction
    ├── theme_manager.py      # ThemeManager — overlay, snapback, rotation; reads _bg_suppressed on theme change
    ├── panels.py             # PanelManager — all panel open/close flows
    ├── book_detail_panel.py  # Book detail (stats, history, tags, cover header, inline edit)
    ├── stats_panel.py        # Stats panel, SessionListWidget, _RangeBar, HourlyHeatmap, StreakGrid, TasselOverlay
    ├── tag_manager.py        # TagManagerWidget — tag list, tag panel, book grid, color picker
    ├── title_bar.py          # Custom title bar
    ├── speed_controls.py     # Speed panel
    ├── sleep_timer.py        # Sleep timer panel
    ├── sprint_panel.py       # SprintPanel — Listening Sprint timer, grace-warning pulsation, Reset all sprint data
    ├── audio_controls.py     # Audio settings panel (normalisation, voice boost, balance, stereo/mono)
    ├── excluded_books.py     # ExcludedBooksSection (toggle line) + ExcludedBooksPopup (MainWindow-level popup, ChapterList's architecture — hover-reveal-eye restore rows)
    ├── carousel.py           # CoverCarousel — ambient scrolling strip in no-book state
    ├── flow_layout.py        # FlowLayout (heightForWidth implemented)
    ├── icon_utils.py         # load_themed_icon, load_currentcolor_icon, render_logo_placeholder(_bordered) — icon/SVG renderers
    ├── cover_placeholder.py  # Cover-art placeholder logo rendering (no-cover books, in the cover label)
    ├── ui_helpers.py         # _load_svg_pixmap/_load_svg_icon (+ LRU cache) — shared by app.py and main_window_builders
    ├── main_window_builders.py # build_* functions extracted from MainWindow._build_* — each takes `mw` and assigns widgets onto it
    ├── transport_bar_blur.py # TransportBarBlurOverlay — live backdrop blur for the mini transport bar behind an open panel
    ├── visual_area_blur.py   # ClippedBlurEffect — blur for `visual_area`, clipped to the panel-occluded region (sliver stays sharp)
    ├── hover_tracker.py      # ScrollHoverTracker — re-resolves a scroll area's hovered row from cursor position (QSS :hover goes stale on scroll); suspend() is the keyboard-coexistence hook
    ├── line_edit_dragfix.py  # DragSafeLineEdit — QLineEdit base for ALL text inputs; suppresses Qt's stray-move drag-select
    ├── scrollbar_jump.py     # ScrollBarJumpFilter — app-wide right-click-gutter-to-jump; suppresses the native scrollbar context menu
    ├── sidebar_hotspot.py    # SidebarHotspot — invisible 15x15 hover-intent zone, second sidebar-open method alongside right-click
    └── text_context_menu.py  # Right-click Cut/Copy/Paste/Delete context menu for metadata and tag fields
```

---

## Stylesheet Architecture

Each major component owns its stylesheet. Never call `main_window.setStyleSheet()` with a full-app stylesheet.

| Widget | Function |
|---|---|
| `main_window` | `get_base_stylesheet()` — bg, tooltips, chapter_dropdown, undo overlay |
| `title_bar` | `get_title_bar_stylesheet()` |
| `content_container` | `get_player_stylesheet()` — cover, sliders, playback buttons, metadata labels |
| `library_panel` | `get_library_stylesheet()` — skipped during hover |
| `settings_panel`, `speed_panel`, `sleep_panel` | `get_settings_stylesheet()` |
| `sprint_panel` | `get_sprint_stylesheet()` — own function, NOT `get_settings_stylesheet()`; any object name shared with another panel (e.g. `#stats_reset_btn`) needs its own rule defined here too, or Qt silently falls back to default styling (see NOTES.md 2026-08-12) |
| `sidebar` | `get_sidebar_stylesheet()` |
| `stats_panel` | `get_stats_stylesheet()` |
| `tags_panel` (`TagManagerWidget`) | `get_tags_stylesheet()` |

### Wrapping a layout in a `QWidget` for naming purposes requires explicit `setSpacing`

When a `QHBoxLayout` is added directly to a parent layout via `addLayout`, it fills the full available width and inherits style-derived spacing. When the same layout is wrapped in a `QWidget` (for `setObjectName`, `setVisible`, etc.) and added via `addWidget`, two things change: (1) the widget shrinks to its children's fixed sizes unless given `setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)`, and (2) spacing is no longer guaranteed by style inheritance. Always call `setSpacing(N)` explicitly on any layout inside a named `QWidget` wrapper.

### `WA_StyledBackground` required for QSS on plain `QWidget` containers

Any `QWidget` subclass (not `QFrame`, not `QLabel`) that owns a background-color QSS rule **must** call `setAttribute(Qt.WA_StyledBackground, True)`. Without it Qt silently ignores the background rule — the widget appears either fully transparent or painted by the system palette. This applies to every panel root widget and any intermediate container that needs its own background. Child containers that should be transparent must NOT set `WA_StyledBackground` — set it only on the root. Verified on `TagManagerWidget` (2026-05-24).

---

*Reorganization note (2026-07-13): the "Critical Architecture Rules" section was restructured to remove repetition — it previously existed as two passes (a full-prose section and a later condensed second pass covering many of the same rules). The two were merged: rules that appeared in both now appear once, under whichever fact they share, with no information dropped. Rules unique to either pass are unchanged. See the note directly under the "Critical Architecture Rules" heading for detail.*

*Last updated: 2026-09-18 Session 3 — Fixed mono/swap/L/R balance (silently broken against mpv's
own native `pan` filter shadowing ffmpeg's filter of the same name — confirmed live against a real
`ao='pulse'` mpv instance, fixed by wrapping as `lavfi=[pan=...]`); added a 5-band EQ to Settings >
Audio replacing Normalization (100/300/1000/3000/8000 Hz, ±6dB, tuned for narration not music,
reusing the confirmed-working `equalizer=f=...` syntax voice_boost already used); fixed a Settings
tab-to-tab header-pitch drift (`#settings_header`'s un-pinned height varied 1-2px per label from
font-metric descenders, independent of available space — proven via a live empirical test padding a
spacious tab with dummy groups to rule out space-driven compression, then fixed by pinning
`min-height`/`max-height: 18px`) and a Themes-tab button-row spacing outlier (a stray
`setSpacing(4)` override, the only one across every Settings button row); and fixed a same-day
regression where the cover-art-theme hover preview (closed earlier the same session) applied
synchronously with no debounce, unlike every theme swatch's 150ms queue — a brief pass-over
committed the preview instantly, fixed by routing it through the same debounce mechanism. All
live-verified by Pryme. Commits `97b5b38`, `119a2e6`, `1cc3ba9`, `b4f1325`, `5757f4e`.

*Previously: 2026-09-16 Session 2 — Volume wheel-scroll, mute click-to-restore, and a chain of
six hand-cursor/hitzone fixes, all live-verified by Pryme. Several widgets in the vol_stack area
and the chapter label are laid out wider than their visible content (a small icon centered in a
much larger label, centered text in a wider transparent-background button, a scrolling label in a
stretch=1 layout cell) — click/cursor gated on the WIDGET's bounds reached well past what was
actually on screen. Fixed, in order, each triggering live-testing that surfaced the next: the
muted icon's click/wheel/cursor zone (`_muted_icon_rect`, from the pixmap's real 14x14 size); a
stale hand cursor left over after a scroll-to-mute page swap under a stationary mouse
(`_resync_muted_icon_cursor`, called from `_settle_vol_stack`); `progress_slider`/`volume_slider`
never having a hand cursor at all (only `chapter_progress_slider` did, traced to an incidental
side effect of an unrelated feature, not a deliberate choice); the sleep/sprint countdown label's
full-button hitzone (confirmed NOT a routing bug — `QPushButton`'s whole rect is legitimately
clickable by convention when its background is transparent — narrowed anyway via
`_indicator_label_text_rect`, a font-metrics rect, per Pryme's preference); and the chapter label's
`ScrollingLabel` class-level fix (`_text_rect`, covering all three `paintEvent` cases: scrolling,
elided, static), including a follow-up stale-cursor bug found immediately after — advancing
chapters via keyboard while hovering a scrolling title's edge, landing on a short non-scrolling
chapter, left the cursor stuck until the mouse moved. That one's resync lives INSIDE
`ScrollingLabel.setText` itself (the one choke point every text change already routes through)
rather than requiring each external caller to remember a resync call, the more fragile shape the
muted-icon/sleep-label fixes used. Unrelated to the Undo/smart-rewind entries below (same day,
earlier conversation) — this entry is scoped to the vol_stack/chapter-label cursor chain only.
Commits `f2526d7`, `0370816`. Also resolved a SESSION.md structural issue: two separate
"2026-09-16 Session 1" headers had accumulated from two different conversations — merged into one
Session 1 and renumbered this work as Session 2.

*Previously: 2026-09-16 Session 1 — Extended the standard Undo distance gate to regular
skip taps/holds, live-verified by Pryme. `handle_rewind`/`handle_forward` previously only called
`_trigger_undo` for `long_skip=True` — a single regular-skip tap (`</>` buttons, or Left/Right,
default `skip_duration` 10s) or a held button/key (both auto-repeat) never armed or showed Undo
regardless of cumulative distance. Now calls `_trigger_undo` unconditionally: a single tap stays
silent on its own (10s is well under the 60s gate), but a spree of taps or a held key/button
accumulates via `save_seek_position`'s coalescing anchor and earns Undo once cumulative displacement
crosses 60s — the same mechanism the chapter-slider wheel fix already uses, now covering a fourth
input modality. Keyboard Left/Right and Shift+Left/Shift+Right route through these same methods, so
no separate keyboard-side change was needed. Commit `df1923e`. TODO.md's `[2026-07-15] Undo doesn't
return to true origin after rapid repeat Next/Prev` entry — which had narrowed the bug's scope to
Next/Prev specifically — was closed and moved to TODO_ARCHIVE.md with a correction: today's
investigation found the real root cause was general to every distance-gated call site, not
Next/Prev-specific; Next/Prev was just the easiest repro.

*Previously: 2026-09-16 Session 1 — Two follow-up Undo fixes, both live-verified by Pryme, closing
gaps the same-day anchoring fix below left open: the long-skip buttons and `|<`-to-restart
(`threshold=0.0`, "always show") showed Undo for a forward long-skip silently refused near EOF by
`seek_async`'s own guard (nothing moved) and for a backward long-skip/restart already near the start
of the book (a real but trivial move) — fixed with the standard `60 * speed` distance gate, measured
against `self.player.time_pos` read back AFTER `seek_async` returns rather than the pre-computed
target, since only the read-back correctly reads "zero" for the near-EOF silent-refusal case.
Commit `651c557`. The chapter-slider wheel scrub (`skip = max(10.0, chap_dur * 0.10)`, ~24s for a
4m04s chapter) had the identical `threshold=0.0` issue for its own reason — a 2026-05-30 commit
message's belief that the existing coalescing timestamp guard alone would "prevent spam" was never
actually true (that guard stabilizes the anchor, not whether the overlay shows) — fixed the same
way. Commit `1a6e633`. **Both retract a claim in the "Undo must anchor to a seek spree's start" rule
below stating these three sites "never had a distance gate before and must not gain one" — see that
rule's own correction note before trusting anything it says about `threshold=0.0` sites.**

*Previously: 2026-09-16 Session 1 — Fixed a separate undo-anchoring bug, live-verified by Pryme:
`Player.save_seek_position` now captures the undo anchor unconditionally on every call within a
coalescing spree, gating only whether the overlay is SHOWN on cumulative distance from that anchor
— not, as before, gating the anchor capture itself on each individual seek's own displacement. That
had let a spree of small seeks (e.g. Next through a short chapter, into a longer one) skip capturing
the true spree-start anchor on any non-qualifying press, so Undo landed on a mid-spree position
instead. New `tests/test_undo_position.py` (6 tests, no mpv/QApplication). See the "Undo must anchor
to a seek spree's start" rule under "Critical Architecture Rules" for full detail (now corrected —
see the entry directly above). Commits `3fe85a0`, `693274f` (date-typo follow-up).

*Previously: 2026-09-16 Session 1 — Fixed two smart-rewind bugs, both live-verified by Pryme:
`Player.apply_smart_rewind` no longer leaks across a book switch (`MainWindow._last_pause_timestamp`
is now cleared in `_on_book_selected_from_library`, the EOF-restart branch of `toggle_play_pause`,
and `_on_book_removed` — it lives on `MainWindow`, not `Player`, so `load_book`'s own per-book reset
never reached it), and its chapter-boundary clamp now walks `chapter_list` with
`_CHAPTER_WALK_TOLERANCE` instead of reading `self.chapter` (a confirmed third violation of the
"DO NOT use `self.player.chapter`" rule below). New `tests/test_smart_rewind.py` (7 tests, no
mpv/QApplication). See both rules under "Critical Architecture Rules" for full detail, including a
separate pre-existing mpv seek-landing-drift issue (chapter-start clipping) surfaced but not
actioned during this testing. Commit `1cffb90`.

*Previously: 2026-09-16 Session 1 — Removed the dead "dot" and "gradient" paint styles from
`ui/focus_marker.py`'s `TravelingFocusMarker`, keeping only the shipped "rotate" style (the
separate, QSS-driven `fill_highlight` config option is untouched — a different mechanism
entirely, not a fourth marker style). `_MARKER_STYLE`'s three-way dispatch, `_paint_dot`,
`_paint_gradient_trail`, and their style-only tunables (`_DOT_RADIUS`,
`_TRAIL_LENGTH_PX`/`_TRAIL_SAMPLES`/`_TRAIL_WIDTH`) are gone; `paintEvent` now calls
`_paint_rotating_border` unconditionally. Docstrings/comments describing a three-way style choice
were rewritten to describe the rotate-only mechanism, with one note pointing at git history if
either removed style is wanted again. `themes.py`'s `focus_marker`/`focus_marker_alpha` GROUP 9
doc lines, which called themselves "dot style only," were corrected — both keys are still live as
the rotate sweep's plain base color/alpha ceiling, used when no palette position applies. Full
narrative: SESSION.md, 2026-09-16 Session 1. Commit `8f6e24b`.

*Previously: 2026-09-15 Session 1 — Hover-pickup keyboard navigation (keys picking up from
wherever the mouse is hovering) shipped for Settings/Speed/Sleep/Sprint/Stats, and mouse-reclaim-
from-keyboard shipped for Settings'/Stats' tab bars — closing two TODO items that had been paused
since 2026-09-08/2026-09-10. Also gave Tags' thumbnail grid mouse/keyboard hover reconciliation for
the first time. Three live-reported rounds of bugs, each traced to a distinct, confirmed cause
rather than patched on inference. Full trace-by-trace narrative: SESSION.md and NOTES.md, both
2026-09-15. Commit `513631e`.

**Two generalizable facts worth keeping separate from the session narrative:**

1. **`_kbdnav_cursor_anchor` cannot be shared by any second consumer, even read-only, even with
   care.** It answers one specific question — "where was the mouse when keyboard mode BEGAN" — and
   `_set_keyboard_nav_active(True)` fires on EVERY qualifying keypress, not just the first; its
   early-return only skips the anchor WRITE once already active, so the very FIRST arrow press
   after a panel opens (the `False`→`True` transition) always re-stamps this anchor to the mouse's
   CURRENT position before any handler that reads it runs. A hover-pickup feature needing "has the
   mouse moved since I last checked" needs its OWN anchor (`_pickup_cursor_anchor`, added this
   session) — this is the THIRD independently-discovered failure from assuming these two questions
   could share one variable (TODO_ARCHIVE.md's "Attempt 1"/"Attempt 2" for the first two, in a
   different form each time).
2. **`QTabBar`'s native `:hover` is driven by real `HoverEnter`/`HoverMove`/`HoverLeave` events
   (`WA_Hover`), not `MouseMove`.** A synthetic `QMouseEvent(MouseMove)` dispatched via
   `QApplication.sendEvent` does NOT update `State_MouseOver` (confirmed directly — matches this
   file's documented Wayland/KDE synthetic-event unreliability elsewhere, e.g. the Themes swatch
   grid), but a synthetic `QHoverEvent(HoverMove)` DOES, cleanly and correctly. While the keyboard
   suppresses native hover via QSS (`[kbdnav="true"]...`), the mouse resting elsewhere never
   delivers such an event to the bar, so Qt's internal hover state goes stale and does NOT
   self-correct even on later genuine mouse movement (leaving and re-entering the bar doesn't fix
   it — only a click does). `MainWindow._resync_tab_bar_hover` dispatches one corrective
   `QHoverEvent(HoverMove)` at the real cursor position the instant keyboard mode releases — this
   is what finally makes Settings' two pre-existing tab-bar hover-suppression QSS rules safe to
   port to Stats (two earlier 2026-09-10 attempts broke reclaim in exactly this way and were
   reverted with "no mechanism confirmed" — see NOTES.md 2026-09-10 and 2026-09-15).

*Previously: 2026-09-13 Session 1 — Tab/Shift+Tab added to the Tags list, followed by a chain of
keyboard bugs in a tag's detail view, one genuinely data-loss-adjacent (Enter silently removing a
book from a tag) and one caused by the fix for it (the whole panel dismissing itself). Full
trace-by-trace narrative: SESSION.md, 2026-09-13 Session 1. Commits `3e21fc7`, `dc4e176`, `ae8bc9d`,
`44e0b63`.

**New, generalizable Qt fact worth keeping separate from the session narrative:** a `QLineEdit`
slot connected to `returnPressed` that changes focus SYNCHRONOUSLY (e.g. `clearFocus()`) causes Qt
to redeliver the SAME physical Return keypress to an app-wide event filter a SECOND time, once
focus has already moved — confirmed with a live offscreen harness before any fix was written on top
of the claim, precisely because it was the load-bearing fact behind a destructive bug (Enter
removing a book from a tag with no undo). Neither event identity (`id(event)`/`is`) nor
`event.spontaneous()` reliably distinguishes this phantom redelivery from a genuinely separate,
second real keypress — both were tested empirically and both failed as a detection signal. The only
robust fix found was requiring the ACTUAL widget the key is meant to act on to genuinely hold real
Qt `hasFocus()` at the moment of acting, not merely inferring intent from some other piece of state
(a non-`None` cached position, in this case) that a phantom redelivery could still satisfy. Where
that alone isn't enough — because the redelivery arrives AFTER a deliberate focus hand-off to the
very widget that's supposed to act next — the more robust fix is removing the destructive action's
ability to fire from an unselected/neutral state at all, rather than adding a guard against one more
way to reach it: TagManagerWidget's thumbnail grid now only lets Left/Right/Up/Down seed a keyboard
cursor from `None`, never Enter/Space, closing the whole class of "a bare Enter with nothing visibly
selected does something destructive" by construction. A companion, narrower Qt fact from the same
investigation: `MainWindow._focus_allows_global_shortcuts()`'s `focus is None` case (correct for "no
panel is open at all") is NOT safe once a panel IS open but a widget inside it has merely dropped
focus without another panel-local widget claiming it — a bare `clearFocus()` with no follow-up
`setFocus()` onto a sibling can silently leave a panel one arrow-key press away from calling
`hide_all_panels()` via the volume shortcut, the exact old bug the "Keyboard focus ownership"
section already documents, reachable here through a brand-new path. Any future `clearFocus()` call
inside an open panel should have a matching `setFocus()` onto some other panel-local widget in the
same breath, not left to drop to `None`.

*Previously: 2026-09-09 Session 1 — App-wide confirmation-dialog keyboard consistency: audited
all nine "arm a destructive confirmation, auto-revert after 7s" sites (Book Detail's four, Tag
Manager's delete-a-tag, Stats' reset-all-stats, Sprint's reset-all-sprint-data + a generic
conflict-confirm overlay, Sleep's own conflict-confirm overlay), then unified them on two rules:
Escape (or ANY key other than Space/Enter/Return) cancels just the confirmation and swallows that
press — never falling through to close the whole panel or perform the key's normal action — and,
at three of them, Delete now arms the confirmation from anywhere on the relevant surface.
Committed `dd3b0e6`, `fc29062`, `9eeddbc`, `ca9036f`.

**New load-bearing fact, discovered twice independently in the same pass, worth stating once
here rather than leaving it implicit in two separate commit messages:** a `keyPressEvent`
override on a panel WIDGET is not reliably reachable for every key that widget's own confirm
logic needs to intercept — TWO different keys failed this way, for two different underlying
reasons, at three different confirmations, before the actual fix landed.

- **Escape, at Sprint's and Sleep's conflict-confirm overlays.** Neither panel's widget ever
  holds real Qt focus (`PanelManager._claim_panel_focus` targets a child button instead —
  see the "Keyboard focus ownership" section above), so a `keyPressEvent` override on the
  PANEL itself was silently dead code regardless of what it contained. Confirmed via a direct
  synthetic test (not assumed) that `QObject::installEventFilter`'s documented reverse-install
  order is real: the MOST RECENTLY installed filter runs first, so `MainWindow`'s own
  `__init__`-time `QApplication`-wide filter — installed before any panel exists — runs BEFORE
  a panel's `keyPressEvent` would ever get the chance, for any key that filter chain claims
  first. The fix is the same shape Stats' `StatsPanel.eventFilter` already used correctly:
  install the panel's OWN `QApplication`-wide filter in `showEvent` (i.e. AFTER `MainWindow`'s),
  so it intercepts first. Any future confirm/dismiss logic on Sprint, Sleep, or a similar panel
  that doesn't itself hold real focus must go in `eventFilter`, not `keyPressEvent`.
- **Tab, at three Book Detail confirmations and separately at Tags' delete-tag confirm.**
  Different root cause, same shape of bug: Tab is deliberately dispatched entirely inside
  `BookDetailPanel.eventFilter` (sealed there specifically to stop it leaking to the library
  underneath — see that branch's own long-standing comment), which runs before
  `BookDetailPanel.keyPressEvent` is ever reached — so a swallow-and-dismiss check added to
  `keyPressEvent`/`_history_key_event` could never see a Tab press at all. Found live, THREE
  separate times, all traced to the one root cause and fixed in ONE place: the top of
  `eventFilter`'s own Tab branch, ahead of every tab-specific thing that branch already does
  (entering metadata edit mode, the Tags-tab field-focus toggle) — covering all four Book
  Detail confirms (two top-level: remove/mark-finished; two History-tab-local: bulk delete,
  per-row delete) in that one place, since the branch runs regardless of which tab is active.
  The IDENTICAL root cause was independently found and fixed the same session for Tags' own
  delete-tag confirm (`tag_manager.py`'s `_handle_tag_detail_keys`), where Tab was checked
  unconditionally ahead of the `_confirming_delete` swallow block, for the same underlying
  reason: Tab and "every other key" were never actually the same dispatch path to begin with.

**The transferable lesson, stated once for future reuse:** a swallow/dismiss check placed inside
one method only protects the keys that are ACTUALLY DISPATCHED THROUGH that method. Before
declaring a "catch every key except X/Y/Z" rule complete at any site, check whether every key in
that catch-all genuinely reaches the code doing the catching — Tab, Escape, and any
app-installed-`eventFilter`-intercepted key are the recurring exceptions in this codebase, not a
one-off, having now caused this same class of gap at four confirmations across two files.

**Design note on the swallow-vs-navigate question itself:** the confirm-dismiss rule chose
"swallow the triggering key entirely" (pure dismiss, no side navigation on that same press) over
"dismiss AND also perform the key's normal action" — the ONE pre-existing site that already had
any such behavior (Tags' delete-tag confirm) already swallowed, and it was kept as the reference
design rather than switched to match click-outside's own "dismiss AND land on the click target"
behavior. The two aren't actually parallel: a click's meaning is inherently spatial (it always
lands somewhere concrete), while a key's meaning is entirely contextual — letting Down both
cancel a confirm and silently move a row selection underneath it was judged a busier, less
predictable side effect than a click landing somewhere visible. Live-check list: TESTING.md's
new "Confirmation-dialog keyboard consistency" section. Full narrative, including the two failed
first attempts (an unreachable `keyPressEvent` override; a widened-but-still-incomplete Delete
scope corrected twice from live feedback) and the exact live reports that caught each gap:
SESSION.md, 2026-09-09 Session 1.

*Previously: 2026-09-08 Session 4 — Stats Day/Week/Month row-list keyboard-nav follow-through
from live testing (branch `feature/traveling-focus-marker`, still NOT merged): a pre-existing
pointing-hand-cursor-over-dead-space bug, a mouse/keyboard hover fight that took two failed ad hoc
attempts before being rewritten as a real port of the traveling marker's own poll mechanism, and a
focus-strand bug that made the marker bleed onto Book Detail. Committed `6845317`, `929cc85`.

**Mouse/keyboard hover fight — the fix is now the reference implementation for this app's
"most-recent-input-wins" principle on a `QAbstractItemView`, and TWO EARLIER ATTEMPTS at the
identical Stats bug both failed live before this one shipped.** Keyboard Up/Down/PgUp/PgDn/
Home/End on `StatsRowListView` (Day/Week/Month) move `_hovered_row` — the SAME state mouse hover
writes, by explicit live design call ("down arrow goes to the first row, highlights using the
current mouse hover"). `keyPressEvent`'s own `self.scrollTo(...)` moves row content under a
stationary cursor, and Qt still re-evaluates what's under it and can re-fire `entered` for
whatever row the mouse now occupies — even with zero real movement. Attempt 1 (exact
`QCursor.pos()` equality, refreshed on every `mouseMoveEvent`) failed live: this desktop's
cursor-position reporting is not reliably exact-equal across two reads even with the physical
mouse untouched (matches this file's own existing Wayland/KDE cursor-and-hover-quirk catalog), so
the gate was a near-always-true "moved" reading — "goes back to mouse... more aggressively"
(worse than before the fix, since the accompanying cursor-shape fix made Qt's hover
re-evaluation fire more reliably). Attempt 2 (a flat 150ms suppression window after every
keyboard move) never addressed the deeper problem: reacting to `entered` AT ALL inherits its
firing-order ambiguity relative to `scrollTo()`, which is a Qt internal, not a contract.

**The fix that actually worked ports `MainWindow._kbdnav_cursor_poll`/`_KBDNAV_CURSOR_JITTER_PX`
verbatim in shape** (the traveling-focus-marker's own, proven mechanism, already used by
Settings/Speed/Sleep/Sprint) rather than inventing a fourth mechanism: `StatsRowListView` gets its
own `QTimer` (`_kbdnav_hover_poll`, same 60ms/3px constants as the app-level version, see
`_STATS_KBDNAV_HOVER_POLL_MS`/`_STATS_KBDNAV_HOVER_JITTER_PX`) that independently samples
`QCursor.pos()` on its own clock — never reacting to any Qt hover SIGNAL while keyboard mode is
active (`_on_entered` is silenced outright) — and only hands control back to the mouse once it has
moved past jitter tolerance AND is genuinely resting over a real, DIFFERENT row (mirrors
`_cursor_over_navigable_control`'s two-part test: moved, AND actually over something). **If any
future panel needs this same "keyboard wins unless the mouse genuinely moved onto something else"
behavior, start from this poll design — an anchor-refresh design (the shape both failed Stats
attempts used, and the shape the still-paused Settings/Speed/Sleep/Sprint hover-pickup TODO item
tried and abandoned twice, see TODO.md) has now failed at this exact problem three separate
times.** Pryme's own framing, worth keeping verbatim for any future session extending this:
"Make the keys pickup from where the mouse is, and make the keys win unless the mouse hovered over
something else. This principle should be observed throughout the app with a holistic approach" —
named explicitly as not-yet-applied to Library's own pagination (same symptom: "Library doesn't
get it correctly either. Pagination makes it jump to the mouse"), deferred to TODO.md.

A SECOND, related bug surfaced from the same live re-test once the poll shipped: `showEvent` and
`leaveEvent` (both pre-existing, from the 2026-08-09 blur-grab hover-flicker fix) fire on EVERY
one of `TransportBarBlurOverlay._grab_and_blur`'s 5-15x/sec hide/show ticks while blur is enabled
and a book plays, completely unrelated to real mouse input — and both were unconditionally
re-deriving/blanking `_hovered_row` from the current cursor position on every single tick,
defeating the poll's exclusivity entirely. Pryme's own diagnosis pinned it directly: "The problem
is the blur. If I turn it off, I can navigate there with arrows. If it is on, mouse always wins."
Fixed by making both handlers defer to keyboard-hover mode exactly like `_on_entered` does — an
EARLIER version of the `showEvent` fix had called `_exit_kbdnav_hover_mode()` unconditionally
there, reasoning (wrongly) that a blur-grab-triggered visibility change was "unrelated to keyboard
state" and should always win; it is in fact the opposite, being the highest-frequency source of
spurious hover reclaims in the whole system.

**Third bug, found live during the SAME re-test session, not part of any original report: the
marker bled onto Book Detail when opened over Stats with blur on.** Traced to
`TransportBarBlurOverlay.frost_panel_backdrop`'s one-shot backdrop grab (fires once, when Book
Detail's slide-in finishes) passing Book Detail itself as the `panel` to hide for
`_grab_and_blur`'s grab (a deliberate self-exclusion, so the panel BEHIND it shows through the
frost) — Book Detail had just been given real Qt focus by `_claim_panel_focus` moments earlier at
open-start, and `_grab_and_blur`'s bare `panel.hide()`/`panel.show()` had no focus handling around
either call. Per this file's own already-documented Qt gotcha (hide() on a still-focused widget
silently re-grants focus to whatever else is around — see the "Keyboard focus ownership" section's
consequence 3), this hide handed focus back to whatever was focused in Stats BEFORE Book Detail
opened, firing a genuine FocusIn there that re-triggered the marker via the normal
`TabFocusReason`/`_update_focus_marker` path — and `panel.show()` never reclaimed focus
afterward, so it could stay stranded on the underlay rather than only flickering. Fixed by
saving/restoring focus around the hide, joining the two OTHER known side effects
`_grab_and_blur` already compensates for at the exact same hide/show pair: cursor shape
(2026-07-21 fix) and mouse hit-testing (2026-08-01 fix). **Any future addition to
`_grab_and_blur`'s hide/show block should check whether the hidden panel could plausibly hold real
Qt focus at that moment — this is now the third independently-discovered side effect of the same
two lines, not a one-off.** Confirmed working live: "I confirm it fixed. It doesn't reappear."
Also confirmed in the same pass that Session 3's `[STATS-FOCUS-TRACE]` diagnostic probe (armed for
a separate, unrelated intermittent stuck-focus bug) stopped reproducing once the
`_on_tab_changed`-tab-bar-reclaim fix from earlier this session landed — the probe was removed as
no-longer-needed. Live-check list: TESTING.md's new "Stats Day/Week/Month row-list keyboard nav"
section. Full trace, including the exact wording of both failed attempts and Pryme's own
mid-session correction about not extending working logic between panels: SESSION.md 2026-09-08
Session 4.

*Previously: 2026-09-08 Session 3 — Fill-highlight follow-up fixes, and a theme-key rename.
Two real regressions found in Session 2 earlier the same day: `kbdnav_fill_active` could get stuck
`"true"` on a panel after switching from "fill_highlight" back to "traveling" — nothing ever
cleared it under traveling style, since it's written only from the fill_highlight branch — fixed
via `MainWindow.clear_all_kbdnav_fill_active()`, the mirror-image of the existing switch-TO-
fill_highlight clear that only handled one direction. Also: **`_set_kbdnav_property`'s repolish
loop never walked the settings `QTabBar` itself, only `QPushButton` children** — `QTabBar`'s
`::tab` sub-controls cache their own style state and don't re-resolve from an ancestor's
unpolish/polish alone (the exact same fact `_set_keyboard_nav_active` already has its own
tab-bar-specific repolish block for, 2026-09-04 — the newer, more general helper never got the
same treatment). This made a new `kbdnav_tab_focused` property's own QSS rule (added this session
so fill_highlight shows a highlight on the tab bar itself, not just inside a tab) appear to work
only when an UNRELATED event — a theme switch, which does its own full repolish — happened to
also repolish the tab bar; reported live as "worked for some themes, then didn't on the same
themes again." **Any future property whose QSS rule targets a `QTabBar`/`::tab` must repolish the
tab bar explicitly — repolishing an ancestor is not enough**, joining the existing "polishing a
parent does not re-resolve a child's cached style" rule in this file's Debugging discipline
section as a second, tab-bar-specific instance of it. Also fixed: `kbdnav_fill_highlight` was
missing from `_NO_BASE_INHERIT_KEYS`, so every theme silently inherited The Color Purple's
override; and — per live color-consistency feedback comparing a Look-tab pattern-button screenshot
against a Library-tab tab-bar screenshot — keyboard focus on the tab bar was switched from the
pattern-button fill color to the SAME color mouse hover already uses, surfacing that the relevant
key was already shared across Settings/Stats/Book Detail despite its `settings_tab_hover_*`
name — renamed to `tab_hover_bg`/`_opacity`/`_text` (all ~30 theme entries, both stylesheet
functions, and a stray reference in `cover_theme.py`'s cover-art generator that the rename grep
caught). Mouse hover on a different tab is now also suppressed once keyboard focus lands on the
tab bar (narrow fix, not the full hover-pickup consolidation — that stays paused, see TODO.md).
Theme-key doc groups renumbered (GROUP 8 had shrunk to one entry, folded into GROUP 9/MISC UI).
Also this session: Look/Controls tab reordering, a Themes-tab label/spacing fix, and dimming the
theme-pool bulk buttons when they'd be a no-op — all direct live-feedback fixes, no new mechanism.
Full trace: SESSION.md, 2026-09-08 Session 3. Commits `ac0c9f1`, `8eedb00`.

*Previously: 2026-09-08 Session 2 — Added a second, alternate keyboard-nav marker style:
"fill highlight" (Settings > Look toggle, alongside the existing "Traveling marker", default
unchanged) tints the focused control's own background toward a lighter/desaturated accent instead
of drawing the separate `TravelingFocusMarker` overlay widget. `config.get_keyboard_marker_style()`
("traveling" | "fill_highlight"). New: `themes.derive_lighter_accent_rgb()` (Qt-free, `colorsys`,
same hue/lighten-desaturate design as `StreakGrid._derive_longest_fill` but independently tuned —
+12/255 value boost after two live tune-downs from +60/255, since a single global boost read wrong
on some themes' accents regardless of tuning); `kbdnav_fill_highlight` (Group 10 optional
per-theme hex override, for exactly the themes where the derived color still doesn't fit — see the
theme-key doc block); `kbdnav_fill_active` (a THIRD kbdnav QSS property, deliberately distinct
from the pre-existing `kbdnav_marker_active` — the two must never be conflated, see below);
`kbdnav_style` (a new, always-set property recording which style is active, needed because the
two style-specific properties above are each written only by their own style's code path and are
therefore unreliable to gate an "is NOT this style" check on).

**Four live-reported bugs in one feature, escalating in subtlety, each requiring the fix to be
re-opened rather than a fresh guess layered on top:** a genuinely novel QSS combinator
(`QTabBar:focus::tab:selected`, a pseudo-state chained ahead of a sub-control — nothing else in
this codebase's stylesheets does this) caused paint artifacts on Settings tab switch and was
removed outright rather than debugged blind; the new fill rule was first gated on the PRE-EXISTING
`kbdnav_marker_active` property, which is the traveling style's own "is the marker's patrol
visible" flag — conflating the two made the fill paint on top of the real traveling marker
whenever it was genuinely showing ("traveling marker still everywhere" after supposedly switching
to fill_highlight — the two style names were briefly swapped in the live bug report itself, caught
and corrected mid-diagnosis); a missing `QPushButton:focus:hover` compound (this codebase's
established pattern for a control that's simultaneously hovered and keyboard-focused) was a real
but INSUFFICIENT fix for "fill skips painting when the mouse rests on the target button" — the
actual, deeper cause was a set of pre-existing, style-unaware `[kbdnav="true"] #pattern_button:hover
{ background: transparent; }` suppression rules (2026-09-03/04 vintage, written when only the
traveling style existed) whose ID-selector specificity beat even the `:focus:hover` fix; fixing
that split the ramp-preset buttons' own separate highlight (`kbdnav_marker_active` no longer went
true at all under fill_highlight, since it's normally set only by the marker's own dormant-state
callbacks) — closed by also driving that property off the same active/inactive value
`kbdnav_fill_active` gets. Full trace-by-trace narrative, including which fixes were later shown
incomplete rather than wrong: SESSION.md, 2026-09-08 Session 2.

*Previously: 2026-09-07 Session 1 — Full keyboard navigation added to the Speed, Sleep and
Sprint panels (branch `feature/traveling-focus-marker`, still NOT merged) — the three panels
that were never tab-based, so this also required GENERALIZING the traveling-marker modality
machinery (`_set_keyboard_nav_active`, `_focus_marker_in_scope`, the `kbdnav` QSS property,
the cursor hand-back poll) beyond Settings for the first time, via a new
`_kbdnav_active_panel_key` that parameterizes on the active panel rather than rewriting the
Settings-only logic — Settings' own path stayed byte-for-byte reachable throughout, verified
against the full 504-test suite plus no live regression reports. `PanelManager.
flat_panel_rows()`/`grid_layout_for()` are the new row source for a tabless panel — a third row
shape (a real `QGridLayout`, unlike anything on a Settings tab) is represented as one opaque
stop, same architecture as Themes' `swatch_box`, that hands off to `MainWindow.
_handle_panel_grid_arrows` for real 2-D grid movement read straight from Qt's own row/column/
span structure. **Five live-found bugs, several requiring a second correction after an
initially-plausible fix was shown wrong by direct evidence**: Sprint's entire grace-period
submenu was unreachable (`flat_panel_rows`'s walk had no case for a bare `QWidget` row-wrapper —
added recursive handling that tells a `QHBoxLayout` wrapper, one row, apart from a `QVBoxLayout`
wrapper, several rows); plain Space did nothing because the code explicitly swallowed it instead
of deferring to Qt's own native Space-click; Right/Left at any row boundary could silently jump
to an unrelated row because deferring to Qt's native inter-sibling arrow stepping is NOT actually
scoped to the visual row — it follows construction order — the exact same shape
`_handle_settings_arrows` also uses and has "never shown live, but only out of luck," now flagged
in TODO.md rather than left implicit; a keyboard-focus QSS rule written as a bare
`QPushButton:focus` type selector leaked onto every plain button in the panel including
`stats_reset_btn` (a wrong in-code claim that its own ID rule would "outrank" the generic one —
it had no competing `:focus` rule at all), fixed by giving the grid's one non-ramped button
(`end_chap_btn`/`_eoc_btn`) a dedicated objectName; and the marker visibly slid off-panel with a
closing panel's slide-out on Speed/Sleep/Sprint (Settings already had this exact fix from an
earlier session, just never generalized) — now one shared `_clear_focus_marker_for_close`
helper instead of three near-copies. Also fixed: Sprint was completely missing from Tab/
Shift+Tab cycling, a pre-existing gap unrelated to this session's own work. Design corrections
applied live, not deferred: a text field's Left/Right went from "defer to native" (wrong — moves
the text cursor) to "swallow" (also rejected — "just let them continue the navigation") to
remapping Left/Right onto Up/Down for a one-item row; Sprint's duration field gained the same
digit-redirect Sleep already had, with an explicit rule that a bare digit always means duration,
never the second, conditional grace-custom field. Full narrative, including every live report
that caught each bug, in SESSION.md 2026-09-07 Session 1; live checks in TESTING.md; the
now-closed TODO.md item is removed, with the Settings-side Left/Right risk newly flagged there
instead of left implicit.

*Previously: 2026-09-06 Session 2 — Full keyboard navigation added to Settings' Themes tab
(branch `feature/traveling-focus-marker`, still NOT merged), closing out keyboard nav for the
whole Settings panel — Themes was the one tab deferred across every prior pass because its swatch
grid is bin-packed (a variable item count per row), not a fixed button row. `PanelManager.
themes_tab_rows()` is a Themes-specific row source (the generic `settings_tab_button_rows()` walk
can't see inside `pool_container`, which nests the bulk/interval rows); the swatch grid itself is
ONE opaque row (`swatch_box`, same shape as `folder_list_widget`) that owns its own internal
Left/Right/Up/Down (`MainWindow._handle_themes_swatch_arrows`) once focus reaches it. Left/Right
wrap in reading order across rows; Up/Down move by column, clamped — deliberately different
gestures. Arrival at a swatch previews it automatically through the existing 150ms hover-debounce
pipeline; Space toggles pool membership (left-click equivalent), Enter selects and activates
immediately (right-click equivalent) — these were briefly built identical and split apart after a
live design correction. **Two new "plausible QSS property, silently inert on this widget" gotchas
found by direct pixel comparison, joining the QComboBox/QListWidget ones already documented**:
`Qt.WA_UnderMouse` (even paired with `unpolish`/`polish`, even via a real dispatched
`QEnterEvent`) does NOT drive `:hover` QSS matching — confirmed by identical before/after
screenshots; fixed with a plain QSS property (`kbdnav_hover`) instead, the same mechanism
`selected`/`active_display` already use successfully in this file. `text-decoration: underline`
does NOT render on `QLabel` via QSS at all (same pixel-comparison method) — fixed with
`border-bottom` instead. A third bug needed log tracing rather than pixel comparison: the grid's
row model could silently diverge from the real on-screen layout, because `build_themes_tab` bin-
packs the swatch rows ONCE against `settings_panel`'s pre-layout width, while the keyboard-nav
code was recomputing that same limit from the panel's CURRENT (wider, post-layout) width on every
call — invalidating `get_packed_themes()`'s limit-keyed cache and returning a different packing
than what was actually painted; fixed by reading the cache directly. A fourth needed the same
category-error framing as the transport-bar-blur bug below it in this file: the keyboard exit path
was reusing `swatch_box`'s real MOUSE leaveEvent handler (`_on_themes_tab_left`), whose entire job
is telling a genuine mouse leave apart from a stationary-cursor/blur-grab artifact by comparing the
mouse's CURRENT position against where it last hovered — a keyboard exit never moves the mouse, so
a resting cursor near its last real hover position silently swallowed every arrow/Tab exit as
spurious jitter; fixed by calling the revert directly, bypassing mouse-specific disambiguation a
keyboard action doesn't need. Full narrative, including the exact live reports that caught each of
these, in SESSION.md 2026-09-06 Session 2; live checks in TESTING.md; the TODO.md item this closed
is removed — next up: Playback, Sleep and Sprint panels.

*Previously: 2026-09-05/06 Session 1 — Library's folder-list keyboard model rebuilt: cursor
position and selection are now fully independent — arrows never touch selection, Space/Enter is
the only thing that does, toggling (never splitting into add/remove keys).
`QListWidget.setCurrentRow()` is banned from this codebase's own arrow-nav paths for exactly this
widget's `ExtendedSelection` mode — it silently does `ClearAndSelect`; `_move_list_current_row`
(`QItemSelectionModel.setCurrentIndex(idx, NoUpdate)`) is the only correct way to move the cursor
alone. The current row shows as a small dot (`_FolderListItemDelegate`, `focus_folder_list_dot`),
not the traveling marker or a second fill — a fill couldn't stay legible once real selection
existed alongside it. Excluded Books (`ExcludedBooksPopup`) gained a full keyboard model of its
own, mirroring `ChapterList`'s Up/Down-scroll / Left-Right-expand / Space-Enter-activate split,
with the per-row hover-reveal eye itself standing in for a marker. Along the way: a genuine,
branch-independent interference bug between `transport_bar_blur`'s hide/show grab cycle and any
hover-driven UI (a real, matched leave+enter pair delivered to a perfectly stationary mouse,
confirmed live) — see that file's `_grab_and_blur` docstring and the "Hover-flicker" section
above, and `_leave_suppressed_recently` in `excluded_books.py` for the fix shape (suppressing only
half of a spurious pair is not enough; the matching half needs its own flag). Full narrative in
SESSION.md 2026-09-05/06 Session 1; live checks in TESTING.md.

*Previously: 2026-09-05 — Keyboard navigation extended from Look to Controls, Audio and Library
(branch `feature/traveling-focus-marker`, still NOT merged). Adding a button-row tab is now one
line in `panels._ARROW_NAV_TABS`; row membership goes by focus policy, and a widget in a tab's own
column becomes a one-item row (Audio's slider, Library's folder list). Large filled controls show
focus as a QSS fill shift instead of the marker (`_FILL_FOCUS_OBJECT_NAMES`). Full narrative in
SESSION.md 2026-09-05; live checks in TESTING.md; open items in TODO.md.

*Previously: 2026-09-04 — Traveling focus marker (branch `feature/traveling-focus-marker`, NOT
merged): rebased onto current `main` after being parked since 2026-07-10, geometry corrected, made
keyboard-only, given row-aware arrow navigation on Settings > Look, and paired with mouse-hover
suppression so only one affordance answers "where am I?" at a time. Two new Qt gotchas added to
Debugging discipline above — a tab CLICK arrives as `TabFocusReason` (so no focus reason can mean
"mouse"; record modality from the press), and polishing a parent does not re-resolve a child's
cached style (property-gated QSS needs each widget polished). Full narrative, including the three
failed modality designs and why each was wrong, in SESSION.md 2026-09-03/04; live-check list in
TESTING.md's "Traveling focus marker" section. Next session extends this to the other Settings tabs
and other panels — `_settings_is_active`/`_look_tab_is_active` and `look_tab_button_rows()` are the
Look-specific pieces that will need generalizing.

*Changelog entries from 2026-08-13 down through 2026-07-11 Session 3 (9 entries: two rounds of
scrollbar row-alignment work, Book Detail History-tab hover/focus fixes, the Stats lazy-delegate
migration across Day/Week/Month, the panel-backdrop restyle perf fix, theme hover/preview
reliability, the `visual_area` blur clip, and the transport-keyboard-shortcuts focus bugs) were
moved to NOTES.md 2026-09-12 — see "CLAUDE.md changelog tail, extracted 2026-09-12" there for the
full entries verbatim. As with the 2026-08-02 passes below, every entry had already had its
load-bearing rule or lesson promoted into a standing CLAUDE.md rule or Debugging discipline bullet
before being moved.

*Changelog entries older than 2026-07-13 (2026-06-13 through 2026-06-27 Session 3) were moved to
NOTES.md 2026-08-02 — see "CLAUDE.md changelog tail, extracted 2026-08-02" there for the full
entries verbatim, per the 2026-08-02 file-health audit (`review/Review_260802_CLAUDEMD.md`,
category 2). One correction was made before that extraction: the oldest entry (2026-06-13, the
"What's Built" audit) referenced `streak_longest_fill`/`streak_finished_dot` as current fact;
those theme keys were replaced by `streak_grid_outline`/`streak_grid_dot` on 2026-06-18 (the entry
immediately following it at the time) and do not exist in current `themes.py` — the NOTES.md copy
reflects the correction. A second pass the same day moved a further 17 entries (2026-07-01 through
2026-08-01) — see "CLAUDE.md changelog tail, extracted 2026-08-02 (second pass...)" immediately
below the first extraction in NOTES.md. Every entry moved in either pass had already had its
load-bearing rule or lesson promoted into a standing CLAUDE.md rule or Debugging discipline
bullet before being moved; nothing here was deleted, only relocated to where the file's own
Conventions section says session narrative belongs.*

