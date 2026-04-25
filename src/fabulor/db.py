import sqlite3
from pathlib import Path
from datetime import datetime, date, timedelta
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
        """Opens a new connection for a single operation to ensure thread safety."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
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
                    last_played DATETIME
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_books_last_played ON books (last_played)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_books_title ON books (title)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_books_author ON books (author)")
            conn.execute("PRAGMA foreign_keys = ON")

            # Migration: add started_at to pre-existing databases
            try:
                conn.execute("ALTER TABLE books ADD COLUMN started_at DATETIME")
            except sqlite3.OperationalError:
                pass  # Column already exists

            conn.execute("""
                CREATE TABLE IF NOT EXISTS listening_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_path TEXT NOT NULL,
                    book_title TEXT,
                    book_author TEXT,
                    session_start TEXT NOT NULL,
                    session_end TEXT NOT NULL,
                    position_start REAL,
                    position_end REAL,
                    furthest_position REAL
                )
            """)

    # --- Scan Locations CRUD ---

    def add_scan_location(self, path):
        """Adds a new directory to the scan list."""
        try:
            with self._get_conn() as conn:
                with conn:
                    conn.execute("INSERT INTO scan_locations (path) VALUES (?)", (str(path),))
            return True
        except sqlite3.IntegrityError:
            return False

    def get_scan_locations(self):
        """Returns a list of all registered scan paths."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT path FROM scan_locations")
            return [row['path'] for row in cursor.fetchall()]

    def remove_scan_location(self, path):
        """Removes a directory from the scan list."""
        with self._get_conn() as conn:
            with conn:
                # Remove books from this folder first
                conn.execute(
                    "DELETE FROM books WHERE path LIKE ?",
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
                title=excluded.title,
                author=excluded.author,
                narrator=COALESCE(NULLIF(excluded.narrator, ''), books.narrator),
                duration=excluded.duration,
                progress=COALESCE(excluded.progress, books.progress),
                cover_path=excluded.cover_path,
                year=COALESCE(excluded.year, books.year)
        """
        with self._get_conn() as conn:
            with conn:
                conn.execute(query, cleaned)

    def get_book(self, path):
        """Retrieves a single book's metadata by its path."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM books WHERE path = ?", (str(path),))
            row = cursor.fetchone()
            return Book.from_dict(dict(row)) if row else None

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
            cursor = conn.execute(f"SELECT * FROM books ORDER BY {sort_by}{collate} {order}")
            return [Book.from_dict(dict(row)) for row in cursor.fetchall()]

    def get_book_count(self):
        """Returns the total number of books in the library."""
        with self._get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]

    def update_last_played(self, path):
        """Updates the last_played timestamp to the current time."""
        with self._get_conn() as conn:
            with conn:
                conn.execute(
                    "UPDATE books SET last_played = ? WHERE path = ?",
                    (datetime.now().isoformat(), str(path))
                )

    def update_progress(self, path, progress):
        """Updates the saved playback position (in seconds)."""
        with self._get_conn() as conn:
            with conn:
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
            with conn:
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
                      session_start, session_end, position_start, position_end, furthest_position):
        """Inserts one listening session row."""
        with self._get_conn() as conn:
            with conn:
                conn.execute("""
                    INSERT INTO listening_sessions
                        (book_path, book_title, book_author, book_duration,
                         session_start, session_end,
                         position_start, position_end, furthest_position)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(book_path) if book_path else None,
                    book_title,
                    book_author,
                    book_duration,
                    session_start.isoformat(),
                    session_end.isoformat(),
                    position_start,
                    position_end,
                    furthest_position,
                ))

    def get_daily_book_breakdown(self, date_str: str, day_start_hour: int) -> list[dict]:
        """Returns per-book listening rows for a given day, with cover from books table via LEFT JOIN."""
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    ls.book_path,
                    ls.book_title,
                    ls.book_author,
                    ls.book_duration,
                    SUM((julianday(ls.session_end) - julianday(ls.session_start)) * 86400) as clock_seconds,
                    SUM(ls.position_end - ls.position_start) as book_seconds_advanced,
                    MAX(ls.furthest_position) as furthest_position,
                    b.cover_path,
                    MAX(CASE WHEN be.event_type = 'finished' THEN 1 ELSE 0 END) as is_finished
                FROM listening_sessions ls
                LEFT JOIN books b ON ls.book_path = b.path
                LEFT JOIN book_events be ON ls.book_path = be.book_path AND be.event_type = 'finished'
                WHERE strftime('%Y-%m-%d', datetime(ls.session_start, ?)) = ?
                GROUP BY ls.book_path
                ORDER BY clock_seconds DESC, COALESCE(book_seconds_advanced, 0) DESC
            """, (offset, date_str)).fetchall()
        return [dict(r) for r in rows]

    def set_started_at(self, book_path: str, started_at: datetime):
        """Sets started_at only if it has not been set yet."""
        with self._get_conn() as conn:
            with conn:
                conn.execute(
                    "UPDATE books SET started_at = ? WHERE path = ? AND started_at IS NULL",
                    (started_at.isoformat(), str(book_path))
                )

    def get_book_started_at(self, book_path: str) -> datetime | None:
        """Returns the started_at datetime for the given path, or None."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT started_at FROM books WHERE path = ?",
                (str(book_path),)
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
                "  book_path,"
                "  book_title,"
                "  SUM((julianday(session_end) - julianday(session_start)) * 86400) AS seconds"
                " FROM listening_sessions"
                " GROUP BY period, book_path"
                " ORDER BY period DESC, seconds DESC",
                (fmt, offset)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_per_book_stats(self, book_path: str, day_start_hour: int) -> dict:
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            agg = conn.execute(
                "SELECT"
                "  MAX(furthest_position) AS furthest_position,"
                "  SUM((julianday(session_end) - julianday(session_start)) * 86400) AS total_seconds"
                " FROM listening_sessions"
                " WHERE book_path = ?",
                (book_path,)
            ).fetchone()
            if agg is None or agg['total_seconds'] is None:
                return {'furthest_position': 0.0, 'total_seconds': 0.0, 'per_day': []}
            per_day = conn.execute(
                "SELECT"
                "  strftime('%Y-%m-%d', datetime(session_start, ?)) AS date,"
                "  SUM((julianday(session_end) - julianday(session_start)) * 86400) AS seconds"
                " FROM listening_sessions"
                " WHERE book_path = ?"
                " GROUP BY date"
                " ORDER BY date ASC",
                (offset, book_path)
            ).fetchall()
            return {
                'furthest_position': agg['furthest_position'] or 0.0,
                'total_seconds': agg['total_seconds'] or 0.0,
                'per_day': [dict(row) for row in per_day],
            }

    def get_overall_stats(self, day_start_hour: int = 0) -> dict:
        with self._get_conn() as conn:
            agg = conn.execute("""
                SELECT
                    COUNT(*) as total_sessions,
                    COUNT(DISTINCT book_path) as books_started,
                    SUM((julianday(session_end) - julianday(session_start)) * 86400) as total_seconds,
                    AVG((julianday(session_end) - julianday(session_start)) * 86400) as avg_seconds
                FROM listening_sessions
            """).fetchone()

            longest = conn.execute("""
                SELECT book_title,
                    (julianday(session_end) - julianday(session_start)) * 86400 as seconds
                FROM listening_sessions
                ORDER BY seconds DESC
                LIMIT 1
            """).fetchone()

            top = conn.execute("""
                SELECT book_title,
                    SUM((julianday(session_end) - julianday(session_start)) * 86400) as seconds
                FROM listening_sessions
                GROUP BY book_path
                ORDER BY seconds DESC
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
            'most_listened_title': top['book_title'] if top else None,
            'most_listened_seconds': top['seconds'] if top else 0.0,
        }

    def get_last_n_days(self, n: int = 7, day_start_hour: int = 0) -> list[dict]:
        """Returns total listening seconds per day for the last N days.
        Days with no activity are included as zero so the chart has a consistent shape."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    strftime('%Y-%m-%d', datetime(session_start, ?)) as date,
                    SUM((julianday(session_end) - julianday(session_start)) * 86400) as seconds
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

        result = []
        today = date.today()
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
                    ls.book_path,
                    ls.book_title,
                    ls.book_author,
                    ls.book_duration,
                    SUM((julianday(ls.session_end) - julianday(ls.session_start)) * 86400) as clock_seconds,
                    SUM(ls.position_end - ls.position_start) as book_seconds_advanced,
                    MAX(ls.furthest_position) as furthest_position,
                    b.cover_path,
                    MAX(CASE WHEN be.event_type = 'finished' THEN 1 ELSE 0 END) as is_finished
                FROM listening_sessions ls
                LEFT JOIN books b ON ls.book_path = b.path
                LEFT JOIN book_events be ON ls.book_path = be.book_path AND be.event_type = 'finished'
                WHERE strftime(?, datetime(ls.session_start, ?)) = ?
                GROUP BY ls.book_path
                ORDER BY clock_seconds DESC, COALESCE(book_seconds_advanced, 0) DESC
            """, (fmt, offset, period_label)).fetchall()
        return [dict(r) for r in rows]

    def get_finished_in_period(self, granularity: str, period_label: str, day_start_hour: int) -> list[dict]:
        """Returns books with a finished event whose event_time falls within the given period."""
        formats = {
            'day':   '%Y-%m-%d',
            'week':  '%Y-W%W',
            'month': '%Y-%m',
            'year':  '%Y',
        }
        if granularity not in formats:
            raise ValueError(f"Invalid granularity: {granularity}")
        fmt = formats[granularity]
        offset = f'-{day_start_hour} hours'
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT
                    be.book_path,
                    be.event_time,
                    b.cover_path,
                    COALESCE(b.title, be.book_path) as book_title,
                    COALESCE(b.author, '') as book_author
                FROM book_events be
                LEFT JOIN books b ON be.book_path = b.path
                WHERE be.event_type = 'finished'
                AND strftime(?, datetime(be.event_time, ?)) = ?
                ORDER BY be.event_time DESC
            """, (fmt, offset, period_label)).fetchall()
        return [dict(r) for r in rows]