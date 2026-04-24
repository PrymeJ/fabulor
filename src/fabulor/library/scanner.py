import os
import re
import hashlib
import platformdirs
import mutagen
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QThread, Qt
from PySide6.QtGui import QImage
from ..db import LibraryDB

class ScannerWorker(QObject):
    progress = Signal(int, int) # processed, total
    finished = Signal(int)      # total_processed
    
    def __init__(self, db_path, force_refresh=False):
        super().__init__()
        self.db_path = db_path
        self._is_running = True
        self.force_refresh = force_refresh

    def stop(self):
        self._is_running = False

    def run_scan(self):
        db = LibraryDB(self.db_path)
        locations = db.get_scan_locations()
        
        audio_exts = {'.m4b', '.mp3', '.flac', '.m4a'}
        book_dirs = []

        # Phase 1: Discovery (Folder = Book)
        for loc in locations:
            root = Path(loc)
            if not root.exists(): continue
            
            try:
                for entry in root.iterdir():
                    if not self._is_running: return
                    if entry.is_dir():
                        # Check for audio files inside
                        if any(f.suffix.lower() in audio_exts for f in entry.iterdir() if f.is_file()):
                            book_dirs.append(entry)
            except PermissionError:
                continue

        total = len(book_dirs)
        processed = 0
        
        # Optimization: Get all known paths first to avoid re-extracting tags
        known_paths = {b.path for b in db.get_all_books()}

        # Phase 2: Metadata Extraction
        for book_dir in book_dirs:
            if not self._is_running: break
            
            book_path = str(book_dir)
            if not self.force_refresh and book_path in known_paths:
                processed += 1
                self.progress.emit(processed, total)
                continue

            try:
                metadata = self._extract_metadata(book_dir, audio_exts)
                db.upsert_book(metadata)
            except Exception as e:
                print(f"Error scanning {book_dir}: {e}")
            
            processed += 1
            self.progress.emit(processed, total)
            
        self.finished.emit(processed)

    @staticmethod
    def _parse_year(val):
        if val is None:
            return None
        if isinstance(val, (list, tuple)):
            val = val[0] if val else None
        if val is None:
            return None
        if isinstance(val, (bytes, bytearray)):
            raw = val.decode('utf-8', errors='ignore')
        elif hasattr(val, 'text') and val.text:
            raw = str(val.text[0])
        else:
            raw = str(val)
        m = re.search(r'\d{4}', raw)
        if m:
            y = int(m.group())
            if 1800 <= y <= 2030:
                return y
        return None

    def _extract_metadata(self, book_dir, extensions):
        duration = 0.0
        narrator = ""
        tag_title = None
        tag_author = None
        tag_year = None
        cover_path = ""
        
        # Look for cover images
        cover_names = {'cover', 'folder', 'front', 'art'}
        for f in book_dir.iterdir():
            if f.is_file() and f.suffix.lower() in {'.jpg', '.jpeg', '.png'}:
                if f.stem.lower() in cover_names:
                    cover_path = str(f)
                    break
        
        audio_files = sorted([f for f in book_dir.iterdir() if f.suffix.lower() in extensions])
        for idx, af in enumerate(audio_files):
            try:
                m = mutagen.File(af)
                if m and m.info:
                    duration += m.info.length

                # Eagerly grab narrator from tags of the first track
                if idx == 0 and hasattr(m, 'tags') and m.tags:
                    # Check common narrator tags (m4b/mp3)
                    # Support ID3 (TCOM, TEXT) and MP4 (\xa9nrt, \xa9wrt)
                    for tag in ['TXXX:narrator', 'TCOM', 'TEXT', 'composer', 'writer', '\xa9nrt', '\xa9wrt']:
                        if tag in m.tags:
                            val = m.tags[tag]
                            if isinstance(val, (list, tuple)) and len(val) > 0:
                                narrator = str(val[0])
                            elif hasattr(val, 'text') and val.text: # ID3 frames
                                narrator = str(val.text[0])
                            else:
                                narrator = str(val)
                            break

                    # If no external cover found, check for embedded tags to use as hint
                    if not cover_path:
                        if hasattr(m, 'tags') and m.tags and ('covr' in m.tags or any(k.startswith('APIC') for k in m.tags.keys())):
                            cover_path = str(af)

                    # Attempt to extract title and author from tags
                    # M4B/MP4 keys: \xa9nam (title), \xa9ART (author)
                    # MP3/ID3 keys: TIT2 (title), TPE1 (author)
                    if '\xa9nam' in m.tags: tag_title = str(m.tags['\xa9nam'][0])
                    elif 'TIT2' in m.tags: tag_title = str(m.tags['TIT2'])

                    if '\xa9ART' in m.tags: tag_author = str(m.tags['\xa9ART'][0])
                    elif 'TPE1' in m.tags: tag_author = str(m.tags['TPE1'])

                    if tag_year is None:
                        for ytag in ['TDOR', '----:com.apple.iTunes:originaldate',
                                     '----:com.apple.iTunes:ORIGINALDATE',
                                     '\xa9day', 'originaldate', 'original_release_date',
                                     'TDRC', 'TYER', 'date']:
                            if ytag in m.tags:
                                tag_year = self._parse_year(m.tags[ytag])
                                if tag_year:
                                    break
            except:
                continue

        # Thumbnail Caching
        if cover_path:
            try:
                cache_dir = Path(platformdirs.user_cache_dir("fabulor", "fabulor")) / "thumbnails"
                cache_dir.mkdir(parents=True, exist_ok=True)

                # Unique identifier based on path hash for the cache filename
                book_id_hash = hashlib.md5(str(book_dir).encode()).hexdigest()
                thumb_path = cache_dir / f"{book_id_hash}.jpg"

                img = QImage()
                if os.path.splitext(cover_path)[1].lower() in {'.jpg', '.jpeg', '.png'}:
                    img.load(cover_path)
                else:
                    m_cover = mutagen.File(cover_path)
                    if m_cover and m_cover.tags:
                        data = None
                        if 'covr' in m_cover.tags: data = m_cover.tags['covr'][0]
                        else:
                            for key in m_cover.tags.keys():
                                if key.startswith('APIC'):
                                    data = m_cover.tags[key].data
                                    break
                        if data: img.loadFromData(data)

                if not img.isNull():
                    img = img.scaled(226, 344, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    if img.save(str(thumb_path), "JPEG"):
                        cover_path = str(thumb_path)
            except:
                pass

        # Fallback Logic: If tags are missing, parse the main folder name
        if tag_title and tag_author:
            title, author = tag_title, tag_author
        else:
            name = book_dir.name
            folder_author, folder_title = "Unknown Author", name
            if " - " in name:
                parts = name.split(" - ", 1)
                folder_author, folder_title = parts[0], parts[1]
            
            title = tag_title or folder_title
            author = tag_author or folder_author

        return {
            "path": str(book_dir), 
            "folder_name_raw": book_dir.name,
            "title": title, "author": author,
            "narrator": narrator, "duration": duration, "cover_path": cover_path,
            "year": tag_year,
        }

class LibraryScanner(QObject):
    progress = Signal(int, int)
    finished = Signal(int)

    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self._worker_thread = None
        self.worker = None

    def stop(self):
        """Signals the worker to stop and prevents new starts."""
        if self.worker:
            self.worker.stop()

    def is_running(self):
        """Returns True if the scanner's worker thread is currently active."""
        return self._worker_thread is not None and self._worker_thread.isRunning()

    def start(self, force_refresh=False):
        # Prevent multiple overlapping threads
        if self._worker_thread and self._worker_thread.isRunning():
            return

        self._worker_thread = QThread()
        self.worker = ScannerWorker(self.db_path, force_refresh=force_refresh)
        self.worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self.worker.run_scan)
        self.worker.progress.connect(self.progress.emit)
        self.worker.finished.connect(self.finished.emit)
        self.worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.start()