import os
import random
from PySide6.QtCore import QObject, QTimer
from .book_quotes import BOOK_QUOTES

class LibraryController(QObject):
    """Handles library scanning, folder management, and idle UI states."""
    def __init__(self, db, config, scanner, quote_timer,
                 get_current_file_cb, on_book_removed_cb, set_interface_visible_cb,
                 update_folder_list_cb, get_selected_folder_cb, refresh_library_panel_cb,
                 set_status_cb, set_metadata_cb, set_idle_prompts_cb, set_quote_cb,
                 pick_folder_cb):
        super().__init__()
        self.db = db
        self.config = config
        self.scanner = scanner
        self.quote_timer = quote_timer
        
        # Functional UI Callbacks
        self.get_current_file = get_current_file_cb
        self.on_book_removed = on_book_removed_cb
        self.set_interface_visible = set_interface_visible_cb
        self.update_folder_list_ui = update_folder_list_cb
        self.get_selected_folder_ui = get_selected_folder_cb
        self.refresh_library_panel_ui = refresh_library_panel_cb
        self.set_status_ui = set_status_cb
        self.set_metadata_ui = set_metadata_cb
        self.set_idle_prompts_ui = set_idle_prompts_cb
        self.set_quote_ui = set_quote_cb
        self.pick_folder_ui = pick_folder_cb

    def _refresh_folder_list(self):
        """Updates the folder list widget with current scan locations."""
        locs = self.db.get_scan_locations()
        self.update_folder_list_ui(locs)

    def _on_remove_folder_clicked(self):
        """Removes the selected folder from the database and updates UI."""
        path = self.get_selected_folder_ui()
        if path:
            self.db.remove_scan_location(path)
            
            # Unload the book if it was inside the removed library folder
            current_file = self.get_current_file()
            path_p = path if path.endswith(os.sep) else path + os.sep
            if current_file and current_file.startswith(path_p):
                self.on_book_removed()

            self._refresh_folder_list()
            self._check_library_status(manual=True)
            self.refresh_library_panel_ui(force=True)

    def _on_scan_now_clicked(self):
        """Triggers a folder picker and starts scanning."""
        folder = self.pick_folder_ui()
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
        self.set_status_ui("Scan cancelled.", show_banner=True, show_cancel=False)

    def _on_scan_progress(self, current, total):
        """Updates the status banner with scan progress."""
        # Logic for banner updates is now handled by the callback which checks visibility
        self.set_status_ui(f"Loading Library... ({current}/{total})", 
                          show_banner=None, show_cancel=None)
        
        if current == 1:
            self._check_library_status()

    def _on_scan_finished(self, total):
        """Finalizes scan and hides banner."""
        self.set_status_ui(f"Library updated: {total} books.", 
                          show_banner=None, show_cancel=False, auto_hide=True)
        
        self.refresh_library_panel_ui(force=True)
        self._refresh_folder_list()

    def _check_library_status(self, manual=False, force_refresh=False):
        """Determines if the UI should show library prompts or the player interface."""
        locs = self.db.get_scan_locations()
        has_locations = len(locs) > 0
        has_indexed_books = self.db.get_book_count() > 0
        has_book = bool(self.get_current_file())

        self.set_interface_visible(has_book)

        if not has_locations or not has_indexed_books:
            self.quote_timer.start(60000)
            self._rotate_quote()
            self.set_idle_prompts_ui(True)
            self.set_status_ui(None, show_banner=True, show_cancel=None)
            self.set_metadata_ui(None, show_metadata=False, show_go_to_lib=False)
        else:
            self.set_idle_prompts_ui(False)
            self.set_quote_ui(None, show_quote=False)
            self.quote_timer.stop()
            
            if not has_book:
                self.set_metadata_ui("No book selected.", show_metadata=True, show_go_to_lib=True)
            else:
                self.set_metadata_ui(None, show_metadata=False, show_go_to_lib=False)

        if has_locations:
            if not self.scanner._worker_thread or not self.scanner._worker_thread.isRunning():
                if manual or force_refresh or not has_indexed_books:
                    self.set_status_ui("Forcing deep scan..." if force_refresh else "Library scanning...", 
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
            self.set_quote_ui(styled_quote, show_quote=True)