import locale
import math
import os
import time
import warnings
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QPixmap

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

# Tolerance added to time_pos when walking chapter_list to find the current
# chapter, and as a seek epsilon when targeting a chapter boundary. M4B chapter
# metadata floats land ~0.25s short of nominal values; seeks undershoot by one
# AAC frame (~23ms). 0.35s clears both with margin. If a format with worse
# drift appears, change this one constant — it appears in previous_chapter(),
# the VT chapter walk in _on_time_pos_change, and _sync_chapter_ui in app.py.
_CHAPTER_BOUNDARY_EPSILON = 0.35

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
        self._paused_time = None # For UI deadzone logic
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
                vo='null', ao='pulse', vid=False, ytdl=False, keep_open='always'
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
        if self._is_seeking and value is not None:
            global_value = value + (self._file_offset or 0)
            if self._seek_target is None or abs(global_value - self._seek_target) < 1.0:
                self._is_seeking = False
                self._seek_target = None
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
        # Non-VT: self._chapter_list is None — chapter data lives in mpv's native list.
        # self.chapter_list (property) abstracts over both cases: returns self._chapter_list
        # for VT books, falls back to self.instance.chapter_list for non-VT. The
        # inconsistency with the VT branch above is intentional.
        elif self.chapter_list and value is not None:
            curr = 0
            for i, chap in enumerate(self.chapter_list):
                if chap.get('time', 0) <= value + _CHAPTER_BOUNDARY_EPSILON:
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
                play_target, chapters_file = player._resolve_playlist(path)
                player._playlist_resolved.emit(play_target, chapters_file or "")

        # Reset virtual timeline state for new book
        self._virtual_timeline = None
        self._file_offset = 0.0
        self._book_duration = None
        self._chapter_list = None
        self._current_vt_index = 0
        self._pending_local_pos = None
        self._is_vt_file_switch = False
        self._last_vt_chapter = -1
        self._last_nonvt_chapter = -1
        # Clear cached mpv state so stale values from previous book can't leak
        # into saves before the new book's file is loaded.
        self._cached_time_pos = None
        self._cached_duration = None

        QThreadPool.globalInstance().start(_ResolveWorker())

    def _on_playlist_resolved(self, play_target, chapters_file):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                self._playlist_resolved.disconnect(self._on_playlist_resolved)
            except RuntimeError:
                pass
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
        if value is not None:
            if self._virtual_timeline is not None:
                return
            if self._chapter_list is not None:  # cue mode
                return
            if self._is_seeking:
                return
            self.chapter_changed.emit(int(value))
    def _on_file_loaded(self, event):
        if self._pending_local_pos is not None:
            pending = self._pending_local_pos
            self._pending_local_pos = None
            self._seek_target = pending
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

    def seek_async(self, pos: float) -> None:
        """Non-blocking seek. For virtual timeline books, resolves file and local offset."""
        if not self.instance:
            return
        if self._virtual_timeline is not None:
            target_idx = self._resolve_vt_index(pos)
            target_file = self._virtual_timeline[target_idx]
            local_pos = pos - target_file['cumulative_start']
            self._eof = False
            self.is_seeking = True
            self._seek_target = pos
            if target_idx == self._current_vt_index:
                self.instance.command_async('seek', local_pos, 'absolute+exact')
            else:
                self._pending_local_pos = local_pos
                self._current_vt_index = target_idx
                self._file_offset = target_file['cumulative_start']
                self._is_vt_file_switch = True
                self.instance.play(target_file['file_path'])
        else:
            self.instance.command_async('seek', pos, 'absolute+exact')
            self._eof = False
            self.is_seeking = True
            self._seek_target = pos
            self._cached_time_pos = pos
            if self._chapter_list:
                curr = 0
                for i, chap in enumerate(self._chapter_list):
                    if chap.get('time', 0) <= pos + _CHAPTER_BOUNDARY_EPSILON:
                        curr = i
                if curr != self._last_nonvt_chapter:
                    self._last_nonvt_chapter = curr
                    self.chapter_changed.emit(curr)

    @property
    def is_seeking(self): return self._is_seeking
    @is_seeking.setter
    def is_seeking(self, val): self._is_seeking = val

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

    def get_stable_position(self):
        """Handles 'deadzone' logic during pause/seek to prevent jitter in UI labels."""
        mpv_pos = self.time_pos
        if mpv_pos is None: return 0

        if self.pause:
            # Only update display if we are seeking or the change is significant (>1s)
            if self._paused_time is None or self._is_seeking or abs(mpv_pos - self._paused_time) > 1.0:
                self._paused_time = mpv_pos
                self._is_seeking = False
            return self._paused_time

        self._paused_time = None
        return mpv_pos

    # Logical Seek helpers
    def previous_chapter(self):
        if self._virtual_timeline is not None and self._chapter_list:
            curr_time = self.time_pos or 0
            curr_chap = 0
            for i, chap in enumerate(self._chapter_list):
                if chap.get('time', 0) <= curr_time + _CHAPTER_BOUNDARY_EPSILON:
                    curr_chap = i
            chap_start = self._chapter_list[curr_chap].get('time', 0)
            threshold = 2.0 * (self.speed or 1.0)
            if curr_time < chap_start + threshold:
                if curr_chap > 0:
                    target = self._chapter_list[curr_chap - 1].get('time', 0) + _CHAPTER_BOUNDARY_EPSILON
                    self.seek_async(target)
                    return target
            else:
                self.seek_async(chap_start)
                return chap_start
            return curr_time
        else:
            curr_time = self.time_pos or 0
            chap_list = self.chapter_list or []
            curr_chap = 0
            for i, chap in enumerate(chap_list):
                if chap.get('time', 0) <= curr_time + _CHAPTER_BOUNDARY_EPSILON:
                    curr_chap = i
            chap_start = chap_list[curr_chap].get('time', 0) if chap_list and curr_chap < len(chap_list) else 0
            threshold = 2.0 * (self.speed or 1.0)
            if curr_time < chap_start + threshold:
                if curr_chap > 0:
                    target = chap_list[curr_chap - 1].get('time', 0) + _CHAPTER_BOUNDARY_EPSILON
                    self.seek_async(target)
                    return target
            else:
                target = chap_start + _CHAPTER_BOUNDARY_EPSILON
                self.seek_async(target)
                return target

    def next_chapter(self):
        if self._virtual_timeline is not None and self._chapter_list:
            curr_time = self.time_pos or 0
            curr_chap = 0
            for i, chap in enumerate(self._chapter_list):
                if chap.get('time', 0) <= curr_time + _CHAPTER_BOUNDARY_EPSILON:
                    curr_chap = i
            next_chap = curr_chap + 1
            if next_chap < len(self._chapter_list):
                target = self._chapter_list[next_chap].get('time', 0)
                self.seek_async(target)
                return target
            else:
                target = self._book_duration or self.duration or 0
                self.seek_async(target)
                return target
        else:
            chap_list = self.chapter_list or []
            curr_time = self.time_pos or 0
            curr_chap = 0
            for i, chap in enumerate(chap_list):
                if chap.get('time', 0) <= curr_time + _CHAPTER_BOUNDARY_EPSILON:
                    curr_chap = i
            next_chap = curr_chap + 1
            if next_chap < len(chap_list):
                target = chap_list[next_chap].get('time', 0) + _CHAPTER_BOUNDARY_EPSILON
                self.seek_async(target)
                return target
            else:
                target = self._book_duration or self.duration or 0
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
                if chap.get('time', 0) <= curr_time + _CHAPTER_BOUNDARY_EPSILON:
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
                if chap.get('time', 0) <= curr_time + _CHAPTER_BOUNDARY_EPSILON:
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
            if self._virtual_timeline is not None:
                self.seek_async(new_pos)
            else:
                self.time_pos = new_pos
            self.is_seeking = True

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