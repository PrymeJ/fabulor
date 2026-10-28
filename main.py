import locale
import sys
import os

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QFont
from fabulor.logger_setup import setup_logging
from fabulor.app import MainWindow
from fabulor.ui.no_focus_rect_style import NoFocusRectStyle
from fabulor.ui.cover_placeholder_layout import PLACEHOLDER_FONT_FILES

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "src", "fabulor", "assets", "fonts")

if __name__ == "__main__":
    setup_logging()
    app = QApplication(sys.argv)
    app.setStyle(NoFocusRectStyle(app.style()))
    app.setDesktopFileName("fabulor")
    font_id = QFontDatabase.addApplicationFont(
        os.path.join(_FONTS_DIR, "OpenSans-CondensedRegular.ttf")
    )
    if font_id != -1:
        families = QFontDatabase.applicationFontFamilies(font_id)
        target = next((f for f in families if "Condensed" in f), families[0] if families else None)
        if target:
            app.setFont(QFont(target, 11))
    # No-cover placeholder title/author fonts (see ui/cover_placeholder_layout.py).
    for _fn in PLACEHOLDER_FONT_FILES:
        QFontDatabase.addApplicationFont(os.path.join(_FONTS_DIR, _fn))
    locale.setlocale(locale.LC_NUMERIC, "C")  # after Qt, not before
    window = MainWindow()
    window.show()
    sys.exit(app.exec())