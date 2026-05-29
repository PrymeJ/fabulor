import threading
from datetime import datetime
from PySide6.QtCore import QObject, QTimer, Signal


class SessionRecorder(QObject):
    """Owns all listening-session state and persistence logic."""

    session_written = Signal()

    def __init__(self, db, get_position_fn, get_book_fn, parent=None):
        """
        db              — LibraryDB instance
        get_position_fn — callable() -> float, returns current playback position
        get_book_fn     — callable() -> Book | None, returns currently loaded book
        """
        super().__init__(parent)
        self._db = db
        self._get_position = get_position_fn
        self._get_book = get_book_fn

        self._session_start: datetime | None = None
        self._session_segment_start: datetime | None = None
        self._session_listened_seconds: float = 0.0
        self._session_position_start: float | None = None
        self._session_furthest_position: float | None = None
        self._post_seek_pending_position: float | None = None

        self._pause_timer = QTimer(self)
        self._pause_timer.setSingleShot(True)
        self._pause_timer.setInterval(3 * 60 * 1000)  # 3 minutes
        self._pause_timer.timeout.connect(self.close)

        self._seek_credit_timer = QTimer(self)
        self._seek_credit_timer.setSingleShot(True)
        self._seek_credit_timer.setInterval(15 * 1000)  # 15 seconds
        self._seek_credit_timer.timeout.connect(self._on_seek_credit_earned)

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """True when a session is open (playing or paused within the 3-min window)."""
        return self._session_start is not None

    def open(self):
        """Start a brand-new session (first play after no active session)."""
        now = datetime.now()
        pos = self._get_position()
        self._session_start = now
        self._session_segment_start = now
        self._session_listened_seconds = 0.0
        self._session_position_start = pos
        self._session_furthest_position = pos
        book = self._get_book()
        dur = book.duration if book else 0
        pct = (pos / dur * 100) if dur else 0
        s = int(pos)
        pos_str = f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"
        print(f"[open_session] book='{book.title if book else '?'}' clock={now.strftime('%H:%M:%S')} pos={pos_str} ({pct:.1f}%)")

    def resume(self):
        """Resume an existing session after a short pause (< 3 min)."""
        self._session_segment_start = datetime.now()
        self._pause_timer.stop()

    def pause(self):
        """Accumulate the current segment's listened time and start the 3-min timer."""
        if self._session_segment_start is not None:
            segment = (datetime.now() - self._session_segment_start).total_seconds()
            self._session_listened_seconds += segment
            self._session_segment_start = None
        print(f"[pause_session] listened_so_far={self._session_listened_seconds/60:.1f}min")
        self._pause_timer.start()

    def close(self):
        """Flush the session to DB if >= 60s listened, then reset all state."""
        self._pause_timer.stop()
        self._seek_credit_timer.stop()

        if self._session_segment_start is not None:
            segment = (datetime.now() - self._session_segment_start).total_seconds()
            self._session_listened_seconds += segment
            self._session_segment_start = None

        listened = self._session_listened_seconds
        now = datetime.now()
        book = self._get_book()

        if listened >= 60 and book is not None:
            start = self._session_start
            pos_start = self._session_position_start
            pos_end = max(self._get_position(), pos_start)
            furthest = self._session_furthest_position
            dur = book.duration if book else 0
            pct_end = (pos_end / dur * 100) if dur else 0
            s_start = int(pos_start)
            s_end = int(pos_end)
            pos_start_str = f"{s_start//3600:02d}:{(s_start%3600)//60:02d}:{s_start%60:02d}"
            pos_end_str = f"{s_end//3600:02d}:{(s_end%3600)//60:02d}:{s_end%60:02d}"
            print(f"[close_session] book='{book.title}' {pos_start_str}→{pos_end_str} ({pct_end:.1f}%) listened={listened/60:.1f}min")

            def _write():
                try:
                    self._db.write_session(
                        book_id=book.id,
                        book_path=book.path,
                        book_title=book.title,
                        book_author=book.author,
                        book_duration=book.duration,
                        session_start=start,
                        session_end=now,
                        position_start=pos_start,
                        position_end=pos_end,
                        furthest_position=furthest,
                        listened_seconds=listened,
                    )
                    if not self._db.get_book_started_at(book.path):
                        self._db.set_started_at(book.path, start)
                    self.session_written.emit()
                except Exception:
                    pass

            threading.Thread(target=_write, daemon=True).start()
        else:
            print(f"[close_session] discarded — listened={listened:.0f}s < 60s threshold")

        self._session_start = None
        self._session_segment_start = None
        self._session_listened_seconds = 0.0
        self._session_position_start = None
        self._session_furthest_position = None
        self._post_seek_pending_position = None

    def update_furthest_position(self, pos: float | None):
        """Called from the UI timer tick. Updates furthest position if pos advances
        beyond the known furthest and no seek credit is pending."""
        if (self._session_start is not None
                and self._post_seek_pending_position is None
                and self._session_furthest_position is not None
                and pos is not None):
            if pos > self._session_furthest_position:
                self._session_furthest_position = pos

    def notify_seek(self, new_pos: float):
        """Called after any user-initiated seek. Starts the 15s credit timer if the
        seek advances beyond the furthest known position; cancels it if not."""
        if self._session_furthest_position is not None:
            if new_pos > self._session_furthest_position:
                self._post_seek_pending_position = new_pos
                self._seek_credit_timer.start()
            else:
                self._post_seek_pending_position = None
                self._seek_credit_timer.stop()

    # ── Private ───────────────────────────────────────────────────────────────

    def _on_seek_credit_earned(self):
        if self._post_seek_pending_position is not None:
            if self._session_furthest_position is not None:
                self._session_furthest_position = max(
                    self._session_furthest_position,
                    self._post_seek_pending_position,
                )
        self._post_seek_pending_position = None
