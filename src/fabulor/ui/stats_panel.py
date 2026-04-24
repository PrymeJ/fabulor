from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QLabel
)
from PySide6.QtCore import Qt


class StatsPanel(QWidget):
    def __init__(self, db, config, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self.setObjectName("stats_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("stats_tabs")

        for name in ["Overall", "Daily", "Weekly", "Monthly"]:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(10, 10, 10, 10)
            lbl = QLabel(f"{name} stats coming soon...")
            lbl.setObjectName("stats_placeholder_label")
            lbl.setAlignment(Qt.AlignCenter)
            tab_layout.addWidget(lbl)
            tab_layout.addStretch()
            self.tabs.addTab(tab, name)

        layout.addWidget(self.tabs)
