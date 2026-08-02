# Cover Management — Implementation Spec

## Overview

Implement a Cover panel tab in the book detail view. Users can store up to 4 covers per book (1 locked original + 3 user-added), switch the active cover, set a fit mode, and delete user-added covers. The `book_covers` table becomes the single source of truth for all cover display across the app.

---

## Constraints (read before touching anything)

- Do not modify any display logic, aspect ratio logic, or letterbox behavior in `cover_loader.py` or `player.py`
- Do not modify `ScannerWorker._extract_metadata` logic — only add one upsert call at the end of it
- Do not rename any existing signals
- Do not modify `books` table structure
- Do not introduce circular imports
- Keep all new DB methods in `db.py`
- Keep all new file management helpers in a new file: `src/fabulor/library/cover_manager.py`
- Keep the new widget in a new file: `src/fabulor/ui/cover_panel.py`
- All image file I/O must be wrapped in try/except

---

## Pending (do not implement now, note only)

- `books.cover_path` column is marked for eventual deletion once `book_covers` is fully stable. No action required in this spec.

---

## 1. Database Schema

### New table: `book_covers`

```sql
CREATE TABLE IF NOT EXISTS book_covers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    book_path   TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    is_locked   INTEGER NOT NULL DEFAULT 0,   -- 1 = scanner-extracted, cannot be deleted
    is_active   INTEGER NOT NULL DEFAULT 0,   -- 1 = currently displayed everywhere
    fit_mode    TEXT NOT NULL DEFAULT 'fit',  -- 'fit' | 'stretch' | 'tile' | 'crop'
    sort_order  INTEGER NOT NULL DEFAULT 0,   -- 0 = locked original, 1–3 = user-added
    added_at    TEXT NOT NULL,
    FOREIGN KEY (book_path) REFERENCES books(path) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_book_covers_book_path ON book_covers(book_path);
```

Add this `CREATE TABLE` and `CREATE INDEX` to the existing schema initialisation in `db.py` (wherever other `CREATE TABLE IF NOT EXISTS` calls live).

---

## 2. New DB Methods (`db.py`)

Add the following methods to the existing `Database` class. Do not modify any existing methods.

### `get_active_cover(book_path: str) -> dict | None`
Returns the active cover row as a dict (`id`, `file_path`, `fit_mode`) for the given book path. Returns `None` if no rows exist for this book.

```python
def get_active_cover(self, book_path: str) -> dict | None:
    row = self.conn.execute(
        "SELECT id, file_path, fit_mode FROM book_covers "
        "WHERE book_path = ? AND is_active = 1 LIMIT 1",
        (book_path,)
    ).fetchone()
    return dict(row) if row else None
```

### `get_covers_for_book(book_path: str) -> list[dict]`
Returns all cover rows for a book ordered by `sort_order`. Each row as dict: `id`, `file_path`, `is_locked`, `is_active`, `fit_mode`, `sort_order`.

### `upsert_cover(book_path: str, file_path: str, is_locked: bool, is_active: bool, fit_mode: str, sort_order: int) -> int`
Inserts a new row. Returns the new row `id`. Sets `added_at` to current UTC ISO timestamp.

### `set_active_cover(book_path: str, cover_id: int) -> None`
Sets `is_active = 0` for all rows with this `book_path`, then sets `is_active = 1` for the row with this `cover_id`. Single transaction.

### `set_fit_mode(cover_id: int, fit_mode: str) -> None`
Updates `fit_mode` for the given `cover_id`.

### `delete_cover(cover_id: int) -> None`
Deletes the row. Caller is responsible for ensuring `is_locked = 0` before calling. Caller is also responsible for deleting the file from disk.

### `count_covers_for_book(book_path: str) -> int`
Returns the count of rows for this `book_path`.

---

## 3. Scanner Integration (`scanner.py`)

In `ScannerWorker._extract_metadata`, after the existing thumbnail cache logic that sets `cover_path`, add:

```python
# Upsert into book_covers as locked slot 0 if not already present
if cover_path:
    existing = db.get_covers_for_book(book_dir_str)  # use book path key
    locked_exists = any(c['is_locked'] for c in existing)
    if not locked_exists:
        db.upsert_cover(
            book_path=book_dir_str,
            file_path=cover_path,
            is_locked=True,
            is_active=True,
            fit_mode='fit',
            sort_order=0
        )
```

The `book_path` key used here must match the key stored in `books.path` — confirm this before implementing.

---

## 4. `get_active_cover_path` helper (`db.py`)

Add a convenience method that returns just the file path string for use throughout the app:

```python
def get_active_cover_path(self, book_path: str) -> str | None:
    cover = self.get_active_cover(book_path)
    return cover['file_path'] if cover else None
```

### Migration of existing callers

Find every location in the codebase that reads `book.cover_path` (or `books.cover_path`) for the purpose of *displaying* a cover image. Replace each with a call to `db.get_active_cover_path(book.path)`. 

Specifically check:
- `cover_loader.py`
- `player.py` — display path only, not `extract_cover` (leave `extract_cover` untouched)
- Any `BookItem` widget that reads `cover_path` for thumbnail display
- Library panel cover loading

Do not change the scanner's write to `books.cover_path` — that write stays as-is.

---

## 5. File Management (`src/fabulor/library/cover_manager.py`)

New module. No Qt imports — pure file I/O.

```python
from pathlib import Path
import platformdirs
import shutil

COVERS_DIR = Path(platformdirs.user_data_dir("fabulor", "fabulor")) / "covers"

def get_covers_dir() -> Path:
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    return COVERS_DIR

def save_cover_image(book_hash: str, slot_index: int, source_path: str) -> str | None:
    """
    Copies source image into the covers data dir.
    Returns destination path string, or None on failure.
    Slot index 1–3 (slot 0 is scanner-managed).
    """
    try:
        dest = get_covers_dir() / f"{book_hash}_{slot_index}.jpg"
        shutil.copy2(source_path, dest)
        return str(dest)
    except Exception:
        return None

def delete_cover_file(file_path: str) -> None:
    """Silently deletes a cover file. No-op if file does not exist."""
    try:
        Path(file_path).unlink(missing_ok=True)
    except Exception:
        pass

def validate_cover_file(file_path: str) -> str | None:
    """
    Returns None if valid.
    Returns error string if invalid (too large, unreadable format).
    Max size: 5 MB.
    """
    try:
        size = Path(file_path).stat().st_size
        if size > 5 * 1024 * 1024:
            return "Image exceeds 5 MB limit."
        return None
    except Exception:
        return "Could not read file."
```

`book_hash` is the MD5 of the book directory path — same hash already used by the scanner. Reuse that logic.

---

## 6. Cover Panel Widget (`src/fabulor/ui/cover_panel.py`)

### Layout (300×360 canvas, 6px H / 10px V padding)

```
┌──────────────────────────────────────────┐
│ ┌──────┐  ┌─────────────────────────┐   │
│ │ T0   │  │                         │   │
│ │      │  │                         │   │
│ ├──────┤  │     main preview        │   │
│ │ T1   │  │     (fit mode applied)  │   │
│ │      │  │                         │   │
│ ├──────┤  │                         │   │
│ │ T2   │  │                         │   │
│ │      │  └─────────────────────────┘   │
│ ├──────┤  ┌─────────────────────────┐   │
│ │ T3   │  │  [Fit] [Stretch] [Tile] │   │
│ │      │  │  [Crop]                 │   │
│ ├──────┤  └─────────────────────────┘   │
│ │  +   │                                │
└──────────────────────────────────────────┘
```

- Left column width: 72px. Padding between columns: 8px.
- Thumbnail height: ~72px each. Gap between thumbs: 6px.
- `+` button: same 72×36px slot at the bottom of the left column. Hidden when user cover count = 3 (total covers = 4).
- Main preview: remaining width × ~240px height.
- Fit mode buttons: remaining width × ~50px, below preview.

### Thumbnail widget (`CoverThumbnail`, inner class or separate)

Each thumbnail is a `QLabel` or `QFrame` subclass showing a scaled cover image.

**States:**
- Normal: no overlay
- Hovered: bottom overlay appears — left half `×`, right half `✓`, separated by a 1px vertical line. Semi-transparent dark background. Only show `✓` if this thumb is not already active. Always show `×` unless `is_locked = True`.
- Active: 2px solid accent color outline (use existing theme accent). No other indicator needed.
- Selected (clicked, shown in preview): slightly different background tint or border style — TBD, keep subtle.

**Interactions:**
- Click anywhere on thumb (outside overlay): loads this cover into the main preview. Does not change active cover.
- Click `✓`: calls `set_active_cover`. Updates outline states. Emits signal to notify the rest of the app.
- Click `×`: calls `delete_cover` + `delete_cover_file`. Removes thumb from column. If deleted cover was active, promote the locked cover (slot 0) to active automatically.

### Main preview

`QLabel` with fixed size. Renders the selected cover using the current fit mode. Re-renders on fit mode button change without saving until the user confirms — actually, **save immediately** on fit mode button click. No confirm step. The preview is the confirmation.

**Fit mode rendering:**

- `fit`: `Qt.KeepAspectRatio` scaled to fit within preview bounds. Letterbox/pillarbox background fills remainder (use existing letterbox logic from `cover_loader.py` — replicate or call directly).
- `stretch`: `Qt.IgnoreAspectRatio` scaled to fill preview exactly.
- `tile`: paint the image tiled across the preview area. Use `QPainter` with `drawTiledPixmap`.
- `crop`: `Qt.KeepAspectRatioByExpanding` scaled, then center-cropped to preview bounds.

### Fit mode buttons

Segmented control style — four `QPushButton` in a `QHBoxLayout`. Checkable, mutually exclusive (`QButtonGroup`). Active button uses accent color background. Labels: `Fit` `Stretch` `Tile` `Crop`.

On click: updates `fit_mode` in DB via `db.set_fit_mode(cover_id)`, re-renders preview. Only active cover's fit mode is persisted and used elsewhere.

### `+` button

Opens `QFileDialog.getOpenFileName` filtered to `Images (*.jpg *.jpeg *.png)`. On selection:
1. Call `validate_cover_file` — if error, show inline text below the `+` button for 3 seconds, then clear.
2. Convert PNG to JPEG in memory using `QImage` before saving (keep storage consistent).
3. Determine next available `slot_index` (1, 2, or 3).
4. Call `save_cover_image` → get destination path.
5. Call `db.upsert_cover` with `is_locked=False`, `is_active=False`, `fit_mode='fit'`, appropriate `sort_order`.
6. Add new `CoverThumbnail` to the column.
7. Hide `+` button if count now = 4.

### Signals emitted by `CoverPanel`

```python
active_cover_changed = Signal(str)  # emits file_path of new active cover
```

This signal is connected by the parent panel/controller to refresh the player, library item, and any other display locations. Do not implement those refresh connections in this file — emit only.

---

## 7. Integration into existing tab system

The Cover panel is one of the tabs alongside Stats, History, Tags. Wire `CoverPanel` into whichever widget hosts those tabs. Pass `book_path` and `db` instance on construction or via a `load_book(book_path)` method.

Connect `active_cover_changed` signal to:
- Player cover display refresh
- Library `BookItem` thumbnail refresh for this book
- Any other panel currently showing this book's cover

Identify existing refresh/reload patterns in those components and follow them — do not introduce new patterns.

---

## 8. Stylesheet

Add a `get_cover_panel_stylesheet()` function to the existing per-component stylesheet module. Follow the existing pattern exactly. Do not use `QApplication.instance().setStyleSheet()`.

Style targets (use `setObjectName`):
- `CoverThumbnailActive` — active thumb outline
- `CoverThumbnailHover` — overlay background
- `FitModeButton` — base state
- `FitModeButtonActive` — selected state
- `CoverAddButton` — `+` button
- `CoverErrorLabel` — inline error text (red/warning color from theme)

---

## 9. File checklist

Files to **create**:
- `src/fabulor/library/cover_manager.py`
- `src/fabulor/ui/cover_panel.py`

Files to **modify**:
- `db.py` — schema, new methods
- `scanner.py` — one upsert after thumbnail cache write
- `cover_loader.py` — replace `book.cover_path` reads with `db.get_active_cover_path()`
- `player.py` — display path only
- `BookItem` widget — thumbnail display path
- Existing tab host widget — add Cover tab, connect signal
- Existing stylesheet module — add `get_cover_panel_stylesheet()`

Files to **not touch**:
- `player.py` `extract_cover` method
- Any aspect ratio / letterbox logic
- `ScannerWorker._extract_metadata` logic (add only, at the end)
- Any existing signal definitions

---

## 10. Testing checklist (add to TESTING.md)

- [ ] Fresh book scan: `book_covers` row created with `is_locked=1`, `is_active=1`
- [ ] Cover tab opens: locked thumb visible with no `×` overlay
- [ ] Add cover: file picker opens, PNG converts to JPEG, thumb appears, DB row inserted
- [ ] Add cover > 5MB: inline error appears, no DB write, no file copy
- [ ] Add 3 user covers: `+` button disappears
- [ ] Delete user cover: thumb removed, DB row deleted, file deleted from disk
- [ ] Delete active user cover: locked cover becomes active automatically
- [ ] Set active: outline moves to new thumb, `active_cover_changed` signal fires
- [ ] Player cover updates after active cover change
- [ ] Library thumbnail updates after active cover change
- [ ] Fit mode buttons: preview re-renders immediately for each mode
- [ ] Fit mode persisted: close and reopen Cover tab, correct button selected
- [ ] Book with no `book_covers` rows (pre-migration): `get_active_cover_path` returns `None` gracefully
