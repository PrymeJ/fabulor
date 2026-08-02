# `review/` — standalone analysis documents

Everything here is a **dated, point-in-time artifact**. Nothing in this folder is maintained after
the day it was written, and nothing here is authoritative about how the app works *now*. The live,
maintained documents are all at the repo root: `CLAUDE.md`, `NOTES.md`, `SESSION.md`, `TODO.md`,
`DEBT_INVENTORY.md`, `TESTING.md`, `KEYBINDINGS.md`.

## Naming

    Type_YYMMDD_topic.md

The date is **mandatory** and is the date the document was written, not the period it covers. A
file without a date reads as current forever; two of these (`SPEC_cover_management.md`,
`VALIDATION_RUNBOOK.md`) had no date until 2026-08-02 for exactly that reason.

`topic` is lowercase snake_case. The older `Review_260612_1..8` batch keeps its numeric suffixes —
they are one sequential audit, and renaming them would break the many references in NOTES.md and
SESSION.md for no gain.

## Types

Six, chosen by **what the document is for**, not by what activity produced it:

| prefix | what it is |
|---|---|
| `Review_` | Findings about the codebase — audits, invariant sweeps, targeted passes, one-off investigations that reached a conclusion. **The default.** |
| `Investigation_` | A single bug or mechanism traced in depth, usually diagnosis-only with no fix applied yet. |
| `Report_` | A question asked and answered, usually with measurements (feasibility, cost, "is X avoidable"). |
| `Data_` | Raw measurements. A companion to a NOTES.md entry, not a narrative. |
| `Snapshot_` | A description of how something works **as of one commit**. Goes stale fastest; must say so in its own header. |
| `Spec_` / `Runbook_` | Forward-looking: what to build, or a procedure to follow by hand. |

**`Audit_` is not a type.** It was tried on 2026-08-02 and folded into `Review_` the same day: the
existing `Review_260612_1` calls itself an "Invariant Audit", `Review_260706_2` calls itself an
"INVESTIGATION", and `Review_260802_CLAUDEMD` calls itself an "audit". The prefixes were already
interchangeable in practice, so a separate one drew a distinction that does not exist.

## Two rules that exist because they were broken

**1. Never name a file here the same as a root document.** `review/DEBT_INVENTORY.md` (a frozen
2026-06-12 snapshot) sat alongside the live `/DEBT_INVENTORY.md` and was read as a second, competing
debt index by a reviewer on 2026-08-02 — *despite* a `> **STALE**` banner in its first three lines.
The banner did not help, because the collision is in the **filename**, which is what gets seen first
in a file list, a grep result, or an editor tab. It is now
`Snapshot_260612_debt_inventory.md`.

**2. Every document here must be linked from a root doc.** An unreferenced file is an invisible
one. Seven files from the 2026-07-20..21 theme work were written to the repo root, cited from no
main doc, and went unread for six weeks — one of them (`Review_260720_theme_reach.md`) was
rediscovered only because it happened to be opened in an editor, while a later session re-derived a
worse version of its call-site inventory from greps. Worse, `review/` already held three closely
related perf reports that the same session never found, including
`Report_260715_apply_stylesheets_avoidable_work.md` — direct prior art on the exact question it was
investigating.

So: write the document here, then summarize its conclusion into `NOTES.md` (root-cause writeups),
`TODO.md` (deferred work) or `DEBT_INVENTORY.md` (known debt), and link it from there.
`DEBT_INVENTORY.md` carries an index of the theme-work documents with their current status.
