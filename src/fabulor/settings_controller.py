"""SettingsController: separates UI visuals, library actions, and player actions.

The controller decides what should happen; the passed-in interfaces perform how
those actions are executed. This module intentionally contains no direct GUI
manipulation.
"""
from typing import Any


class SettingsController:
    """Controller for settings-related actions.

    Constructor signature is intentionally explicit and minimal:

        SettingsController(config, visuals, library_actions, player_actions)

    - `config` exposes get/set methods for settings (used for business logic).
    - `visuals` exposes ONLY UI update methods (selection highlights, labels,
      styling, visual state updates). No business logic or side-effects should
      be implemented in the controller.
    - `library_actions` exposes `reparse_db(pattern)` and
      `refresh_library_panel(force=False)`.
    - `player_actions` exposes `get_current_file()` and `load_cover_art(path)`.
    """

    def __init__(self, config: Any, visuals: Any, library_actions: Any, player_actions: Any):
        self.config = config
        self.visuals = visuals
        self.library_actions = library_actions
        self.player_actions = player_actions

    # --- Naming pattern -------------------------------------------------
    def _update_naming_pattern(self, pattern: str):
        """Changes the folder parsing pattern and triggers a database re-parse.

        Behavior preserved from the previous implementation:
        - update config
        - reparse library with the new pattern
        - update pattern visuals
        - refresh the library panel (force=True)
        - if a current file exists, refresh its cover art
        """
        # business logic
        self.config.set_naming_pattern(pattern)
        # delegate heavy work to the library actions interface
        # library_actions.reparse_db is responsible for the DB side-effect
        self.library_actions.reparse_db(pattern)

        # visuals-only: update selection/highlight state
        self._update_pattern_visuals()

        # refresh library listing via interface
        # allow library_actions to interpret the force flag as needed
        try:
            self.library_actions.refresh_library_panel(force=True)
        except TypeError:
            # fallback if implementer doesn't accept force kwarg
            self.library_actions.refresh_library_panel(True)

        # refresh current book metadata on main screen if a book is loaded
        current = self.player_actions.get_current_file()
        if current:
            self.player_actions.load_cover_art(current)

    def _update_pattern_visuals(self):
        """Updates the highlight/dim state of naming pattern buttons.

        This method must ONLY call the visuals interface (no direct UI work).
        It reads the minimal state it needs from `config` and instructs
        `visuals` how to render that state.
        """
        current = self.config.get_naming_pattern()
        # visuals is responsible for deciding how to represent `current` in UI
        # (which buttons are selected, re-polishing styles, etc.).
        self.visuals.set_naming_pattern_selection(current)

    # --- Folder list ----------------------------------------------------
    def _update_folder_list_widget(self, paths):
        """Set the folder list contents. Delegates rendering to visuals."""
        self.visuals.set_folder_list(paths)

    def _get_selected_folder_path(self):
        """Return the currently selected folder path via visuals interface.

        The controller does not access widgets directly; visuals provides the
        information.
        """
        return self.visuals.get_selected_folder_path()

    def _get_new_folder_path(self):
        """Ask visuals to present a folder-selection dialog and return the
        selected path. The visuals layer owns dialog creation.
        """
        return self.visuals.open_folder_dialog()

    # --- Status / metadata UI -------------------------------------------
    def _update_status_banner_ui(self, text=None, show_banner=None, show_cancel=None, auto_hide=False):
        return self.visuals.update_status_banner(text=text, show_banner=show_banner, show_cancel=show_cancel, auto_hide=auto_hide)

    def _update_metadata_ui(self, text=None, show_metadata=None, show_go_to_lib=None):
        return self.visuals.update_metadata(text=text, show_metadata=show_metadata, show_go_to_lib=show_go_to_lib)

    def _update_chapter_title_text(self, text):
        return self.visuals.set_chapter_title(text)

    # Additional small helpers may delegate to visuals as needed. Keep the
    # controller free of direct GUI manipulation and limited to orchestration.
