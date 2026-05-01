import locale
import os
import math
from PySide6.QtCore import QObject, Signal
import time
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

class Player(QObject):
    chapter_changed = Signal(int)
    file_loaded = Signal()

    def __init__(self):
        super().__init__()
        self.instance = None  # deferred
        self._eof = False
        self._paused_time = None # For UI deadzone logic
        self._is_seeking = False # For UI deadzone logic
        self._undo_pos = None # For undo seek logic
        self._last_undo_click_time = 0 # For undo seek logic
        self._base_volume = 100.0 # User's set volume (log scale)
        self._fade_ratio = 1.0   # Sleep timer fade (0.0 to 1.0)

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
            self.instance.event_callback('file-loaded')(self._on_file_loaded)

    def _on_pause_test(self, name, value):
        if value:
            pos = self.instance.time_pos
            dur = self.instance.duration
            if pos is not None and dur is not None and pos >= dur - 1.5:
                self._eof = True

    def load_book(self, path, start_paused=True):
        self._ensure_mpv()
        self._eof = False
        self.instance.play(path)
        if start_paused:
            self.instance.pause = True
        

    def _on_chapter_change(self, name, value):
        if value is not None:
            self.chapter_changed.emit(int(value))

    def _on_file_loaded(self, event):
        self.file_loaded.emit()

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
    def pause(self): return self.instance.pause if self.instance else True
    @pause.setter
    def pause(self, value): 
        if self.instance: self.instance.pause = value

    @property
    def time_pos(self): return self.instance.time_pos if self.instance else None
    @time_pos.setter
    def time_pos(self, value):
        if self.instance:
            self.instance.time_pos = value
            self._eof = False

    @property
    def is_seeking(self): return self._is_seeking
    @is_seeking.setter
    def is_seeking(self, val): self._is_seeking = val

    @property
    def duration(self): return self.instance.duration if self.instance else None
    @property
    def chapter(self): return self.instance.chapter if self.instance else None
    @chapter.setter
    def chapter(self, value): 
        if self.instance:
            self.instance.chapter = value
            self._eof = False

    @property
    def chapters(self): return self.instance.chapters if self.instance else 0
    @property
    def chapter_list(self): return self.instance.chapter_list if self.instance else []
    
    @property
    def speed(self): return self.instance.speed if self.instance else 1.0
    @speed.setter
    def speed(self, value): 
        if self.instance: self.instance.speed = value

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
            self.instance.terminate()
            self.instance = None

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
        curr_time = self.time_pos or 0
        curr_chap = self.chapter or 0
        chap_list = self.chapter_list or []
        chap_start = chap_list[curr_chap].get('time', 0) if chap_list and curr_chap < len(chap_list) else 0

        # Dynamic threshold: scale the 2s grace period by playback speed
        threshold = 2.0 * (self.speed or 1.0)
        if curr_time < chap_start + threshold:
            if curr_chap > 0:
                self.chapter = curr_chap - 1
        else:
            self.time_pos = chap_start

    def next_chapter(self):
        curr_chap = self.chapter or 0
        total_chaps = self.chapters or 0
        if curr_chap < total_chaps - 1:
            self.chapter = curr_chap + 1
        elif self.duration:
            self.time_pos = self.duration

    def seek_within_chapter(self, fraction: float):
        """
        Seeks to a position within the current chapter.
        fraction is 0.0-1.0.
        """
        if not self.instance or not self.duration:
            return

        curr_chap = self.chapter or 0
        chap_list = self.chapter_list or []
        if chap_list and curr_chap < len(chap_list):
            dur = self.duration
            start = chap_list[curr_chap].get('time', 0)
            end = chap_list[curr_chap+1].get('time', dur) if curr_chap + 1 < len(chap_list) else dur
            chap_dur = end - start
            if chap_dur > 0:
                new_chap_pos = fraction * chap_dur
                new_pos = start + new_chap_pos
                self.time_pos = new_pos
                self.is_seeking = True

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
                
            self.time_pos = max(start_limit, (self.time_pos or 0) - rewind_amt)
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
            self.time_pos = self._undo_pos
            self.is_seeking = True
            self._undo_pos = None # Clear after use