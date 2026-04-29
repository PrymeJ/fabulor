## Known Architectural Debt

### _update_speed_grid_styling in settings_controller.py
Misnamed — orchestrates all panel visual updates, not just speed grid.
Rename to `_refresh_panel_visuals` when refactoring SettingsController.

### Stats page sluggishness on Weekly and Monthly tabs
Both BookDayRow and FinishedBookThumb load from disk synchronously in __init__. pixmap.load() with SmoothTransformation scaling is the culprit, and it compounds with each row added.
The fix is to defer cover loading out of __init__ using the existing CoverLoader pattern.