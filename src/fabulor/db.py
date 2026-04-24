import sqlite3
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
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
                    (str(path) + "%",)
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
            return dict(row) if row else None

    def get_all_books(self, sort_by="title"):
        """Returns all books in the library."""
        with self._get_conn() as conn:
            cursor = conn.execute(f"SELECT * FROM books ORDER BY {sort_by}")
            return [dict(row) for row in cursor.fetchall()]

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