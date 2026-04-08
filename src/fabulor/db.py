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
                    title TEXT,
                    author TEXT,
                    narrator TEXT,
                    duration REAL,
                    progress REAL DEFAULT 0,
                    cover_path TEXT,
                    date_added DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_played DATETIME
                )
            """)
            # Ensure progress column exists for older databases
            try:
                conn.execute("ALTER TABLE books ADD COLUMN progress REAL DEFAULT 0")
            except sqlite3.OperationalError:
                pass 

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
        path, title, author, narrator, duration, progress, cover_path
        """
        query = """
            INSERT INTO books (path, title, author, narrator, duration, progress, cover_path)
            VALUES (:path, :title, :author, :narrator, :duration, :progress, :cover_path)
            ON CONFLICT(path) DO UPDATE SET
                title=excluded.title,
                author=excluded.author,
                narrator=excluded.narrator,
                duration=excluded.duration,
                progress=COALESCE(excluded.progress, books.progress),
                cover_path=excluded.cover_path
        """
        cleaned = {
            k: (v.strip() if isinstance(v, str) else v) for k, v in book_data.items()
        }
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