import locale
import os
from PySide6.QtCore import QObject, Signal
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
    
    def _on_end_file(self, event):
        print(f"end-file fired")
        if not self._eof:
            self._eof = True

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
        if self.instance: self.instance.volume = value

    @property
    def eof_reached(self):
        return self._eof

    def terminate(self):
        if self.instance:
            self.instance.terminate()
            self.instance = None

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