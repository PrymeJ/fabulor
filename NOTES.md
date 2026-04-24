## Known Architectural Debt

### SimpleNamespace interfaces in app.py
`visuals`, `library_actions`, `player_actions` passed to `SettingsController` 
are bags of callbacks with no proper interface. Controller should eventually 
own direct references or use a proper protocol. Low urgency, high risk to touch.

### _update_speed_grid_styling in settings_controller.py
Misnamed — orchestrates all panel visual updates, not just speed grid.
Rename to `_refresh_panel_visuals` when refactoring SettingsController.

### List ↔ 1 per row transition cost is a known limitation, deferred to model/view rewrite.