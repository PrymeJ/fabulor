import json
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

        self._checkpoint_path = self._db.db_path.parent / "session_checkpoint.json"

        self._checkpoint_timer = QTimer(self)
        self._checkpoint_timer.setInterval(30 * 1000)  # 30 seconds
        self._checkpoint_timer.timeout.connect(self._write_checkpoint)

        self._recover_checkpoint()

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
        self._checkpoint_timer.start()
        self._session_segment_start = now
        self._session_listened_seconds = 0.0
        self._session_position_start = pos
        self._session_furthest_position = pos
        # A fresh session must not inherit a pending seek-credit window from a
        # prior session. If open() runs while a forward-seek's 15s credit timer
        # is still live (no intervening close()), the stale pending position
        # blocks every update_furthest_position tick and furthest never advances.
        self._post_seek_pending_position = None
        self._seek_credit_timer.stop()
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

    def close(self, at_eof: bool = False):
        """Flush the session to DB if >= 60s listened, then reset all state."""
        self._checkpoint_timer.stop()
        self._pause_timer.stop()
        self._seek_credit_timer.stop()

        if self._session_segment_start is not None:
            segment = (datetime.now() - self._session_segment_start).total_seconds()
            self._session_listened_seconds += segment
            self._session_segment_start = None

        listened = self._session_listened_seconds
        now = datetime.now()
        book = self._get_book()

        if (listened >= 60 or at_eof) and book is not None:
            start = self._session_start
            pos_start = self._session_position_start
            live_pos = self._get_position()
            pos_end = max(live_pos, self._session_furthest_position or pos_start or 0.0, pos_start or 0.0)
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
                    if not self._db.get_book_started_at(book.id):
                        self._db.set_started_at(book.id, start)
                    self.session_written.emit()
                    self._checkpoint_path.unlink(missing_ok=True)
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

    def _write_checkpoint(self):
        if self._session_start is None:
            return
        book = self._get_book()
        if book is None:
            return
        listened = self._session_listened_seconds
        if self._session_segment_start is not None:
            listened += (datetime.now() - self._session_segment_start).total_seconds()
        data = {
            "book_id": book.id,
            "book_path": str(book.path),
            "book_title": book.title,
            "book_author": book.author,
            "book_duration": book.duration,
            "session_start": self._session_start.isoformat(),
            "position_start": self._session_position_start,
            "furthest_position": self._session_furthest_position,
            "listened_seconds": listened,
            "segment_start": self._session_segment_start.isoformat() if self._session_segment_start else None,
        }
        try:
            self._checkpoint_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _recover_checkpoint(self):
        if not self._checkpoint_path.exists():
            return
        try:
            data = json.loads(self._checkpoint_path.read_text(encoding="utf-8"))
            listened = float(data.get("listened_seconds", 0))
            if listened < 60:
                self._checkpoint_path.unlink(missing_ok=True)
                return
            session_start = datetime.fromisoformat(data["session_start"])
            session_end = datetime.now()
            position_start = float(data.get("position_start") or 0)
            furthest = data.get("furthest_position")
            if furthest is not None:
                furthest = float(furthest)

            def _write():
                try:
                    self._db.write_session(
                        book_id=data["book_id"],
                        book_path=data["book_path"],
                        book_title=data["book_title"],
                        book_author=data["book_author"],
                        book_duration=data["book_duration"],
                        session_start=session_start,
                        session_end=session_end,
                        position_start=position_start,
                        position_end=furthest if furthest is not None else position_start,
                        furthest_position=furthest,
                        listened_seconds=listened,
                    )
                    if not self._db.get_book_started_at(data["book_id"]):
                        self._db.set_started_at(data["book_id"], session_start)
                except Exception:
                    pass
                finally:
                    self._checkpoint_path.unlink(missing_ok=True)

            threading.Thread(target=_write, daemon=True).start()
        except Exception:
            self._checkpoint_path.unlink(missing_ok=True)

    def _on_seek_credit_earned(self):
        if self._post_seek_pending_position is not None:
            if self._session_furthest_position is not None:
                self._session_furthest_position = max(
                    self._session_furthest_position,
                    self._post_seek_pending_position,
                )
        self._post_seek_pending_position = None
