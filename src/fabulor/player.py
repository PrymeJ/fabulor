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

    def __init__(self):
        super().__init__()
        self.instance = None  # deferred

    def _ensure_mpv(self):
        if self.instance is None:
            locale.setlocale(locale.LC_NUMERIC, "C")
            self.instance = MPV(
                vo='null',
                ao='pulse',
                vid=False,
                ytdl=False,
                keep_open=True
            )
            self.instance.observe_property('chapter', self._on_chapter_change)

    def load_book(self, path, start_paused=True):
        self._ensure_mpv()
        self.instance.play(path)
        if start_paused:
            self.instance.pause = True
        

    def _on_chapter_change(self, name, value):
        if value is not None:
            self.chapter_changed.emit(int(value))

    def extract_cover(self, file_path):
        """Extracts cover art from file tags."""
        if not mutagen:
            return QPixmap()

        pixmap = QPixmap()
        try:
            audio = mutagen.File(file_path)
            if audio and audio.tags:
                if 'covr' in audio.tags:
                    data = audio.tags['covr'][0]
                    pixmap.loadFromData(data)
                elif 'APIC:' in audio.tags:
                    data = audio.tags['APIC:'].data
                    pixmap.loadFromData(data)
        except Exception as e:
            print(f"Metadata extraction error: {e}")
        return pixmap

    # Playback Control Proxies
    @property
    def pause(self): return self.instance.pause
    @pause.setter
    def pause(self, value): self.instance.pause = value

    @property
    def time_pos(self): return self.instance.time_pos
    @time_pos.setter
    def time_pos(self, value): self.instance.time_pos = value

    @property
    def duration(self): return self.instance.duration
    @property
    def chapter(self): return self.instance.chapter
    @chapter.setter
    def chapter(self, value): self.instance.chapter = value

    @property
    def chapters(self): return self.instance.chapters
    @property
    def chapter_list(self): return self.instance.chapter_list
    
    @property
    def speed(self): return self.instance.speed
    @speed.setter
    def speed(self, value): self.instance.speed = value

    @property
    def volume(self): return self.instance.volume
    @volume.setter
    def volume(self, value): self.instance.volume = value

    @property
    def eof_reached(self): return getattr(self.instance, 'eof_reached', False)

    def terminate(self):
        self.instance.terminate()

    # Logical Seek helpers
    def previous_chapter(self):
        curr_time = self.time_pos or 0
        curr_chap = self.chapter or 0
        chap_list = self.chapter_list or []
        chap_start = chap_list[curr_chap].get('time', 0) if chap_list and curr_chap < len(chap_list) else 0

        if curr_time < chap_start + 2.0:
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