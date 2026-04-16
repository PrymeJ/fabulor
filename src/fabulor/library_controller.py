import os
import random
from PySide6.QtWidgets import QFileDialog
from PySide6.QtCore import QObject, QTimer, Qt
from .book_quotes import BOOK_QUOTES

class LibraryController(QObject):
    """Handles library scanning, folder management, and idle UI states."""
    def __init__(self, db, config, scanner, library_panel, status_label, status_banner, 
                 cancel_scan_btn, folder_list_widget, metadata_label, go_to_library_btn, 
                 library_prompt_label, scan_now_btn, scan_info_label, quote_label, quote_timer,
                 get_current_file_cb, on_book_removed_cb, set_interface_visible_cb):
        super().__init__()
        self.db = db
        self.config = config
        self.scanner = scanner
        self.library_panel = library_panel
        self.status_label = status_label
        self.status_banner = status_banner
        self.cancel_scan_btn = cancel_scan_btn
        self.folder_list_widget = folder_list_widget
        self.metadata_label = metadata_label
        self.go_to_library_btn = go_to_library_btn
        self.library_prompt_label = library_prompt_label
        self.scan_now_btn = scan_now_btn
        self.scan_info_label = scan_info_label
        self.quote_label = quote_label
        self.quote_timer = quote_timer
        
        # Callbacks to MainWindow state
        self.get_current_file = get_current_file_cb
        self.on_book_removed = on_book_removed_cb
        self.set_interface_visible = set_interface_visible_cb

    def _refresh_folder_list(self):
        """Updates the folder list widget with current scan locations."""
        self.folder_list_widget.clear()
        for loc in self.db.get_scan_locations():
            self.folder_list_widget.addItem(loc)

    def _on_remove_folder_clicked(self):
        """Removes the selected folder from the database and updates UI."""
        current_item = self.folder_list_widget.currentItem()
        if current_item:
            path = current_item.text()
            self.db.remove_scan_location(path)
            
            # Unload the book if it was inside the removed library folder
            current_file = self.get_current_file()
            path_p = path if path.endswith(os.sep) else path + os.sep
            if current_file and current_file.startswith(path_p):
                self.on_book_removed()

            self._refresh_folder_list()
            self._check_library_status(manual=True)
            self.library_panel.refresh(force=True)

    def _on_scan_now_clicked(self):
        """Triggers a folder picker and starts scanning."""
        folder = QFileDialog.getExistingDirectory(None, "Select Library Folder")
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
        self.status_label.setText("Scan cancelled.")
        self.cancel_scan_btn.hide()

    def _on_scan_progress(self, current, total):
        """Updates the status banner with scan progress."""
        if self.status_banner.isVisible():
            self.status_label.setText(f"Loading Library... ({current}/{total})")
            self.status_banner.raise_()
        
        if current == 1:
            self._check_library_status()

    def _on_scan_finished(self, total):
        """Finalizes scan and hides banner."""
        if self.status_banner.isVisible():
            self.status_label.setText(f"Library updated: {total} books.")
            self.cancel_scan_btn.hide()
            QTimer.singleShot(3000, self.status_banner.hide)
        
        self.library_panel.refresh(force=True)
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
            self.library_prompt_label.show()
            self.scan_now_btn.show()
            self.scan_info_label.show()
            self.status_banner.show()
            self.metadata_label.hide()
            self.go_to_library_btn.hide()
        else:
            self.library_prompt_label.hide()
            self.scan_now_btn.hide()
            self.scan_info_label.hide()
            self.quote_label.hide()
            self.quote_timer.stop()
            
            if not has_book:
                self.metadata_label.setText("No book selected.")
                self.metadata_label.show()
                self.go_to_library_btn.show()
            else:
                self.go_to_library_btn.hide()

        if has_locations:
            if not self.scanner._worker_thread or not self.scanner._worker_thread.isRunning():
                if manual or force_refresh or not has_indexed_books:
                    self.status_label.setText("Forcing deep scan..." if force_refresh else "Library scanning...")
                    self.cancel_scan_btn.show()
                    self.status_banner.show()
                
                self.scanner.start(force_refresh=force_refresh)

    def _rotate_quote(self):
        """Update metadata label with a random quote when idle."""
        if not self.db.get_scan_locations():
            text, title, text_size, title_size, color, text_align = random.choice(BOOK_QUOTES)
            styled_quote = (
                f"<div style='font-size: {text_size}px; color: {color}; text-align: {text_align}; width: 100%;'>{text}</div>"
                f"<div style='text-align: right; font-size: {title_size}px; color: #ddd;'><br>{title}</div>"
            )
            self.quote_label.setText(styled_quote)
            self.quote_label.show()