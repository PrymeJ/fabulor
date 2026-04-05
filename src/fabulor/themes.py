THEMES = {
    "default": {
        "bg_deep":      "#0D001A",  # title bar, darkest
        "bg_main":      "#1A002E",  # main window background
        "bg_slider":    "#4B0082",  # slider groove / inactive
        "accent":       "#7B2CBF",  # primary buttons, hover states
        "accent_light": "#9D4EDD",  # button hover
        "accent_dark":  "#5A189A",  # button pressed
        "highlight":    "#C8A2C8",  # slider fill and handle (lilac)
        "text":         "#F0F0F0",  # all labels and button text
    }
}

def get_stylesheet(theme_name="default"):
    t = THEMES.get(theme_name, THEMES["default"])
    return f"""
        QWidget#mainwindow {{
            background-color: {t['bg_main']};
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
        }}
        TitleBar QPushButton:hover {{
            background: {t['accent']};
        }}
        QLabel {{
            color: {t['text']};
        }}
        QLabel#percentage_label {{
            color: rgba(255, 255, 255, 0.85);
            font-weight: bold;
            font-size: 16px;
            background: transparent;
        }}
        QPushButton {{
            background-color: {t['accent']};
            color: {t['text']};
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
        QSlider {{
            background: {t['bg_slider']};
        }}
        QSlider::groove:horizontal {{
            border: none;
            background: {t['bg_slider']};
            height: 24px;
        }}
        QSlider::sub-page:horizontal {{
            background: {t['highlight']};
            height: 24px;
        }}
        QSlider::handle:horizontal {{
            background: {t['highlight']};
            width: 2px;
            margin: 0px;
        }}
    """