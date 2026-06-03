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
        """Removes all selected folders from the database and updates UI."""
        self.scanner.stop()
        paths = self.browser.get_selected_folders()
        if not paths:
            return

        current_file = self.app.get_current_file()

        # Determine upfront whether a book unload is needed, before any DB changes.
        # Unload if the current book is inside any removed folder, OR if removing all
        # selected would leave zero folders remaining.
        remaining = [loc for loc in self.db.get_scan_locations() if loc not in paths]
        no_folders_left = len(remaining) == 0
        needs_unload = False
        if current_file:
            for path in paths:
                path_p = path if path.endswith(os.sep) else path + os.sep
                if current_file.startswith(path_p):
                    needs_unload = True
                    break
            if no_folders_left:
                needs_unload = True

        for path in paths:
            self.db.remove_scan_location(path)

        if needs_unload:
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

    def _on_rescan_clicked(self):
        """Rescans selected paths, or all configured paths if none selected."""
        selected = self.browser.get_selected_folders()
        state = self.apply_current_state()
        if selected:
            self.handle_background_tasks(state, manual=True, force_refresh=True, locations=selected)
        else:
            self.handle_background_tasks(state, manual=True, force_refresh=True)

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
        QTimer.singleShot(0, self.apply_current_state)
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
        has_indexed_books = self.db.get_visible_book_count() > 0
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

        # Empty-like state covers both "no library folders" and "folders exist but
        # zero indexed audiobooks" — both warrant the scan/quote prompt rather than
        # the no-book carousel (which leads to a Library that has nothing to show).
        # Note: compute_library_state already collapses both into mode == "empty",
        # so the `not has_indexed_books` clause is currently redundant but kept as a
        # guard against future mode-logic changes.
        if state["mode"] == "empty" or not state["has_indexed_books"]:
            self.ui.set_visible(False)  # empty state never coexists with player chrome
            self.ui.set_library_btn_visible(False)  # nothing to browse — hide Library
            self.ui.hide_carousel()
            # Discriminate by has_locations: no paths vs. paths-with-no-books.
            if not state["has_locations"]:
                self.ui.set_prompt_text("No library folders.")
            elif self.scanner.is_running():
                self.ui.set_prompt_text("Scanning for audiobooks...")
            else:
                self.ui.set_prompt_text("No audiobooks in the folders added.")
            self.ui.set_quote_rotation(True)
            self._rotate_quote()
            self.ui.update_prompts(True)
            # Clear any stale banner (e.g. "Library updated: N books.") left over
            # from a prior scan when all folders are removed.
            if not state["has_locations"]:
                self.ui.update_status("", show_banner=False, show_cancel=False)
            self.ui.update_metadata(None, show_metadata=False, show_go_to_lib=False)
        else:
            self.ui.set_library_btn_visible(True)  # books indexed — Library is useful
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

    def handle_background_tasks(self, state, manual=False, force_refresh=False, locations=None):
        """Triggers scans based on current mode and location status."""
        if state["mode"] != "scanning" and state["has_locations"]:
            if manual or force_refresh or not state["has_indexed_books"]:
                if locations is not None:
                    n = len(locations)
                    msg = f"Rescanning {n} folder{'s' if n != 1 else ''}..."
                else:
                    msg = "Rescanning all folders..." if force_refresh else "Library scanning..."
                self.ui.update_status(msg, show_banner=True, show_cancel=True)
            self.ui.set_scan_buttons_enabled(False)
            self.scanner.start(force_refresh=force_refresh, locations=locations)

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
        """Update metadata label with a random quote when idle.
        Called only from the empty-like branch of apply_library_state, so it applies
        to both sub-cases: no folders configured, and folders with zero audiobooks.
        (The old `if not get_scan_locations()` guard suppressed quotes in the latter.)"""
        text, title, text_size, title_size, color, text_align = random.choice(BOOK_QUOTES)
        styled_quote = (
            f"<div style='font-size: {text_size}px; color: {color}; text-align: {text_align}; width: 100%;'>{text}</div>"
            f"<div style='text-align: right; font-size: {title_size}px; color: #ddd;'><br>{title}</div>"
        )
        self.ui.update_quote(styled_quote, show_quote=True)