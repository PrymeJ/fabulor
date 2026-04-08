import os
import mutagen
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QThread
from ..db import LibraryDB

class ScannerWorker(QObject):
    progress = Signal(int, int) # processed, total
    finished = Signal(int)      # total_processed
    
    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self._is_running = True

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
        
        # Phase 2: Metadata Extraction
        for book_dir in book_dirs:
            if not self._is_running: break
            
            try:
                metadata = self._extract_metadata(book_dir, audio_exts)
                db.upsert_book(metadata)
            except Exception as e:
                print(f"Error scanning {book_dir}: {e}")
            
            processed += 1
            self.progress.emit(processed, total)
            
        self.finished.emit(processed)

    def _extract_metadata(self, book_dir, extensions):
        duration = 0.0
        narrator = ""
        tag_title = None
        tag_author = None
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
                    for tag in ['TXXX:narrator', 'composer', 'writer', '\xa9nrt']:
                        if tag in m.tags:
                            narrator = str(m.tags[tag][0])
                            break
                    
                    # Attempt to extract title and author from tags
                    # M4B/MP4 keys: \xa9nam (title), \xa9ART (author)
                    # MP3/ID3 keys: TIT2 (title), TPE1 (author)
                    if '\xa9nam' in m.tags: tag_title = str(m.tags['\xa9nam'][0])
                    elif 'TIT2' in m.tags: tag_title = str(m.tags['TIT2'])

                    if '\xa9ART' in m.tags: tag_author = str(m.tags['\xa9ART'][0])
                    elif 'TPE1' in m.tags: tag_author = str(m.tags['TPE1'])
            except:
                continue

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
            "path": str(book_dir), "title": title, "author": author,
            "narrator": narrator, "duration": duration, "cover_path": cover_path
        }

class LibraryScanner(QObject):
    progress = Signal(int, int)
    finished = Signal(int)

    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self._worker_thread = None

    def start(self):
        self._worker_thread = QThread()
        self.worker = ScannerWorker(self.db_path)
        self.worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self.worker.run_scan)
        self.worker.progress.connect(self.progress.emit)
        self.worker.finished.connect(self.finished.emit)
        self.worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.start()