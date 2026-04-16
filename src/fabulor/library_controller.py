import os
import random
from PySide6.QtCore import QObject, QTimer
from .book_quotes import BOOK_QUOTES

class LibraryController(QObject):
    """Handles library scanning, folder management, and idle UI states."""
    def __init__(self, db, config, scanner, ui, app, browser):
        super().__init__()
        self.db = db
        self.config = config
        self.scanner = scanner

        # Grouped Interfaces
        self.ui = ui
        self.app = app
        self.browser = browser

    def _refresh_folder_list(self):
        """Updates the folder list widget with current scan locations."""
        locs = self.db.get_scan_locations()
        self.ui.update_folders(locs)

    def _on_remove_folder_clicked(self):
        """Removes the selected folder from the database and updates UI."""
        path = self.browser.get_selected_folder()
        if path:
            self.db.remove_scan_location(path)
            
            # Unload the book if it was inside the removed library folder
            current_file = self.app.get_current_file()
            path_p = path if path.endswith(os.sep) else path + os.sep
            if current_file and current_file.startswith(path_p):
                self.app.on_book_removed()

            self._refresh_folder_list()
            self._check_library_status(manual=True)
            self.ui.refresh_panel(force=True)

    def _on_scan_now_clicked(self):
        """Triggers a folder picker and starts scanning."""
        folder = self.browser.pick_folder()
        if folder:
            new_path = os.path.abspath(folder)
            existing = self.db.get_scan_locations()
            
            # Redundancy logic
            is_redundant = False
            for loc in existing:
                loc_p = loc if loc.endswith(os.sep) else loc + os.sep
                new_p = new_path if new_path.endswith(os.sep) else new_path + os.sep
                
                if new_p.startswith(loc_p): 
                    is_redundant = True
                    break
                if loc_p.startswith(new_p):
                    self.db.remove_scan_location(loc)
            
            if not is_redundant:
                self.scanner.stop()
                self.db.add_scan_location(new_path)
                self._check_library_status(manual=True)
                self._refresh_folder_list()

    def _on_cancel_scan_clicked(self):
        """Stops the current scan."""
        self.scanner.stop()
        self.ui.update_status("Scan cancelled.", show_banner=True, show_cancel=False)

    def _on_scan_progress(self, current, total):
        """Updates the status banner with scan progress."""
        # Logic for banner updates is now handled by the callback which checks visibility
        self.ui.update_status(f"Loading Library... ({current}/{total})", 
                             show_banner=None, show_cancel=None)
        
        if current == 1:
            self._check_library_status()

    def _on_scan_finished(self, total):
        """Finalizes scan and hides banner."""
        self.ui.update_status(f"Library updated: {total} books.", 
                             show_banner=None, show_cancel=False, auto_hide=True)
        
        self.ui.refresh_panel(force=True)
        self._refresh_folder_list()

    def _check_library_status(self, manual=False, force_refresh=False):
        """Determines if the UI should show library prompts or the player interface."""
        locs = self.db.get_scan_locations()
        has_locations = len(locs) > 0
        has_indexed_books = self.db.get_book_count() > 0
        has_book = bool(self.app.get_current_file())

        self.ui.set_visible(has_book)

        if not has_locations or not has_indexed_books:
            self.app.quote_timer.start(60000)
            self._rotate_quote()
            self.ui.update_prompts(True)
            self.ui.update_status(None, show_banner=True, show_cancel=None)
            self.ui.update_metadata(None, show_metadata=False, show_go_to_lib=False)
        else:
            self.ui.update_prompts(False)
            self.ui.update_quote(None, show_quote=False)
            self.app.quote_timer.stop()
            
            if not has_book:
                self.ui.update_metadata("No book selected.", show_metadata=True, show_go_to_lib=True)
            else:
                self.ui.update_metadata(None, show_metadata=False, show_go_to_lib=False)

        if has_locations:
            if not self.app.is_running():
                if manual or force_refresh or not has_indexed_books:
                    self.ui.update_status("Forcing deep scan..." if force_refresh else "Library scanning...", 
                                         show_banner=True, show_cancel=True)
                
                self.scanner.start(force_refresh=force_refresh)

    def _rotate_quote(self):
        """Update metadata label with a random quote when idle."""
        if not self.db.get_scan_locations():
            text, title, text_size, title_size, color, text_align = random.choice(BOOK_QUOTES)
            styled_quote = (
                f"<div style='font-size: {text_size}px; color: {color}; text-align: {text_align}; width: 100%;'>{text}</div>"
                f"<div style='text-align: right; font-size: {title_size}px; color: #ddd;'><br>{title}</div>"
            )
            self.ui.update_quote(styled_quote, show_quote=True)