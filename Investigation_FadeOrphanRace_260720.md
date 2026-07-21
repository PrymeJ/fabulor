# Investigation: `_pending_fade_call` Orphan-Then-Late-Resume Race

**Date:** 2026-07-20
**Branch:** `blur-composited-overlay` (base: `main`, merge-base commit `cc793e3`)
**Scope:** Determine whether the 10-second `_pending_fade_call` orphan race (hover-mid-fade → stash → unresolved until an unrelated `complete_main_fade()` call) is a long-latent bug that simply never had the right timing line up, or something newly introduced/newly much-more-reachable on this branch.

## Direct answer

**This is newly reachable, not long-latent — and the branch commit that made it reachable is identifiable with certainty: `ca492a8` (2026-07-20 04:51, this branch).**

More precisely: the *orphan-write* mechanism (`.stop()` not emitting `finished`, silently stranding `_pending_fade_call`) has existed, structurally unchanged, since `_pending_fade_call` was introduced in commit `c281ee3` (2026-07-18, pre-branch). But **prior to `ca492a8`, `complete_main_fade()` had no code path that could ever drain or resume an orphaned stash at all** — the only consumer of `_pending_fade_call` was `_on_fade_finished`, wired to `QPropertyAnimation.finished`, which `complete_main_fade()`'s own `_fade_anim.stop()` call bypasses by Qt design. So pre-branch, hitting this exact sequence would not have produced a 10-second-late resume — it would have produced a **permanent** stash orphan (until some other, unrelated event happened to overwrite/reset the relevant state some other way), which is a different and arguably worse-looking failure mode than what was traced. The specific "eventually resolved by an unrelated panel-open" behavior the log trace shows is only possible because `ca492a8` added that exact resume branch to `complete_main_fade()` on this branch, three days ago.

## Evidence

### 1. Pre-branch state of `_pending_fade_call` and `complete_main_fade`

- `_pending_fade_call` was introduced in commit `c281ee3` ("fix: defer the pool-theme revert when a book is excluded while a panel is open", 2026-07-18 02:26, an ancestor of the branch merge-base). Its commit message documents the design explicitly: *"[the pending call] resumes via `_fade_anim`'s own finished signal (`_on_fade_finished`), zero-delay and event-driven."* No other resume path was added by this commit.
- `complete_main_fade()` itself predates `_pending_fade_call` entirely — it was introduced by an earlier commit `ba88847` ("fix: complete an in-flight main-window theme fade cleanly when the sidebar opens"). `c281ee3` did **not** touch `complete_main_fade()` at all.
- Read directly at the branch merge-base (`git show cc793e3:src/fabulor/ui/theme_manager.py`, lines 751–781), `complete_main_fade()` at that point:
  ```python
  def complete_main_fade(self):
      ...
      self.flush_deferred_restyle()
      if not getattr(self, '_fade_in_flight', False):
          return
      self._fade_in_flight = False
      if hasattr(self, '_fade_anim') and self._fade_anim.state() == QPropertyAnimation.Running:
          self._fade_anim.stop()          # <-- does NOT emit `finished`
      ...
      self._apply_stylesheets(self._active_display_theme, hover=self._is_hover_active)
  ```
  There is **no reference to `_pending_fade_call` anywhere in this method** at the merge-base. It unconditionally falls through to reapplying `self._active_display_theme`/`self._is_hover_active` — the exact stale-state fallback described in the bug trace — but it never checks, drains, or resumes `_pending_fade_call`.
- `_on_fade_finished()` at the same merge-base commit (lines 187–207) is the *only* method with the drain/resume logic:
  ```python
  def _on_fade_finished(self):
      ...
      if self._pending_fade_call is not None:
          pending = self._pending_fade_call
          self._pending_fade_call = None
          self._on_theme_changed(*pending)
  ```
  This is connected via `self._fade_anim.finished.connect(self._on_fade_finished)` — the Qt `finished` signal, which `QPropertyAnimation.stop()` does not emit.

**Conclusion for step 1:** at the commit immediately before the branch diverged, calling `.stop()` on the fade animation from `complete_main_fade()` while `_pending_fade_call` held a stash would orphan it with **no resume path in the entire codebase** — not a 10-second-late resume, an indefinite/permanent one (until whatever next fully-independent call happened to overwrite the stale fields through some other mechanism, if ever). The theoretical trigger condition (hover mid-fade, then `.stop()` without draining the stash) was present pre-branch, but its *consequence* was structurally different and had no code-level mechanism to ever self-correct.

### 2. What changed on `blur-composited-overlay`

Full list of branch-only commits (`git log main..blur-composited-overlay`, base `cc793e3`):

| Commit | Summary | Touches fade/hover timing? |
|---|---|---|
| `e068d27` | docs only | no |
| `b2e0eb0` | feat: composited-overlay blur for transport bar | new feature, blur-grab machinery, no `_fade_anim`/`_pending_fade_call` changes |
| `ca492a8` | **fix: event-driven blur refresh + feedback-loop fix + diagnostic tracing** | **YES — see below** |
| `11c764d` | docs only | no |
| `b68d820` | wip: partial guard on `ThemeItem.enterEvent` | touches hover-adjacent code in `title_bar.py`, not `_pending_fade_call`/`complete_main_fade` |
| `a531d7c` | docs only | no |
| `0439c76` | fix: `_active_display_theme` privatization (`get_active_theme()`) + hover gate in `refresh_dirty()` | Adds the `_is_hover_active` read-gate in `transport_bar_blur.py`'s `refresh_dirty()` (already ruled out of scope per task — confirmed working as scoped, and confirmed it does not touch `_fade_anim`/`_pending_fade_call`/`complete_main_fade`'s control flow) |
| `6587f1b` | docs only | no |

**`ca492a8` is the only commit on this branch that touches `complete_main_fade()`'s control flow around `_pending_fade_call`.** Its diff (confirmed by direct read, see diff excerpt below) adds:
1. Diagnostic `[BLEED-TRACE]` logging (no behavior change).
2. **The actual drain/resume branch** inside `complete_main_fade()`:
   ```python
   if self._pending_fade_call is not None:
       pending = self._pending_fade_call
       self._pending_fade_call = None
       logger.warning(f"[BLEED-TRACE] complete_main_fade RESUMING pending call args={pending!r}")
       self._on_theme_changed(*pending)
       ...
       return
   ```
   placed after `_fade_anim.stop()` and before the old unconditional stale-reapply fallback.

The commit message for `ca492a8` is explicit that this is new, unverified code, added specifically in response to suspecting this exact bug: *"complete_main_fade() (theme_manager.py): a fix for a suspected fade-orphan bug is present but UNVERIFIED — testing so far has not exercised the condition it targets."*

This is not a case of the branch changing *scheduling pressure* on the event loop (more frequent timers, more repaints, more `.stop()` calls elsewhere) — it is simpler and more direct than that: **the branch added the only code path capable of resuming an orphaned stash from `complete_main_fade()` at all.** Before `ca492a8` existed, there was no "late" resume to observe, because there was no resume.

Regarding the hover gate in `refresh_dirty()` (`transport_bar_blur.py`, added in `0439c76`): it reads `_is_hover_active` on repaint-triggered ticks but does not call `.stop()` on `_fade_anim`, does not touch `_pending_fade_call`, and does not call `complete_main_fade()` or `_on_theme_changed()`. It is a pure read-only gate on an unrelated grab decision. No causal link to the orphan/resume timing was found in this commit; it is correctly excluded per the task's framing, and this investigation independently confirms that exclusion.

### 3. Reachability reasoning

Could the exact 10-second orphan-then-late-resume have happened on pre-branch code (`cc793e3` and earlier), given enough hover/dismiss cycles?

**No — not in the form it was traced.** Pre-branch, `complete_main_fade()` had no `_pending_fade_call` awareness whatsoever. The *write* side of the race (stash a call while `_fade_in_flight`, then `.stop()` the animation from `complete_main_fade()` without emitting `finished`) was reachable pre-branch — nothing about that half changed. But the *read/resume* side did not exist pre-branch in `complete_main_fade()`. So pre-branch, hitting this sequence would not self-correct via a later, unrelated `complete_main_fade()` call (there was nothing in that method to trigger a correction) — the stash would sit indefinitely, and the visible symptom (if it ever occurred) would look like a permanent bleed until something else independently reset `_active_display_theme_internal`/`_is_hover_active` through a wholly different mechanism (e.g., a full theme reapply from an unrelated flow), not a "10 seconds later, self-heals" pattern.

This also explains why the user never observed this in months of pre-branch use: the failure mode pre-branch would have been a **persistent, sticky** theme-bleed, not a transient 10-second flash — a much more noticeable and different-looking symptom that, if it had ever triggered, would likely have been reported/noticed differently (or perhaps never actually triggered at all pre-branch, since nothing in this investigation found evidence that the write side was exercised in practice before now — that's a separate, unresolved question about the write-side rate, not addressed by this investigation's scope).

**Confidence: high.** This conclusion rests on direct reads of the actual code at the merge-base commit (`git show cc793e3:...`) showing the complete absence of any `_pending_fade_call` reference in `complete_main_fade()`, cross-checked against the commit that introduced the resume branch (`ca492a8`) and its own commit message, which independently corroborates that this exact fix was written in direct response to a live-traced bleed bug on 2026-07-20 (today, on this branch) and was explicitly marked unverified at the time it was added.

### 4. Specific causal mechanism

The blur-branch commit `ca492a8` is implicated, but **not** via the hover-gate/scheduling-pressure theory the user's framing raised as a hypothesis to check. The concrete mechanism is simpler:

- **Before `ca492a8`:** `complete_main_fade()` → `_fade_anim.stop()` → stash in `_pending_fade_call` is never read by this method → method falls through to its old unconditional `self._apply_stylesheets(self._active_display_theme, hover=self._is_hover_active)` fallback, using stale state, forever (or until unrelated code resets those fields).
- **After `ca492a8`:** `complete_main_fade()` → `_fade_anim.stop()` → **new code checks `_pending_fade_call`, and if set, drains it and re-invokes `_on_theme_changed(*pending)`** — which is exactly the mechanism the live trace observed firing 10 seconds late, from an unrelated panel-open's call into `complete_main_fade()`.

No evidence was found that `ca492a8` (or any other branch commit) changed *when* `.stop()` gets called, *how often* fades restart, or *how often* `complete_main_fade()`/`_on_theme_changed()` run relative to each other. The hover-gate in `refresh_dirty()` (`0439c76`) was checked specifically per the task's instruction and found to have no call path into `_fade_anim`, `complete_main_fade`, or `_pending_fade_call` — it cannot plausibly be the cause, and no other candidate besides `ca492a8` was found among the branch's commits.

## Summary table

| Question | Answer |
|---|---|
| Did the `.stop()`-without-`finished` orphan-*write* mechanism exist pre-branch? | Yes, since `c281ee3` (2026-07-18), unchanged since. |
| Did a resume path for that orphan exist in `complete_main_fade()` pre-branch? | **No.** Confirmed by direct read of `cc793e3:theme_manager.py`. |
| What added the resume path? | `ca492a8` (this branch, 2026-07-20 04:51), the diagnostic-logging + "fix for a live-traced bug" commit, explicitly marked unverified at commit time. |
| Is the hover gate in `refresh_dirty()` implicated? | No causal link found; it doesn't touch `_fade_anim`/`_pending_fade_call`/`complete_main_fade`. |
| Latent-but-never-surfaced, or newly reachable? | **Newly reachable in this specific late-resume form** — pre-branch the same trigger sequence would have produced a different (permanent, not transient) failure mode, because nothing existed to resume it. |
