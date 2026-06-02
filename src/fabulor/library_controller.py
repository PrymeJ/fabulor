import os
import random
from PySide6.QtCore import QObject
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
        self.scanner.stop()
        path = self.browser.get_selected_folder()
        if path:
            self.db.remove_scan_location(path)

            # Unload the book if it was inside the removed folder, OR if no library
            # folders remain at all (the loaded book is now unreachable regardless of
            # whether its specific folder matched). Unload must precede the state apply.
            current_file = self.app.get_current_file()
            path_p = path if path.endswith(os.sep) else path + os.sep
            no_folders_left = len(self.db.get_scan_locations()) == 0
            if current_file and (current_file.startswith(path_p) or no_folders_left):
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
        self.ui.set_scan_buttons_enabled(True)
        self.ui.update_status("Scan cancelled.", show_banner=True, show_cancel=False)

    def _on_scan_progress(self, current, total):
        """Updates the status banner with scan progress."""
        # Logic for banner updates is now handled by the callback which checks visibility
        self.ui.update_status(f"Loading library... ({current}/{total})", 
                             show_banner=None, show_cancel=None)
        
        if current == 1:
            self._check_library_status()

    def _on_scan_finished(self, total):
        """Finalizes scan and hides banner."""
        self.ui.set_scan_buttons_enabled(True)
        self.ui.update_status(f"Library updated: {total} books.",
                             show_banner=None, show_cancel=False, auto_hide=True)
        self.apply_current_state()
        self.ui.refresh_panel(force=True)
        self.app.refresh_tag_manager()
        self.app.refresh_stats()
        self._refresh_folder_list()

        # Refresh player cover after scan — ensures the active book_covers entry
        # is used, not a stale cache entry from before the scan.
        current = self.app.get_current_file()
        if current:
            self.app.load_cover_art(current)

    def compute_library_state(self):
        """Computes the current logical state of the library."""
        locs = self.db.get_scan_locations()
        has_locations = len(locs) > 0
        has_indexed_books = self.db.get_book_count() > 0
        has_book = bool(self.app.get_current_file())

        if not has_locations or not has_indexed_books:
            mode = "empty"
        elif self.scanner.is_running():
            mode = "scanning"
        else:
            mode = "ready"

        return {
            "mode": mode,
            "has_book": has_book,
            "has_locations": has_locations,
            "has_indexed_books": has_indexed_books
        }

    def apply_library_state(self, state):
        """Updates the UI components based on the provided state object."""
        self.ui.set_visible(state["has_book"])

        if state["mode"] == "empty":
            self.ui.set_visible(False)  # empty state never coexists with player chrome
            self.ui.hide_carousel()
            self.ui.set_quote_rotation(True)
            self._rotate_quote()
            self.ui.update_prompts(True)
            # Clear any stale banner (e.g. "Library updated: N books.") left over
            # from a prior scan when all folders are removed.
            self.ui.update_status("", show_banner=False, show_cancel=False)
            self.ui.update_metadata(None, show_metadata=False, show_go_to_lib=False)
        else:
            self.ui.update_prompts(False)
            self.ui.update_quote(None, show_quote=False)
            self.ui.set_quote_rotation(False)

            if not state["has_book"]:
                self.ui.update_metadata(None, show_metadata=False, show_go_to_lib=True)
                # Ambient cover carousel — reshuffled on each no-book entry.
                self.ui.show_carousel()
            else:
                # Leave metadata_label visibility to _load_cover_art — it controls
                # whether to show "author - title" when no cover exists.
                self.ui.update_metadata(None, show_go_to_lib=False)
                self.ui.hide_carousel()

    def handle_background_tasks(self, state, manual=False, force_refresh=False):
        """Triggers scans based on current mode and location status."""
        if state["mode"] != "scanning" and state["has_locations"]:
            if manual or force_refresh or not state["has_indexed_books"]:
                msg = "Forcing deep scan..." if force_refresh else "Library scanning..."
                self.ui.update_status(msg, show_banner=True, show_cancel=True)
            self.ui.set_scan_buttons_enabled(False)
            self.scanner.start(force_refresh=force_refresh)

    def apply_current_state(self):
        """Compute and apply library UI state. No background-task/scan side effects.
        Returns the computed state so callers that also need it (e.g. background
        task scheduling) can reuse it without recomputing."""
        state = self.compute_library_state()
        self.apply_library_state(state)
        return state

    def _check_library_status(self, manual=False, force_refresh=False):
        """Main entry point for verifying library health and starting scans."""
        state = self.apply_current_state()
        self.handle_background_tasks(state, manual, force_refresh)

    def _rotate_quote(self):
        """Update metadata label with a random quote when idle."""
        if not self.db.get_scan_locations():
            text, title, text_size, title_size, color, text_align = random.choice(BOOK_QUOTES)
            styled_quote = (
                f"<div style='font-size: {text_size}px; color: {color}; text-align: {text_align}; width: 100%;'>{text}</div>"
                f"<div style='text-align: right; font-size: {title_size}px; color: #ddd;'><br>{title}</div>"
            )
            self.ui.update_quote(styled_quote, show_quote=True)