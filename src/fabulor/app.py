import sys
from PySide6.QtWidgets import QApplication, QLabel

def run():
    app = QApplication(sys.argv)

    label = QLabel("Fabulor")
    label.resize(300, 100)
    label.show()

    sys.exit(app.exec())
