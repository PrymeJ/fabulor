THEMES = {
    "default": {
        "bg_deep":      "#0D001A",  # title bar, darkest
        "bg_main":      "#1A002E",  # main window background
        "slider_overall_bg":   "#4B0082",
        "slider_overall_fill": "#C8A2C8",
        "slider_chapter_bg":   "#330066",
        "slider_chapter_fill": "#A080A0",
        "slider_vol_bg":       "#220044",
        "slider_vol_fill":     "#7B2CBF",
        "accent":              "#7B2CBF",  # primary buttons, hover states
        "accent_light": "#9D4EDD",  # button hover
        "accent_dark":  "#5A189A",  # button pressed
        "bg_sidebar":   "#120024",  # drawer background
        "sidebar_opacity": 0.6,
        "sidebar_opacity_hover": 0.8,
        "text":         "#F0F0F0",  # all labels and button text
    }
}

def _hex_to_rgb(hex_str):
    h = hex_str.lstrip('#')
    return ",".join(str(int(h[i:i+2], 16)) for i in (0, 2, 4))

def get_stylesheet(theme_name="default"):
    t = THEMES.get(theme_name, THEMES["default"])
    sidebar_rgb = _hex_to_rgb(t['bg_sidebar'])
    text_rgb = _hex_to_rgb(t['text'])

    return f"""
        QWidget#mainwindow {{
            background-color: {t['bg_main']};
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
        QWidget#sidebar {{
            background-color: rgba({sidebar_rgb}, {t['sidebar_opacity']});
            border-right: 1px solid {t['slider_overall_bg']};
            border-radius: 0px;
        }}
        QWidget#sidebar:hover {{
            background-color: rgba({sidebar_rgb}, {t['sidebar_opacity_hover']});
        }}
        TitleBar QLabel {{
            color: {t['text']};
            font-weight: bold;
        }}
        QWidget#sidebar QLabel {{
            font-size: 12px;
            color: rgba({text_rgb}, {t['sidebar_opacity']});
        }}
        QWidget#sidebar:hover QLabel {{
            color: rgba({text_rgb}, {t['sidebar_opacity_hover']});
        }}
        QLabel#sidebar_title {{
            font-weight: bold;
            margin-bottom: 10px;
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
        QPushButton#chapter_selector {{
            background: transparent;
            border: none;
            padding: 2px;
            font-size: 13px;
        }}
        QListWidget#chapter_dropdown {{
            background-color: {t['bg_deep']};
            border: 1px solid {t['accent']};
            outline: none;
        }}
        QListWidget#chapter_dropdown::item:selected {{
            background-color: {t['accent']};
            color: {t['text']};
        }}
        /* Overall Progress Slider */
        QSlider#overall_progress::groove:horizontal {{
            background: {t['slider_overall_bg']};
            height: 24px;
        }}
        QSlider#overall_progress::sub-page:horizontal {{
            background: {t['slider_overall_fill']};
            height: 24px;
        }}
        QSlider#overall_progress::handle:horizontal {{
            background: {t['slider_overall_fill']};
            width: 2px;
        }}

        /* Chapter Progress Slider */
        QSlider#chapter_progress::groove:horizontal {{
            background: {t['slider_chapter_bg']};
            height: 12px;
        }}
        QSlider#chapter_progress::sub-page:horizontal {{
            background: {t['slider_chapter_fill']};
            height: 12px;
        }}
        QSlider#chapter_progress::handle:horizontal {{
            background: {t['slider_chapter_fill']};
            width: 2px;
        }}

        /* Volume Slider */
        QSlider#volume_slider::groove:horizontal {{
            background: {t['slider_vol_bg']};
            height: 8px;
        }}
        QSlider#volume_slider::sub-page:horizontal {{
            background: {t['slider_vol_fill']};
            height: 8px;
        }}
        QSlider#volume_slider::handle:horizontal {{
            background: {t['slider_vol_fill']};
            width: 8px;
            margin: -2px 0;
        }}
    """
