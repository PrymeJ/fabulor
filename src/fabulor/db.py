import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import contextmanager
from .models.book import Book
import platformdirs

class LibraryDB:
    """Handles all SQLite database operations for the audiobook library."""
    
    def __init__(self, db_path=None):
        if db_path is None:
            # Cross-platform data directory resolution
            data_dir = Path(platformdirs.user_data_dir("fabulor", "fabulor"))
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = data_dir / "library.db"
        else:
            self.db_path = Path(db_path)

        self._create_tables()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _create_tables(self):
        """Initializes the database schema."""
        with self._get_conn() as conn:
            # Stores folders/locations the user wants the app to monitor
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scan_locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL
                )
            """)
            
            # Stores individual book metadata
            conn.execute("""
                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    folder_name_raw TEXT,
                    title TEXT,
                    author TEXT,
                    narrator TEXT,
                    duration REAL,
                    progress REAL DEFAULT 0,
                    cover_path TEXT,
                    year INTEGER,
                    date_added DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_played DATETIME,
                    started_at DATETIME,
                    finished_at DATETIME,
                    chapter_source TEXT DEFAULT 'embedded',
                    is_deleted INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_books_last_played ON books (last_played)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_books_title ON books (title)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_books_author ON books (author)")
            conn.execute("PRAGMA foreign_keys = ON")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS listening_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_path TEXT NOT NULL,
                    book_title TEXT,
                    book_author TEXT,
                    book_duration REAL,
                    session_start TEXT NOT NULL,
                    session_end TEXT NOT NULL,
                    position_start REAL,
                    position_end REAL,
                    furthest_position REAL,
                    listened_seconds REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_path_start ON listening_sessions (book_path, session_start)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS book_tags (
                    book_path TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    UNIQUE(book_path, tag)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    name TEXT PRIMARY KEY,
                    color TEXT DEFAULT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS book_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_path TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_time DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_book_events_book_path ON book_events (book_path)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_book_events_event_type ON book_events (event_type)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS book_covers (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_path   TEXT NOT NULL,
                    file_path   TEXT NOT NULL,
                    is_locked   INTEGER NOT NULL DEFAULT 0,
                    is_active   INTEGER NOT NULL DEFAULT 0,
                    fit_mode    TEXT NOT NULL DEFAULT 'fit',
                    sort_order  INTEGER NOT NULL DEFAULT 0,
                    added_at    TEXT NOT NULL,
                    FOREIGN KEY (book_path) REFERENCES books(path) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_book_covers_book_path ON book_covers(book_path)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS book_files (
                    book_path TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    cumulative_start_ms INTEGER NOT NULL,
                    title TEXT,
                    PRIMARY KEY (book_path, file_path)
                )
            """)

            # Flat date -> 0|1 grid for the 364-day streak panel. Maintained
            # incrementally by write/delete paths; full rebuild on day_start_hour
            # change or cache-date mismatch. See build_streak_grid_cache.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS streak_grid_cache (
                    date TEXT PRIMARY KEY,
                    listened INTEGER NOT NULL DEFAULT 0
                )
            """)

            # Migrate: add book_id FK columns to session/event/tag tables
            ls_cols = {row[1] for row in conn.execute("PRAGMA table_info(listening_sessions)").fetchall()}
            if "book_id" not in ls_cols:
                conn.execute("ALTER TABLE listening_sessions ADD COLUMN book_id INTEGER REFERENCES books(id)")
                conn.execute("""
                    UPDATE listening_sessions
                    SET book_id = (SELECT id FROM books WHERE books.path = listening_sessions.book_path)
                    WHERE book_id IS NULL
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_book_id ON listening_sessions (book_id)")

            be_cols = {row[1] for row in conn.execute("PRAGMA table_info(book_events)").fetchall()}
            if "book_id" not in be_cols:
                conn.execute("ALTER TABLE book_events ADD COLUMN book_id INTEGER REFERENCES books(id)")
                conn.execute("""
                    UPDATE book_events
                    SET book_id = (SELECT id FROM books WHERE books.path = book_events.book_path)
                    WHERE book_id IS NULL
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_book_events_book_id ON book_events (book_id)")

            # Migrate: add 'source' to book_events. Distinguishes a 'finished' event
            # written by playback (reaching EOF) from one set manually via the detail-
            # panel toggle. Backfills to 'playback' — every pre-existing finished event
            # came from EOF. The streak grid counts only source='playback' finishes
            # (a manual finish is bookkeeping, not listening), so manual finishes are
            # invisible to the grid (no fill, no dot); all other finished queries count
            # both. See review/DESIGN_finished_toggle.md.
            if "source" not in be_cols:
                conn.execute(
                    "ALTER TABLE book_events ADD COLUMN source TEXT NOT NULL DEFAULT 'playback'"
                )

            bt_cols = {row[1] for row in conn.execute("PRAGMA table_info(book_tags)").fetchall()}
            if "book_id" not in bt_cols:
                conn.execute("ALTER TABLE book_tags ADD COLUMN book_id INTEGER REFERENCES books(id)")
                conn.execute("""
                    UPDATE book_tags
                    SET book_id = (SELECT id FROM books WHERE books.path = book_tags.book_path)
                    WHERE book_id IS NULL
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_book_tags_book_id ON book_tags (book_id)")

            # Migrate: add is_deleted column if absent
            col_names = {row[1] for row in conn.execute("PRAGMA table_info(books)").fetchall()}
            if "is_deleted" not in col_names:
                conn.execute(
                    "ALTER TABLE books ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0"
                )
            if "is_excluded" not in col_names:
                conn.execute(
                    "ALTER TABLE books ADD COLUMN is_excluded INTEGER NOT NULL DEFAULT 0"
                )
            if "title_locked" not in col_names:
                conn.execute(
                    "ALTER TABLE books ADD COLUMN title_locked INTEGER NOT NULL DEFAULT 0"
                )
            if "author_locked" not in col_names:
                conn.execute(
                    "ALTER TABLE books ADD COLUMN author_locked INTEGER NOT NULL DEFAULT 0"
                )
            if "narrator_locked" not in col_names:
                conn.execute(
                    "ALTER TABLE books ADD COLUMN narrator_locked INTEGER NOT NULL DEFAULT 0"
                )
            if "year_locked" not in col_names:
                conn.execute(
                    "ALTER TABLE books ADD COLUMN year_locked INTEGER NOT NULL DEFAULT 0"
                )

            # Populate tags table from existing book_tags (idempotent, safe to run each startup)
            conn.execute("""
                INSERT OR IGNORE INTO tags (name)
                SELECT DISTINCT tag FROM book_tags
            """)


    # --- Scan Locations CRUD ---

    def add_scan_location(self, path):
        """Adds a new directory to the scan list."""
        try:
            with self._get_conn() as conn:
                conn.execute("INSERT INTO scan_locations (path) VALUES (?)", (str(path),))
            return True
        except sqlite3.IntegrityError:
            return False

    def restore_books_under_path(self, path):
        """Un-soft-deletes books under `path` whose location was previously
        removed (mirrors remove_scan_location's soft-delete). Books the user
        explicitly excluded (is_excluded = 1) stay hidden — re-adding a
        location must not silently resurrect those; only a manual force
        rescan does."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE books SET is_deleted = 0 WHERE path LIKE ? AND is_deleted = 1 AND is_excluded = 0",
                (str(path).rstrip("/") + "/%",)
            )

    def get_scan_locations(self):
        """Returns a list of all registered scan paths."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT path FROM scan_locations")
            return [row['path'] for row in cursor.fetchall()]

    def remove_scan_location(self, path):
        """Removes a directory from the scan list."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE books SET is_deleted = 1 WHERE path LIKE ?",
                (str(path).rstrip("/") + "/%",)
            )
            conn.execute("DELETE FROM scan_locations WHERE path = ?", (str(path),))

    # --- Books CRUD ---

    def upsert_book(self, book_data):
        """
        Adds a book or updates its metadata if it already exists.
        book_data should be a dictionary containing:
        path, folder_name_raw, title, author, narrator, duration, progress, cover_path
        """
        # Construct parameters dictionary with defaults to prevent binding errors.
        # The scanner typically doesn't provide progress, so we default it to None here
        # and handle the fallback to 0 within the SQL query itself.
        params = {
            "path": book_data.get("path"),
            "folder_name_raw": book_data.get("folder_name_raw"),
            "title": book_data.get("title"),
            "author": book_data.get("author"),
            "narrator": book_data.get("narrator"),
            "duration": book_data.get("duration"),
            "progress": book_data.get("progress"),
            "cover_path": book_data.get("cover_path"),
            "year": book_data.get("year"),
        }

        cleaned = {
            k: (v.strip() if isinstance(v, str) else v) for k, v in params.items()
        }

        # COALESCE(:progress, 0) ensures new records start at 0 if no progress is supplied.
        # COALESCE(excluded.progress, books.progress) ensures updates don't overwrite saved progress with NULL.
        query = """
            INSERT INTO books (path, folder_name_raw, title, author, narrator, duration, progress, cover_path, year)
            VALUES (:path, :folder_name_raw, :title, :author, :narrator, :duration, COALESCE(:progress, 0), :cover_path, :year)
            ON CONFLICT(path) DO UPDATE SET
                folder_name_raw=COALESCE(excluded.folder_name_raw, books.folder_name_raw),
                title=CASE WHEN books.title_locked THEN books.title ELSE excluded.title END,
                author=CASE WHEN books.author_locked THEN books.author ELSE excluded.author END,
                narrator=CASE WHEN books.narrator_locked THEN books.narrator ELSE COALESCE(NULLIF(excluded.narrator, ''), books.narrator) END,
                duration=excluded.duration,
                progress=COALESCE(NULLIF(excluded.progress, 0.0), books.progress),
                cover_path=excluded.cover_path,
                year=CASE WHEN books.year_locked THEN books.year ELSE COALESCE(excluded.year, books.year) END,
                is_deleted=0,
                is_excluded=0
        """
        with self._get_conn() as conn:
            conn.execute(query, cleaned)

    def upsert_books_batch(self, book_data_list):
        if not book_data_list:
            return
        query = """
            INSERT INTO books (path, folder_name_raw, title, author, narrator, duration, progress, cover_path, year)
            VALUES (:path, :folder_name_raw, :title, :author, :narrator, :duration, COALESCE(:progress, 0), :cover_path, :year)
            ON CONFLICT(path) DO UPDATE SET
                folder_name_raw=COALESCE(excluded.folder_name_raw, books.folder_name_raw),
                title=CASE WHEN books.title_locked THEN books.title ELSE excluded.title END,
                author=CASE WHEN books.author_locked THEN books.author ELSE excluded.author END,
                narrator=CASE WHEN books.narrator_locked THEN books.narrator ELSE COALESCE(NULLIF(excluded.narrator, ''), books.narrator) END,
                duration=excluded.duration,
                progress=COALESCE(NULLIF(excluded.progress, 0.0), books.progress),
                cover_path=excluded.cover_path,
                year=CASE WHEN books.year_locked THEN books.year ELSE COALESCE(excluded.year, books.year) END,
                is_deleted=0,
                is_excluded=0
        """
        cleaned_list = [
            {k: (v.strip() if isinstance(v, str) else v) for k, v in {
                "path": d.get("path"), "folder_name_raw": d.get("folder_name_raw"),
                "title": d.get("title"), "author": d.get("author"),
                "narrator": d.get("narrator"), "duration": d.get("duration"),
                "progress": d.get("progress"), "cover_path": d.get("cover_path"),
                "year": d.get("year"),
            }.items()}
            for d in book_data_list
        ]
        with self._get_conn() as conn:
            conn.executemany(query, cleaned_list)

    def get_book(self, path):
        """Retrieves a single book's metadata by its path."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM books WHERE path = ?", (str(path),))
            row = cursor.fetchone()
            return Book.from_dict(dict(row)) if row else None

    def get_book_dict(self, book_path: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM books WHERE path = ?", (str(book_path),)).fetchone()
            return dict(row) if row else None

    _ALLOWED_SORT_COLUMNS = frozenset({
        "title", "author", "narrator", "duration", "progress",
        "last_played", "date_added", "year", "folder_name_raw",
    })
    _TEXT_SORT_COLUMNS = frozenset({"title", "author", "narrator", "folder_name_raw"})

    def get_all_books(self, sort_by="title", order="ASC"):
        """Returns all books in the library."""
        if sort_by not in self._ALLOWED_SORT_COLUMNS:
            raise ValueError(f"Invalid sort column: {sort_by!r}")
        if order not in ("ASC", "DESC"):
            raise ValueError(f"Invalid sort order: {order!r}")
        collate = " COLLATE NOCASE" if sort_by in self._TEXT_SORT_COLUMNS else ""
        with self._get_conn() as conn:
            cursor = conn.execute(f"SELECT * FROM books WHERE is_deleted = 0 AND is_excluded = 0 ORDER BY {sort_by}{collate} {order}")
            return [Book.from_dict(dict(row)) for row in cursor.fetchall()]

    def get_all_book_paths(self) -> set:
        """Returns the paths of ALL books regardless of is_excluded or is_deleted.
        Used by the scanner to determine which paths have been seen before — excluded
        and soft-deleted books must be included so they are not re-upserted (which
        would reset is_excluded/is_deleted to 0, resurrecting them)."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT path FROM books").fetchall()
            return {row[0] for row in rows}

    def get_book_count(self):
        """Returns the total number of books in the library."""
        with self._get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]

    def get_visible_book_count(self) -> int:
        """Returns the number of books visible in the library (excludes soft-deleted and excluded)."""
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM books WHERE is_deleted = 0 AND is_excluded = 0"
            ).fetchone()[0]

    def has_books_with_progress(self) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT 1 FROM books
                   WHERE is_deleted = 0 AND is_excluded = 0
                   AND progress > 1.0
                   LIMIT 1"""
            ).fetchone()
            return row is not None

    def has_finished_books(self) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT 1 FROM books b
                   WHERE b.is_deleted = 0 AND b.is_excluded = 0
                   AND EXISTS (
                       SELECT 1 FROM book_events be
                       WHERE be.book_id = b.id
                       AND be.event_type = 'finished'
                   )
                   LIMIT 1"""
            ).fetchone()
            return row is not None

    def get_finished_book_data(self) -> dict:
        """Returns {book_id: most_recent_finished_datetime} for all visible books
        that have at least one finished event."""
        from datetime import datetime
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT b.id, MAX(be.event_time) as last_finished
                   FROM books b
                   JOIN book_events be ON be.book_id = b.id
                   WHERE b.is_deleted = 0 AND b.is_excluded = 0
                   AND be.event_type = 'finished'
                   GROUP BY b.id"""
            ).fetchall()
            result = {}
            for row in rows:
                try:
                    result[row[0]] = datetime.fromisoformat(row[1])
                except (TypeError, ValueError):
                    result[row[0]] = datetime.min
            return result

    def get_all_cover_paths(self) -> list[str]:
        """Returns cached cover paths for all visible books that have one.
        Used by the no-book-state cover carousel."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT cover_path FROM books "
                "WHERE is_deleted = 0 AND is_excluded = 0 "
                "AND cover_path IS NOT NULL AND cover_path != ''"
            ).fetchall()
            return [row[0] for row in rows]

    def set_metadata_locks(self, book_path: str, title: bool, author: bool, narrator: bool, year: bool) -> None:
        """Updates all four metadata lock columns for the given book path."""
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE books 
                SET title_locked=?, author_locked=?, narrator_locked=?, year_locked=? 
                WHERE path=?""",
                (int(title), int(author), int(narrator), int(year), book_path)
            )

    def get_metadata_locks(self, book_path: str) -> dict:
        """Returns current lock states for a book. Defaults to all False if not found."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT title_locked, author_locked, narrator_locked, year_locked FROM books WHERE path=?",
                (book_path,)
            ).fetchone()
            if row:
                return {
                    'title': bool(row['title_locked']),
                    'author': bool(row['author_locked']),
                    'narrator': bool(row['narrator_locked']),
                    'year': bool(row['year_locked'])
                }
            return {'title': False, 'author': False, 'narrator': False, 'year': False}

    def update_last_played(self, path):
        """Updates the last_played timestamp to the current time."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE books SET last_played = ? WHERE path = ?",
                (datetime.now().isoformat(), str(path))
            )

    def update_progress(self, path, progress):
        """Updates the saved playback position (in seconds)."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE books SET progress = ? WHERE path = ?",
                (float(progress), str(path))
            )

    def reparse_library(self, pattern):
        """
        Updates all books in the database by re-parsing the folder_name_raw
        based on the provided pattern ("Author - Title" or "Title - Author").
        If folder_name_raw is missing, falls back to the folder's name from its path.
        """
        with self._get_conn() as conn:
            rows = conn.execute("SELECT id, path, folder_name_raw FROM books").fetchall()
            for row in rows:
                    # Fallback to the directory name from the path if raw string is missing
                    raw = row["folder_name_raw"] or Path(row["path"]).name
                    if not raw:
                        continue

                    if " - " in raw:
                        parts = raw.split(" - ", 1)
                        if pattern == "Title - Author":
                            title, author = parts[0].strip(), parts[1].strip()
                        else: # Default: "Author - Title"
                            author, title = parts[0].strip(), parts[1].strip()
                    else:
                        title, author = raw.strip(), ""

                    conn.execute(
                        "UPDATE books SET title = ?, author = ?, folder_name_raw = ? WHERE id = ?",
                        (title, author, raw, row["id"])
                    )

    # --- Session Recording ---

    def write_session(self, book_path, book_title, book_author, book_duration,
                      session_start, session_end, position_start, position_end,
                      furthest_position, listened_seconds, book_id: int | None = None,
                      day_start_hour: int = 0):
        """Inserts one listening session row and updates the streak grid cell(s)
        for this session's adjusted date(s). A session spanning the day boundary
        updates both its start-day and end-day cells."""
        start_iso = session_start.isoformat()
        end_iso = session_end.isoformat()
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO listening_sessions
                    (book_id, book_path, book_title, book_author, book_duration,
                     session_start, session_end,
                     position_start, position_end, furthest_position,
                     listened_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                book_id,
                str(book_path) if book_path else None,
                book_title,
                book_author,
                book_duration,
                start_iso,
                end_iso,
                position_start,
                position_end,
                furthest_position,
                listened_seconds,
            ))
            start_date = conn.execute(
                "SELECT strftime('%Y-%m-%d', datetime(?, ?))", (start_iso, offset)
            ).fetchone()[0]
            end_date = conn.execute(
                "SELECT strftime('%Y-%m-%d', datetime(?, ?))", (end_iso, offset)
            ).fetchone()[0]
            for d in {start_date, end_date}:  # dedup if same day
                self._update_streak_grid_cache_for_date(conn, d, day_start_hour)

    def get_daily_book_breakdown(self, date_str: str, day_start_hour: int) -> list[dict]:
        """Returns per-book listening rows for a given day, with cover from books table via LEFT JOIN."""
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    b.id AS book_id,
                    ls.book_path,
                    COALESCE(b.title, ls.book_title) as book_title,
                    COALESCE(b.author, ls.book_author) as book_author,
                    ls.book_duration,
                    SUM(COALESCE(ls.listened_seconds, (julianday(ls.session_end) - julianday(ls.session_start)) * 86400)) as clock_seconds,
                    SUM(ls.position_end - ls.position_start) as book_seconds_advanced,
                    MAX(ls.furthest_position) as furthest_position,
                    b.cover_path,
                    b.is_deleted,
                    b.is_excluded,
                    (SELECT MAX(CASE WHEN be.event_type = 'finished' THEN 1 ELSE 0 END)
                     FROM book_events be WHERE be.book_id = b.id) as is_finished,
                    (SELECT ls2.position_start FROM listening_sessions ls2
                     WHERE ls2.book_id = ls.book_id
                     AND strftime('%Y-%m-%d', datetime(ls2.session_start, ?)) = ?
                     ORDER BY ls2.session_start ASC LIMIT 1) as period_position_start,
                    (SELECT ls2.position_end FROM listening_sessions ls2
                     WHERE ls2.book_id = ls.book_id
                     AND strftime('%Y-%m-%d', datetime(ls2.session_start, ?)) = ?
                     ORDER BY ls2.session_start DESC LIMIT 1) as period_position_end
                FROM listening_sessions ls
                LEFT JOIN books b ON ls.book_id = b.id
                WHERE strftime('%Y-%m-%d', datetime(ls.session_start, ?)) = ?
                GROUP BY ls.book_id
                ORDER BY clock_seconds DESC, COALESCE(book_seconds_advanced, 0) DESC
            """, (offset, date_str, offset, date_str, offset, date_str)).fetchall()
        return [dict(r) for r in rows]

    def set_started_at(self, book_id: int, started_at: datetime):
        """Sets started_at only if it has not been set yet."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE books SET started_at = ? WHERE id = ? AND started_at IS NULL",
                (started_at.isoformat(), book_id)
            )

    def get_book_started_at(self, book_id: int) -> datetime | None:
        """Returns the started_at datetime for the given book_id, or None."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT started_at FROM books WHERE id = ?",
                (book_id,)
            )
            row = cursor.fetchone()
            if row is None or row["started_at"] is None:
                return None
            return datetime.fromisoformat(row["started_at"])

    # --- Listening Stats ---

    _GRANULARITY_FORMATS = {
        'day':   '%Y-%m-%d',
        'week':  '%Y-W%W',
        'month': '%Y-%m',
        'year':  '%Y',
    }

    def get_active_periods(self, granularity: str, day_start_hour: int) -> list[str]:
        if granularity not in self._GRANULARITY_FORMATS:
            raise ValueError(f"Invalid granularity: {granularity!r}")
        fmt = self._GRANULARITY_FORMATS[granularity]
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT DISTINCT strftime(?, datetime(session_start, ?)) AS period"
                " FROM listening_sessions"
                " ORDER BY period DESC",
                (fmt, offset)
            )
            return [row['period'] for row in cursor.fetchall()]

    def get_listening_time_per_period(self, granularity: str, day_start_hour: int) -> list[dict]:
        if granularity not in self._GRANULARITY_FORMATS:
            raise ValueError(f"Invalid granularity: {granularity!r}")
        fmt = self._GRANULARITY_FORMATS[granularity]
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT"
                "  strftime(?, datetime(session_start, ?)) AS period,"
                "  book_id,"
                "  book_path,"
                "  book_title,"
                "  SUM(COALESCE(listened_seconds, (julianday(session_end) - julianday(session_start)) * 86400)) AS seconds"
                " FROM listening_sessions"
                " GROUP BY period, book_id"
                " ORDER BY period DESC, seconds DESC",
                (fmt, offset)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_book_stats(self, book_id: int, day_start_hour: int) -> dict:
        with self._get_conn() as conn:
            agg = conn.execute("""
                SELECT
                    MAX(furthest_position) as furthest_position,
                    SUM(COALESCE(listened_seconds, (julianday(session_end) - julianday(session_start)) * 86400)) as total_seconds,
                    COUNT(*) as session_count,
                    MIN(session_start) as first_session,
                    MAX(session_end) as last_session
                FROM listening_sessions
                WHERE book_id = ?
            """, (book_id,)).fetchone()

            per_day = conn.execute("""
                SELECT
                    strftime('%Y-%m-%d', datetime(session_start, ?)) as date,
                    SUM(COALESCE(listened_seconds, (julianday(session_end) - julianday(session_start)) * 86400)) as seconds
                FROM listening_sessions
                WHERE book_id = ?
                GROUP BY date
                ORDER BY date ASC
            """, (f'-{day_start_hour} hours', book_id)).fetchall()

            finished = conn.execute("""
                SELECT COUNT(*) as n, MAX(event_time) as last_finished
                FROM book_events
                WHERE book_id = ? AND event_type = 'finished'
            """, (book_id,)).fetchone()

        return {
            'furthest_position': agg['furthest_position'] or 0.0,
            'total_seconds': agg['total_seconds'] or 0.0,
            'session_count': agg['session_count'] or 0,
            'first_session': agg['first_session'],
            'last_session': agg['last_session'],
            'finished_count': finished['n'] or 0,
            'last_finished': finished['last_finished'],
            'per_day': [dict(r) for r in per_day],
        }

    def get_overall_stats(self, day_start_hour: int = 0) -> dict:
        with self._get_conn() as conn:
            agg = conn.execute("""
                SELECT
                    COUNT(*) as total_sessions,
                    COUNT(DISTINCT book_path) as books_started,
                    SUM(COALESCE(listened_seconds, (julianday(session_end) - julianday(session_start)) * 86400)) as total_seconds,
                    AVG(COALESCE(listened_seconds, (julianday(session_end) - julianday(session_start)) * 86400)) as avg_seconds
                FROM listening_sessions
            """).fetchone()

            longest = conn.execute("""
                SELECT COALESCE(b.title, ls.book_title) as book_title,
                    COALESCE(ls.listened_seconds, (julianday(ls.session_end) - julianday(ls.session_start)) * 86400) as seconds,
                    ls.session_start
                FROM listening_sessions ls
                LEFT JOIN books b ON ls.book_id = b.id
                ORDER BY seconds DESC
                LIMIT 1
            """).fetchone()

            last = conn.execute("""
                SELECT COALESCE(b.title, ls.book_title) as book_title,
                    COALESCE(ls.listened_seconds, (julianday(ls.session_end) - julianday(ls.session_start)) * 86400) as seconds,
                    ls.session_start
                FROM listening_sessions ls
                LEFT JOIN books b ON ls.book_id = b.id
                ORDER BY ls.session_start DESC
                LIMIT 1
            """).fetchone()

            finished = conn.execute("""
                SELECT COUNT(*) as n FROM book_events WHERE event_type = 'finished'
            """).fetchone()

        return {
            'total_sessions': agg['total_sessions'] or 0,
            'books_started': agg['books_started'] or 0,
            'total_seconds': agg['total_seconds'] or 0.0,
            'avg_session_seconds': agg['avg_seconds'] or 0.0,
            'books_finished': finished['n'] or 0,
            'longest_session_title': longest['book_title'] if longest else None,
            'longest_session_seconds': longest['seconds'] if longest else 0.0,
            'longest_session_start': longest['session_start'] if longest else None,
            'last_session_title': last['book_title'] if last else None,
            'last_session_seconds': last['seconds'] if last else 0.0,
            'last_session_start': last['session_start'] if last else None,
        }

    def get_last_n_days(self, n: int = 7, day_start_hour: int = 0) -> list[dict]:
        """Returns total listening seconds per day for the last N days.
        Days with no activity are included as zero so the chart has a consistent shape."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    strftime('%Y-%m-%d', datetime(session_start, ?)) as date,
                    SUM(COALESCE(listened_seconds, (julianday(session_end) - julianday(session_start)) * 86400)) as seconds
                FROM listening_sessions
                WHERE datetime(session_start, ?) >= datetime('now', ?)
                GROUP BY date
                ORDER BY date ASC
            """, (
                f'-{day_start_hour} hours',
                f'-{day_start_hour} hours',
                f'-{n} days',
            )).fetchall()

        by_date = {r['date']: r['seconds'] for r in rows}

        now = datetime.now()
        today = (now - timedelta(hours=day_start_hour)).date()

        result = []
        for i in range(n - 1, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            result.append({'date': d, 'seconds': by_date.get(d, 0.0)})
        return result

    def get_books_listened_in_period(self, granularity: str, period_label: str, day_start_hour: int) -> list[dict]:
        if granularity not in self._GRANULARITY_FORMATS:
            raise ValueError(f"Invalid granularity: {granularity!r}")
        fmt = self._GRANULARITY_FORMATS[granularity]
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    b.id AS book_id,
                    ls.book_path,
                    COALESCE(b.title, ls.book_title) as book_title,
                    COALESCE(b.author, ls.book_author) as book_author,
                    ls.book_duration,
                    SUM(COALESCE(ls.listened_seconds, (julianday(ls.session_end) - julianday(ls.session_start)) * 86400)) as clock_seconds,
                    SUM(ls.position_end - ls.position_start) as book_seconds_advanced,
                    MAX(ls.furthest_position) as furthest_position,
                    b.cover_path,
                    b.is_deleted,
                    b.is_excluded,
                    (SELECT MAX(CASE WHEN be.event_type = 'finished' THEN 1 ELSE 0 END)
                     FROM book_events be WHERE be.book_id = b.id) as is_finished,
                    (SELECT ls2.position_start FROM listening_sessions ls2
                     WHERE ls2.book_id = ls.book_id
                     AND strftime(?, datetime(ls2.session_start, ?)) = ?
                     ORDER BY ls2.session_start ASC LIMIT 1) as period_position_start,
                    (SELECT ls2.position_end FROM listening_sessions ls2
                     WHERE ls2.book_id = ls.book_id
                     AND strftime(?, datetime(ls2.session_start, ?)) = ?
                     ORDER BY ls2.session_start DESC LIMIT 1) as period_position_end
                FROM listening_sessions ls
                LEFT JOIN books b ON ls.book_id = b.id
                WHERE strftime(?, datetime(ls.session_start, ?)) = ?
                GROUP BY ls.book_id
                ORDER BY clock_seconds DESC, COALESCE(book_seconds_advanced, 0) DESC
            """, (fmt, offset, period_label, fmt, offset, period_label, fmt, offset, period_label)).fetchall()
        return [dict(r) for r in rows]

    def get_finished_in_period(self, granularity: str, period_label: str, day_start_hour: int) -> list[dict]:
        """Returns books with a finished event whose event_time falls within the given period."""
        if granularity not in self._GRANULARITY_FORMATS:
            raise ValueError(f"Invalid granularity: {granularity}")
        fmt = self._GRANULARITY_FORMATS[granularity]
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    be.book_id,
                    be.book_path,
                    be.event_time,
                    b.cover_path,
                    b.is_deleted,
                    b.is_excluded,
                    COALESCE(b.title, be.book_path) as book_title,
                    COALESCE(b.author, '') as book_author
                FROM book_events be
                LEFT JOIN books b ON be.book_id = b.id
                WHERE be.event_type = 'finished'
                AND strftime(?, datetime(be.event_time, ?)) = ?
                GROUP BY be.book_id
                ORDER BY be.event_time DESC
            """, (fmt, offset, period_label)).fetchall()
        return [dict(r) for r in rows]
    
    def get_recently_finished(self, limit: int = 5) -> list[dict]:
        """Returns the most recently finished books, up to limit."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    be.book_id,
                    be.book_path,
                    MAX(be.event_time) as event_time,
                    b.cover_path,
                    b.is_deleted,
                    b.is_excluded,
                    COALESCE(b.title, be.book_path) as book_title,
                    COALESCE(b.author, '') as book_author
                FROM book_events be
                LEFT JOIN books b ON be.book_id = b.id
                WHERE be.event_type = 'finished'
                GROUP BY be.book_id
                ORDER BY event_time DESC
                LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    
    def write_book_event(self, book_path: str, event_type: str, book_id: int | None = None,
                         day_start_hour: int = 0, source: str = 'playback'):
        """Writes a book_event. source distinguishes a playback (EOF) finish from a
        manual (detail-panel toggle) finish: only source='playback' finishes light
        the streak grid (a manual finish is bookkeeping, not listening). The cache
        recompute below already filters to playback, so a manual finish touches no
        cell — it shows in the Finished tab / filter / detail icon but is invisible
        to the streak grid (no fill, no dot)."""
        with self._get_conn() as conn:
            event_time = datetime.now().isoformat()
            conn.execute("""
                INSERT INTO book_events (book_id, book_path, event_type, event_time, source)
                VALUES (?, ?, ?, ?, ?)
            """, (book_id, book_path, event_type, event_time, source))
            # A playback 'finished' event lights its day in the streak grid
            # (finished ⟹ listened), even with no qualifying session. Same
            # adjusted-date as sessions so the dot and fill share a cell. A manual
            # finish is streak-neutral — _update_streak_grid_cache_for_date counts
            # only source='playback', so re-evaluating the cell here leaves a
            # manual-only day dark. Non-finished events don't touch the grid.
            if event_type == 'finished':
                adj_date = conn.execute(
                    "SELECT strftime('%Y-%m-%d', datetime(?, ?))",
                    (event_time, f'-{day_start_hour} hours')
                ).fetchone()[0]
                self._update_streak_grid_cache_for_date(conn, adj_date, day_start_hour)

    def unfinish_book(self, book_id: int, day_start_hour: int = 0) -> None:
        """Deletes the most recent 'finished' event for a book, then re-evaluates
        that day's streak cell — if the finish was the only thing lighting the day
        (no qualifying session, no other finished event), the cell darkens. Mirrors
        write_book_event's finished ⟹ listened invariant in reverse."""
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, strftime('%Y-%m-%d', datetime(event_time, ?)) AS d "
                "FROM book_events "
                "WHERE book_id = ? AND event_type = 'finished' "
                "ORDER BY event_time DESC LIMIT 1",
                (offset, book_id)
            ).fetchone()
            if row is None:
                return
            conn.execute("DELETE FROM book_events WHERE id = ?", (row["id"],))
            self._update_streak_grid_cache_for_date(conn, row["d"], day_start_hour)

    def clear_finished(self, book_id: int, day_start_hour: int = 0) -> None:
        """Deletes ALL 'finished' events for a book — the detail-panel toggle-off
        ('Mark unfinished' = status reset, a boolean, vs the banner revert which
        deletes only the most recent). Re-evaluates every affected day's streak cell
        so any playback-finish days darken if nothing else backs them; manual-finish
        days were never lit, so clearing them is a no-op on the grid."""
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT strftime('%Y-%m-%d', datetime(event_time, ?)) AS d "
                "FROM book_events WHERE book_id = ? AND event_type = 'finished'",
                (offset, book_id)
            ).fetchall()
            conn.execute(
                "DELETE FROM book_events WHERE book_id = ? AND event_type = 'finished'",
                (book_id,)
            )
            for r in rows:
                if r["d"]:
                    self._update_streak_grid_cache_for_date(conn, r["d"], day_start_hour)

    def reset_stats(self):
        """Deletes all listening sessions and book events, resets started_at and finished_at on all books."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM listening_sessions")
            conn.execute("DELETE FROM book_events")
            conn.execute("UPDATE books SET started_at = NULL, finished_at = NULL")
        # No sessions remain, so every grid cell is 0 — no per-date check needed.
        self.reset_streak_grid_cache()

    def get_book_sessions(self, book_id: int) -> list[dict]:
        """Returns individual sessions for a book, newest first."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    id,
                    session_start,
                    COALESCE(listened_seconds,
                        (julianday(session_end) - julianday(session_start)) * 86400
                    ) as listened_seconds,
                    position_start,
                    position_end
                FROM listening_sessions
                WHERE book_id = ?
                ORDER BY session_start DESC
            """, (book_id,)).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: int, day_start_hour: int = 0):
        """Hard-deletes a single listening session by id, then re-evaluates its
        adjusted grid cell(s). Both start-day and end-day are checked so a
        midnight-spanning session clears both. Single transaction so cache never
        disagrees with rows."""
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT strftime('%Y-%m-%d', datetime(session_start, ?)), "
                "       strftime('%Y-%m-%d', datetime(session_end, ?)) "
                "FROM listening_sessions WHERE id = ?",
                (offset, offset, session_id)
            ).fetchone()
            conn.execute("DELETE FROM listening_sessions WHERE id = ?", (session_id,))
            if row is not None:
                for d in {row[0], row[1]}:  # dedup if same day
                    self._update_streak_grid_cache_for_date(conn, d, day_start_hour)

    def delete_book_stats(self, book_id: int, book_path: str, day_start_hour: int = 0):
        """Deletes all session and event rows for a specific book, then
        re-evaluates each affected adjusted grid cell. Both start-day and end-day
        of every session are gathered so midnight-spanning sessions clear both;
        'finished' event days are gathered too so a finished-but-no-session day
        darkens correctly (finished ⟹ listened, reversed on delete).
        Single transaction."""
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT strftime('%Y-%m-%d', datetime(session_start, ?)), "
                "       strftime('%Y-%m-%d', datetime(session_end, ?)) "
                "FROM listening_sessions WHERE book_id = ?",
                (offset, offset, book_id)
            ).fetchall()
            dates = {d for r in rows for d in r}  # all distinct start/end days
            fin_rows = conn.execute(
                "SELECT strftime('%Y-%m-%d', datetime(event_time, ?)) "
                "FROM book_events WHERE book_id = ? AND event_type = 'finished'",
                (offset, book_id)
            ).fetchall()
            dates.update(r[0] for r in fin_rows if r[0])  # finished days too
            conn.execute("DELETE FROM listening_sessions WHERE book_id = ?", (book_id,))
            conn.execute("DELETE FROM book_events WHERE book_id = ?", (book_id,))
            conn.execute(
                "UPDATE books SET started_at = NULL, finished_at = NULL WHERE path = ?",
                (book_path,)
            )
            for d in dates:
                self._update_streak_grid_cache_for_date(conn, d, day_start_hour)

    def get_streaks(self, day_start_hour: int) -> dict:
        """Returns current and longest listening streaks in days.

        A day counts toward a streak if it has a session OR a 'finished' book_event
        (finished ⟹ listened), using the same day_start_hour adjustment as the
        streak-grid cache. This keeps get_streaks() consistent with the cache and
        with StreakGrid._compute_longest_run — a finished-but-no-session day fills
        its cell AND extends the streak, never one without the other."""
        from datetime import date, timedelta, datetime

        now = datetime.now()
        adjusted_today = (now - timedelta(hours=day_start_hour)).date()
        adjusted_yesterday = adjusted_today - timedelta(days=1)

        offset = f'-{day_start_hour} hours'
        active_set = set(self.get_active_periods('day', day_start_hour))
        with self._get_conn() as conn:
            fin_rows = conn.execute(
                "SELECT DISTINCT strftime('%Y-%m-%d', datetime(event_time, ?)) "
                "FROM book_events WHERE event_type = 'finished' AND source = 'playback'",
                (offset,)
            ).fetchall()
        active_set.update(r[0] for r in fin_rows if r[0])
        if not active_set:
            return {'current': 0, 'longest': 0}

        # Convert to date objects, sorted newest first
        dates = sorted(
            [date.fromisoformat(d) for d in active_set],
            reverse=True
        )

        # Current streak — walk back from today or yesterday
        current = 0
        anchor = adjusted_today if dates[0] == adjusted_today else adjusted_yesterday
        for d in dates:
            if d == anchor:
                current += 1
                anchor -= timedelta(days=1)
            elif d < anchor:
                break

        # Longest streak — walk entire history
        longest = 1
        run = 1
        for i in range(1, len(dates)):
            if dates[i - 1] - dates[i] == timedelta(days=1):
                run += 1
                longest = max(longest, run)
            else:
                run = 1

        return {'current': current, 'longest': longest}

    # ---- Streak grid cache (364-day date -> 0|1 grid) ----
    #
    # Date attribution adjusts via strftime('%Y-%m-%d', datetime(ts, '-N hours')),
    # keeping the shift in SQL to avoid Python ISO-parse drift. A session "touches"
    # a grid cell if EITHER its start OR its end adjusted-date equals that cell —
    # so a session spanning the day boundary (e.g. 23:50→00:18) marks BOTH days.
    # This is intentionally broader than get_active_periods (which keys on
    # session_start only); the grid is a "did I listen at all that day" view, so
    # both endpoints count. Sessions spanning >1 full day (paused overnight) only
    # mark their two endpoints, not the interior — acceptable for realistic use.
    # day_start_hour is always threaded in as a parameter (this class never reads
    # config — same contract as every other day-boundary method here).

    _STREAK_GRID_DAYS = 364  # today + previous 363 = 52 weeks

    def build_streak_grid_cache(self, day_start_hour: int) -> None:
        """Full rebuild of the 364-day streak grid.

        Drops rows older than the window, seeds all 364 dates at listened=0,
        then flips listened=1 for every adjusted date that has >=1 session.
        Called on first open and on cache-date / day_start_hour mismatch.
        """
        offset = f'-{day_start_hour} hours'
        span = self._STREAK_GRID_DAYS - 1  # 363
        with self._get_conn() as conn:
            today = conn.execute(
                "SELECT strftime('%Y-%m-%d', datetime('now', 'localtime', ?))",
                (offset,)
            ).fetchone()[0]
            oldest = conn.execute(
                "SELECT date(?, ?)", (today, f'-{span} days')
            ).fetchone()[0]

            conn.execute(
                "DELETE FROM streak_grid_cache WHERE date < ?", (oldest,)
            )
            # Seed every day in the window at 0 (idempotent).
            conn.executemany(
                "INSERT OR IGNORE INTO streak_grid_cache (date, listened) VALUES (?, 0)",
                [(d,) for d in (
                    conn.execute("SELECT date(?, ?)", (today, f'-{n} days')).fetchone()[0]
                    for n in range(self._STREAK_GRID_DAYS)
                )]
            )
            # Flip active days on — both start and end adjusted-dates count, so a
            # midnight-spanning session marks both days. Restricted to the window
            # (IN streak_grid_cache rows) so a stray old session can't resurrect a
            # pruned row. A 'finished' book_event ALSO lights its day: a book taken
            # to finished is a listened day even if no session cleared the 60s
            # threshold — otherwise the grid shows a finished dot on an unlit cell.
            # Finished events use the SAME day_start_hour adjustment as sessions so
            # the dot and the fill land on the same cell (see get_streak_grid_finished_dates).
            conn.execute(
                "UPDATE streak_grid_cache SET listened = 1 WHERE date IN ("
                "  SELECT strftime('%Y-%m-%d', datetime(session_start, ?))"
                "  FROM listening_sessions"
                "  UNION"
                "  SELECT strftime('%Y-%m-%d', datetime(session_end, ?))"
                "  FROM listening_sessions"
                "  UNION"
                "  SELECT strftime('%Y-%m-%d', datetime(event_time, ?))"
                "  FROM book_events WHERE event_type = 'finished' AND source = 'playback'"
                ")",
                (offset, offset, offset)
            )

    def get_streak_grid_cache(self) -> dict[str, int]:
        """Returns the whole grid as {date_str: 0|1}."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT date, listened FROM streak_grid_cache"
            ).fetchall()
        return {row['date']: row['listened'] for row in rows}

    def get_streak_grid_finished_dates(self, day_start_hour: int = 0) -> set[str]:
        """ISO date strings within the last 364 days on which at least one book was
        finished. Sourced from book_events (event_type='finished') — books.finished_at
        is never written. Uses the SAME day_start_hour adjustment as the listened-cell
        cache so the finished dot and the listened fill land on the same grid cell
        (a finished day is always a listened day — see build_streak_grid_cache)."""
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT strftime('%Y-%m-%d', datetime(be.event_time, ?)) AS d "
                "FROM book_events be WHERE be.event_type='finished' AND be.source='playback' "
                "AND date(be.event_time) >= date('now','-364 days')",
                (offset,)
            ).fetchall()
        return {row['d'] for row in rows if row['d']}

    def _update_streak_grid_cache_for_date(self, conn, date_str: str,
                                           day_start_hour: int) -> None:
        """Re-evaluate one grid cell against current sessions, on an open conn.

        date_str is the adjusted date (already day_start_hour-shifted). The
        COUNT re-derives the adjusted date in SQL so attribution stays in one
        place. A session counts toward this cell if its start OR end adjusted-date
        matches — mirroring build_streak_grid_cache, so midnight-spanning sessions
        keep both days active. A 'finished' book_event on this adjusted date ALSO
        keeps the cell lit — so deleting the last session on a day a book was
        finished does NOT darken it (finished ⟹ listened, consistent with
        build_streak_grid_cache). Only writes rows already inside the window (the
        seeded grid) — a date outside it is silently ignored to avoid resurrecting
        pruned cells.
        """
        offset = f'-{day_start_hour} hours'
        count = conn.execute(
            "SELECT COUNT(*) FROM listening_sessions "
            "WHERE strftime('%Y-%m-%d', datetime(session_start, ?)) = ? "
            "   OR strftime('%Y-%m-%d', datetime(session_end, ?)) = ?",
            (offset, date_str, offset, date_str)
        ).fetchone()[0]
        if count == 0:
            count = conn.execute(
                "SELECT COUNT(*) FROM book_events "
                "WHERE event_type = 'finished' AND source = 'playback' "
                "  AND strftime('%Y-%m-%d', datetime(event_time, ?)) = ?",
                (offset, date_str)
            ).fetchone()[0]
        conn.execute(
            "UPDATE streak_grid_cache SET listened = ? WHERE date = ?",
            (1 if count > 0 else 0, date_str)
        )

    def reset_streak_grid_cache(self) -> None:
        """Sets every grid cell to 0. Used when all sessions are gone
        (reset_stats) or on day_start_hour change before a rebuild."""
        with self._get_conn() as conn:
            conn.execute("UPDATE streak_grid_cache SET listened = 0")

    def update_book_metadata(self, path: str, title: str, author: str,
                          narrator: str, year: str) -> bool:
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """UPDATE books
                    SET title=?, author=?, narrator=?, year=?
                    WHERE path=?""",
                    (title or None, author or None, narrator or None, int(year) if year and year.strip().isdigit() else None, path)
                )
            return True
        except Exception:
            return False

    def get_book_tags(self, book_id: int) -> list[str]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT tag FROM book_tags WHERE book_id=? ORDER BY tag",
                (book_id,)
            ).fetchall()
        return [r[0] for r in rows]

    def add_book_tag(self, book_path: str, tag: str, book_id: int | None = None) -> bool:
        """Returns False if tag already exists on this book, per-book limit reached, or global tag limit reached."""
        tag = tag.strip().lower()[:20]
        if not tag:
            return False
        with self._get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM book_tags WHERE book_path=?",
                (book_path,)
            ).fetchone()[0]
            if count >= 5:
                return False
            # Only enforce global limit for new tags not already in use
            is_new_tag = conn.execute(
                "SELECT COUNT(*) FROM book_tags WHERE tag=?", (tag,)
            ).fetchone()[0] == 0
            if is_new_tag:
                global_count = conn.execute(
                    "SELECT COUNT(DISTINCT tag) FROM book_tags"
                ).fetchone()[0]
                if global_count >= 50:
                    return False
            try:
                conn.execute(
                    "INSERT INTO book_tags (book_id, book_path, tag) VALUES (?, ?, ?)",
                    (book_id, book_path, tag)
                )
                conn.execute(
                    "INSERT OR IGNORE INTO tags (name) VALUES (?)",
                    (tag,)
                )
                return True
            except Exception:
                return False  # UNIQUE constraint hit

    def remove_book_tag(self, book_id: int, tag: str) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM book_tags WHERE book_id=? AND tag=?",
                (book_id, tag)
            )

    def get_hourly_heatmap(self, n_days: int = 14) -> list[dict]:
        """Returns per-(date, hour) listening data for the last n_days calendar days.

        Uses real wall-clock time with no day-start offset so hours are accurate.
        Each row: {date, hour, seconds, books: [{title, minutes}]}
        Sessions that span multiple hours are split so no cell exceeds 3600s.
        Hours with no activity are omitted — the widget fills them as empty cells.
        """
        from collections import defaultdict
        from datetime import datetime as dt, timedelta

        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    COALESCE(b.title, ls.book_title, ls.book_path) as title,
                    ls.session_start,
                    ls.session_end,
                    COALESCE(ls.listened_seconds,
                        (julianday(ls.session_end) - julianday(ls.session_start)) * 86400) as seconds
                FROM listening_sessions ls
                LEFT JOIN books b ON ls.book_id = b.id
                WHERE strftime('%Y-%m-%d', ls.session_start) IN (
                    SELECT DISTINCT strftime('%Y-%m-%d', session_start)
                    FROM listening_sessions
                    ORDER BY strftime('%Y-%m-%d', session_start) DESC
                    LIMIT ?
                )
                ORDER BY ls.session_start ASC
            """, (n_days,)).fetchall()

        # Split each session across the clock hours it spans
        cells: dict = defaultdict(lambda: {'seconds': 0.0, 'books': defaultdict(float)})
        for r in rows:
            try:
                t_start = dt.fromisoformat(r['session_start'])
                t_end = dt.fromisoformat(r['session_end'])
            except ValueError:
                continue
            total_wall = (t_end - t_start).total_seconds()
            if total_wall <= 0:
                continue
            listened = float(r['seconds'])
            title = r['title']

            # Walk hour boundaries from t_start to t_end
            cursor = t_start
            while cursor < t_end:
                hour_end = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                slice_end = min(hour_end, t_end)
                wall_slice = (slice_end - cursor).total_seconds()
                # Proportion of total wall time in this slice → same proportion of listened_seconds
                slice_listened = listened * (wall_slice / total_wall)
                date_str = cursor.strftime('%Y-%m-%d')
                hour = cursor.hour
                cells[(date_str, hour)]['seconds'] += slice_listened
                cells[(date_str, hour)]['books'][title] += slice_listened
                cursor = slice_end

        result = []
        for (date_str, hour), data in sorted(cells.items()):
            books = [
                {'title': t, 'minutes': max(1, round(s / 60))}
                for t, s in sorted(data['books'].items(), key=lambda x: -x[1])
            ]
            result.append({
                'date': date_str,
                'hour': hour,
                'seconds': min(data['seconds'], 3600.0),
                'books': books,
            })
        return result

    def get_all_tags(self) -> list[dict]:
        """Returns all unique tags with book count and color, sorted alphabetically."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT bt.tag, COUNT(*) as count, t.color
                FROM book_tags bt
                LEFT JOIN tags t ON bt.tag = t.name
                GROUP BY bt.tag
                ORDER BY bt.tag"""
            ).fetchall()
        return [{'tag': r[0], 'count': r[1], 'color': r[2]} for r in rows]

    def get_tag_color(self, tag: str) -> str | None:
        """Returns the color key for a tag, or None if not set."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT color FROM tags WHERE name=?", (tag,)
            ).fetchone()
        return row[0] if row else None

    def set_tag_color(self, tag: str, color: str | None) -> None:
        """Sets the color key for a tag. Pass None to reset to neutral."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO tags (name, color) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET color=excluded.color",
                (tag, color)
            )

    def get_books_by_tag(self, tag: str) -> list[dict]:
        """Returns books that have the given tag, with path, title, author, cover_path."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT b.id AS book_id, b.path, b.title, b.author, b.cover_path, b.is_deleted, b.is_excluded
                FROM books b
                JOIN book_tags t ON b.id = t.book_id
                WHERE t.tag = ?
                ORDER BY b.title""",
                (tag,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_paths_for_tag_prefix(self, prefix: str) -> set[str]:
        """Returns the set of book paths that have any tag starting with prefix."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT book_path FROM book_tags WHERE tag LIKE ?",
                (f"{prefix}%",)
            ).fetchall()
        return {r[0] for r in rows}

    def rename_tag(self, old_tag: str, new_tag: str) -> bool:
        """Renames a tag across all books. Returns False if new_tag already exists."""
        new_tag = new_tag.strip().lower()[:20]
        if not new_tag or new_tag == old_tag:
            return False
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) FROM book_tags WHERE tag=?", (new_tag,)
            ).fetchone()[0]
            if existing:
                return False
            conn.execute("UPDATE book_tags SET tag=? WHERE tag=?", (new_tag, old_tag))
        return True

    def delete_tag(self, tag: str) -> None:
        """Removes a tag from all books."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM book_tags WHERE tag=?", (tag,))

    def get_unique_tag_count(self) -> int:
        with self._get_conn() as conn:
            return conn.execute("SELECT COUNT(DISTINCT tag) FROM book_tags").fetchone()[0]

    def get_tag_suggestions(self, prefix: str, book_id: int) -> list[str]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT tag FROM book_tags
                WHERE tag LIKE ?
                AND tag NOT IN (
                    SELECT tag FROM book_tags WHERE book_id=?
                )
                ORDER BY tag LIMIT 10""",
                (f"{prefix.lower()}%", book_id)
            ).fetchall()
        return [r[0] for r in rows]

    # --- Book Covers ---

    def get_active_cover(self, book_path: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, file_path, fit_mode FROM book_covers "
                "WHERE book_path = ? AND is_active = 1 LIMIT 1",
                (book_path,)
            ).fetchone()
            return dict(row) if row else None

    def get_active_cover_path(self, book_path: str) -> str | None:
        cover = self.get_active_cover(book_path)
        return cover['file_path'] if cover else None

    def get_covers_for_book(self, book_path: str) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, file_path, is_locked, is_active, fit_mode, sort_order "
                "FROM book_covers WHERE book_path = ? ORDER BY sort_order",
                (book_path,)
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_cover(self, book_path: str, file_path: str, is_locked: bool,
                     is_active: bool, fit_mode: str, sort_order: int) -> int:
        from datetime import datetime, timezone
        added_at = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO book_covers "
                "(book_path, file_path, is_locked, is_active, fit_mode, sort_order, added_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (book_path, file_path, int(is_locked), int(is_active), fit_mode, sort_order, added_at)
            )
            return cursor.lastrowid

    def set_active_cover(self, book_path: str, cover_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE book_covers SET is_active = 0 WHERE book_path = ?",
                (book_path,)
            )
            conn.execute(
                "UPDATE book_covers SET is_active = 1 WHERE id = ?",
                (cover_id,)
            )

    def set_fit_mode(self, cover_id: int, fit_mode: str) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE book_covers SET fit_mode = ? WHERE id = ?",
                (fit_mode, cover_id)
            )

    def delete_cover(self, cover_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM book_covers WHERE id = ?", (cover_id,))

    def count_covers_for_book(self, book_path: str) -> int:
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM book_covers WHERE book_path = ?",
                (book_path,)
            ).fetchone()[0]

    # --- Book Files ---

    def upsert_book_files(self, book_path: str, files: list[dict]) -> None:
        """
        Inserts or replaces per-file records for a multi-file book.
        Each dict in files must have keys:
            file_path (str), sort_order (int), duration_ms (int),
            cumulative_start_ms (int), title (str or None)
        Deletes existing rows for book_path before inserting,
        so the table always reflects the current file set.
        """
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM book_files WHERE book_path = ?", (book_path,)
            )
            conn.executemany(
                """INSERT INTO book_files
                   (book_path, file_path, sort_order, duration_ms, cumulative_start_ms, title)
                   VALUES (:book_path, :file_path, :sort_order, :duration_ms, :cumulative_start_ms, :title)""",
                [{"book_path": book_path, **f} for f in files]
            )

    def is_book_excluded(self, path: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT is_excluded FROM books WHERE path = ?", (path,)
            ).fetchone()
            return bool(row and row[0])

    def set_book_excluded(self, path: str, excluded: bool) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE books SET is_excluded = ? WHERE path = ?",
                (1 if excluded else 0, path)
            )

    def get_book_files(self, book_path: str) -> list[dict]:
        """
        Returns per-file records for a multi-file book, ordered by sort_order.
        Returns empty list if no records exist (single-file or M4B book,
        or book not yet scanned with this version).
        Each returned dict has keys:
            file_path, sort_order, duration_ms, cumulative_start_ms, title
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT file_path, sort_order, duration_ms, cumulative_start_ms, title
                   FROM book_files
                   WHERE book_path = ?
                   ORDER BY sort_order""",
                (book_path,)
            ).fetchall()
        return [dict(row) for row in rows]