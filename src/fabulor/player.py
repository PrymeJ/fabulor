import locale
import logging
import math
import os
import time
import warnings
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QPixmap

logger = logging.getLogger(__name__)

# Stub workaround and libmpv check logic lives here
os.environ["MPV_HOME"] = ""
try:
    from mpv import MPV
except OSError as e:
    msg = str(e)
    if "libmpv" in msg or "libcaca" in msg or "libtinfo" in msg or "_nc_curscr" in msg:
        raise SystemExit(
            "❌ libmpv not found.\n\n"
            "Install it with:\n"
            "  • openSUSE: sudo zypper install libmpv\n"
            "  • Ubuntu: sudo apt install libmpv\n"
            "  • macOS: brew install mpv\n"
            "  • Windows: choco install mpv\n"
            "Then try again."
        )
    raise

try:
    import mutagen
except ImportError:
    mutagen = None

# Tolerance for walking chapter_list to map a position -> chapter index (display
# labels AND the current-chapter detection in next/previous_chapter). Must exceed
# mpv's PAUSED-seek undershoot: while paused, an exact seek lands ~0.37s SHORT of
# its target (measured 2026-06-13). If this tolerance is below that, the nav walk
# resolves the chapter we just left, so paused Next/Prev gets stuck re-targeting
# the same chapter and the slider freezes. 0.5 clears the ~0.37s undershoot with
# margin and is still far below the minimum real chapter spacing (~2s), so it can
# never misattribute to an adjacent chapter. This is a read-side lookup tolerance
# only — NOT a seek offset (see _EMBEDDED_CHAPTER_SEEK_OFFSET).
_CHAPTER_WALK_TOLERANCE = 0.5

# Legacy seek-target epsilon for VT/CUE chapter-boundary seeks (kept unchanged to
# preserve their audio landing). Embedded M4B uses _EMBEDDED_CHAPTER_SEEK_OFFSET
# instead. Do not reuse this for position->index walks — use
# _CHAPTER_WALK_TOLERANCE for those.
_CHAPTER_BOUNDARY_EPSILON = 0.35

# SEEK-side offset applied to embedded-M4B chapter-nav targets only. Measured
# 2026-06-13 across 5 M4Bs (67 chapter seeks): mpv's exact seek overshoots the
# nominal boundary by ~0.09s (1-2 AAC frames) on its own. Adding the old +0.35
# display epsilon to seek targets skipped ~0.44s of every chapter's opening
# ("Part 3" -> "3", "Nineteen" -> "teen"). Seeking to nominal - 0.09 lets mpv's
# natural overshoot cancel it, landing ~on the true boundary. Embedded M4B only —
# VT (file-start, lands at sample 0) and CUE keep _CHAPTER_BOUNDARY_EPSILON.
_EMBEDDED_CHAPTER_SEEK_OFFSET = -0.09

# Forward correction added to an embedded-M4B seek target ONLY when paused. Measured
# 2026-06-13: while playing, mpv's exact seek lands accurately; while PAUSED it
# undershoots its target by ~0.37s (and its time-pos observer reports unstable
# intermediate values). Any paused seek to a boundary (undo, chapter-notch wheel,
# chapter nav) therefore lands in the previous chapter's tail unless compensated.
# This is applied to the mpv seek command only — _seek_target / _cached_time_pos
# keep the logical (uncompensated) position so the chapter walk and UI stay correct.
# Embedded M4B only; VT/CUE paused-seek behaviour was not characterised.
_PAUSED_SEEK_UNDERSHOOT_COMP = 0.37
_MP3_SEEK_THRESHOLD: float = 60.0  # long seeks on single VBR MP3 use stop-and-load
_VT_MP3_SIZE_THRESHOLD: int = 40 * 1024 * 1024  # 40 MB — VT files above this use stop-and-load

class Player(QObject):
    chapter_changed = Signal(int)
    file_loaded = Signal()
    file_switched = Signal()
    book_ready = Signal()
    load_failed = Signal(str)  # reason string from mpv end-file event
    _playlist_resolved = Signal(str, str)  # play_target, chapters_file ('' if none)

    def __init__(self, db, config=None):
        super().__init__()
        self.db = db
        self.config = config
        self.instance = None  # deferred
        self._eof = False
        self._is_seeking = False # For UI deadzone logic
        self._undo_pos = None # For undo seek logic
        self._last_undo_click_time = 0 # For undo seek logic
        self._base_volume = 100.0 # User's set volume (log scale)
        self._fade_ratio = 1.0   # Sleep timer fade (0.0 to 1.0)
        self._cached_time_pos: float | None = None
        self._cached_duration: float | None = None
        self._cached_pause: bool = True
        self._cached_speed: float = 1.0
        self._seek_target: float | None = None
        # Virtual timeline state (multi-file MP3 books)
        self._virtual_timeline: list | None = None
        self._file_offset: float = 0.0
        self._book_duration: float | None = None
        self._chapter_list: list | None = None
        self._current_vt_index: int = 0
        self._pending_local_pos: float | None = None
        self._is_vt_file_switch: bool = False
        self._last_vt_chapter: int = -1
        self._last_nonvt_chapter: int = 0
        self._held_play: tuple | None = None
        self._play_target: str | None = None
        self._mp3_seek_reload_pending: bool = False
        self._mp3_seek_target: float = 0.0
        self._mp3_seek_was_playing: bool = False
        self._mp3_seek_visual_lock: bool = False
        self._is_embedded_m4b: bool = False

    @staticmethod
    def format_time(seconds):
        """Converts seconds to HH:MM:SS format."""
        if seconds is None:
            return "00:00:00"
        seconds = max(0, seconds)
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02}"

    def _ensure_mpv(self):
        if self.instance is None:
            locale.setlocale(locale.LC_NUMERIC, "C")
            self.instance = MPV(
                vo='null', ao='pulse', vid=False, ytdl=False, keep_open='always',
                audio_client_name='fabulor'
            )
            self.instance.observe_property('chapter', self._on_chapter_change)
            self.instance.observe_property('pause', self._on_pause_test)  # ADD
            self.instance.observe_property('time-pos', self._on_time_pos_change)
            self.instance.observe_property('duration', self._on_duration_change)
            self.instance.observe_property('speed', self._on_speed_change)
            self.instance.event_callback('file-loaded')(self._on_file_loaded)
            self.instance.event_callback('end-file')(self._on_end_file)

    def _on_time_pos_change(self, name, value):
        self._cached_time_pos = value
        if self._is_seeking and value is not None and self._seek_target is not None:
            global_value = value + (self._file_offset or 0)
            if abs(global_value - self._seek_target) < 1.0:
                self._is_seeking = False
                self._seek_target = None
                # Reset chapter tracking counters so the subsequent position walk
                # always emits chapter_changed with the settled chapter. Without this,
                # if the final chapter == last tracked chapter (updated during intermediate
                # seek events that were blocked by the is_seeking label gate), the
                # curr != _last_*_chapter check would be False and no emit would fire —
                # leaving the chapter label showing the wrong book's chapter.
                self._last_nonvt_chapter = -1
                self._last_vt_chapter = -1
        # VT: use self._chapter_list directly — it holds the virtual timeline chapter
        # data (exact DB times, global positions). self._file_offset translates the
        # local mpv time_pos into the global VT position.
        if self._virtual_timeline is not None and self._chapter_list and value is not None:
            global_pos = (value or 0.0) + self._file_offset
            curr = 0
            for i, chap in enumerate(self._chapter_list):
                if chap.get('time', 0) <= global_pos:
                    curr = i
            if curr != self._last_vt_chapter:
                self._last_vt_chapter = curr
                self.chapter_changed.emit(curr)
        # Non-VT: self.chapter_list (property) returns _chapter_list for embedded M4B
        # (cached snapshot set by cache_chapter_list() at load) or _chapter_list for CUE,
        # so instance.chapter_list is never read live during playback. The inconsistency
        # with the VT branch above (which reads _chapter_list directly) is intentional.
        elif self.chapter_list and value is not None:
            curr = 0
            for i, chap in enumerate(self.chapter_list):
                if chap.get('time', 0) <= value + _CHAPTER_WALK_TOLERANCE:
                    curr = i
            if curr != self._last_nonvt_chapter:
                self._last_nonvt_chapter = curr
                self.chapter_changed.emit(curr)

    def _on_duration_change(self, name, value):
        self._cached_duration = value

    def _on_speed_change(self, name, value):
        if value is not None:
            self._cached_speed = value

    def _advance_or_finish(self):
        """Called when current file/stream reaches its end.
        For VT books: advance to next file or set _eof if last.
        For all other books: set _eof."""
        if self._virtual_timeline is not None:
            next_idx = self._current_vt_index + 1
            if next_idx < len(self._virtual_timeline):
                next_file = self._virtual_timeline[next_idx]
                self._current_vt_index = next_idx
                self._file_offset = next_file['cumulative_start']
                self._is_vt_file_switch = True
                self._pending_local_pos = None
                self.instance.play(next_file['file_path'])
                if self.instance.pause:
                    self.instance.pause = False
            else:
                self._eof = True
        else:
            self._eof = True

    def _on_pause_test(self, name, value):
        self._cached_pause = value
        if value:
            if self._is_vt_file_switch:
                return  # transient pause during file load — ignore
            pos = self.instance.time_pos
            dur = self.instance.duration
            if pos is not None and dur is not None and pos >= dur - 1.5:
                self._advance_or_finish()

    _AUDIO_EXTENSIONS = {'.m4b', '.mp3', '.m4a', '.flac'}

    def _resolve_playlist(self, path: str) -> tuple:
        files = sorted(
            f for f in Path(path).iterdir()
            if f.is_file() and f.suffix.lower() in self._AUDIO_EXTENSIONS
        )
        if not files:
            return (path, None)
        if len(files) == 1:
            audio_file = files[0]
            if audio_file.suffix.lower() in ('.m4b', '.m4a'):
                chapter_source = self._get_chapter_source_setting()
                if chapter_source == 'cue':
                    cue_files = [f for f in Path(path).iterdir() if f.suffix.lower() == '.cue']
                    cue_path = self._select_cue_file(cue_files, path)
                    if cue_path:
                        book = self.db.get_book(path)
                        file_duration = book.duration if book and book.duration else None
                        chapters = self._parse_cue(cue_path, audio_file, file_duration)
                        if chapters:
                            self._chapter_list = chapters
            return (str(audio_file), None)

        db_files = self.db.get_book_files(path)
        if not db_files:
            return (path, None)

        timeline = []
        chapter_list = []
        total_duration = 0.0
        for row in db_files:
            start_s = row['cumulative_start_ms'] / 1000.0
            dur_s = row['duration_ms'] / 1000.0
            timeline.append({
                'file_path': row['file_path'],
                'cumulative_start': start_s,
                'duration': dur_s,
            })
            chapter_list.append({
                'time': start_s,
                'title': row['title'] or '',
            })
            total_duration = start_s + dur_s
        self._virtual_timeline = timeline
        self._chapter_list = chapter_list
        self._book_duration = total_duration
        self._file_offset = 0.0
        return (db_files[0]['file_path'], None)

    def _get_chapter_source_setting(self) -> str:
        if self.config is not None:
            return self.config.get_chapter_list_source()
        return 'embedded'

    def _select_cue_file(self, cue_files: list, folder_path: str):
        if not cue_files:
            return None
        if len(cue_files) == 1:
            return cue_files[0]
        # Multiple CUE files: try to match stem against folder name pattern "Author - Title"
        folder_name = Path(folder_path).name.lower()
        parts = folder_name.split(' - ', 1)
        candidates = [parts[-1].strip()] if len(parts) == 2 else [folder_name]
        for cue in cue_files:
            stem = cue.stem.lower()
            if any(stem == c or stem in c or c in stem for c in candidates):
                return cue
        return None

    def _parse_cue(self, cue_path, audio_file, file_duration: float | None = None) -> list | None:
        try:
            text = cue_path.read_text(encoding='utf-8-sig', errors='replace')
        except OSError:
            return None

        chapters = []
        current_title = ''
        file_validated = False

        for line in text.splitlines():
            stripped = line.strip()
            upper = stripped.upper()

            if upper.startswith('FILE '):
                # Extract filename between quotes or as bare token
                if '"' in stripped:
                    fname = stripped.split('"')[1]
                else:
                    fname = stripped.split()[1]
                if Path(fname).stem.lower() != audio_file.stem.lower():
                    return None
                file_validated = True
                continue

            if upper.startswith('TITLE '):
                raw = stripped[6:].strip()
                current_title = raw.strip('"')
                continue

            if upper.startswith('INDEX 01 '):
                ts = stripped.split()[-1]  # MM:SS:FF
                parts = ts.split(':')
                if len(parts) != 3:
                    continue
                try:
                    mm, ss, ff = int(parts[0]), int(parts[1]), int(parts[2])
                except ValueError:
                    continue
                # FF is CD frames (nominally 0-74, 75fps); be lenient with non-standard values
                time_s = mm * 60 + ss + ff / 75.0
                chapters.append({'title': current_title, 'time': time_s})
                current_title = ''

        if not file_validated or len(chapters) < 2:
            return None
        if chapters[0]['time'] != 0.0:
            return None
        if any(chapters[i]['time'] <= chapters[i - 1]['time'] for i in range(1, len(chapters))):
            return None
        if file_duration is not None and any(chap['time'] >= file_duration for chap in chapters):
            return None
        return chapters

    def load_book(self, path, start_paused=True):
        self._ensure_mpv()
        self._is_seeking = True
        self._eof = False
        self._start_paused = start_paused
        self._play_gated = True
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                self._playlist_resolved.disconnect(self._on_playlist_resolved)
            except RuntimeError:
                pass
        self._playlist_resolved.connect(self._on_playlist_resolved)

        player = self

        class _ResolveWorker(QRunnable):
            def run(self):
                # Defensive: path can vanish between the caller's existence check and
                # this worker actually running (race window). Without this catch, any
                # OSError from Path(path).iterdir() propagates out of QRunnable.run(),
                # is swallowed by Qt's thread pool, and _playlist_resolved never fires —
                # the load dies silently and playback continues on whatever was already
                # loaded. Catch broadly: the goal is "don't die silently on the thread,"
                # not "handle specific error types differently."
                try:
                    play_target, chapters_file = player._resolve_playlist(path)
                except Exception as e:
                    print(f"[load_book] _resolve_playlist failed for {path!r}: {e!r}")
                    return
                player._playlist_resolved.emit(play_target, chapters_file or "")

        # Reset virtual timeline state for new book
        self._virtual_timeline = None
        self._file_offset = 0.0
        self._book_duration = None
        self._chapter_list = None
        self._is_embedded_m4b = False
        self._current_vt_index = 0
        self._pending_local_pos = None
        self._is_vt_file_switch = False
        self._last_vt_chapter = -1
        self._last_nonvt_chapter = -1
        self._play_target = None
        self._mp3_seek_reload_pending = False
        self._mp3_seek_visual_lock = False
        # Clear cached mpv state so stale values from previous book can't leak
        # into saves before the new book's file is loaded.
        self._cached_time_pos = None
        self._cached_duration = None
        self._seek_target = None

        QThreadPool.globalInstance().start(_ResolveWorker())

    def _on_playlist_resolved(self, play_target, chapters_file):
        self._play_target = play_target
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                self._playlist_resolved.disconnect(self._on_playlist_resolved)
            except RuntimeError:
                pass
        # play_target is a directory only when _resolve_playlist found no audio
        # files in the folder — the folder exists but has no playable content.
        # Don't hand this to mpv (it would error as "Unrecognized file format");
        # emit load_failed directly so the app can soft-delete the book.
        if os.path.isdir(play_target):
            self.load_failed.emit("no audio files in folder")
            return
        if not self._play_gated:
            # Gate already lifted before resolve finished — play immediately.
            self.instance.chapters_file = chapters_file or None
            if self._virtual_timeline is not None:
                # VT book: fire book_ready now (Qt thread, VT data ready)
                self.book_ready.emit()
            self.instance.play(play_target)
            if self._start_paused:
                self.instance.pause = True
        else:
            self._held_play = (play_target, chapters_file)

    def ungate_play(self):
        """Call after panel animation finishes (or immediately for non-library loads)."""
        self._play_gated = False
        if self._held_play is None:
            return
        play_target, chapters_file = self._held_play
        self._held_play = None
        self.instance.chapters_file = chapters_file or None
        if self._virtual_timeline is not None:
            # VT book: fire book_ready now (Qt thread, VT data ready)
            self.book_ready.emit()
        self.instance.play(play_target)
        if self._start_paused:
            self.instance.pause = True
        

    def _on_chapter_change(self, name, value):
        # For non-VT non-CUE (embedded M4B), _on_time_pos_change handles chapter
        # tracking via position walk. The native mpv chapter property update is async
        # and races with _on_time_pos_change — it fires after _is_seeking is already
        # cleared, so the _is_seeking guard here can't protect against the stale value.
        # Suppressing it entirely avoids the snap-back on chapter navigation.
        return
    def _on_file_loaded(self, event):
        if self._mp3_seek_reload_pending:
            self._mp3_seek_reload_pending = False
            self._is_seeking = False
            self._seek_target = None
            self.instance.pause = not self._mp3_seek_was_playing
            self._mp3_seek_visual_lock = False
            return
        if self._pending_local_pos is not None:
            pending = self._pending_local_pos
            self._pending_local_pos = None
            # Defensive EOF guard: mpv hangs silently if seeked within ~2s of a
            # file's duration. `pending` is a local offset into the just-switched
            # VT file; a cross-file seek normally lands near that file's start so
            # this is not hit in practice, but the guard keeps the path safe if
            # future VT logic ever lets the target land near EOF. Mirrors the
            # same-file branch in seek_async. On skip, clear seek state so the
            # slider isn't left waiting on a seek that never issues.
            target_file = (self._virtual_timeline[self._current_vt_index]
                           if self._virtual_timeline is not None else None)
            if target_file is not None and target_file['duration'] - pending < 2.0:
                self._is_seeking = False
                self._seek_target = None
            else:
                # _seek_target must be GLOBAL: the settle in _on_time_pos_change compares
                # abs((value + _file_offset) - _seek_target) < 1.0. Storing the LOCAL
                # `pending` here (the previous behaviour) made that distance ~the file's
                # cumulative_start, so a cross-file seek NEVER settled and is_seeking stuck
                # True forever → permanent chapter-UI freeze (captured 2026-06-15, VT books).
                # The mpv command stays LOCAL (`pending`); only the logical target is global.
                # Use the timeline entry (self-consistent with _current_vt_index) not the bare
                # _file_offset field, so it can't drift if that field is ever stale.
                target_offset = target_file['cumulative_start'] if target_file is not None else (self._file_offset or 0)
                # Tripwire: this fix assumes _current_vt_index identifies the file mpv just
                # loaded (true while VT loads are serialized — verified 2026-06-15). If that
                # ever stops holding, fail loudly here rather than silently re-freeze.
                try:
                    _loaded = self.instance.path
                except Exception:
                    _loaded = None
                if _loaded and target_file is not None and os.path.basename(_loaded) != os.path.basename(target_file['file_path']):
                    print(f"[VT-DESYNC] loaded={os.path.basename(_loaded)} != "
                          f"target_idx={self._current_vt_index} "
                          f"path={os.path.basename(target_file['file_path'])} — VT load no longer serialized!", flush=True)
                self._seek_target = pending + target_offset
                self.instance.command_async('seek', pending, 'absolute+exact')
        if self._virtual_timeline is not None:
            self._is_vt_file_switch = False
            self.file_switched.emit()
        else:
            self.book_ready.emit()

    def _on_end_file(self, event):
        data = event.data  # MpvEventEndFile struct with integer reason field
        reason_int = data.reason if data else -1
        # MpvEventEndFile constants: EOF=0, RESTARTED=1, ABORTED=2, QUIT=3, ERROR=4, REDIRECT=5
        if reason_int == 4:  # ERROR
            error_str = event.as_dict().get('file_error', b'').decode('utf-8', errors='replace')
            detail = error_str if error_str else 'unknown error'
            self.load_failed.emit(detail)
        if reason_int == 0:
            self._advance_or_finish()

    def extract_cover(self, file_path):
        """Extracts cover art from file tags."""
        if not mutagen:
            return QPixmap()

        pixmap = QPixmap()
        # Handle the "Folder = Book" logic
        target_file = file_path
        if os.path.isdir(file_path):
            audio_exts = {'.m4b', '.mp3', '.flac', '.m4a'}
            files = sorted([f for f in os.listdir(file_path) if os.path.splitext(f)[1].lower() in audio_exts])
            if not files: return pixmap
            target_file = os.path.join(file_path, files[0])

        try:
            audio = mutagen.File(target_file)
            if audio is None:
                return pixmap
            if audio and audio.tags:
                if 'covr' in audio.tags:
                    data = audio.tags['covr'][0]
                    pixmap.loadFromData(data)
                else:
                    for key in audio.tags.keys():
                        if key.startswith('APIC'):
                            pixmap.loadFromData(audio.tags[key].data)
                            break
        except Exception as e:
            print(f"Metadata extraction error: {e}")
        return pixmap
    
    @property
    def is_initialized(self): return bool(self.instance)

    # Playback Control Proxies
    @property
    def pause(self): return self._cached_pause
    @pause.setter
    def pause(self, value): 
        if self.instance: self.instance.pause = value

    @property
    def time_pos(self):
        if self._cached_time_pos is None:
            return None
        if self._virtual_timeline is not None:
            return self._file_offset + self._cached_time_pos
        return self._cached_time_pos
    @time_pos.setter
    def time_pos(self, value):
        if self.instance:
            self.instance.time_pos = value
            self._eof = False

    def _resolve_vt_index(self, global_pos: float) -> int:
        for i in range(len(self._virtual_timeline) - 1, -1, -1):
            if global_pos >= self._virtual_timeline[i]['cumulative_start']:
                return i
        return 0

    def _mp3_stop_and_load(self, target_pos: float, file_path: str | None = None, local_pos: float | None = None) -> None:
        """Reload MP3 at target_pos to avoid VBR stream-scan latency on long seeks.

        For single-file books, file_path/local_pos are None and target_pos is global == local.
        For VT same-file seeks, file_path is the VT file and local_pos is the offset within it;
        _cached_time_pos is set to local_pos so time_pos getter (_file_offset + _cached_time_pos)
        returns the correct global position without double-counting the offset.
        """
        was_playing = not self._cached_pause
        self._mp3_seek_reload_pending = True
        self._mp3_seek_was_playing = was_playing
        self._eof = False
        self._is_seeking = True
        self._seek_target = target_pos
        self._cached_time_pos = local_pos if local_pos is not None else target_pos
        self._mp3_seek_visual_lock = True
        load_path = file_path if file_path is not None else self._play_target
        start_pos = local_pos if local_pos is not None else target_pos
        self.instance.pause = True
        self.instance.command('loadfile', load_path, 'replace', '0', f'start={start_pos}')

    def seek_async(self, pos: float) -> None:
        """Non-blocking seek. For virtual timeline books, resolves file and local offset."""
        if not self.instance:
            return
        # Floor the target. _EMBEDDED_CHAPTER_SEEK_OFFSET is negative, so a nav to
        # chapter 0 (nominal ~0.0) would otherwise produce a negative absolute seek;
        # mpv treats a negative/zero absolute seek as undefined and can land at EOF
        # (observed: "previous chapter" near book start jumping to 100%/finished).
        # A small positive floor keeps the seek inside the file at the very start.
        if pos < 0.05:
            pos = 0.05
        if self._virtual_timeline is not None:
            target_idx = self._resolve_vt_index(pos)
            target_file = self._virtual_timeline[target_idx]
            local_pos = pos - target_file['cumulative_start']
            if target_idx == self._current_vt_index:
                if local_pos >= target_file['duration']:
                    return  # past end — no state mutation, let natural EOF handle it
                self._eof = False
                self.is_seeking = True
                self._seek_target = pos
                if (target_file['file_path'].lower().endswith('.mp3')
                        and abs(local_pos - ((self._cached_time_pos or 0.0) - self._file_offset)) > _MP3_SEEK_THRESHOLD
                        and os.path.getsize(target_file['file_path']) > _VT_MP3_SIZE_THRESHOLD
                        and 2.0 < local_pos < target_file['duration'] - 5.0
                        and not self._mp3_seek_reload_pending):
                    self._mp3_stop_and_load(pos, file_path=target_file['file_path'], local_pos=local_pos)
                    return
                if target_file['duration'] - local_pos < 2.0:
                    return  # too close to file end — let natural EOF handle it
                self.instance.command_async('seek', local_pos, 'absolute+exact')
            else:
                self._eof = False
                self.is_seeking = True
                self._seek_target = pos
                self._pending_local_pos = local_pos
                self._current_vt_index = target_idx
                self._file_offset = target_file['cumulative_start']
                self._is_vt_file_switch = True
                self.instance.play(target_file['file_path'])
        else:
            dur = self._cached_duration
            if dur and dur - pos < 2.0:
                return  # too close to EOF — let natural EOF handle it
            if (self._play_target is not None
                    and self._play_target.lower().endswith('.mp3')
                    and abs(pos - (self._cached_time_pos or 0.0)) > _MP3_SEEK_THRESHOLD
                    and not self._mp3_seek_reload_pending):
                self._mp3_stop_and_load(pos)
                return
            # Paused embedded-M4B seeks undershoot by ~0.37s; nudge the mpv command
            # forward to land on target. Logical state below keeps the true pos.
            seek_pos = pos
            if self._is_embedded_m4b and self._cached_pause:
                seek_pos = pos + _PAUSED_SEEK_UNDERSHOOT_COMP
                dur = self._cached_duration
                if dur and dur - seek_pos < 2.0:
                    seek_pos = pos  # don't push the compensated target into the EOF deadzone
            self.instance.command_async('seek', seek_pos, 'absolute+exact')
            self._eof = False
            self.is_seeking = True
            self._seek_target = pos
            self._cached_time_pos = pos
            if self._chapter_list:
                curr = 0
                for i, chap in enumerate(self._chapter_list):
                    if chap.get('time', 0) <= pos + _CHAPTER_WALK_TOLERANCE:
                        curr = i
                if curr != self._last_nonvt_chapter:
                    self._last_nonvt_chapter = curr
                    self.chapter_changed.emit(curr)

    @property
    def is_seeking(self): return self._is_seeking
    @is_seeking.setter
    def is_seeking(self, val): self._is_seeking = val

    @property
    def mp3_seek_visual_lock(self) -> bool:
        return self._mp3_seek_visual_lock

    @property
    def mp3_seek_reload_pending(self) -> bool:
        return self._mp3_seek_reload_pending

    @property
    def duration(self):
        if self._virtual_timeline is not None:
            return self._book_duration
        return self._cached_duration
    @property
    def seekable(self): return bool(self.instance.seekable) if self.instance else False
    @property
    def chapter(self):
        if self._virtual_timeline is not None and self._chapter_list:
            pos = self.time_pos or 0.0
            curr = 0
            for i, chap in enumerate(self._chapter_list):
                if chap.get('time', 0) <= pos:
                    curr = i
            return curr
        return self.instance.chapter if self.instance else None
    @chapter.setter
    def chapter(self, value): 
        if self.instance:
            self.instance.chapter = value
            self._eof = False

    @property
    def chapters(self):
        if self._virtual_timeline is not None:
            return len(self._chapter_list) if self._chapter_list else 0
        return self.instance.chapters if self.instance else 0
    @property
    def chapter_list(self):
        if self._chapter_list is not None:
            return self._chapter_list
        return self.instance.chapter_list if self.instance else []

    def cache_chapter_list(self):
        """Snapshot instance.chapter_list into _chapter_list for embedded M4B books.
        Called once at load from app.py after mpv signals file-loaded (stable point).
        Eliminates the live C-layer read race where _sync_chapter_ui reads transiently
        inconsistent boundary data from the mpv thread during/after a seek."""
        if self._chapter_list is None and self._virtual_timeline is None and self.instance:
            raw = self.instance.chapter_list
            if raw:
                self._chapter_list = list(raw)  # snapshot — detached from mpv's memory
                self._is_embedded_m4b = True

    @property
    def speed(self): return self._cached_speed
    @speed.setter
    def speed(self, value):
        if self.instance:
            self.instance.speed = value
            self._cached_speed = value

    @property
    def volume(self): return self.instance.volume if self.instance else 100
    @volume.setter
    def volume(self, value):
        self._base_volume = value
        self._update_mpv_volume()

    def set_volume_from_slider(self, value: int):
        """Translates linear slider value (0-100) to logarithmic volume."""
        if value <= 0:
            self._base_volume = 0
        else:
            # Logarithmic scale: makes the lower end of the slider more granular
            self._base_volume = 100 * (math.log10(value) / 2.0)
        self._update_mpv_volume()

    def set_fade_ratio(self, ratio: float):
        """Applies a multiplier to the current volume (e.g., for sleep fade)."""
        self._fade_ratio = max(0.0, min(1.0, ratio))
        self._update_mpv_volume()

    def _update_mpv_volume(self):
        """Internal sync of actual engine volume."""
        if self.instance:
            self.instance.volume = self._base_volume * self._fade_ratio

    def apply_audio_processing(self, norm=False, mono=False, swap=False, balance=0.0, voice_boost=False):
        if not self.instance: return

        filters = []
        if norm:
            filters.append("dynaudnorm")

        if voice_boost:
            filters.append("equalizer=f=500:width_type=o:width=2:g=3")
            filters.append("equalizer=f=2000:width_type=o:width=2:g=5")
            filters.append("equalizer=f=4000:width_type=o:width=2:g=3")

        if mono:
            filters.append("pan=1:c0=0.5*c0+0.5*c1")
        elif swap or balance != 0.0:
            l_mul = 1.0 if balance <= 0 else max(0.0, 1.0 - balance)
            r_mul = 1.0 if balance >= 0 else max(0.0, 1.0 + balance)
            
            if swap:
                filters.append(f"pan=2:c0={r_mul:.2f}*c1:c1={l_mul:.2f}*c0")
            else:
                filters.append(f"pan=2:c0={l_mul:.2f}*c0:c1={r_mul:.2f}*c1")

        try:
            self.instance.command('af', 'clr', '')
            for f in filters:
                self.instance.command('af', 'add', f)
        except Exception as e:
            print(f"af command error: {e}")

    @property
    def eof_reached(self):
        return self._eof

    def terminate(self):
        if self.instance:
            instance = self.instance
            self.instance = None
            instance.terminate()
            instance.wait_for_shutdown()

    def _chapter_seek_offset(self) -> float:
        """Seek-side offset for a chapter-boundary target. Embedded M4B uses
        _EMBEDDED_CHAPTER_SEEK_OFFSET (mpv overshoots ~0.09s on its own, so we seek
        slightly early to land on the boundary). CUE/VT keep the legacy
        _CHAPTER_BOUNDARY_EPSILON. Embedded M4B detected via _is_embedded_m4b flag."""
        if self._is_embedded_m4b:
            return _EMBEDDED_CHAPTER_SEEK_OFFSET
        return _CHAPTER_BOUNDARY_EPSILON

    def activate_chapter_index(self, idx: int) -> float | None:
        """Navigate to chapter `idx` by seeking to its boundary. Public entry point
        for chapter-list clicks across ALL book types (embedded M4B, CUE, VT), so the
        UI does not branch on private attributes. Uses the same canonical target form
        as previous_chapter/next_chapter — `nominal + self._chapter_seek_offset()` —
        where the offset is mode-aware (embedded: -0.09 to cancel mpv's overshoot;
        VT/CUE: +_CHAPTER_BOUNDARY_EPSILON). Routing through seek_async (rather than
        the native `self.chapter = idx`) sets _seek_target, so the UI's is_seeking
        guard clears on settle and the chapter slider/labels refresh. Returns the
        seek target, or None if idx is out of range."""
        chaps = self.chapter_list or []
        if not (0 <= idx < len(chaps)):
            return None
        target = chaps[idx].get('time', 0.0) + self._chapter_seek_offset()
        self.seek_async(target)
        return target

    # Logical Seek helpers
    def previous_chapter(self):
        if self._virtual_timeline is not None and self._chapter_list:
            curr_time = self.time_pos or 0
            curr_chap = 0
            for i, chap in enumerate(self._chapter_list):
                if chap.get('time', 0) <= curr_time + _CHAPTER_WALK_TOLERANCE:
                    curr_chap = i
            chap_start = self._chapter_list[curr_chap].get('time', 0)
            # In the FIRST chapter there is no "previous chapter" to step back to, so the
            # 2s restart-vs-previous threshold does not apply: Prev always rewinds to the
            # book start (0:00). Without this, sitting in the first 2s of chapter 0 made
            # Prev a no-op, leaving 0:01 awkward to clear to 0:00.
            if curr_chap == 0:
                self.seek_async(0.0)
                return 0.0
            threshold = 2.0 * (self.speed or 1.0)
            if curr_time < chap_start + threshold:
                target = self._chapter_list[curr_chap - 1].get('time', 0) + _CHAPTER_BOUNDARY_EPSILON
                self.seek_async(target)
                return target
            else:
                self.seek_async(chap_start)
                return chap_start
        else:
            curr_time = self.time_pos or 0
            chap_list = self.chapter_list or []
            curr_chap = 0
            for i, chap in enumerate(chap_list):
                if chap.get('time', 0) <= curr_time + _CHAPTER_WALK_TOLERANCE:
                    curr_chap = i
            chap_start = chap_list[curr_chap].get('time', 0) if chap_list and curr_chap < len(chap_list) else 0
            # First chapter: no previous chapter, so the 2s threshold doesn't apply —
            # Prev always rewinds to the book start (0:00). (See VT branch above.)
            if curr_chap == 0:
                self.seek_async(0.0)
                return 0.0
            threshold = 2.0 * (self.speed or 1.0)
            if curr_time < chap_start + threshold:
                nominal = chap_list[curr_chap - 1].get('time', 0)
                target = nominal + self._chapter_seek_offset()
                self.seek_async(target)
                return target
            else:
                target = chap_start + self._chapter_seek_offset()
                self.seek_async(target)
                return target

    def next_chapter(self):
        if self._eof:
            return
        if self._virtual_timeline is not None and self._chapter_list:
            curr_time = self.time_pos or 0
            curr_chap = 0
            for i, chap in enumerate(self._chapter_list):
                if chap.get('time', 0) <= curr_time + _CHAPTER_WALK_TOLERANCE:
                    curr_chap = i
            if curr_chap >= len(self._chapter_list) - 1:
                return
            target = self._chapter_list[curr_chap + 1].get('time', 0) + _CHAPTER_BOUNDARY_EPSILON
            self.seek_async(target)
            return target
        else:
            chap_list = self.chapter_list or []
            curr_time = self.time_pos or 0
            curr_chap = 0
            for i, chap in enumerate(chap_list):
                if chap.get('time', 0) <= curr_time + _CHAPTER_WALK_TOLERANCE:
                    curr_chap = i
            if not chap_list or curr_chap >= len(chap_list) - 1:
                return
            next_chap = curr_chap + 1
            nominal = chap_list[next_chap].get('time', 0)
            target = nominal + self._chapter_seek_offset()
            self.seek_async(target)
            return target

    def seek_within_chapter(self, fraction: float):
        """
        Seeks to a position within the current chapter.
        fraction is 0.0-1.0.
        """
        if not self.instance or not self.duration:
            return

        if self._virtual_timeline is not None and self._chapter_list:
            curr_time = self.time_pos or 0
            curr_chap = 0
            for i, chap in enumerate(self._chapter_list):
                if chap.get('time', 0) <= curr_time + _CHAPTER_WALK_TOLERANCE:
                    curr_chap = i
            dur = self.duration
            start = self._chapter_list[curr_chap].get('time', 0)
            end = self._chapter_list[curr_chap + 1].get('time', dur) if curr_chap + 1 < len(self._chapter_list) else dur
            chap_dur = end - start
            if chap_dur > 0:
                new_pos = start + fraction * chap_dur
                self.seek_async(new_pos)
                return new_pos
        else:
            curr_time = self.time_pos or 0
            chap_list = self.chapter_list or []
            curr_chap = 0
            for i, chap in enumerate(chap_list):
                if chap.get('time', 0) <= curr_time + _CHAPTER_WALK_TOLERANCE:
                    curr_chap = i
            if chap_list and curr_chap < len(chap_list):
                dur = self.duration
                start = chap_list[curr_chap].get('time', 0)
                end = chap_list[curr_chap + 1].get('time', dur) if curr_chap + 1 < len(chap_list) else dur
                chap_dur = end - start
                if chap_dur > 0:
                    new_pos = start + fraction * chap_dur
                    self.seek_async(new_pos)
                    return new_pos

    def apply_smart_rewind(self, last_pause_ts: float, wait_min: int, rewind_sec: int):
        """
        Calculates and applies smart rewind logic.
        Rewinds based on how long the user was away.
        """
        if not self.instance or not last_pause_ts or wait_min <= 0 or rewind_sec <= 0:
            return

        away_duration = time.time() - last_pause_ts
        if away_duration >= (wait_min * 60):
            speed = self.speed or 1.0
            rewind_amt = rewind_sec * speed
            
            # Respect chapter boundaries
            start_limit = 0
            curr_idx = self.chapter
            chaps = self.chapter_list
            if curr_idx is not None and chaps and curr_idx < len(chaps):
                start_limit = chaps[curr_idx].get('time', 0)
                
            new_pos = max(start_limit, (self.time_pos or 0) - rewind_amt)
            self.seek_async(new_pos)
            # is_seeking is set True inside seek_async already

    def save_seek_position(self, old_pos: float, duration_limit: int) -> bool:
        """
        Saves the current position as an undo point if conditions are met.
        Returns True if an undo point was set/updated.
        """
        if duration_limit == 0: return False
        now = time.time()
        if self._undo_pos is None or (now - self._last_undo_click_time > duration_limit):
            self._undo_pos = old_pos
        self._last_undo_click_time = now
        return True

    def undo_seek(self):
        """Seeks back to the last saved undo position."""
        if self.instance and self._undo_pos is not None:
            self.seek_async(self._undo_pos)
            self._undo_pos = None # Clear after use