"""One-time cleanup: zero already-poisoned sub-threshold progress values.

Root cause (fixed 2026-07-13, `_logical_pos`, see NOTES.md "Compounding seek drift fixed via
`_logical_pos`" and "Near-zero saved positions show spurious library progress"): before the fix,
`_save_current_progress` persisted mpv's raw reported `time_pos`, which could carry a small
residual (e.g. the `_PAUSED_SEEK_UNDERSHOOT_COMP` undershoot) even for a book opened and closed
without genuine playback. Values below `MIN_PROGRESS` (1.0s, `ui/library.py`) don't display as
progress, but `MIN_PROGRESS` is a coarse gate — the underlying value can still creep just above it
and draw a spurious progress bar/percentage in the library. Those existing sub-threshold values
won't self-heal now that the source fix has landed; this script zeroes them one time.

Cleans BOTH stores:
  - DB `books.progress` (SQLite, `platformdirs.user_data_dir("fabulor", "fabulor")/library.db`)
  - QSettings `pos_{file_path}` keys (org "Fabulor", app "Fabulor")

Threshold: zeroes any value in `(0, MIN_PROGRESS]` — matches `ui/library.py`'s own `MIN_PROGRESS`
gate exactly, so nothing that would already display as real progress is touched.

Usage:
    python tools/cleanup_poisoned_progress.py            # dry run — reports what WOULD change
    python tools/cleanup_poisoned_progress.py --apply     # actually writes the zeroing

Safety: the DB should be backed up before running with --apply (this script does not do it for
you — the file is a plain SQLite file, trivially copied). QSettings changes are logged with their
prior values printed to stdout, so they can be manually restored if needed (QSettings has no
built-in backup/restore).
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import platformdirs
from PySide6.QtCore import QSettings

MIN_PROGRESS = 1.0  # must match ui/library.py's MIN_PROGRESS


def clean_db(db_path: Path, apply: bool) -> int:
    if not db_path.exists():
        print(f"DB not found at {db_path} — skipping DB cleanup.")
        return 0
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT path, title, progress FROM books WHERE progress > 0 AND progress <= ?",
            (MIN_PROGRESS,),
        ).fetchall()
        print(f"\nDB: {len(rows)} poisoned row(s) found in {db_path}")
        for r in rows:
            print(f"  {r['progress']!r}  {r['title']}")
        if apply and rows:
            conn.execute(
                "UPDATE books SET progress = 0.0 WHERE progress > 0 AND progress <= ?",
                (MIN_PROGRESS,),
            )
            conn.commit()
            print(f"DB: zeroed {len(rows)} row(s).")
        return len(rows)
    finally:
        conn.close()


def clean_qsettings(apply: bool) -> int:
    settings = QSettings("Fabulor", "Fabulor")
    poisoned = []
    for key in settings.allKeys():
        if not key.startswith("pos_"):
            continue
        val = settings.value(key)
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        if 0 < fval <= MIN_PROGRESS:
            poisoned.append((key, fval))

    print(f"\nQSettings: {len(poisoned)} poisoned pos_ key(s) found")
    for key, val in poisoned:
        print(f"  {val!r}  {key}")
    if apply:
        for key, _ in poisoned:
            settings.setValue(key, 0.0)
        settings.sync()
        print(f"QSettings: zeroed {len(poisoned)} key(s).")
    return len(poisoned)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually write the changes (default is dry-run)")
    args = parser.parse_args()

    db_path = Path(platformdirs.user_data_dir("fabulor", "fabulor")) / "library.db"

    if not args.apply:
        print("DRY RUN — pass --apply to actually zero these values.\n")

    db_count = clean_db(db_path, args.apply)
    qs_count = clean_qsettings(args.apply)

    print(f"\nTotal: {db_count} DB row(s), {qs_count} QSettings key(s)"
          f" {'zeroed' if args.apply else 'would be zeroed'}.")


if __name__ == "__main__":
    main()
