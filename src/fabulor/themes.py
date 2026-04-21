import math
"""
CORE BACKGROUND COLORS
bg_deep: The darkest background color. Used for the custom title bar, the background behind the volume overlay, and the status banner at the bottom.
bg_main: The primary background color for the main window and panels (settings, library, speed, etc.).
bg_sidebar: The background color for the sliding sidebar on the left.
bg_dropdown: The background color for lists and dropdown menus (like the chapter list and folder list).
bg_library: The background color for the library book display area. Falls back to dark grey (#1A1A1A).
library_row_one: Background color for odd rows in 1-per-row and List views. Falls back to bg_library.
library_row_two: Background color for even rows in 1-per-row and List views. Falls back to bg_library.
library_item_hover_color: Background color for a book item when hovered. Falls back to accent.
library_item_hover_alpha: Opacity (0.0 to 1.0) for the library item hover background. Falls back to 0.5.
library_title: Text color for book titles in the library view.
library_author: Text color for book authors in the library view.
library_narrator: Text color for book narrators in the library view.
library_slider_bg: Background color for the progress bar groove in library items.
library_slider_fill: Fill color for the progress bar in library items.
library_elapsed: Text color for elapsed time labels in library items.
library_total: Text color for total duration labels in library items.
library_percentage: Text color for the progress percentage in library items.
library_input_bg: Background color for sort/view dropdowns and the search field in the library. Falls back to bg_dropdown.
library_input_text: Text color for sort/view dropdowns and the search field in the library. Falls back to text.
settings_tab_hover_bg: Background color for unselected tabs when hovered. Falls back to accent.
settings_tab_hover_opacity: Opacity for unselected tabs when hovered. Falls back to 0.85.
settings_tab_hover_text: Text color for unselected tabs when hovered. Falls back to text.

UI TEXT COLORS
text: The default color for most labels and UI text.
button_text: (Optional) Specific color for text inside buttons. If not provided, it falls back to text_on_light_bg or text.
progress_text: (Optional) Color for the percentage label that sits on top of the overall progress slider.
sidebar_text: (Optional) Color for text and buttons inside the sidebar. Falls back to the main text color.
dropdown_text: (Optional) Color for text inside the chapter dropdown list.
dropdown_time_text: (Optional) Color for the duration text inside the chapter dropdown list.
text_on_light_bg: (Optional) Used as a fallback for buttons or specific labels if they are placed over light-colored elements.
panel_theme_names_dimmed: Specifically used in the Settings panel for theme names that are currently unselected/dimmed.

SLIDERS
slider_overall_bg: Background (groove) color of the main book progress bar.
slider_overall_fill: The filled portion color of the main book progress bar.
slider_chapter_bg: Background of the chapter-specific progress bar.
slider_chapter_fill: The filled portion of the chapter-specific progress bar.
slider_vol_bg: Background of the volume slider.
slider_vol_fill: The filled portion of the volume slider.

ACCENT AND INTERACTION COLORS
accent: The primary interaction color. Used for selected tabs, slider handles (implicitly via fill), and primary buttons.
accent_light: The color used when hovering over buttons or selecting list items.
accent_dark: The color used for borders or when a button is actively pressed.
curr_chap_highlight: The color used to highlight the currently playing chapter within the chapter dropdown list.

TRANSPARENCY AND EFFECTS
sidebar_opacity: A float (0.0 to 1.0) defining how transparent the sidebar is when idle.
panel_opacity_hover: A float (0.0 to 1.0) defining the transparency of the sidebar and settings panels when interacted with.
bg_image: (Optional) A string path (e.g., "img/overlook.png") to set a background image for the cover art area.

DYNAMIC GRADIENTS
The theme engine supports linear gradients for several components. You can define these by adding the following keys using a specific prefix:

Prefixes: bg, sidebar, accent, slider_fill
Properties:
gradient_[prefix]_start: Hex color for the start of the gradient.
gradient_[prefix]_end: Hex color for the end of the gradient.
gradient_[prefix]_angle: Integer angle in degrees (e.g., 115 or 135).
"""

THEMES = {
        "Alzabo": {
        "text":                   "#9CBAD4",
        "accent":                 "#366FF4",
        "accent_light":           "#7A9BB5",
        "accent_dark":            "#0A375A",
        "bg_main":                "#1A0570",
        "bg_deep":                "#0A0E82",
        "slider_overall_bg":      "#4A5F6F",
        "slider_overall_fill":    "#DE1515",
        "slider_chapter_bg":      "#771327",
        "slider_chapter_fill":    "#205A86",
        "slider_vol_bg":          "#084A84",
        "slider_vol_fill":        "#7A9BB5",
        "sidebar_text":           "#D61717",
        "bg_sidebar":             "#060A49",
        "sidebar_text_hover":     "#5A97C6",
        "sidebar_opacity":        0.70,
        "bg_dropdown":            "#4A5F6F",
        "curr_chap_highlight":    "#A13F73",
        "dropdown_time_text":     "#6FA0F9",
        "bg_library":             "#0D0630",
        "library_row_one":        "#130848",
        "library_row_two":        "#0D0630",
        "library_item_hover_color": "#1049CF",
        "library_item_hover_alpha": 0.50,
        "library_title":          "#7ACAC9",
        "library_author":         "#22BDDD",
        "library_narrator":       "#9CBAD4",
        "library_elapsed":        "#9CBAD4",
        "library_total":          "#9CBAD4",
        "library_percentage":     "#9CBAD4",
        "library_slider_bg":      "#4A5F6F",
        "library_slider_fill":    "#DE1515",
        "library_input_bg":       "#06263F",
        "library_input_text":     "#FFFFFF",
        "settings_tab_hover_bg":      "#FF0000",
        "settings_tab_hover_opacity": 0.9,
        "settings_tab_hover_text":    "#150C79",
        "panel_theme_names_dimmed": "#CDE1E1",
        "panel_opacity_hover":    1.00,
    },
    "Anomander": { # Black & White with Deep Amber Progress Text
        "bg_deep":      "#000000",
        "bg_main":      "#000000",
        "slider_overall_bg":   "#1A1A1A",
        "slider_overall_fill": "#FFFFFF",
        "slider_chapter_bg":   "#111111",
        "slider_chapter_fill": "#FFFFFF",
        "slider_vol_bg":       "#000000",
        "slider_vol_fill":     "#FFFFFF",
        "accent":              "#FFFFFF",
        "accent_light":        "#E0E0E0",
        "accent_dark":         "#404040",
        "library_row_one":        "#000000",
        "library_row_two":        "#0C0C0C",
        "bg_sidebar":          "#000000",
        "bg_dropdown":         "#080808",
        "curr_chap_highlight": "#FFA807",
        "library_item_hover_alpha": 0.15,
        "sidebar_opacity":     0.8,
        "panel_opacity_hover": 0.9,
        "panel_theme_names_dimmed": "#FFA807",
        "button_text":         "#000000",
        "progress_text":       "#FFBF00",
        "text":                "#FFFFFF",
        "sidebar_text_hover":  "#E0E0E0",
        "settings_tab_hover_text":    "#000000",
    },
    "Blood Meridian": {
        "bg_deep": "#2F1A0F", # Dried blood brown
        "bg_main": "#4A2F1F", # Sun-bleached rust
        "slider_overall_bg": "#5A3F2F",
        "slider_overall_fill": "#8B0000", # Crimson violence accent
        "slider_chapter_bg": "#4A2F1F",
        "slider_chapter_fill": "#7A0000",
        "slider_vol_bg": "#2F1A0F",
        "slider_vol_fill": "#8B0000",
        "accent": "#C10808",
        "accent_light": "#A52A2A",
        "accent_dark": "#CD3F3F",
        "bg_sidebar": "#3C1F10",
        "bg_dropdown": "#4A2F1F",
        "curr_chap_highlight": "#8B0000",
        "sidebar_text_hover": "#A52A2A",
        "sidebar_opacity": 0.72,
        "panel_opacity_hover": 0.91,
        "panel_theme_names_dimmed": "#E47575",
        "text": "#F5E6D3", # Bone cream text
    },
    "Blue Moranth": { # Navy/Green theme
        "bg_deep":      "#001219",
        "bg_main":      "#001B2E", # Navy blue background
        "slider_overall_bg":   "#003547",
        "slider_overall_fill": "#39FF14", # Vibrant green accent
        "slider_chapter_bg":   "#002A38",
        "slider_chapter_fill": "#3CA4E0",
        "slider_vol_bg":       "#3CA4E0",
        "slider_vol_fill":     "#39FF14",
        "accent":              "#3C7BE0",
        "accent_light":        "#29E442",
        "accent_dark":         "#00A32A",
        "bg_sidebar":          "#001219",
        "bg_dropdown":         "#001B2E",
        "curr_chap_highlight": "#227AED",
        "dropdown_time_text":  "#6FA0F9",
        "sidebar_text_hover":  "#7CFF8A",
        "sidebar_opacity":     0.9,
        "panel_opacity_hover": 0.95,
        "panel_theme_names_dimmed": "#8DCECF",
        "bg_library":             "#11064A",
        "library_title":         "#3EA5EA",
        "library_author":         "#10D742",
        "library_row_one":        "#0E0442",
        "library_row_two":        "#0A032A",
        "library_item_hover_color": "#1049CF",
        "library_item_hover_alpha": 0.50,
        "text":                "#B9EFEE",
    },
    "Brave New World": {
        "bg_deep": "#3A2F5F", # Sterile purple
        "bg_main": "#5A4A7F", # Controlled indigo
        "slider_overall_bg": "#6A5A8F",
        "slider_overall_fill": "#77B2CC", # Cool blue accent
        "slider_chapter_bg": "#5A4A7F",
        "slider_chapter_fill": "#5A9BBF",
        "slider_vol_bg": "#3A2F5F",
        "slider_vol_fill": "#77B2CC",
        "accent": "#77B2CC",
        "accent_light": "#9ACFE0",
        "accent_dark": "#4F8FAF",
        "bg_sidebar": "#3A2F5F",
        "bg_dropdown": "#5A4A7F",
        "curr_chap_highlight": "#77B2CC",
        "sidebar_text_hover": "#9ACFE0",
        "sidebar_opacity": 0.7,
        "panel_opacity_hover": 0.9,
        "panel_theme_names_dimmed": "#CA94CB",
        "bg_library":             "#240B2E",
        "library_author":         "#D71087",
        "text": "#F1E7C2", # Pale lemon text
    },
        "Camorr": {
        "bg_deep": "#0F1419",
        "bg_main": "#1A1F24", 
        "slider_overall_bg": "#2A2F34",
        "slider_overall_fill": "#00A98B",
        "slider_chapter_bg": "#1A1F24",
        "slider_chapter_fill": "#008B6F",
        "slider_vol_bg": "#0F1419",
        "slider_vol_fill": "#00A98B",
        "accent": "#00A98B",
        "accent_light": "#00D4B3",
        "accent_dark": "#006F5A",
        "bg_sidebar": "#032516",
        "bg_dropdown": "#1A1F24",
        "curr_chap_highlight": "#00A98B",
        "sidebar_text_hover": "#00D4B3",
        "sidebar_opacity": 0.65,
        "panel_opacity_hover": 0.88,
        "panel_theme_names_dimmed": "#C0D8CA",
        "library_title":          "#BEE6DF",
        "library_percentage":        "#5FFD0A",
        "library_item_hover_color": "#00A98B",
        "library_item_hover_alpha": 0.80,
        "library_row_one":        "#012D20",
        "library_row_two":        "#082A03",
        "text": "#B1EBAF",
    },
    "Chatsubo": {
        "bg_deep":      "#0D001A",
        "bg_main":      "#1A002E",
        "bg_library":  "#260242",
        "slider_overall_bg":   "#333333",
        "slider_overall_fill": "#FF00FF",
        "slider_chapter_bg":   "#2A2A2A",
        "slider_chapter_fill": "#00FFFF",
        "slider_vol_bg":       "#0D001A",
        "slider_vol_fill":     "#00FF00",
        "accent":              "#FF00FF",
        "accent_light":        "#FF33FF",
        "accent_dark":         "#CC00CC",
        "bg_sidebar":          "#0D001A",
        "bg_dropdown":         "#1A1A1A",
        "curr_chap_highlight": "#FF00FF",
        "sidebar_opacity":     0.7,
        "panel_opacity_hover": 0.9,
        "text":                "#E0E0E0",
        "sidebar_text_hover": "#FF33FF",
        "panel_theme_names_dimmed": "#00F7FF",
        "dropdown_text":       "#FFFF00",
        "library_title":          "#00EAFF",
        "library_narrator":        "#FFFF00",
        "library_elapsed":        "#6CFAFF",
        "library_total":          "#00C8FF",
        "library_percentage":     "#D97DEC",
        "library_row_one":        "#26053F",
        "library_row_two":        "#1A032C",
        "library_item_hover_color": "#FF66CC",
        "library_item_hover_alpha": 0.20,

    },
    "Cibola Burn": {
        "bg_deep":                "#1A1210",
        "bg_main":                "#2E1C16",
        "bg_library":             "#1E1524",
        "slider_overall_bg":      "#4A3024",
        "slider_overall_fill":    "#E87A3A",
        "slider_chapter_bg":      "#4A3024",
        "slider_chapter_fill":    "#F0944C",
        "slider_vol_bg":          "#2E1C16",
        "slider_vol_fill":        "#E87A3A",
        "accent":                 "#E87A3A",
        "accent_light":           "#F0944C",
        "accent_dark":            "#A85222",
        "bg_sidebar":             "#1A1210",
        "bg_dropdown":            "#4A3024",
        "curr_chap_highlight":    "#E87A3A",
        "sidebar_text_hover":     "#F0944C",
        "sidebar_opacity":        0.7,
        "panel_opacity_hover":    0.9,
        "library_item_hover_color": "#CD591A",
        "library_item_hover_alpha": 0.80,
        "text":                   "#F5E2D0"
    },
    "Crimson Guard": {
        "bg_deep":                "#1A0F1A",
        "bg_main":                "#2E1A24",
        "slider_overall_bg":      "#4A2A3A",
        "slider_overall_fill":    "#D96A2A",
        "slider_chapter_bg":      "#4A2A3A",
        "slider_chapter_fill":    "#E87A3A",
        "slider_vol_bg":          "#2E1A24",
        "slider_vol_fill":        "#D96A2A",
        "accent":                 "#B84A6A",
        "accent_light":           "#D06A8A",
        "accent_dark":            "#7A2A4A",
        "bg_sidebar":             "#1A0F1A",
        "bg_dropdown":            "#4A2A3A",
        "curr_chap_highlight":    "#E87A3A",
        "sidebar_text_hover": "#F19616",
        "sidebar_opacity":        0.84,
        "panel_opacity_hover":    0.92,
        "panel_theme_names_dimmed": "#D8C0D4",
        "library_title":          "#EBF4CF",
        "library_narrator":        "#F0A9CF",
        "library_elapsed":        "#F0A9CF",
        "library_total":          "#F0A9CF",
        "library_percentage":     "#F0A9CF",
        "text":                   "#F2E0E8"

},
    "Dorian Grey": { 
        "bg_deep":      "#121212",
        "bg_main":      "#1E1E1E",
        "slider_overall_bg":   "#333333",
        "slider_overall_fill": "#E67E22", 
        "slider_chapter_bg":   "#252525",
        "slider_chapter_fill": "#8B4513", 
        "slider_vol_bg":       "#121212",
        "slider_vol_fill":     "#D35400", 
        "accent":              "#E67E22",
        "accent_light":        "#F39C12",
        "accent_dark":         "#A04000",
        "bg_sidebar":          "#121212",
        "bg_dropdown":         "#1E1E1E",
        "curr_chap_highlight": "#8B4513",
        "sidebar_text_hover": "#F39C12",
        "sidebar_opacity":     0.8,
        "panel_opacity_hover": 0.9,
        "panel_theme_names_dimmed": "#BCB6BB",
        "text":                "#E8BC6C", 
        "button_text":         "#000000",
        "progress_text":       "#FCD586",
        "sidebar_text_hover": "#F39C12",
    },
    "Earthsea": {
        "bg_deep": "#1A2A44", # Deep ocean indigo
        "bg_main": "#2B4A6A", # Stormy sea blue
        "slider_overall_bg": "#3A5A7A",
        "slider_overall_fill": "#4A90A7", # Volcanic teal accent
        "slider_chapter_bg": "#2B4A6A",
        "slider_chapter_fill": "#3A7A90",
        "slider_vol_bg": "#1A2A44",
        "slider_vol_fill": "#4A90A7",
        "accent": "#4A90A7",
        "accent_light": "#6AB8C7",
        "accent_dark": "#2F6A80",
        "bg_sidebar": "#1A2A44",
        "bg_dropdown": "#2B4A6A",
        "curr_chap_highlight": "#4A90A7",
        "sidebar_text_hover": "#6AB8C7",
        "sidebar_opacity": 0.7,
        "panel_opacity_hover": 0.9,
        "panel_theme_names_dimmed": "#D2ECF1",
        "text": "#B9D7E2", # Cool light text
    },
    "Emiko": {
        "bg_deep":                "#0A1F0A",
        "bg_main":                "#123312",
        "slider_overall_bg":      "#1F4F1F",
        "slider_overall_fill":    "#2EFF7A",
        "slider_chapter_bg":      "#1F4F1F",
        "slider_chapter_fill":    "#4CFF94",
        "slider_vol_bg":          "#123312",
        "slider_vol_fill":        "#2EFF7A",
        "accent":                 "#2EFF7A",
        "accent_light":           "#6CFFB0",
        "accent_dark":            "#1AA652",
        "bg_sidebar":             "#0A1F0A",
        "bg_dropdown":            "#1F4F1F",
        "curr_chap_highlight":    "#4CFF94",
        "sidebar_text_hover":     "#6CFFB0",
        "sidebar_opacity":        0.82,
        "panel_opacity_hover":    0.9,
        "text":                   "#D0FFD0"
    },
    "Eyes of Ibad": {
        "bg_deep":                "#0A1128",
        "bg_main":                "#0F1A3A",
        "slider_overall_bg":      "#1A2A5A",
        "slider_overall_fill":    "#3B6AFF",
        "slider_chapter_bg":      "#1A2A5A",
        "slider_chapter_fill":    "#5B8AFF",
        "slider_vol_bg":          "#0A1128",
        "slider_vol_fill":        "#3B6AFF",
        "accent":                 "#3B6AFF",
        "accent_light":           "#6B9AFF",
        "accent_dark":            "#1A3A9A",
        "bg_sidebar":             "#0A1128",
        "bg_dropdown":            "#1A2A5A",
        "curr_chap_highlight":    "#5B8AFF",
        "sidebar_text_hover":     "#6B9AFF",
        "sidebar_opacity":        0.85,
        "panel_opacity_hover":    0.92,
        "panel_theme_names_dimmed": "#8FEBE6",
        "text":                   "#C4D7F2"
    },
    "Gormenghast": {
        "bg_deep":                "#3B2A24",
        "bg_main":                "#543D34",
        "slider_overall_bg":      "#70554A",
        "slider_overall_fill":    "#A57254",
        "slider_chapter_bg":      "#70554A",
        "slider_chapter_fill":    "#B88462",
        "slider_vol_bg":          "#543D34",
        "slider_vol_fill":        "#A57254",
        "accent":                 "#9C6E4E",
        "accent_light":           "#B88462",
        "accent_dark":            "#6E4A34",
        "bg_sidebar":             "#3B2A24",
        "bg_dropdown":            "#70554A",
        "curr_chap_highlight":    "#B88462",
        "sidebar_text_hover":     "#B88462",
        "sidebar_opacity":        0.85,
        "panel_opacity_hover":    0.92,
        "panel_theme_names_dimmed": "#E4C7B7",
        "text":                   "#F0E6D8"
    },
    "Gravity's Rainbow": {
        "bg_deep":      "#1a0033",
        "bg_main":      "#2b0052",
        "slider_overall_bg":   "#4B0082",
        "slider_overall_fill": "#ED37B3", # Red
        "slider_chapter_bg":   "#330066",
        "slider_chapter_fill": "#FF7F00", # Orange
        "slider_vol_bg":       "#1a0033",
        "slider_vol_fill":     "#FFFF00", # Yellow
        "accent":              "#00FF00", # Green
        "accent_light":        "#00FFFF", # Cyan
        "accent_dark":         "#0000FF", # Blue
        "bg_sidebar":          "#1a0033",
        "bg_dropdown":         "#2b0052",
        "curr_chap_highlight": "#8B00FF", # Violet
        "sidebar_opacity":     0.7,
        "panel_opacity_hover": 0.9,
        "text":                "#CFECEC", # Cyan text
        "progress_text":       "#FF00FF", # Magenta progress
        "sidebar_text_hover": "#00FFFF",
        "panel_theme_names_dimmed": "#E94F4F",
        "button_text":         "#2b0052",
        "gradient_bg_angle":      115,
        "gradient_bg_start":      "#D328D3",
        "gradient_bg_end":        "#1900FF",
    },
    "Hear Me Roar": {
        "bg_deep":      "#230903",
        "bg_main":      "#451208",
        "slider_overall_bg":   "#741A06",
        "slider_overall_fill": "#FDA605",
        "slider_chapter_bg":   "#741A06",
        "slider_chapter_fill": "#D60808",
        "slider_vol_bg":       "#230903",
        "slider_vol_fill":     "#E3B23C",
        "accent":              "#FDA605",
        "accent_light":        "#D60808",
        "accent_dark":         "#A37B14",
        "bg_sidebar":          "#230903",
        "bg_dropdown":         "#451208",
        "curr_chap_highlight": "#E3B23C", # chapter dropdown selection
        "sidebar_text_hover": "#D60808",
        "sidebar_opacity":     0.6,
        "panel_opacity_hover": 0.9,
        "panel_theme_names_dimmed": "#F47272",
        "text":                "#F9F7F3",
    },
    "Horrorshow": {
        "bg_deep": "#84500B", 
        "bg_main": "#BD6914", 
        "slider_overall_bg": "#FFBF1E",
        "slider_overall_fill": "#E6A15D",
        "slider_chapter_bg": "#B77E46",
        "slider_chapter_fill": "#FBDA8E",
        "slider_vol_bg": "#783D15",
        "slider_vol_fill": "#E5BA8C",
        "accent": "#EEB34C",
        "accent_light": "#E1B67E",
        "accent_dark": "#F1741A",
        "bg_sidebar": "#8A620A",
        "bg_dropdown": "#762610",
        "curr_chap_highlight": "#3B404C",
        "sidebar_opacity": 0.7,
        "panel_opacity_hover": 0.9,
        "sidebar_text_hover": "#E1B67E",
        "panel_theme_names_dimmed": "#FEC074",
        "text": "#F1E7C2", # Pale lemon text
    },
    "Ithaca": {
        "bg_deep": "#1A2F44", # Stormy Aegean depths
        "bg_main": "#2F4A66", # Sea mist blue
        "slider_overall_bg": "#3F5A77",
        "slider_overall_fill": "#4682B4", # Steel blue horizon accent
        "slider_chapter_bg": "#2F4A66",
        "slider_chapter_fill": "#3A6FAF",
        "slider_vol_bg": "#1A2F44",
        "slider_vol_fill": "#4682B4",
        "accent": "#4682B4",
        "accent_light": "#5A94D0",
        "accent_dark": "#2F5A8F",
        "bg_sidebar": "#1A2F44",
        "bg_dropdown": "#2F4A66",
        "curr_chap_highlight": "#4682B4",
        "sidebar_text_hover": "#5A94D0",
        "sidebar_opacity": 0.73,
        "panel_opacity_hover": 0.92,
        "panel_theme_names_dimmed": "#EEECF9",
        "text": "#D7E8EE", # Cool seafoam text
    },
    "Jade City": { # New theme, tones of jade
        "bg_deep":      "#002E22",
        "bg_main":      "#003D2E",
        "slider_overall_bg":   "#004D3B",
        "slider_overall_fill": "#00A86B",
        "slider_chapter_bg":   "#003D2E",
        "slider_chapter_fill": "#40B58D",
        "slider_vol_bg":       "#002E22",
        "slider_vol_fill":     "#00A86B",
        "accent":              "#00A86B",
        "accent_light":        "#2ECC71",
        "accent_dark":         "#007A4D",
        "bg_sidebar":          "#002E22",
        "bg_dropdown":         "#003D2E",
        "curr_chap_highlight": "#00A86B",
        "sidebar_text_hover": "#2ECC71",
        "sidebar_opacity":     0.7,
        "panel_opacity_hover": 0.9,
        "panel_theme_names_dimmed": "#DCDCC7",
        "text":                "#CBE4E3",
    },
    "Manderley": {
        "bg_deep":                "#2E2B33",
        "bg_main":                "#423E48",
        "slider_overall_bg":      "#5A5562",
        "slider_overall_fill":    "#9288A8",
        "slider_chapter_bg":      "#5A5562",
        "slider_chapter_fill":    "#A89AB5",
        "slider_vol_bg":          "#423E48",
        "slider_vol_fill":        "#9288A8",
        "accent":                 "#A89AB5",
        "accent_light":           "#C2B5CC",
        "accent_dark":            "#6A607A",
        "bg_sidebar":             "#2E2B33",
        "bg_dropdown":            "#5A5562",
        "curr_chap_highlight":    "#A89AB5",
        "sidebar_text_hover":     "#C2B5CC",
        "sidebar_opacity":        0.86,
        "panel_opacity_hover":    0.93,
        "panel_theme_names_dimmed": "#876B81",
        "text":                   "#ECBEDF"
    },
    "Melnibonéan": {
        "bg_deep":                "#2A353C",
        "bg_main":                "#3E4A52",
        "slider_overall_bg":      "#55626B",
        "slider_overall_fill":    "#8FAAAD",
        "slider_chapter_bg":      "#55626B",
        "slider_chapter_fill":    "#AFC9CC",
        "slider_vol_bg":          "#3E4A52",
        "slider_vol_fill":        "#8FAAAD",
        "accent":                 "#A8C3C6",
        "accent_light":           "#C2D6D9",
        "accent_dark":            "#6F868A",
        "bg_sidebar":             "#2A353C",
        "bg_dropdown":            "#55626B",
        "curr_chap_highlight":    "#AFC9CC",
        "sidebar_text_hover":     "#C2D6D9",
        "sidebar_opacity":        0.82,
        "panel_opacity_hover":    0.9,
        "text":                   "#F0F3F0"
    },
    "Oranges Are Not the Only Fruit": { # Test long name
        "bg_deep":      "#2C3E50",
        "bg_main":      "#34495E",
        "slider_overall_bg":   "#4A627A",
        "slider_overall_fill": "#E74C3C", # Red accent
        "slider_chapter_bg":   "#34495E",
        "slider_chapter_fill": "#C0392B",
        "slider_vol_bg":       "#2C3E50",
        "slider_vol_fill":     "#E74C3C",
        "accent":              "#E74C3C",
        "accent_light":        "#F05948",
        "accent_dark":         "#B02A1B",
        "bg_sidebar":          "#2C3E50",
        "bg_dropdown":         "#34495E",
        "curr_chap_highlight": "#E74C3C",
        "sidebar_text_hover": "#F05948",
        "sidebar_opacity":     0.7,
        "panel_opacity_hover": 0.9,
        "panel_theme_names_dimmed": "#8CF1F8FF",
        "text":                "#ECF0F1", # Light text
    },
    "Razorgirl": {
        "bg_deep": "#0A0F1A", # Void space black
        "bg_main": "#1A1F2E", # Cyberdeck navy
        "slider_overall_bg": "#2A344A",
        "slider_overall_fill": "#00FFFF", # Neon cyan accent
        "slider_chapter_bg": "#1A1F2E",
        "slider_chapter_fill": "#00CCCC",
        "slider_vol_bg": "#0A0F1A",
        "slider_vol_fill": "#00FFFF",
        "accent": "#00FFFF",
        "accent_light": "#66FFFF",
        "accent_dark": "#009999",
        "bg_sidebar": "#0A0F1A",
        "bg_dropdown": "#1A1F2E",
        "curr_chap_highlight": "#00FFFF",
        "sidebar_text_hover": "#66FFFF",
        "sidebar_opacity": 0.7,
        "panel_opacity_hover": 0.9,
        "panel_theme_names_dimmed": "#DBECF0",
        "button_text":         "#2A0A60",
        "text": "#A5C4E2",
        "settings_tab_hover_opacity": 0.9,
        "settings_tab_hover_text":    "#0B0A0A",
    },
    "Rebma": {
        "bg_deep": "#2D4A2D", # Deep mossy earth
        "bg_main": "#4A704A", # Lush garden green
        "slider_overall_bg": "#5A805A",
        "slider_overall_fill": "#90C090", # Blooming rose accent
        "slider_chapter_bg": "#4A704A",
        "slider_chapter_fill": "#80B080",
        "slider_vol_bg": "#2D4A2D",
        "slider_vol_fill": "#90C090",
        "accent": "#90C090",
        "accent_light": "#A8D0A8",
        "accent_dark": "#6A906A",
        "bg_sidebar": "#2D4A2D",
        "bg_dropdown": "#4A704A",
        "curr_chap_highlight": "#C59EC5",
        "sidebar_text_hover": "#A8D0A8",
        "sidebar_opacity": 0.75,
        "panel_opacity_hover": 0.92,
        "text": "#F8F0F7", # Soft cream text
        "panel_theme_names_dimmed": "#E6E9CD", # Use 6-digit hex to avoid ARGB/RGBA confusion
    },
    "Red Rising": { # Tones of red, Martian aesthetic
        "bg_deep":      "#2b0000",
        "bg_main":      "#4a0000",
        "slider_overall_bg":   "#1a0000",
        "slider_overall_fill": "#ff0000",
        "slider_chapter_bg":   "#2b0000",
        "slider_chapter_fill": "#a30000",
        "slider_vol_bg":       "#1a0000",
        "slider_vol_fill":     "#ff4d4d",
        "accent":              "#ff0000",
        "accent_light":        "#ff6666",
        "accent_dark":         "#800000",
        "bg_sidebar":          "#2b0000",
        "bg_dropdown":         "#4a0000",
        "curr_chap_highlight": "#ff0000",
        "sidebar_text_hover": "#ff6666",
        "sidebar_opacity":     0.7,
        "panel_opacity_hover": 0.9,
        "panel_theme_names_dimmed": "#FFFFFFFF",
        "text":                "#ffcccc",
        "button_text":         "#000000",
        "progress_text":       "#f88a8a", # Contrast against bright red fill
    },
    "Rivendell": { # Lord of the Rings - Elven, light, natural
        "bg_deep":      "#E0E7E9",
        "bg_main":      "#F0FFF0", # Tinted green
        "slider_overall_bg":   "#B0BEC5",
        "slider_overall_fill": "#4CAF50", # Green accent
        "slider_chapter_bg":   "#CFD8DC",
        "slider_chapter_fill": "#81C784",
        "slider_vol_bg":       "#E0E7E9",
        "slider_vol_fill":     "#66BB6A",
        "accent":              "#66BB6A",
        "accent_light":        "#81C784",
        "accent_dark":         "#388E3C",
        "bg_sidebar":          "#E0E7E9",
        "bg_dropdown":         "#CFD8DC",
        "curr_chap_highlight": "#81C784",
        "sidebar_text_hover": "#81C784",
        "sidebar_opacity":     0.9,
        "panel_opacity_hover": 0.95,
        "text":                "#263238",
        "panel_theme_names_dimmed": "#2C464C", # Dark text
        "text_on_light_bg":    "#1D3022",
    },
    "Shai-Hulud": {
        "bg_deep":                "#4A3B2D",
        "bg_main":                "#6B5A49",
        "gradient_bg_angle":      115,
        "gradient_bg_start":      "#4A3B2D",
        "gradient_bg_end":        "#7E6B58",
        "slider_overall_bg":      "#8C7B6A",
        "slider_overall_fill":    "#D4A85C",
        "gradient_slider_fill_angle": 90,
        "gradient_slider_fill_start": "#D4A85C",
        "gradient_slider_fill_end":   "#E8BC6C",
        "slider_chapter_bg":      "#6B5A49",
        "slider_chapter_fill":    "#B48B4C",
        "slider_vol_bg":          "#4A3B2D",
        "slider_vol_fill":        "#D4A85C",
        "accent":                 "#D4A85C",
        "accent_light":           "#E2CDA7",
        "accent_dark":            "#A47B3C",
        "gradient_accent_angle":  45,
        "gradient_accent_start":  "#D4A85C",
        "gradient_accent_end":    "#C49A4A",
        "bg_sidebar":             "#4A3B2D",
        "gradient_sidebar_angle": 180,
        "gradient_sidebar_start": "#3E3024",
        "gradient_sidebar_end":   "#5A4838",
        "bg_dropdown":            "#6B5A49",
        "curr_chap_highlight":    "#D4A85C",
        "sidebar_text_hover":     "#E2CDA7",
        "sidebar_opacity":        0.6,
        "panel_opacity_hover":    0.9,
        "panel_theme_names_dimmed": "#B1A792",
        "text":                   "#F5F5DC"
    },
    "Shade of the Evening": {
        "bg_deep":                "#0A0A1A",
        "bg_main":                "#11162B",
        "slider_overall_bg":      "#1A2140",
        "slider_overall_fill":    "#4A6FA5",
        "slider_chapter_bg":      "#1A2140",
        "slider_chapter_fill":    "#5B80B8",
        "slider_vol_bg":          "#11162B",
        "slider_vol_fill":        "#4A6FA5",
        "accent":                 "#3A5A8A",
        "accent_light":           "#5B80B8",
        "accent_dark":            "#1E3A5A",
        "bg_sidebar":             "#0A0A1A",
        "bg_dropdown":            "#1A2140",
        "curr_chap_highlight":    "#5B80B8",
        "sidebar_text_hover":     "#5B80B8",
        "sidebar_opacity":        0.85,
        "panel_opacity_hover":    0.92,
        "panel_theme_names_dimmed": "#41BAEA",
        "text":                   "#E8EAF6",
        "gradient_bg_angle":      135,
        "gradient_bg_start":      "#0A0A1A",
        "gradient_bg_end":        "#1A2860",
        "gradient_accent_angle":  90,
        "gradient_accent_start":  "#4A6FA5",
        "gradient_accent_end":    "#2A4A7A",
        "gradient_slider_fill_angle": 0,
        "gradient_slider_fill_start": "#4A6FA5",
        "gradient_slider_fill_end":   "#6A8FBD"
    },
    "Shrike": {
        "bg_deep":                "#1B2B3B",
        "bg_main":                "#2E4050",
        "slider_overall_bg":      "#4A5F6F",
        "slider_overall_fill":    "#6A8BA0",
        "slider_chapter_bg":      "#4A5F6F",
        "slider_chapter_fill":    "#7A9BB5",
        "slider_vol_bg":          "#2E4050",
        "slider_vol_fill":        "#7A9BB5",
        "accent":                 "#5E8299",
        "accent_light":           "#7A9BB5",
        "accent_dark":            "#3A5A72",
        "bg_sidebar":             "#1B2B3B",
        "bg_dropdown":            "#4A5F6F",
        "curr_chap_highlight":    "#AC668B",
        "sidebar_text_hover":     "#7A9BB5",
        "sidebar_opacity":        0.88,
        "panel_opacity_hover":    0.94,
        "panel_theme_names_dimmed": "#CDE1E1",
        "text":                   "#CDDBE7"
    },
    "Sitting in the Wing Chair": {
        "bg_deep":                "#1E1814",
        "bg_main":                "#2E241E",
        "slider_overall_bg":      "#4A3A2E",
        "slider_overall_fill":    "#B85C44",
        "slider_chapter_bg":      "#4A3A2E",
        "slider_chapter_fill":    "#CC6C54",
        "slider_vol_bg":          "#2E241E",
        "slider_vol_fill":        "#B85C44",
        "accent":                 "#A84C34",
        "accent_light":           "#CC6C54",
        "accent_dark":            "#7A3420",
        "bg_sidebar":             "#1E1814",
        "bg_dropdown":            "#4A3A2E",
        "curr_chap_highlight":    "#CC6C54",
        "sidebar_text_hover":     "#CC6C54",
        "sidebar_opacity":        0.82,
        "panel_opacity_hover":    0.9,
        "panel_theme_names_dimmed": "#ECECAE",
        "text":                   "#E5E6B3",
    },
    "Slow Regard": {
        "bg_deep":                "#3A2A1E",
        "bg_main":                "#543F2C",
        "slider_overall_bg":      "#765A40",
        "slider_overall_fill":    "#E4A859",
        "slider_chapter_bg":      "#765A40",
        "slider_chapter_fill":    "#F0BC6C",
        "slider_vol_bg":          "#543F2C",
        "slider_vol_fill":        "#E4A859",
        "accent":                 "#E4A859",
        "accent_light":           "#F0BC6C",
        "accent_dark":            "#B87E3A",
        "bg_sidebar":             "#3A2A1E",
        "bg_dropdown":            "#765A40",
        "curr_chap_highlight":    "#F0BC6C",
        "sidebar_text_hover":     "#F0BC6C",
        "sidebar_opacity":        0.84,
        "panel_opacity_hover":    0.91,
        "text":                   "#FFF2E0"
    },
    "Symir": {
        "bg_deep":                "#0A1C1A",
        "bg_main":                "#0F2E2A",
        "slider_overall_bg":      "#1A4A44",
        "slider_overall_fill":    "#2FAA9A",
        "slider_chapter_bg":      "#1A4A44",
        "slider_chapter_fill":    "#4CCCB8",
        "slider_vol_bg":          "#0F2E2A",
        "slider_vol_fill":        "#2FAA9A",
        "accent":                 "#2FAA9A",
        "accent_light":           "#4CCCB8",
        "accent_dark":            "#1A6E62",
        "bg_sidebar":             "#0A1C1A",
        "bg_dropdown":            "#1A4A44",
        "curr_chap_highlight":    "#4CCCB8",
        "sidebar_text_hover":     "#4CCCB8",
        "sidebar_opacity":        0.84,
        "panel_opacity_hover":    0.91,
        "panel_theme_names_dimmed": "#C5DCE1",
        "text":                   "#D9F0EC"
    },
    "The Bone Clocks": {
        "bg_deep":                "#2A2020",
        "bg_main":                "#3D2E2A",
        "slider_overall_bg":      "#5C4A44",
        "slider_overall_fill":    "#E8D8C8",
        "slider_chapter_bg":      "#5C4A44",
        "slider_chapter_fill":    "#F2E6D8",
        "slider_vol_bg":          "#3D2E2A",
        "slider_vol_fill":        "#E8D8C8",
        "accent":                 "#C95A4A",
        "accent_light":           "#E07A6A",
        "accent_dark":            "#9A3A2E",
        "bg_sidebar":             "#2A2020",
        "bg_dropdown":            "#5C4A44",
        "curr_chap_highlight":    "#F2E6D8",
        "sidebar_text_hover":     "#E07A6A",
        "sidebar_opacity":        0.86,
        "panel_opacity_hover":    0.93,
        "panel_theme_names_dimmed": "#D7B6D2",
        "text":                   "#FFF5EC"
    },
        "The City of Stairs": {
        "bg_deep":                "#0E1E24",
        "bg_main":                "#183238",
        "slider_overall_bg":      "#244A52",
        "slider_overall_fill":    "#5A9A8C",
        "slider_chapter_bg":      "#244A52",
        "slider_chapter_fill":    "#6AAAA0",
        "slider_vol_bg":          "#183238",
        "slider_vol_fill":        "#5A9A8C",
        "accent":                 "#4A7A6E",
        "accent_light":           "#6AAAA0",
        "accent_dark":            "#2A5248",
        "bg_sidebar":             "#0E1E24",
        "bg_dropdown":            "#244A52",
        "curr_chap_highlight":    "#6AAAA0",
        "sidebar_text_hover":     "#6AAAA0",
        "sidebar_opacity":        0.83,
        "panel_opacity_hover":    0.91,
        "panel_theme_names_dimmed": "#A2C1C8",
        "text":                   "#EAF2EA"
    },
    "The Color Purple": {
        "bg_deep":      "#0D001A",  # title bar, darkest
        "bg_main":      "#1A002E",  # main window background
        "slider_overall_bg":   "#4B0082",
        "slider_overall_fill": "#BA7BBA",
        "slider_chapter_bg":   "#330066",
        "slider_chapter_fill": "#950E95",
        "slider_vol_bg":       "#220044",
        "slider_vol_fill":     "#7B2CBF",
        "accent":              "#7B2CBF",  # primary buttons, hover states
        "accent_light": "#9D4EDD",  # button hover
        "accent_dark":  "#5A189A",  # button pressed
        "bg_sidebar":   "#120024",  # drawer background
        "bg_dropdown":  "#120024",  # combobox popup
        "curr_chap_highlight": "#C8A2C8", # chapter dropdown selection
        "sidebar_text_hover": "#9D4EDD",
        "sidebar_opacity": 0.6,
        "panel_opacity_hover": 0.9,
        "text":         "#EF94E9",  # all labels and button text
    },
    "The Overlook": {
        "bg_deep":                "#2E1E14",
        "bg_main":                "#341A25",
        "slider_overall_bg":      "#B41E37",
        "slider_overall_fill":    "#F05632",
        "slider_chapter_bg":      "#B41E37",
        "slider_chapter_fill":    "#F05632",
        "slider_vol_bg":          "#4A2E1E",
        "slider_vol_fill":        "#B41E37",
        "accent":                 "#F05632",
        "accent_light":           "#BB0606",
        "accent_dark":            "#8A5428",
        "bg_sidebar":             "#2E1E14",
        "bg_dropdown":            "#6B4530",
        "curr_chap_highlight":    "#BB0606",
        "sidebar_text_hover":     "#BB0606",
        "sidebar_opacity":        0.86,
        "panel_opacity_hover":    0.93,
        "panel_theme_names_dimmed": "#F05632",
        "text":                   "#F8ECD8",
        "bg_image":               "img/overlook.png"
    },
    "The Waste Lands": {
        "bg_deep": "#1A1A1A", # Charred black
        "bg_main": "#2F2F2F", # Dusty ash grey
        "slider_overall_bg": "#404040",
        "slider_overall_fill": "#B8860B", # Faded gold accent
        "slider_chapter_bg": "#2F2F2F",
        "slider_chapter_fill": "#A67C00",
        "slider_vol_bg": "#1A1A1A",
        "slider_vol_fill": "#B8860B",
        "accent": "#B8860B",
        "accent_light": "#DAA520",
        "accent_dark": "#8B6914",
        "bg_sidebar": "#1A1A1A",
        "bg_dropdown": "#2F2F2F",
        "curr_chap_highlight": "#B8860B",
        "sidebar_text_hover": "#DAA520",
        "sidebar_opacity": 0.68,
        "panel_opacity_hover": 0.87,
        "panel_theme_names_dimmed": "#839CA2",
        "text": "#DCDCDC", # Ghostly light grey text
    },
    "Tigana": {
        "bg_deep":                "#121826",
        "bg_main":                "#1E2A3E",
        "slider_overall_bg":      "#30405C",
        "slider_overall_fill":    "#E8E2D0",
        "slider_chapter_bg":      "#30405C",
        "slider_chapter_fill":    "#EEEEEE",
        "slider_vol_bg":          "#1E2A3E",
        "slider_vol_fill":        "#E8E2D0",
        "accent":                 "#C0B89C",
        "accent_light":           "#D8D0B4",
        "accent_dark":            "#8A8268",
        "bg_sidebar":             "#121826",
        "bg_dropdown":            "#30405C",
        "curr_chap_highlight":    "#C4B2D0",
        "sidebar_text_hover":     "#D8D0B4",
        "sidebar_opacity":        0.86,
        "panel_opacity_hover":    0.93,
        "text":                   "#F0ECDC"
    },
    "Tlön": {
        "bg_deep":                "#2A261A",
        "bg_main":                "#3E382A",
        "slider_overall_bg":      "#5C543E",
        "slider_overall_fill":    "#E8D88C",
        "slider_chapter_bg":      "#5C543E",
        "slider_chapter_fill":    "#F2E49C",
        "slider_vol_bg":          "#3E382A",
        "slider_vol_fill":        "#E8D88C",
        "accent":                 "#DCC96C",
        "accent_light":           "#F2E49C",
        "accent_dark":            "#A89448",
        "bg_sidebar":             "#2A261A",
        "bg_dropdown":            "#5C543E",
        "curr_chap_highlight":    "#F2E49C",
        "sidebar_text_hover":     "#F2E49C",
        "sidebar_opacity":        0.84,
        "panel_opacity_hover":    0.91,
        "text":                   "#FFF8E8"
    },
        "Unknown Kadath": {
        "bg_deep":                "#1A1824",
        "bg_main":                "#2A2538",
        "slider_overall_bg":      "#3D3650",
        "slider_overall_fill":    "#B8B0D0",
        "slider_chapter_bg":      "#3D3650",
        "slider_chapter_fill":    "#D0C8E4",
        "slider_vol_bg":          "#2A2538",
        "slider_vol_fill":        "#B8B0D0",
        "accent":                 "#9A8CB8",
        "accent_light":           "#B8B0D0",
        "accent_dark":            "#5E507A",
        "bg_sidebar":             "#1A1824",
        "bg_dropdown":            "#3D3650",
        "curr_chap_highlight":    "#D0C8E4",
        "sidebar_text_hover":     "#B8B0D0",
        "sidebar_opacity":        0.84,
        "panel_opacity_hover":    0.91,
        "panel_theme_names_dimmed": "#C18EAC",
        "text":                   "#F2EFF8"
    },
    "Urras": {
        "bg_deep":      "#001219", # Old Blue Moranth
        "bg_main":      "#001B24",
        "slider_overall_bg":   "#003547",
        "slider_overall_fill": "#94D2BD",
        "slider_chapter_bg":   "#002A38",
        "slider_chapter_fill": "#83C5BE",
        "slider_vol_bg":       "#001219",
        "slider_vol_fill":     "#0A9396",
        "accent":              "#0A9396",
        "accent_light":        "#94D2BD",
        "accent_dark":         "#005F73",
        "bg_sidebar":          "#001219",
        "bg_dropdown":         "#001B24",
        "curr_chap_highlight": "#94D2BD",
        "sidebar_text_hover": "#94D2BD",
        "sidebar_opacity":     0.6,
        "panel_opacity_hover": 0.9,
        "panel_theme_names_dimmed": "#D3EBEC",
        "text":                "#E9D8A6",
    },
    "Waknuk": {
        "bg_deep":                "#1E2229",
        "bg_main":                "#2E343E",
        "slider_overall_bg":      "#464E5C",
        "slider_overall_fill":    "#8A9BB5",
        "slider_chapter_bg":      "#464E5C",
        "slider_chapter_fill":    "#A2B2CC",
        "slider_vol_bg":          "#2E343E",
        "slider_vol_fill":        "#8A9BB5",
        "accent":                 "#7E8DA8",
        "accent_light":           "#A2B2CC",
        "accent_dark":            "#4E5A70",
        "bg_sidebar":             "#1E2229",
        "bg_dropdown":            "#464E5C",
        "curr_chap_highlight":    "#A2B2CC",
        "sidebar_text_hover":     "#A2B2CC",
        "sidebar_opacity":        0.85,
        "panel_opacity_hover":    0.92,
        "panel_theme_names_dimmed": "#726A6A",
        "text":                   "#A4AFC1"
    },
    "Winterfell": {
        "bg_deep":      "#212529",
        "bg_main":      "#343A40",
        "slider_overall_bg":   "#495057",
        "slider_overall_fill": "#E9ECEF",
        "slider_chapter_bg":   "#343A40",
        "slider_chapter_fill": "#CED4DA",
        "slider_vol_bg":       "#212529",
        "slider_vol_fill":     "#ADB5BD",
        "accent":              "#6C757D",
        "accent_light":        "#DEE2E6",
        "accent_dark":         "#343A40",
        "bg_sidebar":          "#212529",
        "bg_dropdown":         "#343A40",
        "curr_chap_highlight": "#DEE2E6", # chapter dropdown selection
        "sidebar_text_hover": "#DEE2E6",
        "sidebar_opacity":     0.6,
        "panel_opacity_hover": 0.9,
        "panel_theme_names_dimmed": "#000000",
        "text":                "#F8F9FA", # Light text for general labels
        "text_on_light_bg":    "#111111", 
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

    if start and end:
        # Convert angle (0=Top-to-Bottom, 90=Left-to-Right) to Qt coordinates
        rad = math.radians(angle)
        x1 = 0.5 - 0.5 * math.sin(rad)
        y1 = 0.5 - 0.5 * math.cos(rad)
        x2 = 0.5 + 0.5 * math.sin(rad)
        y2 = 0.5 + 0.5 * math.cos(rad)
        
        if opacity < 1.0:
            s_rgb = _hex_to_rgb(start)
            e_rgb = _hex_to_rgb(end)
            return (f"qlineargradient(spread:pad, x1:{x1}, y1:{y1}, x2:{x2}, y2:{y2}, "
                    f"stop:0 rgba({s_rgb}, {opacity}), stop:1 rgba({e_rgb}, {opacity}))")
        return f"qlineargradient(spread:pad, x1:{x1}, y1:{y1}, x2:{x2}, y2:{y2}, stop:0 {start}, stop:1 {end})"
    
    if opacity < 1.0:
        return f"rgba({_hex_to_rgb(fallback_color)}, {opacity})"
    return fallback_color

def get_stylesheet(theme_name="default"):
    # Fallback logic for stubs
    base = THEMES["The Color Purple"].copy()
    custom = THEMES.get(theme_name, {})
    base.update(custom)
    t = base

    text_rgb = _hex_to_rgb(t['text'])
    s_text = t.get('sidebar_text', t['text'])
    s_hover = t.get('sidebar_text_hover', '#FFFFFF')

    sidebar_text_rgb = _hex_to_rgb(s_text)
    sidebar_text_hover_rgb = _hex_to_rgb(s_hover)
    lib_bg_rgb = _hex_to_rgb(t.get('bg_library', '#1A1A1A'))

    tab_hover_bg = t.get('settings_tab_hover_bg', t['accent'])
    tab_hover_opacity = t.get('settings_tab_hover_opacity', 0.85)
    tab_hover_text = t.get('settings_tab_hover_text', t['text'])

    # Prepare dynamic backgrounds
    main_bg_style = _get_gradient_style(t, "bg", t['bg_main'])
    sidebar_style = _get_gradient_style(t, "sidebar", t['bg_sidebar'], t['sidebar_opacity'])
    sidebar_hover_style = _get_gradient_style(t, "sidebar", t['bg_sidebar'], t['panel_opacity_hover'])
    accent_style = _get_gradient_style(t, "accent", t['accent'])

    # Determine the color for unselected theme names in the panel
    # Use custom override if available, otherwise fall back to accent_dark
    panel_dimmed_color = t.get('panel_theme_names_dimmed', t['accent_dark'])

    visual_area_bg = ""
    if t.get("bg_image"):
        visual_area_bg = f"background-image: url({t['bg_image']}); background-position: center; background-repeat: no-repeat;"

    return f"""
        QWidget#mainwindow {{
            background: {main_bg_style};
            border-radius: 8px;
        }}
        QToolTip {{
            background-color: {t['bg_deep']};
            color: {t['text']};
            border: 1px solid {t['accent']};
            font-size: 10px;
        }}
        TitleBar {{
            background-color: {t['bg_deep']};
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
        }}
        QWidget#settings_panel, QWidget#speed_panel, QWidget#sleep_panel, QWidget#status_banner {{
            background-color: rgba({_hex_to_rgb(t['bg_main'])}, {t['panel_opacity_hover']});
            border-right: 1px solid {t['accent']};
            border-radius: 0px;

        }}
        QWidget#library_panel {{
            background-color: {'bg_library'}; /* Panel background (includes top bar) */
            border-right: 1px solid {t['accent']};
            border: none;
        }}
        #library_panel QScrollArea, #library_panel QWidget#library_scroll_contents {{
            background-color: rgba({lib_bg_rgb}, {t['panel_opacity_hover']}); /* Actual book display area */
            border: none;
        }}
        #library_panel QScrollArea QWidget#qt_scrollarea_viewport {{
            background-color: transparent;
        }}
        QWidget#sidebar {{ /* Sidebar background opacity */
            background: {sidebar_style};
            border-right: 1px solid {t['slider_overall_bg']};
            border-radius: 0px;
        }}
        QWidget#sidebar:hover {{
            background: {sidebar_hover_style};
        }}
        TitleBar QLabel {{
            color: {t['text']};
            font-weight: bold;
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
            font-size: 12px;
            color: rgb({sidebar_text_rgb});
            background: transparent;
            border: none;
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
        QLabel#settings_header {{
            font-weight: bold;
            font-size: 14px;
            margin-top: 10px;
            color: {t['accent_light']};
        }}
        QWidget#visual_area {{
            background-color: transparent;
            {visual_area_bg}
        }}
        TitleBar QPushButton {{
            background: transparent;
            color: {t['text']};
            border: none;
            font-size: 14px;
            padding: 0;
        }}
        TitleBar QPushButton:hover {{
            background: {t['accent']};
        }}
        TitleBar QPushButton {{
            border-radius: 2px; /* Makes minimize/close buttons square */
        }}
        QWidget#library_top_bar {{
            background-color: rgb({lib_bg_rgb});
        }}
        QLabel {{
            color: {t['text']};
        }}
        QLabel#curr_time_label, QLabel#total_time_label {{
            color: {t['text']};
        }}
        QLabel#percentage_label {{
            color: rgba({_hex_to_rgb(t.get('progress_text', t.get('text_on_light_bg', t['text'])))}, 0.85);
            font-weight: bold;
            font-size: 16px;
            background: transparent;
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
        QPushButton#undo_overlay {{
            font-size: 12px;
            font-size: 11px;
            color: {t['text']};
            background-color: rgba({_hex_to_rgb(t['bg_deep'])}, 0.5);
            background-color: rgba({_hex_to_rgb(t['bg_deep'])}, 0.8);
            border: 0px solid {t['accent_dark']};
            border-radius: 0px;
            padding: 0px 4px;
        }}
        QPushButton#undo_overlay:hover {{
            background-color: {t['accent']};
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
            border: none;
            padding: 0px;
            color: {t['text']};
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
        QProgressBar#scan_progress {{
            background-color: {t['slider_overall_bg']};
            border: none;
            border-radius: 3px;
        }}
        QProgressBar#scan_progress::chunk {{
            background-color: {t['accent']};
            border-radius: 3px;
        }}
        /* Library Panel Styling */
        #book_item {{
            border-radius: 0px;
        }}
        #book_item[alt_row="0"] {{
            background-color: {t.get('library_row_one', t.get('bg_library', '#1A1A1A'))};
        }}
        #book_item[alt_row="1"] {{
            background-color: {t.get('library_row_two', t.get('bg_library', '#1A1A1A'))};
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
        /* Specialized Library Inputs */
        #library_panel QComboBox, #library_panel QLineEdit {{
            background-color: {t.get('library_input_bg', t['bg_dropdown'])};
            color: {t.get('library_input_text', t['text'])};
        }}
        #library_panel QComboBox QAbstractItemView {{
            background-color: {t.get('library_input_bg', t['bg_dropdown'])};
            color: {t.get('library_input_text', t['text'])};
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
            background-color: {t['curr_chap_highlight']}; /* Chapter dropdown selection highlight */
            color: {t['text']};
        }}
        /* Custom ClickSlider Theme Integration */
        #overall_progress {{
            qproperty-bg_color: "{t['slider_overall_bg']}";
            qproperty-fill_color: "{t['slider_overall_fill']}";
        }}
        #chapter_progress {{
            qproperty-bg_color: "{t['slider_chapter_bg']}";
            qproperty-fill_color: "{t['slider_chapter_fill']}";
        }}
        #balance_slider {{
            qproperty-bg_color: "{t['slider_chapter_bg']}";
            qproperty-fill_color: "{t['slider_chapter_fill']}";
        }}
        #volume_slider {{
            qproperty-bg_color: "{t['slider_vol_bg']}";
            qproperty-fill_color: "{t['slider_vol_fill']}";
        }}
        QComboBox {{
            background-color: {t['bg_dropdown']};
            color: {t['text']};
            border: 1px solid {t['accent']};
            border-radius: 4px;
            padding: 3px 5px;
            padding-right: 0px; /* Prevent scrollbar sliver on closed combo box */
            font-size: 12px; /* Increased by 1px */
            min-height: 22px; /* Increased to accommodate larger font */
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox::down-arrow {{
            image: none; /* Hide default arrow */
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
            padding: 0px; /* Remove any default padding that might affect scrollbar */
            font-size: 12px; /* Smaller font for dropdown list items */
        }}
        QComboBox QAbstractItemView::item {{
            min-height: 22px; /* Ensure each item has a minimum height */
        }}
        QLineEdit {{
            background-color: {t['bg_dropdown']};
            color: {t['text']};
            font-size: 12px;
            border: 1px solid {t['accent']};
            border-radius: 4px;
            padding: 2px;
        }}
        /* TabWidget Styling */
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
            margin-left: 2px
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
        QLabel#theme_hint {{
            font-size: 12px;
            color: {t['accent']};
        }}
        QScrollArea, QWidget#theme_selector_container {{
            background: transparent;
            border: none;
        }}
        QScrollArea QWidget#qt_scrollarea_viewport {{
            background: transparent;
        }}
        QPushButton#theme_item, QPushButton#theme_interval_btn {{ /* Default state for unselected, unhovered */
            background: transparent;
            color: {panel_dimmed_color};
            border: none;
            text-align: center;
            font-size: 12px;
            padding: 1px 0px;
        }}
        QPushButton#theme_item {{ font-weight: normal; }}
        QPushButton#theme_interval_btn {{ font-weight: bold; }}
        QPushButton#theme_item[selected="true"], QPushButton#theme_interval_btn[selected="true"] {{
            color: {t['accent']};
            font-weight: bold;
        }}
        QPushButton#theme_item:hover, QPushButton#theme_interval_btn:hover {{
            color: {t['accent_light']};
            background: rgba({_hex_to_rgb(t['accent'])}, 0.1);
        }}
        QPushButton#theme_item[active_display="true"] {{
            text-decoration: underline;
            font-weight: bold;
        }}
        QPushButton#theme_add_all, QPushButton#theme_remove_all, QPushButton#theme_change_now, QPushButton#secondary_button {{
            background: transparent;
            color: {t['text']};
            border: 1px solid {t['accent_dark']};
            font-size: 11px;
            padding: 4px;
            border-radius: 4px;
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
        QPushButton#theme_add_all:hover, QPushButton#theme_remove_all:hover, QPushButton#theme_change_now:hover, QPushButton#secondary_button:hover {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            font-weight: bold;
        }}
        QPushButton#library_add_folder_btn, QPushButton#library_remove_folder_btn, QPushButton#library_rescan_btn {{
            background: transparent;
            color: {t['text']};
            border: 1px solid {t['accent_dark']};
            padding: 4px;
            border-radius: 4px;
            font-weight: bold;
        }}
        QPushButton#library_add_folder_btn:hover, QPushButton#library_remove_folder_btn:hover, QPushButton#library_rescan_btn:hover {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            font-weight: bold;
        }}
        QPushButton#library_add_folder_btn:pressed, QPushButton#library_remove_folder_btn:pressed, QPushButton#library_rescan_btn:pressed {{
            background-color: {t['accent_dark']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            font-weight: bold;
        }}

        #disable_sleep_btn, #reset_audio_btn {{ /* Shared styling for prominent action buttons */
            background: {accent_style};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            font-size: 14px;
            padding: 10px;
            margin-top: 10px;
        }}
        /* Custom Scrollbar for QComboBox dropdown list */
        QComboBox QAbstractItemView QScrollBar:vertical,
        QListWidget#chapter_dropdown QScrollBar:vertical,
        QListWidget#settings_folder_list QScrollBar:vertical,
        #library_panel QScrollBar:vertical {{
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
        QComboBox QAbstractItemView QScrollBar::handle:vertical,
        QListWidget#chapter_dropdown QScrollBar::handle:vertical,
        QListWidget#settings_folder_list QScrollBar::handle:vertical,
        #library_panel QScrollBar::handle:vertical {{
            background: {t['accent']};
            min-height: 20px;
            border-radius: 4px;
        }}
        QComboBox QAbstractItemView QScrollBar::add-line:vertical,
        QComboBox QAbstractItemView QScrollBar::sub-line:vertical,
        QListWidget#chapter_dropdown QScrollBar::add-line:vertical,
        QListWidget#chapter_dropdown QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QComboBox QAbstractItemView QScrollBar::add-page:vertical,
        QComboBox QAbstractItemView QScrollBar::sub-page:vertical,
        QListWidget#chapter_dropdown QScrollBar::add-page:vertical,
        QListWidget#chapter_dropdown QScrollBar::sub-page:vertical {{
            background: none;
        }}
    """


def get_hover_stylesheet(theme_name="default"):
    """
    Returns a minimal stylesheet covering only widgets visible during settings panel hover preview.
    Uses the same theme lookup logic as get_stylesheet().
    """
    base = THEMES["The Color Purple"].copy()
    custom = THEMES.get(theme_name, {})
    base.update(custom)
    t = base

    text_rgb = _hex_to_rgb(t['text'])

    # Prepare dynamic backgrounds
    main_bg_style = _get_gradient_style(t, "bg", t['bg_main'])
    panel_dimmed_color = t.get('panel_theme_names_dimmed', t['accent_dark'])

    tab_hover_bg = t.get('settings_tab_hover_bg', t['accent'])
    tab_hover_opacity = t.get('settings_tab_hover_opacity', 0.85)
    tab_hover_text = t.get('settings_tab_hover_text', t['text'])

    return f"""
        QWidget#mainwindow {{
            background: {main_bg_style};
            border-radius: 8px;
        }}
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
            font-weight: bold;
        }}
        TitleBar QPushButton:hover {{
            background: {t['accent']};
        }}
        TitleBar QPushButton:pressed {{
            background-color: {t['accent_dark']};
        }}
        QLabel#percentage_label {{
            color: rgba({_hex_to_rgb(t.get('progress_text', t.get('text_on_light_bg', t['text'])))}, 0.85);
            font-weight: bold;
            font-size: 16px;
            background: transparent;
        }}
        QLabel#chap_elapsed_label, QLabel#chap_duration_label, QLabel#curr_time_label, QLabel#total_time_label {{
            color: {t['text']};
        }}
        #overall_progress {{
            qproperty-bg_color: "{t['slider_overall_bg']}";
            qproperty-fill_color: "{t['slider_overall_fill']}";
        }}
        #chapter_progress {{
            qproperty-bg_color: "{t['slider_chapter_bg']}";
            qproperty-fill_color: "{t['slider_chapter_fill']}";
        }}
        #volume_slider {{
            qproperty-bg_color: "{t['slider_vol_bg']}";
            qproperty-fill_color: "{t['slider_vol_fill']}";
        }}
        QPushButton#play_pause_btn, QPushButton#prev_btn, QPushButton#rewind_btn, QPushButton#forward_btn, QPushButton#next_btn, QPushButton#speed_btn {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            border-radius: 4px;
            padding: 6px;
            font-weight: normal;
        }}

        QPushButton#sleep_timer_display {{
            background: transparent;
            border: none;
            padding: 0px;
            color: {t['text']};
        }}
        QWidget#settings_panel {{
            background-color: rgba({_hex_to_rgb(t['bg_main'])}, {t['panel_opacity_hover']});
            border-right: 1px solid {t['accent']};
            border-radius: 0px;
        }}
        QTabWidget#settings_tabs {{
            background: transparent;
        }}
        QTabWidget#settings_tabs::pane {{
            border-top: 1px solid {t['accent_dark']};
            background: transparent;
        }}
        QTabBar {{
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
            margin-left: 2px
        }}
        QTabBar::tab:selected {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
        }}
        QPushButton#theme_item {{
            background: transparent;
            color: {panel_dimmed_color};
            border: none;
            text-align: center;
            font-size: 12px;
            padding: 1px 0px;
            font-weight: normal;
        }}
        QPushButton#theme_item[selected="true"] {{
            color: {t['accent']};
            font-weight: bold;
        }}
        QPushButton#theme_item:hover {{
            color: {t['accent_light']};
            background: rgba({_hex_to_rgb(t['accent'])}, 0.1);
        }}
        QPushButton#theme_item[active_display="true"] {{
            text-decoration: underline;
            font-weight: bold;
        }}
        QPushButton#theme_interval_btn {{
            background: transparent;
            color: {panel_dimmed_color};
            border: none;
            text-align: center;
            font-size: 12px;
            padding: 1px 0px;
            font-weight: bold;
        }}
        QPushButton#theme_interval_btn[selected="true"] {{
            color: {t['accent']};
            font-weight: bold;
        }}
        QPushButton#theme_interval_btn:hover {{
            color: {t['accent_light']};
            background: rgba({_hex_to_rgb(t['accent'])}, 0.1);
            font-weight: bold;
        }}
        QPushButton#theme_add_all, QPushButton#theme_remove_all, QPushButton#theme_change_now {{
            background: transparent;
            color: {t['text']};
            border: 1px solid {t['accent_dark']};
            font-size: 11px;
            padding: 4px;
            border-radius: 4px;
            font-weight: bold;
        }}
        QPushButton#theme_add_all:hover, QPushButton#theme_remove_all:hover, QPushButton#theme_change_now:hover {{
            background: {t['accent']};
            color: {t.get('button_text', t.get('text_on_light_bg', t['text']))};
            font-weight: bold;
        }}
        QLabel#theme_hint {{
            font-size: 12px;
            color: {t['accent']};
        }}
        QWidget#visual_area {{
            background-color: transparent;
        }}
    """
