import math
from fabulor.assets import get_asset_path

"""
GROUP 1 — CORE BACKGROUNDS
bg_deep:              The darkest background color. Used for the custom title bar, the background behind the volume overlay, and the status banner at the bottom.
bg_main:              The primary background color for the main window and panels (settings, library, speed, etc.).
bg_sidebar:           The background color for the sliding sidebar on the left.
bg_dropdown:          The background color for lists and dropdown menus (like the chapter list and folder list).
bg_image:             (Optional) A string path (e.g., "img/overlook.png") to set a background image for the cover art area.
panel_opacity_hover:  A float (0.0 to 1.0) defining the transparency of the sidebar and settings panels when interacted with.
undo_hover:           The color used when hovering over the undo button. Fallback: accent.

GROUP 2 — CORE TEXT & ACCENT
text:                 The default color for most labels and UI text.
text_on_light_bg:     (Optional) Used as a fallback for buttons or specific labels placed over light-colored elements.
accent:               The primary interaction color. Used for selected tabs, slider handles (implicitly via fill), and primary buttons.
accent_light:         The color used when hovering over buttons or selecting list items.
accent_dark:          The color used for borders or when a button is actively pressed.

GROUP 3 — PLAYER BUTTONS
button_text:          (Optional) Specific color for text inside buttons. Fallback: text_on_light_bg → text.
button_play:          (Optional) Icon/text color for the play/pause/restart button. Fallback: button_text → text_on_light_bg → text.
button_skip:          (Optional) Icon/text color for the rewind and forward skip buttons. Fallback: button_play.
button_chapter:       (Optional) Icon/text color for the previous and next chapter buttons. Fallback: button_play.
slider_progress:      (Optional) Color for the percentage label that sits on top of the overall progress slider.

GROUP 4 — PLAYER SLIDERS
slider_overall_bg:    Background (groove) color of the main book progress bar.
slider_overall_fill:  The filled portion color of the main book progress bar.
slider_chapter_bg:    Background of the chapter-specific progress bar.
slider_chapter_fill:  The filled portion of the chapter-specific progress bar.
slider_vol_bg:        Background of the volume slider.
slider_vol_fill:      The filled portion of the volume slider.
notch_color:          (Optional) The color of chapter markers on the progress bars.
notch_opacity:        (Optional) The transparency (0-255) of chapter markers.

GROUP 5 — CHAPTER DROPDOWN
dropdown_curr_chap:   The color used to highlight the currently playing chapter within the chapter dropdown list.
dropdown_text:        (Optional) Color for text inside the chapter dropdown list.
dropdown_time_text:   (Optional) Color for the duration text inside the chapter dropdown list.
dropdown_expand:      Button color for the chapter list expand/collapse button. Fallback: accent.

GROUP 6 — SIDEBAR
sidebar_text:         (Optional) Color for text and buttons inside the sidebar. Fallback: text.
sidebar_text_hover:   (Optional) Color for text and buttons inside the sidebar when hovered. Fallback: accent.
sidebar_opacity:      A float (0.0 to 1.0) defining how transparent the sidebar is when idle.

GROUP 7 — LIBRARY
library_bg:           The background color for the library book display area. Fallback: #1A1A1A.
library_grid_bg:      Background color for the grid view. Fallback: library_bg.
library_row_one:      Background color for odd rows in 1-per-row and List views. Fallback: library_bg.
library_row_two:      Background color for even rows in 1-per-row and List views. Fallback: library_bg.
library_item_hover_color: Background color for a book item when hovered. Fallback: accent.
library_item_hover_alpha: Opacity (0.0 to 1.0) for the library item hover background. Fallback: 0.5.
library_title:        Text color for book titles in the library view.
library_author:       Text color for book authors in the library view.
library_narrator:     Text color for book narrators in the library view.
library_year:         Text color for the year field in 1-per-row view. Fallback: library_narrator.
library_elapsed:      Text color for elapsed time labels in library items.
library_total:        Text color for total duration labels in library items.
library_percentage:   Text color for the progress percentage in library items.
library_slider_bg:    Background color for the progress bar groove in library items.
library_slider_fill:  Fill color for the progress bar in library items.
library_input_bg:     Background color for sort/view dropdowns and the search field in the library. Fallback: bg_dropdown.
library_input_text:   Text color for sort/view dropdowns and the search field in the library. Fallback: text.
search_error_text:    (Optional) Text color for the search field when no results are found. Fallback: #ffaaaa.

GROUP 8 — SETTINGS PANEL
settings_tab_hover_bg:      Background color for unselected tabs when hovered. Fallback: accent.
settings_tab_hover_opacity: Opacity for unselected tabs when hovered. Fallback: 0.85.
settings_tab_hover_text:    Text color for unselected tabs when hovered. Fallback: text.
settings_theme_names_dimmed: Color for theme names in the Settings panel that are currently unselected/dimmed.

GROUP 9 — TAGS
tag_list_text:        (Optional) Color for text inside the tag list. Fallback: text.
tag_list_text_hover:  (Optional) Color for text inside the tag list when hovered. Fallback: accent_light.

GROUP 10 — MISC UI
cover_preview_bg:     Background color for book cover previews in the library. Fallback: bg_deep → #000000.

GROUP 11 — PLACEHOLDER COVERS
placeholder_cover:    Color for the Fabulor logo shown in the player cover area when a book has no cover art. Fallback chain: library_narrator → text → #888888.
placeholder_stats:    Color for the Fabulor logo shown in stats panel book thumbnails (BookDayRow, FinishedBookThumb). Fallback chain: placeholder_cover → library_narrator → text → #888888.
placeholder_tags:     Color for the Fabulor logo shown in tag panel book thumbnails. Fallback chain: placeholder_stats → placeholder_cover → library_narrator → text → #888888.

GROUP 12 — CAROUSEL
carousel_bg:          Fill color for the full-width stripe in the no-book state. Fallback: bg_deep.
carousel_stripe:      Color of the 2px horizontal lines at the top and bottom of the stripe. Fallback: auto-calculated from carousel_bg (lightness-shifted) → accent_light → text.

GROUP 13 — DYNAMIC GRADIENTS
The theme engine supports linear gradients for several components. Define them using these keys:
Prefixes: bg, sidebar, accent, slider_fill
gradient_[prefix]_start: Hex color for the start of the gradient.
gradient_[prefix]_end:   Hex color for the end of the gradient.
gradient_[prefix]_angle: Integer angle in degrees (e.g., 115 or 135).
gradient_bg_split:       (Optional) Float stop position (0.0–1.0) where bg gradient holds before transitioning to the end color.

COVER ART BASED THEME COLORS
These keys are generated dynamically by build_cover_theme() in cover_theme.py and are not set in static theme dicts.
lib_hover:  Background color for library item hover, derived from the dominant cover hue (mid-dark). Used as library_item_hover_color.
chap_fill:  Fill color for the chapter progress bar and library slider, derived from the dominant cover hue (slightly lighter than lib_hover). Used as slider_chapter_fill and library_slider_fill.
"""

THEMES = {
    "Alzabo": {
        "bg_deep":                       "#0A0E82",
        "bg_main":                       "#1A0570",
        "bg_sidebar":                    "#060A49",
        "bg_dropdown":                   "#4A5F6F",
        "panel_opacity_hover":           0.88,
        "undo_hover":                    "#1344B7",
        "text":                          "#6096C5",
        "accent":                        "#608CF5",
        "accent_light":                  "#55738A",
        "accent_dark":                   "#305674",
        "button_text":                   "#09365E",
        "button_play":                   "#5F7DA4",
        "button_skip":                   "#285B88",
        "button_chapter":                "#0A4578",
        "slider_overall_bg":             "#4E88B4",
        "slider_overall_fill":           "#DE1515",
        "slider_chapter_bg":             "#771327",
        "slider_chapter_fill":           "#205A86",
        "slider_vol_bg":                 "#084A84",
        "slider_vol_fill":               "#7A9BB5",
        "slider_progress":               "#102F67",
        "notch_color":                   "#3DE8EB",
        "notch_opacity":                 110,
        "dropdown_curr_chap":            "#942761",
        "dropdown_time_text":            "#6FA0F9",
        "dropdown_expand":               "#3313B4",
        "sidebar_text":                  "#E10F0F",
        "sidebar_text_hover":            "#5A97C6",
        "sidebar_opacity":               0.7,
        "library_bg":                    "#0D0630",
        "library_grid_bg":               "#04032D",
        "library_row_one":               "#130848",
        "library_row_two":               "#04032D",
        "library_item_hover_color":      "#1049CF",
        "library_item_hover_alpha":      0.3,
        "library_title":                 "#7ACAC9",
        "library_author":                "#22BDDD",
        "library_narrator":              "#9CBAD4",
        "library_elapsed":               "#9CBAD4",
        "library_total":                 "#9CBAD4",
        "library_percentage":            "#9CBAD4",
        "library_slider_bg":             "#4A5F6F",
        "library_slider_fill":           "#DE1515",
        "library_input_bg":              "#06263F",
        "library_input_text":            "#60D1D7",
        "settings_tab_hover_bg":         "#FF0000",
        "settings_tab_hover_opacity":    0.9,
        "settings_tab_hover_text":       "#150C79",
        "settings_theme_names_dimmed":   "#CDE1E1",
        "tag_list_text":                 "#86C6FF",
        "tag_list_text_hover":           "#FC1543",
        "cover_preview_bg":              "#07576B",
        "carousel_bg":                   "#020937",
        "carousel_stripe":               "#67A0CB"
    },
    "Annihilation": {
        "bg_deep":                       "#0A0F0A",
        "bg_main":                       "#0F1A0F",
        "bg_sidebar":                    "#0A0F0A",
        "bg_dropdown":                   "#1A2A1A",
        "panel_opacity_hover":           0.93,
        "text":                          "#D0F0D8",
        "text_on_light_bg":              "#0A0F0A",
        "accent":                        "#2EAA4A",
        "accent_light":                  "#3AC45A",
        "accent_dark":                   "#1A6A2A",
        "button_text":                   "#173417",
        "slider_progress":               "#D0F0D8",
        "slider_overall_bg":             "#1A2A1A",
        "slider_overall_fill":           "#2EAA4A",
        "slider_chapter_bg":             "#1A2A1A",
        "slider_chapter_fill":           "#3AC45A",
        "slider_vol_bg":                 "#1A2A1A",
        "slider_vol_fill":               "#2EAA4A",
        "notch_color":                   "#3AC45A",
        "notch_opacity":                 180,
        "dropdown_curr_chap":            "#27AB45",
        "dropdown_text":                 "#99F9B1",
        "dropdown_time_text":            "#53EF78",
        "sidebar_text":                  "#D0F0D8",
        "sidebar_text_hover":            "#2EAA4A",
        "sidebar_opacity":               0.86,
        "library_bg":                    "#0F1A0F",
        "library_grid_bg":               "#0F1A0F",
        "library_row_one":               "#0F1A0F",
        "library_row_two":               "#122212",
        "library_item_hover_color":      "#2EAA4A",
        "library_item_hover_alpha":      0.18,
        "library_title":                 "#ECEDAC",
        "library_author":                "#96E6AA",
        "library_narrator":              "#6A947A",
        "library_elapsed":               "#2EAA4A",
        "library_total":                 "#2EAA4A",
        "library_percentage":            "#7EC181",
        "library_slider_bg":             "#1A2A1A",
        "library_slider_fill":           "#2EAA4A",
        "library_input_bg":              "#1A2A1A",
        "library_input_text":            "#B4EEC3",
        "settings_tab_hover_bg":         "#2EAA4A",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#0A0F0A",
        "settings_theme_names_dimmed":   "#4A624A"
    },
    "Anomander": {
        "bg_deep":                       "#000000",
        "bg_main":                       "#000000",
        "bg_sidebar":                    "#000000",
        "bg_dropdown":                   "#080808",
        "panel_opacity_hover":           0.9,
        "undo_hover":                    "#404040",
        "text":                          "#FFFFFF",
        "accent":                        "#FFFFFF",
        "accent_light":                  "#E0E0E0",
        "accent_dark":                   "#404040",
        "button_text":                   "#000000",
        "slider_progress":               "#FFBF00",
        "slider_overall_bg":             "#1A1A1A",
        "slider_overall_fill":           "#FFFFFF",
        "slider_chapter_bg":             "#111111",
        "slider_chapter_fill":           "#FFFFFF",
        "slider_vol_bg":                 "#000000",
        "slider_vol_fill":               "#FFFFFF",
        "dropdown_curr_chap":            "#FFA807",
        "sidebar_text_hover":            "#E0E0E0",
        "sidebar_opacity":               0.8,
        "library_row_one":               "#000000",
        "library_row_two":               "#0C0C0C",
        "library_item_hover_alpha":      0.15,
        "settings_tab_hover_text":       "#000000",
        "settings_theme_names_dimmed":   "#FFA807"
    },
    "Blood Meridian": {
        "bg_deep":                       "#2F1A0F",
        "bg_main":                       "#4A2F1F",
        "bg_sidebar":                    "#3C1F10",
        "bg_dropdown":                   "#4A2F1F",
        "panel_opacity_hover":           0.91,
        "text":                          "#F5E6D3",
        "accent":                        "#C10808",
        "accent_light":                  "#A52A2A",
        "accent_dark":                   "#CD3F3F",
        "slider_overall_bg":             "#5A3F2F",
        "slider_overall_fill":           "#8B0000",
        "slider_chapter_bg":             "#4A2F1F",
        "slider_chapter_fill":           "#7A0000",
        "slider_vol_bg":                 "#2F1A0F",
        "slider_vol_fill":               "#8B0000",
        "dropdown_curr_chap":            "#8B0000",
        "sidebar_text_hover":            "#A52A2A",
        "sidebar_opacity":               0.72,
        "settings_theme_names_dimmed":   "#E47575"
    },
    "Blue Moranth": {
        "bg_deep":                       "#001219",
        "bg_main":                       "#001B2E",
        "bg_sidebar":                    "#001219",
        "bg_dropdown":                   "#001B2E",
        "panel_opacity_hover":           0.95,
        "text":                          "#B9EFEE",
        "accent":                        "#3C7BE0",
        "accent_light":                  "#29E442",
        "accent_dark":                   "#00A32A",
        "slider_progress":               "#E1F4BE",
        "slider_overall_bg":             "#003547",
        "slider_overall_fill":           "#39FF14",
        "slider_chapter_bg":             "#002A38",
        "slider_chapter_fill":           "#3CA4E0",
        "slider_vol_bg":                 "#3CA4E0",
        "slider_vol_fill":               "#39FF14",
        "dropdown_curr_chap":            "#227AED",
        "dropdown_time_text":            "#6FA0F9",
        "sidebar_text_hover":            "#7CFF8A",
        "sidebar_opacity":               0.9,
        "library_bg":                    "#11064A",
        "library_row_one":               "#0E0442",
        "library_row_two":               "#0A032A",
        "library_item_hover_color":      "#1049CF",
        "library_item_hover_alpha":      0.5,
        "library_title":                 "#3EA5EA",
        "library_author":                "#10D742",
        "settings_theme_names_dimmed":   "#8DCECF"
    },
    "Brave New World": {
        "bg_deep":                       "#3A2F5F",
        "bg_main":                       "#5A4A7F",
        "bg_sidebar":                    "#3A2F5F",
        "bg_dropdown":                   "#5A4A7F",
        "panel_opacity_hover":           0.9,
        "text":                          "#F1E7C2",
        "accent":                        "#77B2CC",
        "accent_light":                  "#9ACFE0",
        "accent_dark":                   "#4F8FAF",
        "slider_overall_bg":             "#6A5A8F",
        "slider_overall_fill":           "#77B2CC",
        "slider_chapter_bg":             "#5A4A7F",
        "slider_chapter_fill":           "#5A9BBF",
        "slider_vol_bg":                 "#3A2F5F",
        "slider_vol_fill":               "#77B2CC",
        "dropdown_curr_chap":            "#77B2CC",
        "sidebar_text_hover":            "#9ACFE0",
        "sidebar_opacity":               0.7,
        "library_bg":                    "#240B2E",
        "library_author":                "#D71087",
        "settings_theme_names_dimmed":   "#CA94CB"
    },
    "Camorr": {
        "bg_deep":                       "#0F1419",
        "bg_main":                       "#1A1F24",
        "bg_sidebar":                    "#032516",
        "bg_dropdown":                   "#1A1F24",
        "panel_opacity_hover":           0.88,
        "text":                          "#B1EBAF",
        "accent":                        "#00A98B",
        "accent_light":                  "#00D4B3",
        "accent_dark":                   "#006F5A",
        "slider_overall_bg":             "#2A2F34",
        "slider_overall_fill":           "#00A98B",
        "slider_chapter_bg":             "#1A1F24",
        "slider_chapter_fill":           "#008B6F",
        "slider_vol_bg":                 "#0F1419",
        "slider_vol_fill":               "#00A98B",
        "dropdown_curr_chap":            "#00A98B",
        "sidebar_text_hover":            "#00D4B3",
        "sidebar_opacity":               0.65,
        "library_row_one":               "#012D20",
        "library_row_two":               "#082A03",
        "library_item_hover_color":      "#00A98B",
        "library_item_hover_alpha":      0.8,
        "library_title":                 "#BEE6DF",
        "library_percentage":            "#5FFD0A",
        "settings_theme_names_dimmed":   "#C0D8CA"
    },
    "Cerulean Sea": {
        "bg_deep":                       "#181C20",
        "bg_main":                       "#22262C",
        "bg_sidebar":                    "#181C20",
        "bg_dropdown":                   "#2E323A",
        "panel_opacity_hover":           0.92,
        "text":                          "#DCE0E6",
        "text_on_light_bg":              "#181C20",
        "accent":                        "#5AACCC",
        "accent_light":                  "#7AC0DE",
        "accent_dark":                   "#3A7288",
        "button_text":                   "#181C20",
        "slider_progress":               "#DCE0E6",
        "slider_overall_bg":             "#2E323A",
        "slider_overall_fill":           "#5AACCC",
        "slider_chapter_bg":             "#2E323A",
        "slider_chapter_fill":           "#7AC0DE",
        "slider_vol_bg":                 "#2E323A",
        "slider_vol_fill":               "#5AACCC",
        "notch_color":                   "#7AC0DE",
        "notch_opacity":                 170,
        "dropdown_curr_chap":            "#7AC0DE",
        "dropdown_text":                 "#DCE0E6",
        "dropdown_time_text":            "#78808C",
        "sidebar_text":                  "#DCE0E6",
        "sidebar_text_hover":            "#5AACCC",
        "sidebar_opacity":               0.85,
        "library_bg":                    "#22262C",
        "library_grid_bg":               "#22262C",
        "library_row_one":               "#22262C",
        "library_row_two":               "#282C34",
        "library_item_hover_color":      "#5AACCC",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#E8ECF0",
        "library_author":                "#A8B0BA",
        "library_narrator":              "#78808C",
        "library_elapsed":               "#A8B0BA",
        "library_total":                 "#586064",
        "library_percentage":            "#5AACCC",
        "library_slider_bg":             "#2E323A",
        "library_slider_fill":           "#5AACCC",
        "library_input_bg":              "#2E323A",
        "library_input_text":            "#E8ECF0",
        "settings_tab_hover_bg":         "#5AACCC",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#181C20",
        "settings_theme_names_dimmed":   "#586064"
    },
    "Chatsubo": {
        "bg_deep":                       "#0D001A",
        "bg_main":                       "#1A002E",
        "bg_sidebar":                    "#0D001A",
        "bg_dropdown":                   "#1A1A1A",
        "panel_opacity_hover":           0.9,
        "undo_hover":                    "#12C6D6",
        "text":                          "#E0E0E0",
        "accent":                        "#FF00FF",
        "accent_light":                  "#FF33FF",
        "accent_dark":                   "#CC00CC",
        "slider_overall_bg":             "#333333",
        "slider_overall_fill":           "#FF00FF",
        "slider_chapter_bg":             "#2A2A2A",
        "slider_chapter_fill":           "#00FFFF",
        "slider_vol_bg":                 "#0D001A",
        "slider_vol_fill":               "#00FF00",
        "dropdown_curr_chap":            "#FF00FF",
        "dropdown_text":                 "#FFFF00",
        "sidebar_text_hover":            "#FF33FF",
        "sidebar_opacity":               0.7,
        "library_bg":                    "#260242",
        "library_row_one":               "#26053F",
        "library_row_two":               "#1A032C",
        "library_item_hover_color":      "#FF66CC",
        "library_item_hover_alpha":      0.2,
        "library_title":                 "#00EAFF",
        "library_author":                "#FF00FF",
        "library_narrator":              "#FFFF00",
        "library_elapsed":               "#6CFAFF",
        "library_total":                 "#00C8FF",
        "library_percentage":            "#D97DEC",
        "settings_theme_names_dimmed":   "#00F7FF"
    },
    "Cibola Burn": {
        "bg_deep":                       "#1A0A0A",
        "bg_main":                       "#2A1010",
        "bg_sidebar":                    "#1A0A0A",
        "bg_dropdown":                   "#3A1818",
        "panel_opacity_hover":           0.93,
        "text":                          "#F0E0C8",
        "text_on_light_bg":              "#1A0A0A",
        "accent":                        "#E87A2A",
        "accent_light":                  "#F08A3A",
        "accent_dark":                   "#A84A1A",
        "button_text":                   "#1A0A0A",
        "slider_progress":               "#F0E0C8",
        "slider_overall_bg":             "#3A1818",
        "slider_overall_fill":           "#E87A2A",
        "slider_chapter_bg":             "#3A1818",
        "slider_chapter_fill":           "#F08A3A",
        "slider_vol_bg":                 "#3A1818",
        "slider_vol_fill":               "#E87A2A",
        "notch_color":                   "#F08A3A",
        "notch_opacity":                 180,
        "dropdown_curr_chap":            "#F08A3A",
        "dropdown_text":                 "#F7E780",
        "dropdown_time_text":            "#F0E0C8",
        "sidebar_text":                  "#F0E0C8",
        "sidebar_text_hover":            "#D46A1A",
        "sidebar_opacity":               0.86,
        "library_bg":                    "#2A1010",
        "library_grid_bg":               "#2A1010",
        "library_row_one":               "#2A1010",
        "library_row_two":               "#321818",
        "library_item_hover_color":      "#D46A1A",
        "library_item_hover_alpha":      0.15,
        "library_title":                 "#FECF88",
        "library_author":                "#D09752",
        "library_narrator":              "#C0A078",
        "library_elapsed":               "#F1C58F",
        "library_total":                 "#F1C58F",
        "library_percentage":            "#E87A2A",
        "library_slider_bg":             "#681B1B",
        "library_slider_fill":           "#E87A2A",
        "library_input_bg":              "#3A1818",
        "library_input_text":            "#F6B95E",
        "search_error_text":             "#FF56F1",
        "settings_tab_hover_bg":         "#D46A1A",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#1A0A0A",
        "settings_theme_names_dimmed":   "#D15135",
        "placeholder_cover":             "#F8C50C",
    },
    "City of Stairs": {
        "bg_deep":                       "#0E1E24",
        "bg_main":                       "#183238",
        "bg_sidebar":                    "#0E1E24",
        "bg_dropdown":                   "#244A52",
        "panel_opacity_hover":           0.91,
        "text":                          "#EAF2EA",
        "accent":                        "#4A7A6E",
        "accent_light":                  "#6AAAA0",
        "accent_dark":                   "#2A5248",
        "slider_overall_bg":             "#244A52",
        "slider_overall_fill":           "#5A9A8C",
        "slider_chapter_bg":             "#244A52",
        "slider_chapter_fill":           "#6AAAA0",
        "slider_vol_bg":                 "#183238",
        "slider_vol_fill":               "#5A9A8C",
        "dropdown_curr_chap":            "#6AAAA0",
        "sidebar_text_hover":            "#6AAAA0",
        "sidebar_opacity":               0.83,
        "settings_theme_names_dimmed":   "#A2C1C8"
    },
    "Crimson Guard": {
        "bg_deep":                       "#1A0F1A",
        "bg_main":                       "#2E1A24",
        "bg_sidebar":                    "#1A0F1A",
        "bg_dropdown":                   "#4A2A3A",
        "panel_opacity_hover":           0.92,
        "text":                          "#F2E0E8",
        "accent":                        "#B84A6A",
        "accent_light":                  "#D06A8A",
        "accent_dark":                   "#7A2A4A",
        "slider_overall_bg":             "#4A2A3A",
        "slider_overall_fill":           "#D96A2A",
        "slider_chapter_bg":             "#4A2A3A",
        "slider_chapter_fill":           "#E87A3A",
        "slider_vol_bg":                 "#2E1A24",
        "slider_vol_fill":               "#D96A2A",
        "dropdown_curr_chap":            "#E87A3A",
        "sidebar_text_hover":            "#F19616",
        "sidebar_opacity":               0.84,
        "library_title":                 "#EBF4CF",
        "library_narrator":              "#F0A9CF",
        "library_elapsed":               "#F0A9CF",
        "library_total":                 "#F0A9CF",
        "library_percentage":            "#F0A9CF",
        "settings_theme_names_dimmed":   "#D8C0D4"
    },
    "Dorian Grey": {
        "bg_deep":                       "#222222",
        "bg_main":                       "#333333",
        "bg_sidebar":                    "#222222",
        "bg_dropdown":                   "#333333",
        "panel_opacity_hover":           0.92,
        "undo_hover":                    "#777777",
        "text":                          "#D4D4D4",
        "text_on_light_bg":              "#333333",
        "accent":                        "#D4D4D4",
        "accent_light":                  "#E4E4E4",
        "accent_dark":                   "#B4B4B4",
        "button_text":                   "#333333",
        "slider_progress":               "#D4D4D4",
        "slider_overall_bg":             "#333333",
        "slider_overall_fill":           "#D4D4D4",
        "slider_chapter_bg":             "#333333",
        "slider_chapter_fill":           "#D4D4D4",
        "slider_vol_bg":                 "#333333",
        "slider_vol_fill":               "#D4D4D4",
        "dropdown_curr_chap":            "#D4D4D4",
        "dropdown_text":                 "#D4D4D4",
        "dropdown_time_text":            "#C4C4C4",
        "sidebar_text":                  "#D4D4D4",
        "sidebar_opacity":               0.85,
        "library_bg":                    "#333333",
        "library_row_one":               "#333333",
        "library_row_two":               "#444444",
        "library_item_hover_color":      "#D4D4D4",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#D4D4D4",
        "library_author":                "#C4C4C4",
        "library_narrator":              "#B4B4B4",
        "library_elapsed":               "#C4C4C4",
        "library_total":                 "#B4B4B4",
        "library_percentage":            "#D4D4D4",
        "library_slider_bg":             "#333333",
        "library_slider_fill":           "#D4D4D4",
        "library_input_bg":              "#333333",
        "library_input_text":            "#D4D4D4",
        "settings_tab_hover_bg":         "#D4D4D4",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#333333",
        "settings_theme_names_dimmed":   "#B4B4B4",
        "gradient_bg_start":             "#222222",
        "gradient_bg_end":               "#333333",
        "gradient_bg_angle":             135,
        "gradient_accent_start":         "#D4D4D4",
        "gradient_accent_end":           "#C4C4C4",
        "gradient_accent_angle":         45
    },
    "Driftmark": {
        "bg_deep":                       "#0E1A18",
        "bg_main":                       "#142420",
        "bg_sidebar":                    "#0E1A18",
        "bg_dropdown":                   "#1A3028",
        "bg_image":                      "img/driftmark.png",
        "panel_opacity_hover":           0.92,
        "text":                          "#E8F0EE",
        "text_on_light_bg":              "#0E1A18",
        "accent":                        "#5AA898",
        "accent_light":                  "#7AC8B8",
        "accent_dark":                   "#3A7868",
        "button_text":                   "#0E1A18",
        "slider_progress":               "#E8F0EE",
        "slider_overall_bg":             "#1A3028",
        "slider_overall_fill":           "#5AA898",
        "slider_chapter_bg":             "#1A3028",
        "slider_chapter_fill":           "#7AC8B8",
        "slider_vol_bg":                 "#1A3028",
        "slider_vol_fill":               "#5AA898",
        "notch_color":                   "#7AC8B8",
        "notch_opacity":                 170,
        "dropdown_curr_chap":            "#7AC8B8",
        "dropdown_text":                 "#E8F0EE",
        "dropdown_time_text":            "#88A89E",
        "sidebar_text":                  "#E8F0EE",
        "sidebar_text_hover":            "#6AB8A8",
        "sidebar_opacity":               0.85,
        "library_bg":                    "#142420",
        "library_grid_bg":               "#142420",
        "library_row_one":               "#142420",
        "library_row_two":               "#182C28",
        "library_item_hover_color":      "#6AB8A8",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#E8F0EE",
        "library_author":                "#A8C8C0",
        "library_narrator":              "#88A89E",
        "library_elapsed":               "#A8C8C0",
        "library_total":                 "#5A7A70",
        "library_percentage":            "#5AA898",
        "library_slider_bg":             "#1A3028",
        "library_slider_fill":           "#5AA898",
        "library_input_bg":              "#1A3028",
        "library_input_text":            "#E8F0EE",
        "settings_tab_hover_bg":         "#6AB8A8",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#0E1A18",
        "settings_theme_names_dimmed":   "#5A7A70",
        "gradient_bg_start":             "#0E1A18",
        "gradient_bg_end":               "#1E3A32",
        "gradient_bg_angle":             135,
        "gradient_accent_start":         "#5AA898",
        "gradient_accent_end":           "#D4AA4A",
        "gradient_accent_angle":         45,
        "gradient_slider_fill_start":    "#5AA898",
        "gradient_slider_fill_end":      "#8AD8C8",
        "gradient_slider_fill_angle":    90
    },
    "Earthsea": {
        "bg_deep":                       "#1A2A44",
        "bg_main":                       "#2B4A6A",
        "bg_sidebar":                    "#1A2A44",
        "bg_dropdown":                   "#2B4A6A",
        "panel_opacity_hover":           0.9,
        "text":                          "#B9D7E2",
        "accent":                        "#4A90A7",
        "accent_light":                  "#6AB8C7",
        "accent_dark":                   "#2F6A80",
        "slider_overall_bg":             "#3A5A7A",
        "slider_overall_fill":           "#4A90A7",
        "slider_chapter_bg":             "#2B4A6A",
        "slider_chapter_fill":           "#3A7A90",
        "slider_vol_bg":                 "#1A2A44",
        "slider_vol_fill":               "#4A90A7",
        "dropdown_curr_chap":            "#4A90A7",
        "sidebar_text_hover":            "#6AB8C7",
        "sidebar_opacity":               0.7,
        "settings_theme_names_dimmed":   "#D2ECF1"
    },
    "Emiko": {
        "bg_deep":                       "#0A1F0A",
        "bg_main":                       "#123312",
        "bg_sidebar":                    "#0A1F0A",
        "bg_dropdown":                   "#1F4F1F",
        "panel_opacity_hover":           0.9,
        "undo_hover":                    "#A6A11A",
        "text":                          "#D0FFD0",
        "accent":                        "#2EFF7A",
        "accent_light":                  "#6CFFB0",
        "accent_dark":                   "#1AA652",
        "button_text":                   "#067809",
        "button_play":                   "#F1FD98",
        "slider_overall_bg":             "#1F4F1F",
        "slider_overall_fill":           "#2EFF7A",
        "slider_chapter_bg":             "#1F4F1F",
        "slider_chapter_fill":           "#4CFF94",
        "slider_vol_bg":                 "#123312",
        "slider_vol_fill":               "#2EFF7A",
        "dropdown_curr_chap":            "#1BD063",
        "sidebar_text_hover":            "#6CFFB0",
        "sidebar_opacity":               0.82,
        "settings_theme_names_dimmed":   "#1AA652"
    },
    "Eyes of Ibad": {
        "bg_deep":                       "#0A1128",
        "bg_main":                       "#0F1A3A",
        "bg_sidebar":                    "#0A1128",
        "bg_dropdown":                   "#1A2A5A",
        "panel_opacity_hover":           0.92,
        "text":                          "#C4D7F2",
        "accent":                        "#3B6AFF",
        "accent_light":                  "#6B9AFF",
        "accent_dark":                   "#1A3A9A",
        "slider_overall_bg":             "#1A2A5A",
        "slider_overall_fill":           "#3B6AFF",
        "slider_chapter_bg":             "#1A2A5A",
        "slider_chapter_fill":           "#5B8AFF",
        "slider_vol_bg":                 "#0A1128",
        "slider_vol_fill":               "#3B6AFF",
        "dropdown_curr_chap":            "#5B8AFF",
        "sidebar_text_hover":            "#6B9AFF",
        "sidebar_opacity":               0.85,
        "settings_theme_names_dimmed":   "#8FEBE6"
    },
    "Fifth Season": {
        "bg_deep":                       "#0A0A0A",
        "bg_main":                       "#141414",
        "bg_sidebar":                    "#0A0A0A",
        "bg_dropdown":                   "#1E1E1E",
        "panel_opacity_hover":           0.93,
        "text":                          "#E8E8E0",
        "text_on_light_bg":              "#0A0A0A",
        "accent":                        "#3A6A8A",
        "accent_light":                  "#5A8AAA",
        "accent_dark":                   "#1A4A6A",
        "button_text":                   "#0A0A0A",
        "slider_progress":               "#E8E8E0",
        "slider_overall_bg":             "#2A2A2A",
        "slider_overall_fill":           "#3A6A8A",
        "slider_chapter_bg":             "#2A2A2A",
        "slider_chapter_fill":           "#5A8AAA",
        "slider_vol_bg":                 "#2A2A2A",
        "slider_vol_fill":               "#3A6A8A",
        "notch_color":                   "#5A8AAA",
        "notch_opacity":                 170,
        "dropdown_curr_chap":            "#5A8AAA",
        "dropdown_text":                 "#E8E8E0",
        "dropdown_time_text":            "#787868",
        "sidebar_text":                  "#E8E8E0",
        "sidebar_text_hover":            "#4A7A9A",
        "sidebar_opacity":               0.86,
        "library_bg":                    "#141414",
        "library_grid_bg":               "#141414",
        "library_row_one":               "#141414",
        "library_row_two":               "#1C1C1C",
        "library_item_hover_color":      "#4A7A9A",
        "library_item_hover_alpha":      0.45,
        "library_title":                 "#E8E8E0",
        "library_author":                "#A8A898",
        "library_narrator":              "#787868",
        "library_elapsed":               "#A8A898",
        "library_total":                 "#585848",
        "library_percentage":            "#3A6A8A",
        "library_slider_bg":             "#2A2A2A",
        "library_slider_fill":           "#3A6A8A",
        "library_input_bg":              "#2A2A2A",
        "library_input_text":            "#E8E8E0",
        "settings_tab_hover_bg":         "#4A7A9A",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#E8E8E0",
        "settings_theme_names_dimmed":   "#585848"
    },
    "Fire and Blood": {
        "bg_deep":                       "#0A0505",
        "bg_main":                       "#0F0A0A",
        "bg_sidebar":                    "#0A0505",
        "bg_dropdown":                   "#1A0A0A",
        "bg_image":                      "img/fireandblood.png",
        "panel_opacity_hover":           0.94,
        "text":                          "#F2D8D8",
        "text_on_light_bg":              "#0A0505",
        "accent":                        "#D42020",
        "accent_light":                  "#E83030",
        "accent_dark":                   "#8A1010",
        "button_text":                   "#0A0505",
        "slider_progress":               "#F2D8D8",
        "slider_overall_bg":             "#1A0A0A",
        "slider_overall_fill":           "#D42020",
        "slider_chapter_bg":             "#1A0A0A",
        "slider_chapter_fill":           "#E83030",
        "slider_vol_bg":                 "#1A0A0A",
        "slider_vol_fill":               "#D42020",
        "notch_color":                   "#E83030",
        "notch_opacity":                 180,
        "dropdown_curr_chap":            "#E83030",
        "dropdown_text":                 "#F2D8D8",
        "dropdown_time_text":            "#A07070",
        "sidebar_text":                  "#F2D8D8",
        "sidebar_text_hover":            "#D42020",
        "sidebar_opacity":               0.88,
        "library_bg":                    "#0F0A0A",
        "library_grid_bg":               "#0F0A0A",
        "library_row_one":               "#0F0A0A",
        "library_row_two":               "#140A0A",
        "library_item_hover_color":      "#D42020",
        "library_item_hover_alpha":      0.35,
        "library_title":                 "#F2D8D8",
        "library_author":                "#D42020",
        "library_narrator":              "#F2D8D8",
        "library_elapsed":               "#C09898",
        "library_total":                 "#6A4040",
        "library_percentage":            "#D42020",
        "library_slider_bg":             "#1A0A0A",
        "library_slider_fill":           "#D42020",
        "library_input_bg":              "#1A0A0A",
        "library_input_text":            "#F2D8D8",
        "settings_tab_hover_bg":         "#D42020",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#F2D8D8",
        "settings_theme_names_dimmed":   "#6A4040",
        "gradient_bg_start":             "#0A0505",
        "gradient_bg_end":               "#1A0A0F",
        "gradient_bg_angle":             135,
        "gradient_accent_start":         "#D42020",
        "gradient_accent_end":           "#AA1818",
        "gradient_accent_angle":         90,
        "gradient_slider_fill_start":    "#D42020",
        "gradient_slider_fill_end":      "#E83030",
        "gradient_slider_fill_angle":    90
    },
    "Galatea": {
        "bg_deep":                       "#0A1228",
        "bg_main":                       "#101A38",
        "bg_sidebar":                    "#0A1228",
        "bg_dropdown":                   "#162248",
        "panel_opacity_hover":           0.92,
        "undo_hover":                    "#23B7D6",
        "text":                          "#EBD6A2",
        "text_on_light_bg":              "#0A1228",
        "accent":                        "#E8943A",
        "accent_light":                  "#F0A84A",
        "accent_dark":                   "#B8681E",
        "button_text":                   "#0A1228",
        "slider_progress":               "#FFFB14",
        "slider_overall_bg":             "#162248",
        "slider_overall_fill":           "#E8943A",
        "slider_chapter_bg":             "#162248",
        "slider_chapter_fill":           "#F0A84A",
        "slider_vol_bg":                 "#162248",
        "slider_vol_fill":               "#E8943A",
        "notch_color":                   "#F0A84A",
        "notch_opacity":                 180,
        "dropdown_curr_chap":            "#CE8A31",
        "dropdown_text":                 "#EFEF9B",
        "dropdown_time_text":            "#EFEF9B",
        "sidebar_text":                  "#D8E0F0",
        "sidebar_text_hover":            "#E8943A",
        "sidebar_opacity":               0.85,
        "library_bg":                    "#101A38",
        "library_grid_bg":               "#101A38",
        "library_row_one":               "#101A38",
        "library_row_two":               "#141E40",
        "library_item_hover_color":      "#3F86E2",
        "library_item_hover_alpha":      0.25,
        "library_title":                 "#E9AF1D",
        "library_author":                "#A8B4CC",
        "library_narrator":              "#7A869E",
        "library_elapsed":               "#9AAAD2",
        "library_total":                 "#90A3C8",
        "library_percentage":            "#E8943A",
        "library_slider_bg":             "#162248",
        "library_slider_fill":           "#E8943A",
        "library_input_bg":              "#162248",
        "library_input_text":            "#E8ECF4",
        "settings_tab_hover_bg":         "#E8943A",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#0A1228",
        "settings_theme_names_dimmed":   "#586688"
    },
    "Goldfinch": {
        "bg_deep":                       "#1E1816",
        "bg_main":                       "#2E2220",
        "bg_sidebar":                    "#1E1816",
        "bg_dropdown":                   "#3E302C",
        "panel_opacity_hover":           0.92,
        "text":                          "#E8D4C8",
        "text_on_light_bg":              "#1E1816",
        "accent":                        "#D46A44",
        "accent_light":                  "#E8805A",
        "accent_dark":                   "#9A4228",
        "button_text":                   "#1E1816",
        "slider_progress":               "#E8D4C8",
        "slider_overall_bg":             "#3E302C",
        "slider_overall_fill":           "#D46A44",
        "slider_chapter_bg":             "#3E302C",
        "slider_chapter_fill":           "#E8805A",
        "slider_vol_bg":                 "#3E302C",
        "slider_vol_fill":               "#D46A44",
        "notch_color":                   "#E8805A",
        "notch_opacity":                 180,
        "dropdown_curr_chap":            "#E8805A",
        "dropdown_text":                 "#E8D4C8",
        "dropdown_time_text":            "#9A7A6C",
        "sidebar_text":                  "#E8D4C8",
        "sidebar_text_hover":            "#D46A44",
        "sidebar_opacity":               0.85,
        "library_bg":                    "#2E2220",
        "library_grid_bg":               "#2E2220",
        "library_row_one":               "#2E2220",
        "library_row_two":               "#342824",
        "library_item_hover_color":      "#D46A44",
        "library_item_hover_alpha":      0.45,
        "library_title":                 "#F0E0D4",
        "library_author":                "#C8A898",
        "library_narrator":              "#9A7A6C",
        "library_elapsed":               "#C8A898",
        "library_total":                 "#6A5448",
        "library_percentage":            "#D46A44",
        "library_slider_bg":             "#3E302C",
        "library_slider_fill":           "#D46A44",
        "library_input_bg":              "#3E302C",
        "library_input_text":            "#F0E0D4",
        "settings_tab_hover_bg":         "#D46A44",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#1E1816",
        "settings_theme_names_dimmed":   "#6A5448"
    },
    "Gormenghast": {
        "bg_deep":                       "#3B2A24",
        "bg_main":                       "#543D34",
        "bg_sidebar":                    "#3B2A24",
        "bg_dropdown":                   "#70554A",
        "panel_opacity_hover":           0.92,
        "text":                          "#F0E6D8",
        "accent":                        "#9C6E4E",
        "accent_light":                  "#B88462",
        "accent_dark":                   "#6E4A34",
        "slider_overall_bg":             "#70554A",
        "slider_overall_fill":           "#A57254",
        "slider_chapter_bg":             "#70554A",
        "slider_chapter_fill":           "#B88462",
        "slider_vol_bg":                 "#543D34",
        "slider_vol_fill":               "#A57254",
        "dropdown_curr_chap":            "#B88462",
        "sidebar_text_hover":            "#B88462",
        "sidebar_opacity":               0.85,
        "settings_theme_names_dimmed":   "#E4C7B7"
    },
    "Gravity's Rainbow": {
        "bg_deep":                       "#1A0033",
        "bg_main":                       "#2B0052",
        "bg_sidebar":                    "#1A0033",
        "bg_dropdown":                   "#2B0052",
        "panel_opacity_hover":           0.9,
        "text":                          "#CFECEC",
        "accent":                        "#00FF00",
        "accent_light":                  "#00FFFF",
        "accent_dark":                   "#0000FF",
        "button_text":                   "#156109",
        "button_play":                   "#AD117C",
        "button_skip":                   "#156109",
        "button_chapter":                "#107500",
        "slider_progress":               "#FF00FF",
        "slider_overall_bg":             "#4B0082",
        "slider_overall_fill":           "#ED37B3",
        "slider_chapter_bg":             "#330066",
        "slider_chapter_fill":           "#FF7F00",
        "slider_vol_bg":                 "#1A0033",
        "slider_vol_fill":               "#FFFF00",
        "notch_color":                   "#F4D690",
        "dropdown_curr_chap":            "#8B00FF",
        "sidebar_text_hover":            "#00FFFF",
        "sidebar_opacity":               0.7,
        "library_bg":                    "#1A032B",
        "library_grid_bg":               "#26053F",
        "library_row_one":               "#26053F",
        "library_row_two":               "#370B56",
        "library_item_hover_color":      "#DC137B",
        "library_item_hover_alpha":      0.13,
        "library_title":                 "#DC137B",
        "library_author":                "#EE62AB",
        "library_narrator":              "#FFFF00",
        "library_year":                  "#BDFFAD",
        "library_elapsed":               "#6CFAFF",
        "library_total":                 "#00C8FF",
        "library_percentage":            "#D97DEC",
        "settings_theme_names_dimmed":   "#E94F4F",
        "gradient_bg_start":             "#D328D3",
        "gradient_bg_end":               "#1900FF",
        "gradient_bg_angle":             115
    },
    "Hear Me Roar": {
        "bg_deep":                       "#230903",
        "bg_main":                       "#A40202",
        "bg_sidebar":                    "#461004",
        "bg_dropdown":                   "#451208",
        "bg_image":                      "img/hearmeroar.png",
        "panel_opacity_hover":           0.92,
        "text":                          "#FDE805",
        "accent":                        "#FDA605",
        "accent_light":                  "#F84949",
        "accent_dark":                   "#A37B14",
        "slider_progress":               "#FCDE99",
        "slider_overall_bg":             "#741A06",
        "slider_overall_fill":           "#FDA605",
        "slider_chapter_bg":             "#820D0D",
        "slider_chapter_fill":           "#D60808",
        "slider_vol_bg":                 "#230903",
        "slider_vol_fill":               "#E3B23C",
        "notch_color":                   "#FBE0A0",
        "dropdown_curr_chap":            "#C60C0C",
        "sidebar_text_hover":            "#D60808",
        "sidebar_opacity":               0.8,
        "library_bg":                    "#390606",
        "library_row_one":               "#390606",
        "library_row_two":               "#230303",
        "library_item_hover_color":      "#FF66CC",
        "library_item_hover_alpha":      0.15,
        "library_title":                 "#FFBB00",
        "library_author":                "#FF5E00",
        "library_narrator":              "#FFFF00",
        "library_elapsed":               "#DF7C2B",
        "library_total":                 "#DF7C2B",
        "library_percentage":            "#DF7C2B",
        "search_error_text":             "#CC0000",
        "settings_theme_names_dimmed":   "#F47272"
    },
    "Highgarden": {
        "bg_deep":                       "#1A2A1A",
        "bg_main":                       "#2A3E2A",
        "bg_sidebar":                    "#1A2A1A",
        "bg_dropdown":                   "#3A5238",
        "bg_image":                      "img/highgarden.png",
        "panel_opacity_hover":           0.92,
        "text":                          "#E8F0E0",
        "text_on_light_bg":              "#1A2A1A",
        "accent":                        "#D4A84C",
        "accent_light":                  "#E4B85C",
        "accent_dark":                   "#A07838",
        "button_text":                   "#1A2A1A",
        "slider_progress":               "#E8F0E0",
        "slider_overall_bg":             "#3A5238",
        "slider_overall_fill":           "#7AAA4C",
        "slider_chapter_bg":             "#3A5238",
        "slider_chapter_fill":           "#8ABA5C",
        "slider_vol_bg":                 "#3A5238",
        "slider_vol_fill":               "#7AAA4C",
        "notch_color":                   "#D4A84C",
        "notch_opacity":                 180,
        "dropdown_curr_chap":            "#8ABA5C",
        "dropdown_text":                 "#E8F0E0",
        "dropdown_time_text":            "#9AB08A",
        "sidebar_text":                  "#E8F0E0",
        "sidebar_text_hover":            "#D4A84C",
        "sidebar_opacity":               0.84,
        "library_bg":                    "#2A3E2A",
        "library_grid_bg":               "#2A3E2A",
        "library_row_one":               "#2A3E2A",
        "library_row_two":               "#324632",
        "library_item_hover_color":      "#D4A84C",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#E8F0E0",
        "library_author":                "#B8C8A8",
        "library_narrator":              "#9AB08A",
        "library_elapsed":               "#B8C8A8",
        "library_total":                 "#7A9070",
        "library_percentage":            "#7AAA4C",
        "library_slider_bg":             "#3A5238",
        "library_slider_fill":           "#7AAA4C",
        "library_input_bg":              "#3A5238",
        "library_input_text":            "#E8F0E0",
        "settings_tab_hover_bg":         "#D4A84C",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#1A2A1A",
        "settings_theme_names_dimmed":   "#7A9070",
        "gradient_bg_start":             "#1A2A1A",
        "gradient_bg_end":               "#3E5A3A",
        "gradient_bg_angle":             135,
        "gradient_slider_fill_start":    "#7AAA4C",
        "gradient_slider_fill_end":      "#9ACA6C",
        "gradient_slider_fill_angle":    90
    },
    "Jade City": {
        "bg_deep":                       "#002E22",
        "bg_main":                       "#003D2E",
        "bg_sidebar":                    "#002E22",
        "bg_dropdown":                   "#003D2E",
        "panel_opacity_hover":           0.9,
        "text":                          "#CBE4E3",
        "accent":                        "#00A86B",
        "accent_light":                  "#2ECC71",
        "accent_dark":                   "#007A4D",
        "slider_overall_bg":             "#004D3B",
        "slider_overall_fill":           "#00A86B",
        "slider_chapter_bg":             "#003D2E",
        "slider_chapter_fill":           "#40B58D",
        "slider_vol_bg":                 "#002E22",
        "slider_vol_fill":               "#00A86B",
        "dropdown_curr_chap":            "#00A86B",
        "sidebar_text_hover":            "#2ECC71",
        "sidebar_opacity":               0.7,
        "settings_theme_names_dimmed":   "#DCDCC7"
    },
    "Lilac Girls": {
        "bg_deep":                       "#1E1A24",
        "bg_main":                       "#2C2634",
        "bg_sidebar":                    "#1E1A24",
        "bg_dropdown":                   "#3A3244",
        "panel_opacity_hover":           0.92,
        "undo_hover":                    "#80175B",
        "text":                          "#C895B6",
        "text_on_light_bg":              "#1E1A24",
        "accent":                        "#C496B8",
        "accent_light":                  "#D8AACC",
        "accent_dark":                   "#8A6280",
        "button_text":                   "#3A3245",
        "button_play":                   "#3A3245",
        "button_skip":                   "#3A3245",
        "button_chapter":                "#3A3245",
        "slider_progress":               "#E8DCE8",
        "slider_overall_bg":             "#3A3244",
        "slider_overall_fill":           "#C496B8",
        "slider_chapter_bg":             "#3A3244",
        "slider_chapter_fill":           "#D8AACC",
        "slider_vol_bg":                 "#3A3244",
        "slider_vol_fill":               "#C496B8",
        "notch_color":                   "#D8AACC",
        "notch_opacity":                 170,
        "dropdown_curr_chap":            "#CC50AC",
        "dropdown_text":                 "#E8DCE8",
        "dropdown_time_text":            "#E397E3",
        "sidebar_text":                  "#E8DCE8",
        "sidebar_text_hover":            "#C496B8",
        "sidebar_opacity":               0.85,
        "library_bg":                    "#2C2634",
        "library_grid_bg":               "#2C2634",
        "library_row_one":               "#2C2634",
        "library_row_two":               "#342E3C",
        "library_item_hover_color":      "#CC50AC",
        "library_item_hover_alpha":      0.22,
        "library_title":                 "#D2CBA6",
        "library_author":                "#C8B0C8",
        "library_narrator":              "#9A869A",
        "library_elapsed":               "#C8B0C8",
        "library_total":                 "#C8B0C8",
        "library_percentage":            "#C496B8",
        "library_slider_bg":             "#3A3244",
        "library_slider_fill":           "#C496B8",
        "library_input_bg":              "#3A3244",
        "library_input_text":            "#F0E8F0",
        "settings_tab_hover_bg":         "#C496B8",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#1E1A24",
        "settings_theme_names_dimmed":   "#917991"
    },
    "Manderley": {
        "bg_deep":                       "#2E2B33",
        "bg_main":                       "#423E48",
        "bg_sidebar":                    "#2E2B33",
        "bg_dropdown":                   "#5A5562",
        "panel_opacity_hover":           0.93,
        "undo_hover":                    "#857593",
        "text":                          "#ECBEDF",
        "accent":                        "#A89AB5",
        "accent_light":                  "#C2B5CC",
        "accent_dark":                   "#6A607A",
        "slider_overall_bg":             "#5A5562",
        "slider_overall_fill":           "#9288A8",
        "slider_chapter_bg":             "#5A5562",
        "slider_chapter_fill":           "#A89AB5",
        "slider_vol_bg":                 "#423E48",
        "slider_vol_fill":               "#9288A8",
        "dropdown_curr_chap":            "#A89AB5",
        "sidebar_text_hover":            "#C2B5CC",
        "sidebar_opacity":               0.86,
        "settings_theme_names_dimmed":   "#876B81"
    },
    "Melnibonéan": {
        "bg_deep":                       "#2A353C",
        "bg_main":                       "#3E4A52",
        "bg_sidebar":                    "#2A353C",
        "bg_dropdown":                   "#55626B",
        "panel_opacity_hover":           0.9,
        "text":                          "#F0F3F0",
        "accent":                        "#A8C3C6",
        "accent_light":                  "#C2D6D9",
        "accent_dark":                   "#6F868A",
        "slider_overall_bg":             "#55626B",
        "slider_overall_fill":           "#8FAAAD",
        "slider_chapter_bg":             "#55626B",
        "slider_chapter_fill":           "#AFC9CC",
        "slider_vol_bg":                 "#3E4A52",
        "slider_vol_fill":               "#8FAAAD",
        "dropdown_curr_chap":            "#AFC9CC",
        "sidebar_text_hover":            "#C2D6D9",
        "sidebar_opacity":               0.82,
        "settings_theme_names_dimmed":   "#6F868A"
    },
    "Not the Only Fruit": {
        "bg_deep":                       "#2C3E50",
        "bg_main":                       "#34495E",
        "bg_sidebar":                    "#2C3E50",
        "bg_dropdown":                   "#34495E",
        "panel_opacity_hover":           0.9,
        "text":                          "#ECF0F1",
        "accent":                        "#E74C3C",
        "accent_light":                  "#F05948",
        "accent_dark":                   "#B02A1B",
        "button_play":                   "#FFC5BE",
        "slider_progress":               "#FFC5BE",
        "slider_overall_bg":             "#4A627A",
        "slider_overall_fill":           "#E74C3C",
        "slider_chapter_bg":             "#34495E",
        "slider_chapter_fill":           "#C0392B",
        "slider_vol_bg":                 "#2C3E50",
        "slider_vol_fill":               "#E74C3C",
        "dropdown_curr_chap":            "#E74C3C",
        "sidebar_text_hover":            "#F05948",
        "sidebar_opacity":               0.7,
        "settings_theme_names_dimmed":   "#CCF6F9",
        "placeholder_cover":             "#222D38",
        "placeholder_stats":             "#B3D5DE",
        "placeholder_tags":              "#EAADA6"
    },
    "Pink Institute": {
        "bg_deep":                       "#1A1428",
        "bg_main":                       "#241E34",
        "bg_sidebar":                    "#1A1428",
        "bg_dropdown":                   "#2E2842",
        "panel_opacity_hover":           0.92,
        "text":                          "#E5C4E5",
        "text_on_light_bg":              "#1A1428",
        "accent":                        "#B85878",
        "accent_light":                  "#D87A98",
        "accent_dark":                   "#783A4A",
        "button_text":                   "#291D4B",
        "slider_progress":               "#E5C4E5",
        "slider_overall_bg":             "#2E2842",
        "slider_overall_fill":           "#B85878",
        "slider_chapter_bg":             "#2E2842",
        "slider_chapter_fill":           "#D87A98",
        "slider_vol_bg":                 "#2E2842",
        "slider_vol_fill":               "#B85878",
        "notch_color":                   "#D87A98",
        "notch_opacity":                 170,
        "dropdown_curr_chap":            "#D87A98",
        "dropdown_text":                 "#E5C4E5",
        "dropdown_time_text":            "#E5C4E5",
        "sidebar_text":                  "#E5C4E5",
        "sidebar_text_hover":            "#C86A8A",
        "sidebar_opacity":               0.85,
        "library_bg":                    "#241E34",
        "library_grid_bg":               "#241E34",
        "library_row_one":               "#241E34",
        "library_row_two":               "#2C243C",
        "library_item_hover_color":      "#C86A8A",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#F0E8F0",
        "library_author":                "#B8A8C0",
        "library_narrator":              "#8A7898",
        "library_elapsed":               "#B8A8C0",
        "library_total":                 "#6A5A78",
        "library_percentage":            "#B85878",
        "library_slider_bg":             "#2E2842",
        "library_slider_fill":           "#B85878",
        "library_input_bg":              "#2E2842",
        "library_input_text":            "#E5C4E5",
        "settings_tab_hover_bg":         "#C86A8A",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#1A1428",
        "settings_theme_names_dimmed":   "#6A5A78"
    },
    "Piranesi": {
        "bg_deep":                       "#1A1E20",
        "bg_main":                       "#2A2E30",
        "bg_sidebar":                    "#1A1E20",
        "bg_dropdown":                   "#3A4042",
        "panel_opacity_hover":           0.91,
        "undo_hover":                    "#8E7A48",
        "text":                          "#F0ECDC",
        "text_on_light_bg":              "#1A1E20",
        "accent":                        "#B8A87A",
        "accent_light":                  "#CCBC8C",
        "accent_dark":                   "#7A6A48",
        "button_text":                   "#1A1E20",
        "slider_progress":               "#F0ECDC",
        "slider_overall_bg":             "#3A4042",
        "slider_overall_fill":           "#B8A87A",
        "slider_chapter_bg":             "#3A4042",
        "slider_chapter_fill":           "#CCBC8C",
        "slider_vol_bg":                 "#3A4042",
        "slider_vol_fill":               "#B8A87A",
        "notch_color":                   "#CCBC8C",
        "notch_opacity":                 160,
        "dropdown_curr_chap":            "#CCBC8C",
        "dropdown_text":                 "#F0ECDC",
        "dropdown_time_text":            "#8A8068",
        "sidebar_text":                  "#F0ECDC",
        "sidebar_text_hover":            "#C8B898",
        "sidebar_opacity":               0.84,
        "library_bg":                    "#2A2E30",
        "library_grid_bg":               "#2A2E30",
        "library_row_one":               "#2A2E30",
        "library_row_two":               "#323638",
        "library_item_hover_color":      "#C8B898",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#F0ECDC",
        "library_author":                "#B8AC8A",
        "library_narrator":              "#8A8068",
        "library_elapsed":               "#B8AC8A",
        "library_total":                 "#686258",
        "library_percentage":            "#B8A87A",
        "library_slider_bg":             "#3A4042",
        "library_slider_fill":           "#B8A87A",
        "library_input_bg":              "#3A4042",
        "library_input_text":            "#F0ECDC",
        "settings_tab_hover_bg":         "#C8B898",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#1A1E20",
        "settings_theme_names_dimmed":   "#686258"
    },
    "Plum Island": {
        "bg_deep":                       "#141E22",
        "bg_main":                       "#1E2A2E",
        "bg_sidebar":                    "#141E22",
        "bg_dropdown":                   "#2A3A42",
        "panel_opacity_hover":           0.92,
        "text":                          "#DEB9D1",
        "text_on_light_bg":              "#141E22",
        "accent":                        "#6A4A6A",
        "accent_light":                  "#8A5A8A",
        "accent_dark":                   "#3A2A4A",
        "button_text":                   "#141E22",
        "slider_progress":               "#DEB9D1",
        "slider_overall_bg":             "#2A3A42",
        "slider_overall_fill":           "#6A4A6A",
        "slider_chapter_bg":             "#2A3A42",
        "slider_chapter_fill":           "#8A5A8A",
        "slider_vol_bg":                 "#2A3A42",
        "slider_vol_fill":               "#6A4A6A",
        "notch_color":                   "#8A5A8A",
        "notch_opacity":                 170,
        "dropdown_curr_chap":            "#8A5A8A",
        "dropdown_text":                 "#E8ECF0",
        "dropdown_time_text":            "#DEB9D1",
        "sidebar_text":                  "#E8ECF0",
        "sidebar_text_hover":            "#9AA8B8",
        "sidebar_opacity":               0.85,
        "library_bg":                    "#1E2A2E",
        "library_grid_bg":               "#1E2A2E",
        "library_row_one":               "#1E2A2E",
        "library_row_two":               "#263238",
        "library_item_hover_color":      "#9AA8B8",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#E8ECF0",
        "library_author":                "#A8B4C0",
        "library_narrator":              "#808C98",
        "library_elapsed":               "#A8B4C0",
        "library_total":                 "#58646C",
        "library_percentage":            "#6A4A6A",
        "library_slider_bg":             "#2A3A42",
        "library_slider_fill":           "#6A4A6A",
        "library_input_bg":              "#2A3A42",
        "library_input_text":            "#E8ECF0",
        "settings_tab_hover_bg":         "#9AA8B8",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#141E22",
        "settings_theme_names_dimmed":   "#DE8ACF"
    },
    "Pyke": {
        "bg_deep":                       "#141A1E",
        "bg_main":                       "#1E262E",
        "bg_sidebar":                    "#141A1E",
        "bg_dropdown":                   "#2A343E",
        "bg_image":                      "img/pyke.png",
        "panel_opacity_hover":           0.93,
        "text":                          "#D8E4EC",
        "text_on_light_bg":              "#141A1E",
        "accent":                        "#6A8A9A",
        "accent_light":                  "#7A9AAC",
        "accent_dark":                   "#4A5A6A",
        "button_text":                   "#141A1E",
        "slider_progress":               "#D8E4EC",
        "slider_overall_bg":             "#2A343E",
        "slider_overall_fill":           "#6A8A9A",
        "slider_chapter_bg":             "#2A343E",
        "slider_chapter_fill":           "#7A9AAC",
        "slider_vol_bg":                 "#2A343E",
        "slider_vol_fill":               "#6A8A9A",
        "notch_color":                   "#7A9AAC",
        "notch_opacity":                 160,
        "dropdown_curr_chap":            "#7A9AAC",
        "dropdown_text":                 "#D8E4EC",
        "dropdown_time_text":            "#7A8E9C",
        "sidebar_text":                  "#D8E4EC",
        "sidebar_text_hover":            "#6A8A9A",
        "sidebar_opacity":               0.86,
        "library_bg":                    "#1E262E",
        "library_grid_bg":               "#1E262E",
        "library_row_one":               "#1E262E",
        "library_row_two":               "#222E36",
        "library_item_hover_color":      "#6A8A9A",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#D8E4EC",
        "library_author":                "#9AACB8",
        "library_narrator":              "#7A8E9C",
        "library_elapsed":               "#9AACB8",
        "library_total":                 "#5A6A76",
        "library_percentage":            "#6A8A9A",
        "library_slider_bg":             "#2A343E",
        "library_slider_fill":           "#6A8A9A",
        "library_input_bg":              "#2A343E",
        "library_input_text":            "#D8E4EC",
        "settings_tab_hover_bg":         "#6A8A9A",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#D8E4EC",
        "settings_theme_names_dimmed":   "#5A6A76",
        "gradient_bg_start":             "#141A1E",
        "gradient_bg_end":               "#2A3A42",
        "gradient_bg_angle":             115
    },
    "Razorgirl": {
        "bg_deep":                       "#0A0F1A",
        "bg_main":                       "#1A1F2E",
        "bg_sidebar":                    "#0A0F1A",
        "bg_dropdown":                   "#1A1F2E",
        "panel_opacity_hover":           0.9,
        "undo_hover":                    "#CE06A1",
        "text":                          "#A5C4E2",
        "accent":                        "#00FFFF",
        "accent_light":                  "#66FFFF",
        "accent_dark":                   "#009999",
        "button_text":                   "#2A0A60",
        "slider_progress":               "#ADF6EF",
        "slider_overall_bg":             "#2A344A",
        "slider_overall_fill":           "#A336FC",
        "slider_chapter_bg":             "#1A1F2E",
        "slider_chapter_fill":           "#00CCCC",
        "slider_vol_bg":                 "#0A0F1A",
        "slider_vol_fill":               "#00FFFF",
        "notch_color":                   "#EC6ED9",
        "notch_opacity":                 156,
        "dropdown_curr_chap":            "#7F13D7",
        "dropdown_expand":               "#7F13D7",
        "sidebar_text_hover":            "#66FFFF",
        "sidebar_opacity":               0.7,
        "settings_tab_hover_opacity":    0.9,
        "settings_tab_hover_text":       "#0B0A0A",
        "settings_theme_names_dimmed":   "#AFDFEE"
    },
    "Rebma": {
        "bg_deep":                       "#1A2624",
        "bg_main":                       "#243432",
        "bg_sidebar":                    "#1A2624",
        "bg_dropdown":                   "#304442",
        "panel_opacity_hover":           0.91,
        "text":                          "#E0ECE8",
        "text_on_light_bg":              "#1A2624",
        "accent":                        "#78B8A0",
        "accent_light":                  "#90CCB8",
        "accent_dark":                   "#4A8A72",
        "button_text":                   "#1A2624",
        "slider_progress":               "#E0ECE8",
        "slider_overall_bg":             "#304442",
        "slider_overall_fill":           "#78B8A0",
        "slider_chapter_bg":             "#304442",
        "slider_chapter_fill":           "#90CCB8",
        "slider_vol_bg":                 "#304442",
        "slider_vol_fill":               "#78B8A0",
        "notch_color":                   "#90CCB8",
        "notch_opacity":                 170,
        "dropdown_curr_chap":            "#90CCB8",
        "dropdown_text":                 "#E0ECE8",
        "dropdown_time_text":            "#7A9E94",
        "sidebar_text":                  "#E0ECE8",
        "sidebar_text_hover":            "#78B8A0",
        "sidebar_opacity":               0.84,
        "library_bg":                    "#243432",
        "library_grid_bg":               "#243432",
        "library_row_one":               "#243432",
        "library_row_two":               "#2C3C3A",
        "library_item_hover_color":      "#78B8A0",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#E8F0EC",
        "library_author":                "#A8CCC0",
        "library_narrator":              "#7A9E94",
        "library_elapsed":               "#A8CCC0",
        "library_total":                 "#58706A",
        "library_percentage":            "#78B8A0",
        "library_slider_bg":             "#304442",
        "library_slider_fill":           "#78B8A0",
        "library_input_bg":              "#304442",
        "library_input_text":            "#E8F0EC",
        "settings_tab_hover_bg":         "#78B8A0",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#1A2624",
        "settings_theme_names_dimmed":   "#58706A"
    },
    "Red Rising": {
        "bg_deep":                       "#2B0000",
        "bg_main":                       "#4A0000",
        "bg_sidebar":                    "#2B0000",
        "bg_dropdown":                   "#4A0000",
        "panel_opacity_hover":           0.9,
        "text":                          "#FFCCCC",
        "accent":                        "#FF0000",
        "accent_light":                  "#FF6666",
        "accent_dark":                   "#800000",
        "button_text":                   "#000000",
        "slider_progress":               "#F88A8A",
        "slider_overall_bg":             "#1A0000",
        "slider_overall_fill":           "#FF0000",
        "slider_chapter_bg":             "#2B0000",
        "slider_chapter_fill":           "#A30000",
        "slider_vol_bg":                 "#1A0000",
        "slider_vol_fill":               "#FF4D4D",
        "dropdown_curr_chap":            "#FF0000",
        "sidebar_text_hover":            "#FF6666",
        "sidebar_opacity":               0.7,
        "search_error_text":             "#CC0000",
        "settings_theme_names_dimmed":   "#FFFFFF"
    },
    "Rivendell": {
        "bg_deep":                       "#E0E7E9",
        "bg_main":                       "#F0FFF0",
        "bg_sidebar":                    "#E0E7E9",
        "bg_dropdown":                   "#CFD8DC",
        "panel_opacity_hover":           0.95,
        "text":                          "#263238",
        "text_on_light_bg":              "#1D3022",
        "accent":                        "#66BB6A",
        "accent_light":                  "#81C784",
        "accent_dark":                   "#388E3C",
        "slider_overall_bg":             "#B0BEC5",
        "slider_overall_fill":           "#4CAF50",
        "slider_chapter_bg":             "#CFD8DC",
        "slider_chapter_fill":           "#81C784",
        "slider_vol_bg":                 "#E0E7E9",
        "slider_vol_fill":               "#66BB6A",
        "dropdown_curr_chap":            "#81C784",
        "sidebar_text_hover":            "#81C784",
        "sidebar_opacity":               0.9,
        "library_bg":                    "#D7EBB4",
        "library_row_one":               "#FFFFFF",
        "library_row_two":               "#FFFFFF",
        "settings_theme_names_dimmed":   "#2C464C"
    },
    "Rose Code": {
        "bg_deep":                       "#2A2030",
        "bg_main":                       "#3A2A3E",
        "bg_sidebar":                    "#2A2030",
        "bg_dropdown":                   "#4A3850",
        "panel_opacity_hover":           0.92,
        "text":                          "#EDECE7",
        "text_on_light_bg":              "#2A2030",
        "accent":                        "#C45A7A",
        "accent_light":                  "#D87A98",
        "accent_dark":                   "#8A3A58",
        "button_text":                   "#2A2030",
        "slider_progress":               "#F2E8EC",
        "slider_overall_bg":             "#4A3850",
        "slider_overall_fill":           "#C45A7A",
        "slider_chapter_bg":             "#4A3850",
        "slider_chapter_fill":           "#D87A98",
        "slider_vol_bg":                 "#4A3850",
        "slider_vol_fill":               "#C45A7A",
        "notch_color":                   "#D87A98",
        "notch_opacity":                 170,
        "dropdown_curr_chap":            "#D87A98",
        "dropdown_text":                 "#EEEBC6",
        "dropdown_time_text":            "#EEEBC6",
        "sidebar_text":                  "#F2E8EC",
        "sidebar_text_hover":            "#C86A8A",
        "sidebar_opacity":               0.85,
        "library_bg":                    "#3A2A3E",
        "library_grid_bg":               "#3A2A3E",
        "library_row_one":               "#3A2A3E",
        "library_row_two":               "#423246",
        "library_item_hover_color":      "#C86A8A",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#F2E8EC",
        "library_author":                "#C8A8B8",
        "library_narrator":              "#9A8090",
        "library_elapsed":               "#C8A8B8",
        "library_total":                 "#6A5070",
        "library_percentage":            "#C45A7A",
        "library_slider_bg":             "#4A3850",
        "library_slider_fill":           "#C45A7A",
        "library_input_bg":              "#4A3850",
        "library_input_text":            "#F2E8EC",
        "settings_tab_hover_bg":         "#C86A8A",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#2A2030",
        "settings_theme_names_dimmed":   "#9B78A3",
        "tag_list_text":                 "#E6B9CA"
    },
    "Shade of the Evening": {
        "bg_deep":                       "#0A0A1A",
        "bg_main":                       "#11162B",
        "bg_sidebar":                    "#0A0A1A",
        "bg_dropdown":                   "#1A2140",
        "panel_opacity_hover":           0.92,
        "text":                          "#E9DCB3",
        "accent":                        "#3A5A8A",
        "accent_light":                  "#5B80B8",
        "accent_dark":                   "#1E3A5A",
        "slider_overall_bg":             "#1A2140",
        "slider_overall_fill":           "#4A6FA5",
        "slider_chapter_bg":             "#1A2140",
        "slider_chapter_fill":           "#5B80B8",
        "slider_vol_bg":                 "#11162B",
        "slider_vol_fill":               "#4A6FA5",
        "dropdown_curr_chap":            "#5B80B8",
        "sidebar_text_hover":            "#5B80B8",
        "sidebar_opacity":               0.85,
        "library_bg":                    "#11162B",
        "library_row_one":               "#1A2140",
        "library_row_two":               "#11162B",
        "library_item_hover_color":      "#2576F4",
        "library_item_hover_alpha":      0.22,
        "library_title":                 "#7ED6E0",
        "library_author":                "#B4E5EA",
        "library_narrator":              "#8192AD",
        "library_year":                  "#8192AD",
        "library_elapsed":               "#B4E5EA",
        "library_total":                 "#B4E5EA",
        "library_percentage":            "#E9DCB3",
        "library_slider_bg":             "#526480",
        "library_slider_fill":           "#0731AB",
        "library_input_bg":              "#0A0A1A",
        "settings_theme_names_dimmed":   "#41BAEA",
        "gradient_bg_start":             "#0A0A1A",
        "gradient_bg_end":               "#1A2860",
        "gradient_bg_angle":             135,
        "gradient_accent_start":         "#4A6FA5",
        "gradient_accent_end":           "#2A4A7A",
        "gradient_accent_angle":         90,
        "gradient_slider_fill_start":    "#4A6FA5",
        "gradient_slider_fill_end":      "#6A8FBD",
        "gradient_slider_fill_angle":    0
    },
    "Shai-Hulud": {
        "bg_deep":                       "#4A3B2D",
        "bg_main":                       "#6B5A49",
        "bg_sidebar":                    "#4A3B2D",
        "bg_dropdown":                   "#6B5A49",
        "panel_opacity_hover":           0.9,
        "text":                          "#F5F5DC",
        "accent":                        "#D4A85C",
        "accent_light":                  "#E2CDA7",
        "accent_dark":                   "#A47B3C",
        "slider_overall_bg":             "#8C7B6A",
        "slider_overall_fill":           "#D4A85C",
        "slider_chapter_bg":             "#6B5A49",
        "slider_chapter_fill":           "#B48B4C",
        "slider_vol_bg":                 "#4A3B2D",
        "slider_vol_fill":               "#D4A85C",
        "dropdown_curr_chap":            "#D4A85C",
        "sidebar_text_hover":            "#E2CDA7",
        "sidebar_opacity":               0.6,
        "settings_theme_names_dimmed":   "#B1A792",
        "gradient_bg_start":             "#4A3B2D",
        "gradient_bg_end":               "#7E6B58",
        "gradient_bg_angle":             115,
        "gradient_sidebar_start":        "#3E3024",
        "gradient_sidebar_end":          "#5A4838",
        "gradient_sidebar_angle":        180,
        "gradient_accent_start":         "#D4A85C",
        "gradient_accent_end":           "#C49A4A",
        "gradient_accent_angle":         45,
        "gradient_slider_fill_start":    "#D4A85C",
        "gradient_slider_fill_end":      "#E8BC6C",
        "gradient_slider_fill_angle":    90
    },
    "Shrike": {
        "bg_deep":                       "#1B2B3B",
        "bg_main":                       "#2E4050",
        "bg_sidebar":                    "#1B2B3B",
        "bg_dropdown":                   "#4A5F6F",
        "panel_opacity_hover":           0.94,
        "text":                          "#CDDBE7",
        "accent":                        "#5E8299",
        "accent_light":                  "#7A9BB5",
        "accent_dark":                   "#3A5A72",
        "slider_overall_bg":             "#4A5F6F",
        "slider_overall_fill":           "#6A8BA0",
        "slider_chapter_bg":             "#4A5F6F",
        "slider_chapter_fill":           "#7A9BB5",
        "slider_vol_bg":                 "#2E4050",
        "slider_vol_fill":               "#7A9BB5",
        "dropdown_curr_chap":            "#AC668B",
        "sidebar_text_hover":            "#7A9BB5",
        "sidebar_opacity":               0.88,
        "settings_theme_names_dimmed":   "#CDE1E1"
    },
    "Sitting in the Wing Chair": {
        "bg_deep":                       "#1E1814",
        "bg_main":                       "#2E241E",
        "bg_sidebar":                    "#1E1814",
        "bg_dropdown":                   "#4A3A2E",
        "panel_opacity_hover":           0.9,
        "text":                          "#E5E6B3",
        "accent":                        "#A84C34",
        "accent_light":                  "#CC6C54",
        "accent_dark":                   "#7A3420",
        "slider_overall_bg":             "#4A3A2E",
        "slider_overall_fill":           "#B85C44",
        "slider_chapter_bg":             "#4A3A2E",
        "slider_chapter_fill":           "#CC6C54",
        "slider_vol_bg":                 "#2E241E",
        "slider_vol_fill":               "#B85C44",
        "dropdown_curr_chap":            "#CC6C54",
        "sidebar_text_hover":            "#CC6C54",
        "sidebar_opacity":               0.82,
        "settings_theme_names_dimmed":   "#ECECAE"
    },
    "Slow Regard": {
        "bg_deep":                       "#3A2A1E",
        "bg_main":                       "#543F2C",
        "bg_sidebar":                    "#3A2A1E",
        "bg_dropdown":                   "#765A40",
        "panel_opacity_hover":           0.91,
        "text":                          "#FFF2E0",
        "accent":                        "#E4A859",
        "accent_light":                  "#F0BC6C",
        "accent_dark":                   "#B87E3A",
        "slider_overall_bg":             "#765A40",
        "slider_overall_fill":           "#E4A859",
        "slider_chapter_bg":             "#765A40",
        "slider_chapter_fill":           "#F0BC6C",
        "slider_vol_bg":                 "#543F2C",
        "slider_vol_fill":               "#E4A859",
        "dropdown_curr_chap":            "#F0BC6C",
        "sidebar_text_hover":            "#F0BC6C",
        "sidebar_opacity":               0.84,
        "settings_theme_names_dimmed":   "#B87E3A"
    },
    "Storm's End": {
        "bg_deep":                       "#0A0A0A",
        "bg_main":                       "#141414",
        "bg_sidebar":                    "#0A0A0A",
        "bg_dropdown":                   "#1E1E1E",
        "bg_image":                      "img/stormsend.png",
        "panel_opacity_hover":           0.91,
        "undo_hover":                    "#444444",
        "text":                          "#D4AA3A",
        "text_on_light_bg":              "#0A0A0A",
        "accent":                        "#D4AA3A",
        "accent_light":                  "#E4BA4A",
        "accent_dark":                   "#9A7A2A",
        "button_text":                   "#0A0A0A",
        "slider_progress":               "#F2E8D0",
        "slider_overall_bg":             "#2A2A2A",
        "slider_overall_fill":           "#D4AA3A",
        "slider_chapter_bg":             "#2A2A2A",
        "slider_chapter_fill":           "#E4BA4A",
        "slider_vol_bg":                 "#2A2A2A",
        "slider_vol_fill":               "#D4AA3A",
        "notch_color":                   "#E4BA4A",
        "notch_opacity":                 160,
        "dropdown_curr_chap":            "#6C5825",
        "dropdown_text":                 "#D4AA3A",
        "dropdown_time_text":            "#D4AA3A",
        "sidebar_text":                  "#F2E8D0",
        "sidebar_text_hover":            "#D4AA3A",
        "sidebar_opacity":               0.84,
        "library_bg":                    "#141414",
        "library_grid_bg":               "#141414",
        "library_row_one":               "#141414",
        "library_row_two":               "#1C1C1C",
        "library_item_hover_color":      "#D4AA3A",
        "library_item_hover_alpha":      0.45,
        "library_title":                 "#F2E8D0",
        "library_author":                "#B8A878",
        "library_narrator":              "#8A7A58",
        "library_elapsed":               "#B8A878",
        "library_total":                 "#6A6A5A",
        "library_percentage":            "#D4AA3A",
        "library_slider_bg":             "#2A2A2A",
        "library_slider_fill":           "#D4AA3A",
        "library_input_bg":              "#2A2A2A",
        "library_input_text":            "#F2E8D0",
        "settings_tab_hover_bg":         "#D4AA3A",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#0A0A0A",
        "settings_theme_names_dimmed":   "#6A6A5A"
    },
    "Sunspear": {
        "bg_deep":                       "#2E1E14",
        "bg_main":                       "#4A3020",
        "bg_sidebar":                    "#2E1E14",
        "bg_dropdown":                   "#5A3A28",
        "bg_image":                      "img/sunspear.png",
        "panel_opacity_hover":           0.92,
        "text":                          "#F2D8C0",
        "text_on_light_bg":              "#2E1E14",
        "accent":                        "#E87A3A",
        "accent_light":                  "#F0944C",
        "accent_dark":                   "#A85A22",
        "button_text":                   "#2E1E14",
        "slider_progress":               "#F2D8C0",
        "slider_overall_bg":             "#5A3A28",
        "slider_overall_fill":           "#E87A3A",
        "slider_chapter_bg":             "#5A3A28",
        "slider_chapter_fill":           "#F0944C",
        "slider_vol_bg":                 "#5A3A28",
        "slider_vol_fill":               "#E87A3A",
        "notch_color":                   "#F0944C",
        "notch_opacity":                 180,
        "dropdown_curr_chap":            "#F0944C",
        "dropdown_text":                 "#F2D8C0",
        "dropdown_time_text":            "#C09068",
        "sidebar_text":                  "#F2D8C0",
        "sidebar_text_hover":            "#E87A3A",
        "sidebar_opacity":               0.84,
        "library_bg":                    "#4A3020",
        "library_grid_bg":               "#4A3020",
        "library_row_one":               "#4A3020",
        "library_row_two":               "#523828",
        "library_item_hover_color":      "#E87A3A",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#F2D8C0",
        "library_author":                "#D4A878",
        "library_narrator":              "#C09068",
        "library_elapsed":               "#D4A878",
        "library_total":                 "#A07858",
        "library_percentage":            "#E87A3A",
        "library_slider_bg":             "#5A3A28",
        "library_slider_fill":           "#E87A3A",
        "library_input_bg":              "#5A3A28",
        "library_input_text":            "#F2D8C0",
        "settings_tab_hover_bg":         "#E87A3A",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#F2D8C0",
        "settings_theme_names_dimmed":   "#A07858",
        "gradient_bg_start":             "#2E1E14",
        "gradient_bg_end":               "#5A3A28",
        "gradient_bg_angle":             135,
        "gradient_accent_start":         "#E87A3A",
        "gradient_accent_end":           "#C06A2A",
        "gradient_accent_angle":         45
    },
    "The Color Purple": {
        "bg_deep":                       "#0D001A",
        "bg_main":                       "#1A002E",
        "bg_sidebar":                    "#120024",
        "bg_dropdown":                   "#120024",
        "panel_opacity_hover":           0.9,
        "text":                          "#EF94E9",
        "accent":                        "#7B2CBF",
        "accent_light":                  "#9D4EDD",
        "accent_dark":                   "#5A189A",
        "slider_overall_bg":             "#4B0082",
        "slider_overall_fill":           "#BA7BBA",
        "slider_chapter_bg":             "#330066",
        "slider_chapter_fill":           "#950E95",
        "slider_vol_bg":                 "#220044",
        "slider_vol_fill":               "#7B2CBF",
        "dropdown_curr_chap":            "#C8A2C8",
        "sidebar_text_hover":            "#9D4EDD",
        "sidebar_opacity":               0.6,
        "settings_theme_names_dimmed":   "#6B2FAD"
    },
    "The Eyrie": {
        "bg_deep":                       "#1E2A30",
        "bg_main":                       "#2E3A42",
        "bg_sidebar":                    "#1E2A30",
        "bg_dropdown":                   "#3E4E58",
        "bg_image":                      "img/theyrie.png",
        "panel_opacity_hover":           0.92,
        "text":                          "#E8F0F2",
        "text_on_light_bg":              "#1E2A30",
        "accent":                        "#8AB8CC",
        "accent_light":                  "#A2C8DC",
        "accent_dark":                   "#5A7A8A",
        "button_text":                   "#1E2A30",
        "slider_progress":               "#E8F0F2",
        "slider_overall_bg":             "#3E4E58",
        "slider_overall_fill":           "#8AB8CC",
        "slider_chapter_bg":             "#3E4E58",
        "slider_chapter_fill":           "#A2C8DC",
        "slider_vol_bg":                 "#3E4E58",
        "slider_vol_fill":               "#8AB8CC",
        "notch_color":                   "#A2C8DC",
        "notch_opacity":                 170,
        "dropdown_curr_chap":            "#A2C8DC",
        "dropdown_text":                 "#E8F0F2",
        "dropdown_time_text":            "#8AA0AC",
        "sidebar_text":                  "#E8F0F2",
        "sidebar_text_hover":            "#AAC8D8",
        "sidebar_opacity":               0.85,
        "library_bg":                    "#2E3A42",
        "library_grid_bg":               "#2E3A42",
        "library_row_one":               "#2E3A42",
        "library_row_two":               "#32424A",
        "library_item_hover_color":      "#AAC8D8",
        "library_item_hover_alpha":      0.35,
        "library_title":                 "#E8F0F2",
        "library_author":                "#A8BCC8",
        "library_narrator":              "#8AA0AC",
        "library_elapsed":               "#A8BCC8",
        "library_total":                 "#6A7A84",
        "library_percentage":            "#8AB8CC",
        "library_slider_bg":             "#3E4E58",
        "library_slider_fill":           "#8AB8CC",
        "library_input_bg":              "#3E4E58",
        "library_input_text":            "#E8F0F2",
        "settings_tab_hover_bg":         "#AAC8D8",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#1E2A30",
        "settings_theme_names_dimmed":   "#6A7A84"
    },
    "The Overlook": {
        "bg_deep":                       "#2E1E14",
        "bg_main":                       "#341A25",
        "bg_sidebar":                    "#2E1E14",
        "bg_dropdown":                   "#6B4530",
        "bg_image":                      "img/overlook.png",
        "panel_opacity_hover":           0.93,
        "text":                          "#FFB692",
        "accent":                        "#F05632",
        "accent_light":                  "#BB0606",
        "accent_dark":                   "#8A5428",
        "button_text":                   "#F6EBA9",
        "slider_progress":               "#F6EBA9",
        "slider_overall_bg":             "#B41E37",
        "slider_overall_fill":           "#F05632",
        "slider_chapter_bg":             "#B41E37",
        "slider_chapter_fill":           "#F05632",
        "slider_vol_bg":                 "#4A2E1E",
        "slider_vol_fill":               "#B41E37",
        "dropdown_curr_chap":            "#BB0606",
        "dropdown_text":                 "#F05632",
        "dropdown_expand":               "#210606",
        "sidebar_text_hover":            "#BB0606",
        "sidebar_opacity":               0.86,
        "library_bg":                    "#22060E",
        "library_grid_bg":               "#22060E",
        "library_row_one":               "#22060E",
        "library_row_two":               "#2F0512",
        "library_item_hover_color":      "#E21685",
        "library_item_hover_alpha":      0.12,
        "library_title":                 "#E9AF1D",
        "library_author":                "#F05632",
        "library_narrator":              "#BA611F",
        "library_year":                  "#BA611F",
        "library_elapsed":               "#E9AF1D",
        "library_total":                 "#E9AF1D",
        "library_percentage":            "#E9AF1D",
        "library_slider_bg":             "#4D1333",
        "library_slider_fill":           "#F05632",
        "library_input_bg":              "#22060E",
        "library_input_text":            "#F05632",
        "settings_theme_names_dimmed":   "#F05632"
    },
    "Tigana": {
        "bg_deep":                       "#121826",
        "bg_main":                       "#1E2A3E",
        "bg_sidebar":                    "#121826",
        "bg_dropdown":                   "#30405C",
        "panel_opacity_hover":           0.93,
        "text":                          "#F0ECDC",
        "accent":                        "#C0B89C",
        "accent_light":                  "#D8D0B4",
        "accent_dark":                   "#8A8268",
        "slider_overall_bg":             "#30405C",
        "slider_overall_fill":           "#C1B081",
        "slider_chapter_bg":             "#30405C",
        "slider_chapter_fill":           "#EEEEEE",
        "slider_vol_bg":                 "#1E2A3E",
        "slider_vol_fill":               "#E8E2D0",
        "dropdown_curr_chap":            "#4A1530",
        "sidebar_text_hover":            "#D8D0B4",
        "sidebar_opacity":               0.86,
        "library_row_one":               "#230B17",
        "library_row_two":               "#1C0812",
        "library_item_hover_alpha":      0.12,
        "library_title":                 "C0B89C",
        "settings_theme_names_dimmed":   "#8A8268"
    },
    "Turquoise Days": {
        "bg_deep":                       "#0A1A24",
        "bg_main":                       "#0E2430",
        "bg_sidebar":                    "#0A1A24",
        "bg_dropdown":                   "#143440",
        "panel_opacity_hover":           0.91,
        "text":                          "#E0F0EE",
        "text_on_light_bg":              "#0A1A24",
        "accent":                        "#2AA8A0",
        "accent_light":                  "#3AB8B0",
        "accent_dark":                   "#1A6A66",
        "button_text":                   "#0A1A24",
        "slider_progress":               "#E0F0EE",
        "slider_overall_bg":             "#143440",
        "slider_overall_fill":           "#2AA8A0",
        "slider_chapter_bg":             "#143440",
        "slider_chapter_fill":           "#3AB8B0",
        "slider_vol_bg":                 "#143440",
        "slider_vol_fill":               "#2AA8A0",
        "notch_color":                   "#3AB8B0",
        "notch_opacity":                 170,
        "dropdown_curr_chap":            "#3AB8B0",
        "dropdown_text":                 "#E0F0EE",
        "dropdown_time_text":            "#6A908C",
        "sidebar_text":                  "#E0F0EE",
        "sidebar_text_hover":            "#3AB8B0",
        "sidebar_opacity":               0.84,
        "library_bg":                    "#0E2430",
        "library_grid_bg":               "#0E2430",
        "library_row_one":               "#0E2430",
        "library_row_two":               "#142C38",
        "library_item_hover_color":      "#3AB8B0",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#E0F0EE",
        "library_author":                "#90B8B4",
        "library_narrator":              "#6A908C",
        "library_elapsed":               "#90B8B4",
        "library_total":                 "#4A6A68",
        "library_percentage":            "#2AA8A0",
        "library_slider_bg":             "#143440",
        "library_slider_fill":           "#2AA8A0",
        "library_input_bg":              "#143440",
        "library_input_text":            "#E0F0EE",
        "settings_tab_hover_bg":         "#3AB8B0",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#0A1A24",
        "settings_theme_names_dimmed":   "#4A6A68"
    },
    "Urras": {
        "bg_deep":                       "#001219",
        "bg_main":                       "#001B24",
        "bg_sidebar":                    "#001219",
        "bg_dropdown":                   "#001B24",
        "panel_opacity_hover":           0.9,
        "text":                          "#E9D8A6",
        "accent":                        "#0A9396",
        "accent_light":                  "#94D2BD",
        "accent_dark":                   "#005F73",
        "slider_overall_bg":             "#003547",
        "slider_overall_fill":           "#94D2BD",
        "slider_chapter_bg":             "#002A38",
        "slider_chapter_fill":           "#83C5BE",
        "slider_vol_bg":                 "#001219",
        "slider_vol_fill":               "#0A9396",
        "dropdown_curr_chap":            "#178083",
        "sidebar_text_hover":            "#94D2BD",
        "sidebar_opacity":               0.6,
        "library_bg":                    "#001B24",
        "library_grid_bg":               "#152C24",
        "library_row_one":               "#001B24",
        "library_row_two":               "#0A0E29",
        "library_item_hover_color":      "#64D8CF",
        "library_item_hover_alpha":      0.1,
        "library_title":                 "#7ACAC9",
        "library_author":                "#22BDDD",
        "library_narrator":              "#25A3BD",
        "library_year":                  "#E9D8A6",
        "library_elapsed":               "#9CBAD4",
        "library_total":                 "#9CBAD4",
        "library_percentage":            "#9CBAD4",
        "library_slider_bg":             "#205F60",
        "library_slider_fill":           "#CDC3A3",
        "library_input_bg":              "#06263F",
        "library_input_text":            "#E9D8A6",
        "settings_theme_names_dimmed":   "#D3EBEC"
    },
    "Violeta": {
        "bg_deep":                       "#140A1A",
        "bg_main":                       "#1E1028",
        "bg_sidebar":                    "#140A1A",
        "bg_dropdown":                   "#2A1838",
        "panel_opacity_hover":           0.93,
        "text":                          "#F0E8F4",
        "text_on_light_bg":              "#140A1A",
        "accent":                        "#B84AB8",
        "accent_light":                  "#D46AD4",
        "accent_dark":                   "#7A2A7A",
        "button_text":                   "#140A1A",
        "slider_progress":               "#F0E8F4",
        "slider_overall_bg":             "#2A1838",
        "slider_overall_fill":           "#B84AB8",
        "slider_chapter_bg":             "#2A1838",
        "slider_chapter_fill":           "#D46AD4",
        "slider_vol_bg":                 "#2A1838",
        "slider_vol_fill":               "#B84AB8",
        "notch_color":                   "#D46AD4",
        "notch_opacity":                 180,
        "dropdown_curr_chap":            "#D46AD4",
        "dropdown_text":                 "#F0E8F4",
        "dropdown_time_text":            "#A080B0",
        "sidebar_text":                  "#F0E8F4",
        "sidebar_text_hover":            "#D46AD4",
        "sidebar_opacity":               0.86,
        "library_bg":                    "#1E1028",
        "library_grid_bg":               "#1E1028",
        "library_row_one":               "#1E1028",
        "library_row_two":               "#261830",
        "library_item_hover_color":      "#D46AD4",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#F0E8F4",
        "library_author":                "#C8A8D8",
        "library_narrator":              "#A080B0",
        "library_elapsed":               "#C8A8D8",
        "library_total":                 "#6A5078",
        "library_percentage":            "#B84AB8",
        "library_slider_bg":             "#2A1838",
        "library_slider_fill":           "#B84AB8",
        "library_input_bg":              "#2A1838",
        "library_input_text":            "#F0E8F4",
        "settings_tab_hover_bg":         "#D46AD4",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#140A1A",
        "settings_theme_names_dimmed":   "#CFA3E8"
    },
    "Waknuk": {
        "bg_deep":                       "#1E2229",
        "bg_main":                       "#2E343E",
        "bg_sidebar":                    "#1E2229",
        "bg_dropdown":                   "#464E5C",
        "panel_opacity_hover":           0.92,
        "undo_hover":                    "#777777",
        "text":                          "#A4AFC1",
        "accent":                        "#7E8DA8",
        "accent_light":                  "#A2B2CC",
        "accent_dark":                   "#4E5A70",
        "slider_overall_bg":             "#464E5C",
        "slider_overall_fill":           "#8A9BB5",
        "slider_chapter_bg":             "#464E5C",
        "slider_chapter_fill":           "#A2B2CC",
        "slider_vol_bg":                 "#2E343E",
        "slider_vol_fill":               "#8A9BB5",
        "dropdown_curr_chap":            "#A2B2CC",
        "sidebar_text_hover":            "#A2B2CC",
        "sidebar_opacity":               0.85,
        "settings_theme_names_dimmed":   "#726A6A"
    },
    "Wasp Factory": {
        "bg_deep":                       "#121212",
        "bg_main":                       "#1E1E1E",
        "bg_sidebar":                    "#121212",
        "bg_dropdown":                   "#1E1E1E",
        "panel_opacity_hover":           0.9,
        "text":                          "#E8BC6C",
        "accent":                        "#E67E22",
        "accent_light":                  "#F39C12",
        "accent_dark":                   "#A04000",
        "button_text":                   "#320E0E",
        "slider_progress":               "#FCD586",
        "slider_overall_bg":             "#333333",
        "slider_overall_fill":           "#E67E22",
        "slider_chapter_bg":             "#252525",
        "slider_chapter_fill":           "#8B4513",
        "slider_vol_bg":                 "#121212",
        "slider_vol_fill":               "#D35400",
        "dropdown_curr_chap":            "#8B4513",
        "sidebar_text_hover":            "#F39C12",
        "sidebar_opacity":               0.8,
        "settings_theme_names_dimmed":   "#BCB6BB"
    },
    "Waste Lands": {
        "bg_deep":                       "#1A1A1A",
        "bg_main":                       "#2F2F2F",
        "bg_sidebar":                    "#1A1A1A",
        "bg_dropdown":                   "#2F2F2F",
        "panel_opacity_hover":           0.87,
        "text":                          "#E8D8B2",
        "accent":                        "#B8860B",
        "accent_light":                  "#DAA520",
        "accent_dark":                   "#8B6914",
        "slider_overall_bg":             "#404040",
        "slider_overall_fill":           "#B8860B",
        "slider_chapter_bg":             "#2F2F2F",
        "slider_chapter_fill":           "#A67C00",
        "slider_vol_bg":                 "#1A1A1A",
        "slider_vol_fill":               "#B8860B",
        "dropdown_curr_chap":            "#B8860B",
        "sidebar_text_hover":            "#DAA520",
        "sidebar_opacity":               0.68,
        "settings_theme_names_dimmed":   "#839CA2"
    },
    "Winterfell": {
        "bg_deep":                       "#212529",
        "bg_main":                       "#343A40",
        "bg_sidebar":                    "#212529",
        "bg_dropdown":                   "#343A40",
        "bg_image":                      "img/winterfell.png",
        "panel_opacity_hover":           0.9,
        "text":                          "#DDFBFB",
        "text_on_light_bg":              "#111111",
        "accent":                        "#6C757D",
        "accent_light":                  "#DEE2E6",
        "accent_dark":                   "#343A40",
        "button_text":                   "#BBBBBB",
        "button_play":                   "#9BE4E5",
        "slider_progress":               "#EEEEEE",
        "slider_overall_bg":             "#495057",
        "slider_overall_fill":           "#9BE4E5",
        "slider_chapter_bg":             "#343A40",
        "slider_chapter_fill":           "#CED4DA",
        "slider_vol_bg":                 "#212529",
        "slider_vol_fill":               "#ADB5BD",
        "dropdown_curr_chap":            "#829D98",
        "sidebar_text_hover":            "#DEE2E6",
        "sidebar_opacity":               0.6,
        "settings_theme_names_dimmed":   "#DDDDDD",
        "gradient_bg_start":             "#343A40",
        "gradient_bg_end":               "#9BE4E5",
        "gradient_bg_angle":             180,
        "gradient_bg_split":             0.82
    },
    "Yellowface": {
        "bg_deep":                       "#1A1812",
        "bg_main":                       "#24201A",
        "bg_sidebar":                    "#1A1812",
        "bg_dropdown":                   "#342E24",
        "panel_opacity_hover":           0.91,
        "undo_hover":                    "#A18C41",
        "text":                          "#F8F0E0",
        "text_on_light_bg":              "#1A1812",
        "accent":                        "#E8B020",
        "accent_light":                  "#F0C838",
        "accent_dark":                   "#A07818",
        "button_text":                   "#1A1812",
        "slider_progress":               "#F8F0E0",
        "slider_overall_bg":             "#342E24",
        "slider_overall_fill":           "#E8B020",
        "slider_chapter_bg":             "#342E24",
        "slider_chapter_fill":           "#F0C838",
        "slider_vol_bg":                 "#342E24",
        "slider_vol_fill":               "#E8B020",
        "notch_color":                   "#F0C838",
        "notch_opacity":                 170,
        "dropdown_curr_chap":            "#F0C838",
        "dropdown_text":                 "#F8F0E0",
        "dropdown_time_text":            "#A89878",
        "sidebar_text":                  "#F8F0E0",
        "sidebar_text_hover":            "#F0C030",
        "sidebar_opacity":               0.84,
        "library_bg":                    "#24201A",
        "library_grid_bg":               "#24201A",
        "library_row_one":               "#24201A",
        "library_row_two":               "#2C281E",
        "library_item_hover_color":      "#F0C030",
        "library_item_hover_alpha":      0.4,
        "library_title":                 "#F8F0E0",
        "library_author":                "#D0C0A0",
        "library_narrator":              "#A89878",
        "library_elapsed":               "#D0C0A0",
        "library_total":                 "#6A6250",
        "library_percentage":            "#E8B020",
        "library_slider_bg":             "#342E24",
        "library_slider_fill":           "#E8B020",
        "library_input_bg":              "#342E24",
        "library_input_text":            "#F8F0E0",
        "settings_tab_hover_bg":         "#F0C030",
        "settings_tab_hover_opacity":    0.85,
        "settings_tab_hover_text":       "#1A1812",
        "settings_theme_names_dimmed":   "#6A6250"
    },
}

def _hex_to_rgb(hex_str):
    h = hex_str.lstrip('#')
    return ",".join(str(int(h[i:i+2], 16)) for i in (0, 2, 4))

def _get_gradient_style(t, prefix, fallback_color, opacity=1.0):
    """Helper to construct qlineargradient or fallback to flat color/rgba."""
    start = t.get(f"gradient_{prefix}_start")
    end = t.get(f"gradient_{prefix}_end")
    angle = t.get(f"gradient_{prefix}_angle", 0)
    split = t.get(f"gradient_{prefix}_split")

    if start and end:
        # Convert angle (0=Top-to-Bottom, 90=Left-to-Right) to Qt coordinates
        rad = math.radians(angle)
        x1 = 0.5 - 0.5 * math.sin(rad)
        y1 = 0.5 - 0.5 * math.cos(rad)
        x2 = 0.5 + 0.5 * math.sin(rad)
        y2 = 0.5 + 0.5 * math.cos(rad)
        
        stops = []
        if opacity < 1.0:
            s_rgb = _hex_to_rgb(start)
            e_rgb = _hex_to_rgb(end)
            stops.append(f"stop:0 rgba({s_rgb}, {opacity})")
            if split is not None:
                stops.append(f"stop:{split} rgba({s_rgb}, {opacity})")
            stops.append(f"stop:1 rgba({e_rgb}, {opacity})")
        else:
            stops.append(f"stop:0 {start}")
            if split is not None:
                stops.append(f"stop:{split} {start}")
            stops.append(f"stop:1 {end}")
        
        stops_str = ", ".join(stops)
        return f"qlineargradient(spread:pad, x1:{x1}, y1:{y1}, x2:{x2}, y2:{y2}, {stops_str})"
    
    if opacity < 1.0:
        return f"rgba({_hex_to_rgb(fallback_color)}, {opacity})"
    return fallback_color

def _resolve_theme(theme_name):
    base = THEMES["The Color Purple"].copy()
    if isinstance(theme_name, dict):
        base.update(theme_name)
    else:
        base.update(THEMES.get(theme_name, {}))
    return base


def get_base_stylesheet(theme_name="default"):
    """
    Rules for widgets that live directly on MainWindow or its root_layout:
    main window background, QToolTip, overall progress slider + percentage label,
    status_banner, chapter dropdown (floating child of MainWindow), undo_overlay.
    """
    t = _resolve_theme(theme_name)
    main_bg_style = _get_gradient_style(t, "bg", t['bg_main'])

    return f"""
        QWidget#mainwindow {{
            background: {main_bg_style};
            border-radius: 8px;
        }}
        QToolTip {{
            background-color: {t['bg_deep']};
            color: {t['text']};
            border: 1px solid {t['accent']};
            font-size: 11px;
        }}
        QWidget#status_banner {{
            background-color: transparent;
            border-radius: 0px;
        }}
        QWidget#status_banner QLabel {{
            color: {t['text']};
        }}
        QWidget#status_banner QPushButton {{
            background-color: {t['accent']};
            color: {t['text']};
            font-size: 13px;
            font-weight: bold;
            padding: 0px;
            border: none;
            border-radius: 3px;
        }}
        QWidget#status_banner QPushButton:hover {{
            color: {t['bg_main']};
        }}
        QProgressBar#scan_progress {{
            background-color: {t['slider_overall_bg']};
            border: none;
            border-radius: 3px;
        }}
        QProgressBar#scan_progress::chunk {{
            background-color: {t['accent']};
            border-radius: 3px;
        }}
        #overall_progress {{
            qproperty-bg_color: "{t['slider_overall_bg']}";
            qproperty-fill_color: "{t['slider_overall_fill']}";
            qproperty-notch_color: "{t.get('notch_color', '#FFFFFF')}";
            qproperty-notch_opacity: {t.get('notch_opacity', 100)};
        }}
        QLabel#percentage_label {{
            color: rgba({_hex_to_rgb(t.get('slider_progress', t.get('text_on_light_bg', t['text'])))}, 0.85);
            font-weight: bold;
            font-size: 16px;
            background: transparent;
        }}
        QListWidget#chapter_dropdown {{
            background-color: {t['bg_deep']};
            border: 1px solid {t['accent']};
            outline: none;
            color: {t.get('dropdown_text', t['text'])};
        }}
        QListWidget#chapter_dropdown QLabel {{
            color: {t.get('dropdown_text', t['text'])};
        }}
        QListWidget#chapter_dropdown QLabel#chapter_time {{
            color: {t.get('dropdown_time_text', t.get('dropdown_text', t['text']))};
        }}
        QListWidget#chapter_dropdown::item:selected {{
            background-color: {t['dropdown_curr_chap']};
            color: {t['text']};
        }}
        QListWidget#chapter_dropdown QScrollBar:vertical {{
            width: 8px;
            background: {t['bg_deep']};
            border: none;
            margin: 0px;
        }}
        QListWidget#chapter_dropdown QScrollBar::handle:vertical {{
            background: {t['accent']};
            min-height: 20px;
            border-radius: 4px;
        }}
        QListWidget#chapter_dropdown QScrollBar::add-line:vertical,
        QListWidget#chapter_dropdown QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QListWidget#chapter_dropdown QScrollBar::add-page:vertical,
        QListWidget#chapter_dropdown QScrollBar::sub-page:vertical {{
            background: none;
        }}
        QPushButton#chapter_expand_btn {{
            font-size: 10px;
            color: {t.get('dropdown_text', t['text'])};
            background-color: {t.get('dropdown_expand', t['accent'])};
            border: 0px solid {t['bg_deep']};
            border-radius: 0px;
            padding: 0px;
        }}
        QPushButton#chapter_expand_btn:hover {{
            background-color: {t['accent']};
            color: {t['bg_main']};
        }}
        QPushButton#undo_overlay {{
            font-size: 11px;
            font-weight: bold;
            color: {t['text']};
            background-color: rgba({_hex_to_rgb(t['bg_deep'])}, 0.8);
            border: 0px solid {t['accent_dark']};
            border-radius: 0px;
            padding: 0px 4px;
        }}
        QPushButton#undo_overlay:hover {{
            background-color: {t.get('undo_hover', t.get('accent'))};
        }}
    """

def get_title_bar_stylesheet(theme_name="default"):
    t = _resolve_theme(theme_name)
    return f"""
        TitleBar {{
            background-color: {t['bg_deep']};
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
        }}
        TitleBar QLabel {{
            color: {t['text']};
            font-weight: bold;
        }}
        TitleBar QPushButton {{
            background: transparent;
            color: {t['text']};
            border: none;
            font-size: 14px;
            padding: 0;
            border-radius: 2px;
        }}
        TitleBar QPushButton:hover {{
            background: {t['accent']};
        }}
        TitleBar QPushButton:pressed {{
            background-color: {t['accent_dark']};
        }}
    """


def get_player_stylesheet(theme_name="default", suppress_bg_image=False):
    """
    Rules for content_container and its descendants: playback controls, chapter
    labels, time labels, sliders, visual area. Generic QLabel/QPushButton rules
    here only cascade within content_container's subtree.

    suppress_bg_image: when True, the theme's bg_image is omitted from the
    #visual_area rule entirely. Used by the no-book and empty library states to
    strip the image. It must be omitted at generation time rather than overridden
    on the child widget — Qt's QSS cascade treats `background-image: none` as
    "unspecified" and lets the ancestor rule's url() win, so a child override
    cannot kill the image. The only reliable suppression is to not emit it.
    """
    t = _resolve_theme(theme_name)
    accent_style = _get_gradient_style(t, "accent", t['accent'])

    visual_area_bg = ""
    if t.get("bg_image") and not suppress_bg_image:
        bg_path = get_asset_path(t["bg_image"])
        visual_area_bg = f"background-image: url({bg_path}); background-position: center; background-repeat: no-repeat;"

    return f"""
        QWidget#visual_area {{
            background-color: transparent;
            {visual_area_bg}
        }}
        QLabel {{
            color: {t['text']};
        }}
        QPushButton {{
            background: {accent_style};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            border-radius: 4px;
            padding: 6px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {t['accent_light']};
        }}
        QPushButton:pressed {{
            background-color: {t['accent_dark']};
        }}
        #chapter_selector {{
            background: transparent;
            border: none;
            padding: 2px;
            font-size: 14px;
            color: {t['text']};
        }}
        QLabel#chapter_preview_label {{
            font-size: 12px;
            color: {t['text']};
            background-color: rgba({_hex_to_rgb(t['bg_deep'])}, 0.5);
            border: 1px solid {t['accent_dark']};
            border-radius: 3px;
            padding: 1px 0px 0px 0px;
        }}
        QLabel#quote_label {{
            background-color: rgba(0, 0, 0, 100);
            color: white;
            padding: 15px;
            border-radius: 6px;
            margin: 10px;
        }}
        QPushButton#sleep_timer_display {{
            background: transparent;
            font-size: 16px;
            font-weight: bold;
            border: none;
            padding: 0px;
            color: {t['accent']};
        }}
        #chapter_progress {{
            qproperty-bg_color: "{t['slider_chapter_bg']}";
            qproperty-fill_color: "{t['slider_chapter_fill']}";
            qproperty-notch_color: "{t.get('notch_color', '#FFFFFF')}";
            qproperty-notch_opacity: {t.get('notch_opacity', 100)};
        }}
        #volume_slider {{
            qproperty-bg_color: "{t['slider_vol_bg']}";
            qproperty-fill_color: "{t['slider_vol_fill']}";
        }}
    """


def get_library_stylesheet(theme_name="default"):
    t = _resolve_theme(theme_name)
    lib_bg_rgb = _hex_to_rgb(t.get('library_bg', '#1A1A1A'))
    accent_style = _get_gradient_style(t, "accent", t['accent'])
    input_bg = t.get('library_input_bg', t['bg_dropdown'])
    input_text = t.get('library_input_text', t['text'])

    return f"""
        QFrame#library_panel {{
            background-color: rgb({lib_bg_rgb});
            border: none;
        }}
        QWidget#library_top_bar {{
            background-color: rgb({lib_bg_rgb});
        }}
        QScrollArea,
        QWidget#library_scroll_contents {{
            background-color: rgba({lib_bg_rgb}, {t['panel_opacity_hover']});
            border: none;
        }}
        QScrollArea QWidget#qt_scrollarea_viewport {{
            background-color: transparent;
        }}
        QLabel {{
            color: {t['text']};
        }}
        QPushButton {{
            background: {accent_style};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            border-radius: 4px;
            padding: 6px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {t['accent_light']};
        }}
        QPushButton:pressed {{
            background-color: {t['accent_dark']};
        }}
        QComboBox {{
            background-color: {input_bg};
            color: {input_text};
            border: 1px solid {t['accent']};
            border-radius: 4px;
            padding: 3px 5px;
            padding-right: 0px;
            font-size: 12px;
            min-height: 22px;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid {t['accent']};
            margin-top: 2px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {input_bg};
            color: {input_text};
            selection-background-color: {t['accent']};
            border: 1px solid {t['accent']};
            outline: none;
            padding: 0px;
            font-size: 12px;
        }}
        QComboBox QAbstractItemView::item {{
            min-height: 22px;
        }}
        QListView {{
            border: none;
            outline: 0;
        }}
        QListView::item {{
            border: none;
            padding: 0px;
            margin: 0px;
        }}
        QLineEdit {{
            background-color: {input_bg};
            color: {input_text};
            selection-background-color: {t['accent']};
            selection-color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            font-size: 12px;
            border: 1px solid {t['accent']};
            border-radius: 4px;
            padding: 2px;
        }}
        #book_item {{
            border-radius: 0px;
        }}
        #book_item[alt_row="0"] {{
            background-color: {t.get('library_row_one', t.get('library_bg', '#1A1A1A'))};
        }}
        #book_item[alt_row="1"] {{
            background-color: {t.get('library_row_two', t.get('library_bg', '#1A1A1A'))};
        }}
        #book_item[alt_row="none"] {{
            background-color: transparent;
        }}
        #book_item:hover {{
            background-color: rgba({_hex_to_rgb(t.get('library_item_hover_color', t['accent']))}, {t.get('library_item_hover_alpha', 0.50)});
        }}
        #book_cover {{
            background-color: {t['bg_dropdown']};
            border: 1px solid {t['accent_dark']};
            border-radius: 0px;
        }}
        #book_cover[placeholder="true"] {{
            font-size: 32px;
            font-weight: bold;
            color: {t['accent_light']};
            background-color: {t['bg_deep']};
        }}
        #book_progress_outer {{
            background-color: {t.get('library_slider_bg', t['slider_overall_bg'])};
            border-radius: 0px;
        }}
        #book_progress_inner {{
            background-color: {t.get('library_slider_fill', t['slider_overall_fill'])};
            border-radius: 0px;
        }}
        QProgressBar#overlay_progress_bar {{
            background-color: {t.get('library_slider_bg', t['slider_overall_bg'])};
            border: 1px solid transparent;
            border-radius: 0px;
        }}
        QProgressBar#overlay_progress_bar::chunk {{
            background-color: {t.get('library_slider_fill', t['slider_overall_fill'])};
            border: none;
            border-radius: 0px;
        }}
        #book_item_title {{
            font-weight: bold;
            color: {t.get('library_title', t['text'])};
        }}
        #book_item_author {{
            color: {t.get('library_author', t['accent_light'])};
        }}
        #book_item_narrator {{
            color: {t.get('library_narrator', t['text'])};
        }}
        #book_item_elapsed {{
            color: {t.get('library_elapsed', t['text'])};
        }}
        #book_item_total {{
            color: {t.get('library_total', t['text'])};
        }}
        #book_item_percentage {{
            color: {t.get('library_percentage', t['text'])};
        }}
        QScrollBar:vertical {{
            width: 8px;
            background: {t['bg_deep']};
            border: none;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {t['accent']};
            min-height: 20px;
            border-radius: 4px;
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{
            background: none;
        }}
    """


def get_settings_stylesheet(theme_name="default"):
    """
    Rules for settings_panel, speed_panel, and sleep_panel (all share this
    stylesheet). Contains tab widget styling, theme/pattern buttons, folder list,
    and panel backgrounds.
    """
    t = _resolve_theme(theme_name)
    text_rgb = _hex_to_rgb(t['text'])
    accent_style = _get_gradient_style(t, "accent", t['accent'])
    tab_hover_bg = t.get('settings_tab_hover_bg', t['accent'])
    tab_hover_opacity = t.get('settings_tab_hover_opacity', 0.85)
    tab_hover_text = t.get('settings_tab_hover_text', t['text'])
    panel_dimmed_color = t.get('settings_theme_names_dimmed', t['accent_dark'])

    return f"""
        QWidget#settings_panel, QWidget#speed_panel, QWidget#sleep_panel {{
            background-color: rgba({_hex_to_rgb(t['bg_main'])}, {t['panel_opacity_hover']});
            border-right: 1px solid {t['accent']};
            border-radius: 0px;
        }}
        QLabel {{
            color: {t['text']};
        }}
        QLabel#settings_header {{
            font-weight: bold;
            font-size: 14px;
            margin-top: 10px;
            color: {t['accent_light']};
        }}
        QLabel#theme_hint {{
            font-size: 12px;
            color: {t['accent']};
        }}
        QPushButton {{
            background: {accent_style};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            border-radius: 4px;
            padding: 6px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {t['accent_light']};
        }}
        QPushButton:pressed {{
            background-color: {t['accent_dark']};
        }}
        QComboBox {{
            background-color: {t['bg_dropdown']};
            color: {t['text']};
            border: 1px solid {t['accent']};
            border-radius: 4px;
            padding: 3px 5px;
            padding-right: 0px;
            font-size: 12px;
            min-height: 22px;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid {t['accent']};
            margin-top: 2px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {t['bg_dropdown']};
            color: {t['text']};
            selection-background-color: {t['accent']};
            border: 1px solid {t['accent']};
            outline: none;
            padding: 0px;
            font-size: 12px;
        }}
        QComboBox QAbstractItemView::item {{
            min-height: 22px;
        }}
        QLineEdit {{
            background-color: {t['bg_dropdown']};
            color: {t['text']};
            selection-background-color: {t['accent']};
            selection-color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            font-size: 12px;
            border: 1px solid {t['accent']};
            border-radius: 4px;
            padding: 2px;
        }}
        QTabWidget::pane {{
            border-top: 1px solid {t['accent_dark']};
            background: transparent;
        }}
        QTabBar::tab {{
            background: {t['bg_deep']};
            color: rgba({text_rgb}, 0.9);
            padding: 3px 8px 3px 9px;
            font-size: 12px;
            font-weight: bold;
            border-top-left-radius: 2px;
            border-top-right-radius: 2px;
            margin-right: 0px;
            margin-left: 2px;
        }}
        QTabBar::tab:selected {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
        }}
        QTabBar::tab:hover:!selected {{
            background: rgba({_hex_to_rgb(tab_hover_bg)}, {tab_hover_opacity});
            color: {tab_hover_text};
        }}
        QTabWidget QWidget {{
            background: transparent;
        }}
        QScrollArea,
        QWidget#theme_selector_container {{
            background: transparent;
            border: none;
        }}
        QScrollArea QWidget#qt_scrollarea_viewport {{
            background: transparent;
        }}
        QListWidget#settings_folder_list {{
            background-color: {t['bg_dropdown']};
            border: 1px solid {t['accent']};
            border-radius: 4px;
            color: {t['text']};
            font-size: 12px;
        }}
        QListWidget#settings_folder_list::item:selected {{
            background-color: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
        }}
        QPushButton#theme_item, QPushButton#theme_interval_btn {{
            background: transparent;
            color: {panel_dimmed_color};
            border: none;
            text-align: center;
            font-size: 12px;
            padding: 4px 0px;
        }}
        QPushButton#theme_item {{ font-weight: normal; }}
        QPushButton#theme_item:disabled {{
            color: {panel_dimmed_color};
        }}
        QPushButton#theme_interval_btn {{ font-weight: bold; }}
        QPushButton#theme_item[selected="true"],
        QPushButton#theme_interval_btn[selected="true"] {{
            color: {t['accent']};
            font-weight: bold;
        }}
        QPushButton#theme_item:hover,
        QPushButton#theme_interval_btn:hover {{
            color: {t['accent_light']};
            background: rgba({_hex_to_rgb(t['accent'])}, 0.1);
        }}
        QPushButton#theme_item[active_display="true"] {{
            text-decoration: underline;
            font-weight: bold;
        }}
        QLabel#theme_interval_label {{
            color: {panel_dimmed_color};
            font-size: 12px;
            padding: 1px 0px;
        }}
        QLabel#theme_interval_label[selected="true"] {{
            color: {t['accent']};
            font-weight: bold;
        }}
        QPushButton#theme_add_all, QPushButton#theme_remove_all,
        QPushButton#theme_change_now, QPushButton#secondary_button {{
            background: transparent;
            color: {t['text']};
            border: 1px solid {t['accent_dark']};
            font-size: 11px;
            padding: 4px 8px;
            border-radius: 4px;
            font-weight: bold;
        }}
        QPushButton#theme_add_all:hover, QPushButton#theme_remove_all:hover,
        QPushButton#theme_change_now:hover, QPushButton#secondary_button:hover {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            font-weight: bold;
        }}
        QPushButton#pattern_button {{
            background: transparent;
            color: {panel_dimmed_color};
            border: 1px solid {t['accent_dark']};
            font-size: 11px;
            padding: 4px;
        }}
        QPushButton#pattern_button[selected="true"] {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
        }}
        QPushButton#pattern_button[is_default="true"] {{
            border: 2px solid {t['accent_light']};
        }}
        QPushButton#pattern_button:hover {{
            border: 1px solid {t['accent']};
        }}
        QPushButton#library_add_folder_btn, QPushButton#library_remove_folder_btn,
        QPushButton#library_rescan_btn {{
            background: transparent;
            color: {t['text']};
            border: 1px solid {t['accent_dark']};
            padding: 4px;
            border-radius: 4px;
            font-weight: bold;
        }}
        QPushButton#library_add_folder_btn:hover, QPushButton#library_remove_folder_btn:hover,
        QPushButton#library_rescan_btn:hover {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            font-weight: bold;
        }}
        QPushButton#library_add_folder_btn:pressed, QPushButton#library_remove_folder_btn:pressed,
        QPushButton#library_rescan_btn:pressed {{
            background-color: {t['accent_dark']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            font-weight: bold;
        }}
        #disable_sleep_btn, #reset_audio_btn {{
            background: {accent_style};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            font-size: 14px;
            padding: 10px;
            margin-top: 10px;
        }}
        #balance_slider {{
            qproperty-bg_color: "{t['slider_chapter_bg']}";
            qproperty-fill_color: "{t['slider_chapter_fill']}";
        }}
        QScrollBar:vertical,
        QComboBox QAbstractItemView QScrollBar:vertical,
        QListWidget#settings_folder_list QScrollBar:vertical {{
            width: 8px;
            background: {t['bg_deep']};
            border: none;
            margin: 0px;
        }}
        QComboBox QAbstractItemView QScrollBar::groove:vertical {{
            border: none;
            background: transparent;
            margin: 0px;
        }}
        QScrollBar::handle:vertical,
        QComboBox QAbstractItemView QScrollBar::handle:vertical,
        QListWidget#settings_folder_list QScrollBar::handle:vertical {{
            background: {t['accent']};
            min-height: 20px;
            border-radius: 4px;
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical,
        QComboBox QAbstractItemView QScrollBar::add-line:vertical,
        QComboBox QAbstractItemView QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical,
        QComboBox QAbstractItemView QScrollBar::add-page:vertical,
        QComboBox QAbstractItemView QScrollBar::sub-page:vertical {{
            background: none;
        }}
    """


def get_stats_stylesheet(theme_name="default"):
    """
    Dedicated stylesheet for the StatsPanel. Copy of settings style but with
    reduced horizontal padding for tabs to accommodate more categories.
    """
    t = _resolve_theme(theme_name)
    text_rgb = _hex_to_rgb(t['text'])
    accent_style = _get_gradient_style(t, "accent", t['accent'])
    tab_hover_bg = t.get('settings_tab_hover_bg', t['accent'])
    tab_hover_opacity = t.get('settings_tab_hover_opacity', 0.85)
    tab_hover_text = t.get('settings_tab_hover_text', t['text'])
    panel_dimmed_color = t.get('settings_theme_names_dimmed', t['accent_dark'])
    finished_color = t.get('stats_finished_title', t.get('accent_light', t.get('accent_dark', '#BA7BBA')))

    return f"""
        QWidget#book_detail_panel {{
            background-color: rgba({_hex_to_rgb(t['bg_main'])}, {t['panel_opacity_hover']});
            border-radius: 0px;
        }}
        QLabel#book_detail_save_label {{
            color: {t['accent']};
        }}
        QLabel#book_detail_confirm_remove {{
            font-size: 12px;
            color: {t['accent_light']};
            background-color: rgba({_hex_to_rgb(t['bg_main'])}, {t['panel_opacity_hover']});
            border: 2px solid {t['accent']};
            padding: 0px 0px;
        }}
        QLineEdit#book_detail_title,
        QLineEdit#book_detail_author,
        QLineEdit#book_detail_narrator,
        QLineEdit#book_detail_year {{
            background: transparent;
            border: 1px solid transparent;
            font-size: 14px;
            border-radius: 0px;
            padding: 0px;
            margin: 0px;
            color: {t['text']};
            selection-background-color: {t['accent']};
        }}
        QWidget#stats_panel {{
            background-color: rgba({_hex_to_rgb(t['bg_main'])}, {t['panel_opacity_hover']});
            border-right: 1px solid {t['accent']};
            border-radius: 0px;
        }}
        QLabel {{
            color: {t['text']};
        }}
        QLabel#settings_header {{
            font-weight: bold;
            font-size: 14px;
            margin-top: 10px;
            color: {t['accent_light']};
        }}
        QLabel#stats_day_label {{
            font-size: 15px;
            font-weight: bold;
            color: {t['accent']};
        }}
        QLabel#stats_day_total {{
            font-weight: bold;
            font-size: 15px;
            margin-top: 0px;
            color: {t['accent_light']};
        }}
        QLabel#stats_history_header {{
            font-weight: bold;
            font-size: 15px;
            margin-top: 5px;
            color: {t['accent_light']};
        }}
        QPushButton {{
            background: {accent_style};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            border-radius: 4px;
            padding: 6px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {t['accent_light']};
        }}
        QPushButton:pressed {{
            background-color: {t['accent_dark']};
        }}
        QPushButton#book_detail_close_btn {{
            background-color: {t['accent']};
            color: {t['bg_main']};
            border: none;
            border-radius: 7px;
            font-size: 9px;
            padding: 0px;
        }}
        QPushButton#book_detail_close_btn:hover {{
            background-color: {t['accent']};
            color: {t['text']};
        }}
        QTabWidget::pane {{
            border-top: 1px solid {t['accent_dark']};
            background: transparent;
        }}
        QTabBar::tab {{
            background: {t['bg_deep']};
            color: rgba({text_rgb}, 0.9);
            padding: 3px 7px;
            min-height: 20px;
            font-size: 12px;
            font-weight: bold;
            border-top-left-radius: 2px;
            border-top-right-radius: 2px;
            margin: 0px 1px;
        }}
        QTabBar::tab:selected {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
        }}
        QTabBar::tab:hover:!selected {{
            background: rgba({_hex_to_rgb(tab_hover_bg)}, {tab_hover_opacity});
            color: {tab_hover_text};
        }}
        QTabWidget#stats_tabs QTabBar::tab:last {{
            padding-top: -2px;
            padding-bottom: 0px;
        }}
        QTabWidget QWidget {{
            background: transparent;
        }}
        QWidget#stats_time_tab {{
            background: {t['bg_main']};
        }}
        QWidget#stats_time_tab QWidget {{
            background: transparent;
        }}
        QScrollArea {{
            background: transparent;
            border: none;
        }}
        QScrollArea QWidget#qt_scrollarea_viewport {{
            background: transparent;
        }}
        QPushButton#pattern_button {{
            background: transparent;
            color: {panel_dimmed_color};
            border: 1px solid {t['accent_dark']};
            font-size: 11px;
            padding: 4px;
        }}
        QPushButton#pattern_button[selected="true"] {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
        }}
        QPushButton#pattern_button:hover {{
            border: 1px solid {t['accent']};
        }}
        QSpinBox {{
            background-color: {t['bg_dropdown']};
            color: {t['text']};
            selection-background-color: {t['accent']};
            selection-color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            border: 1px solid {t['accent']};
            border-radius: 4px;
            padding: 1px 2px;
            max-height: 18px;
            font-size: 12px;
            margin-top: 10px;
        }}
        QSpinBox::up-button, QSpinBox::down-button {{
            width: 16px;
            border: none;
            background-color: {t['accent_dark']};
        }}
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
            background-color: {t['accent']};
        }}
        QLabel#stats_key_label {{
            color: {t['accent_light']};
            font-size: 12px;
        }}
        QLabel#stats_session_label {{
            color: {t['accent_light']};
            font-size: 13px;
        }}
        QLabel#tag_display_chip {{
            color: {t['accent_light']};
            font-size: 12px;
            padding: 2px 0px;
        }}
        QLabel#stats_book_title_finished {{
            color: {finished_color};
        }}
        QLabel#stats_book_time_label_dim {{
            color: rgba({_hex_to_rgb(t['text'])}, 0.45);
        }}
        QWidget#stats_book_day_row:hover, QWidget#stats_book_day_row_alt:hover {{
            background-color: rgba({_hex_to_rgb(t['accent'])}, 0.12);
        }}
        QLabel#stats_value_label {{
            color: {t['text']};
            font-weight: bold;
            font-size: 13px;
        }}
        QLabel#stats_placeholder_label {{
            color: {t['accent_dark']};
            font-style: italic;
        }}
        QPushButton#stats_nav_btn:disabled {{
            color: rgba({_hex_to_rgb(t['accent_dark'])}, .90);
        }}
        QPushButton#stats_reset_btn {{
            background: transparent;
            color: {t['text']};
            border: 1px solid {t['accent_dark']};
            padding: 4px;
            border-radius: 4px;
            font-weight: bold;
        }}
        QPushButton#stats_reset_btn:hover {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
        }}
        QPushButton#stats_reset_btn:pressed {{
            background: {t['accent_dark']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
        }}       
        QScrollBar:vertical {{
            width: 8px;
            background: {t['bg_deep']};
            border: none;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {t['accent']};
            min-height: 20px;
            border-radius: 4px;
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{
            background: none;
        }}
        QWidget#tag_manager_row {{
            border-radius: 4px;
        }}
        QWidget#tag_manager_row:hover {{
            background-color: rgba({_hex_to_rgb(t['accent'])}, 0.15);
        }}
        QWidget#tag_manager_row QLabel#tag_chip_label {{
            color: {t['text']};
            font-size: 13px;
        }}
        QPushButton#stats_nav_btn {{
            background: transparent;
            color: {t['accent_light']};
            border: none;
            font-size: 18px;
            font-weight: bold;
            padding: 0px;
        }}
        QPushButton#stats_nav_btn:hover {{
            color: {t['text']};
        }}
        QWidget#tag_chip {{
            background-color: rgba({_hex_to_rgb(t['accent'])}, 0.12);
            border: 1px solid rgba({_hex_to_rgb(t['accent'])}, 0.40);
            border-radius: 0px;
        }}
        QWidget#tag_chip QLabel#tag_chip_label {{
            color: {t['accent_light']};
            font-size: 14px;
            background: transparent;
            border: none;
        }}
        QWidget#tag_chip QPushButton#tag_chip_remove_btn {{
            background: transparent;
            color: rgba({_hex_to_rgb(t['accent_light'])}, 0.60);
            border: none;
            font-size: 11px;
            font-weight: bold;
            padding: 0px;
        }}
        QWidget#tag_chip QPushButton#tag_chip_remove_btn:hover {{
            color: {t['text']};
        }}
        QLineEdit#tag_add_field {{
            background-color: rgba({_hex_to_rgb(t['bg_dropdown'])}, 0.6);
            color: {t['text']};
            selection-background-color: {t['accent']};
            font-size: 13px;
            border: 1px solid {t['accent_dark']};
            border-radius: 6px;
            padding: 4px 8px;
        }}
        QLineEdit#tag_add_field:focus {{
            border: 1px solid {t['accent']};
        }}
        QPushButton#tag_add_btn {{
            background-color: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            border: none;
            border-radius: 6px;
            font-size: 18px;
            font-weight: bold;
            padding: 0px;
        }}
        QPushButton#tag_add_btn:hover {{
            background-color: {t['accent_light']};
        }}
        QPushButton#tag_add_btn:pressed {{
            background-color: {t['accent_dark']};
        }}
        QPushButton#tag_manager_nav_btn {{
            background: transparent;
            color: {t['text']};
            border: 1px solid {t['accent_dark']};
            padding: 4px;
            border-radius: 4px;
            font-weight: bold;
        }}
        QPushButton#tag_manager_nav_btn:hover {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
        }}
        QPushButton#tag_manager_nav_btn:pressed {{
            background: {t['accent_dark']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
        }}
    """


def get_tags_stylesheet(theme_name="default"):
    """Stylesheet for the standalone TagManagerWidget panel."""
    t = _resolve_theme(theme_name)
    accent_style = _get_gradient_style(t, "accent", t['accent'])

    return f"""
        QWidget#tags_panel {{
            background-color: rgba({_hex_to_rgb(t['bg_main'])}, {t['panel_opacity_hover']});
            border-right: 1px solid {t['accent']};
            border-radius: 0px;
        }}
        QWidget#tag_manager_list,
        QWidget#tag_manager_panel,
        QWidget#tag_list_container {{
            background: transparent;
        }}
        QScrollArea,
        QScrollArea QWidget#qt_scrollarea_viewport {{
            background: transparent;
            border: none;
        }}
        QLabel {{
            color: {t['text']};
        }}
        QLabel#settings_header {{
            font-weight: bold;
            font-size: 14px;
            margin-top: 10px;
            color: {t['accent_light']};
        }}
        QWidget#tag_list_row {{
            border-radius: 6px;
        }}
        QWidget#tag_list_row:!hover {{
            background-color: rgba({_hex_to_rgb(t['bg_deep'])}, 0.6);
        }}
        QWidget#tag_list_row:hover {{
            background-color: rgba({_hex_to_rgb(t['accent_dark'])}, 0.6);
        }}
        QLabel#tag_list_name {{
            color: {t.get('tag_list_text', t['text'])};
            font-size: 14px;
            padding-left: 0px;
        }}
        QLabel#tag_list_name:hover {{
            color: {t.get('tag_list_text_hover', t['accent_light'])};
            font-size: 13px;
        }}
        QLabel#book_count_label {{
            font-size: 14px;
            font-weight: bold;
            color: {t['accent']};
        }}
        QLabel#tag_count_badge {{
            background-color: rgba({_hex_to_rgb(t['accent_dark'])}, 0.5);
            color: {t['accent_light']};
            border-radius: 4px;
            font-size: 11px;
            padding: 1px 4px;
        }}
        QLabel#tag_dot_neutral {{
            color: {t['accent_light']};
            padding-top: 0px;
        }}
        QLabel#tag_dot_colored {{
            padding-top: 0px;
        }}
        QLineEdit#tag_name_field {{
            background: transparent;
            border: 1px solid transparent;
            font-size: 14px;
            border-radius: 0px;
            padding: 0px;
            padding-left: -2px;
            padding-bottom: -1px;
            margin: 0px;
            color: {t['text']};
            selection-background-color: {t['accent']};
        }}
        QPushButton#tag_icon_btn {{
            background: transparent;
            color: {t['accent']};
            border: none;
            padding: 0px;
            padding-bottom: -2px;
        }}
        QLabel#tag_confirm_delete {{
            font-size: 12px;
            color: {t['accent_light']};
            background-color: rgba({_hex_to_rgb(t['bg_main'])}, {t['panel_opacity_hover']});
            border: 2px solid {t['accent']};
            padding: 0px 0px;
        }}
        QPushButton {{
            background: {accent_style};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            border-radius: 4px;
            padding: 6px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {t['accent_light']};
        }}
        QPushButton:pressed {{
            background-color: {t['accent_dark']};
        }}
        QPushButton#stats_nav_btn {{
            background: transparent;
            color: {t['accent_light']};
            border: none;
            font-size: 18px;
            font-weight: bold;
            padding: 0px;
        }}
        QPushButton#stats_nav_btn:hover {{
            color: {t['text']};
        }}
        QPushButton#stats_nav_btn:disabled {{
            color: rgba({_hex_to_rgb(t['accent_dark'])}, .90);
        }}
        QPushButton#stats_reset_btn {{
            background: transparent;
            color: {t['text']};
            border: 1px solid {t['accent_dark']};
            padding: 4px;
            border-radius: 4px;
            font-weight: bold;
        }}
        QPushButton#stats_reset_btn:hover {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
        }}
        QPushButton#stats_reset_btn:pressed {{
            background: {t['accent_dark']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
        }}
        QLabel#stats_key_label {{
            color: {t['accent_light']};
            font-size: 12px;
        }}
        QLabel#stats_value_label {{
            color: {t['text']};
            font-weight: bold;
            font-size: 13px;
        }}
        QScrollArea {{
            background: transparent;
            border: none;
        }}
        QScrollArea QWidget#qt_scrollarea_viewport {{
            background: transparent;
        }}
        QScrollBar:vertical {{
            width: 8px;
            background: transparent;
            border: none;
            margin: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {t['accent']};
            min-height: 20px;
            border-radius: 4px;
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{
            background: none;
        }}
    """


def get_sidebar_stylesheet(theme_name="default"):
    t = _resolve_theme(theme_name)
    sidebar_style = _get_gradient_style(t, "sidebar", t['bg_sidebar'], t['sidebar_opacity'])
    sidebar_hover_style = _get_gradient_style(t, "sidebar", t['bg_sidebar'], t['panel_opacity_hover'])
    sidebar_text_rgb = _hex_to_rgb(t.get('sidebar_text', t['text']))
    sidebar_text_hover_rgb = _hex_to_rgb(t.get('sidebar_text_hover', '#FFFFFF'))

    return f"""
        QWidget#sidebar {{
            background: {sidebar_style};
            border-right: 1px solid {t['slider_overall_bg']};
            border-radius: 0px;
        }}
        QWidget#sidebar:hover {{
            background: {sidebar_hover_style};
        }}
        #sidebar QLabel {{
            font-size: 12px;
            color: rgb({sidebar_text_rgb});
            background: transparent;
            border: none;
            text-align: left;
            font-weight: bold;
            padding: 0;
        }}
        #sidebar QPushButton {{
            font-size: 13px;
            color: rgb({sidebar_text_rgb});
            background: transparent;
            border: none;
            margin-left: -1px;
            text-align: left;
            font-weight: bold;
            padding: 0;
        }}
        #sidebar QLabel:hover, #sidebar QPushButton:hover {{
            color: rgb({sidebar_text_hover_rgb});
        }}
        QLabel#sidebar_title {{
            font-weight: bold;
            margin-bottom: 10px;
        }}
    """


def get_cover_panel_stylesheet(theme_name="default"):
    t = _resolve_theme(theme_name)
    accent            = t.get('accent', '#5A8A9F')
    accent_dark       = t.get('accent_dark', '#3A6A7F')
    text              = t.get('text', '#FFFFFF')
    warning           = t.get('warning_color', '#FF6B6B')
    cover_preview_bg  = t.get('cover_preview_bg', 'transparent')

    return f"""
        QLabel#CoverPreview {{
            background-color: {cover_preview_bg};
        }}
        QFrame#CoverThumbnail {{
            background: transparent;
        }}
        QFrame#CoverThumbnailActive {{
            background: transparent;
        }}
        QPushButton#FitModeButton {{
            background-color: transparent;
            color: {text};
            border: 1px solid {accent_dark};
            border-radius: 3px;
            padding: 4px 8px 6px 8px;
            font-size: 12px;
        }}
        QPushButton#FitModeButton:checked {{
            background-color: {accent};
            color: {text};
            border: 1px solid {accent};
        }}
        QPushButton#FitModeButton:hover:!checked {{
            background-color: {accent_dark};
        }}
        QPushButton#CoverAddButton {{
            background-color: #2A2A2A;
            color: {accent};
            border: 1px solid {accent_dark};
            border-radius: 0px;
            font-size: 18px;
            font-weight: bold;
        }}
        QPushButton#CoverAddButton:hover {{
            background-color: {accent_dark};
            color: {text};
        }}
        QLabel#CoverErrorLabel {{
            color: {warning};
            font-size: 11px;
        }}
    """
