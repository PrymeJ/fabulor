import locale
import sys
import os

from PySide6.QtWidgets import QApplication
from fabulor.app import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setDesktopFileName("fabulor") 
    locale.setlocale(locale.LC_NUMERIC, "C")  # after Qt, not before
    window = MainWindow()
    window.show()
    sys.exit(app.exec())