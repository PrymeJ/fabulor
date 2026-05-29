import locale
import sys
import os

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QFont
from fabulor.app import MainWindow

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "src", "fabulor", "assets", "fonts")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setDesktopFileName("fabulor")
    font_id = QFontDatabase.addApplicationFont(
        os.path.join(_FONTS_DIR, "OpenSans-CondensedRegular.ttf")
    )
    if font_id != -1:
        families = QFontDatabase.applicationFontFamilies(font_id)
        target = next((f for f in families if "Condensed" in f), families[0] if families else None)
        if target:
            app.setFont(QFont(target, 11))
    locale.setlocale(locale.LC_NUMERIC, "C")  # after Qt, not before
    window = MainWindow()
    window.show()
    sys.exit(app.exec())