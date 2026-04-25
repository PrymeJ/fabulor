from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QLabel, QGridLayout, QSpinBox, QHBoxLayout
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

    @staticmethod
    def _format_duration(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"

    def _build_overall_tab(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(10, 10, 10, 10)

        grid_container = QWidget()
        grid = QGridLayout(grid_container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        rows = [
            ("Listening time", "—"),
            ("Books started",  "—"),
            ("Sessions",       "—"),
            ("Most listened",  "—"),
        ]

        self._overall_value_labels = []
        for i, (key, default) in enumerate(rows):
            key_lbl = QLabel(key)
            key_lbl.setObjectName("stats_key_label")
            val_lbl = QLabel(default)
            val_lbl.setObjectName("stats_value_label")
            grid.addWidget(key_lbl, i, 0, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(val_lbl, i, 1, Qt.AlignmentFlag.AlignLeft)
            self._overall_value_labels.append(val_lbl)

        

        outer.addStretch()
        outer.addWidget(grid_container, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch()
        return widget

    def refresh_overall(self):
        stats = self.db.get_overall_stats()
        self._overall_value_labels[0].setText(self._format_duration(stats['total_seconds']))
        self._overall_value_labels[1].setText(str(stats['books_started']))
        self._overall_value_labels[2].setText(str(stats['sessions']))
        if stats['most_listened_title']:
            duration = self._format_duration(stats['most_listened_seconds'])
            self._overall_value_labels[3].setText(f"{stats['most_listened_title']}  ({duration})")
        else:
            self._overall_value_labels[3].setText("—")

    def _build_options_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)

        pref_row = QHBoxLayout()
        pref_row.addWidget(QLabel("Day starts at"))
        self.day_start_spin = QSpinBox()
        self.day_start_spin.setRange(0, 23)
        self.day_start_spin.setValue(self.config.get_day_start_hour())
        self.day_start_spin.valueChanged.connect(self.config.set_day_start_hour)
        pref_row.addWidget(self.day_start_spin)
        pref_row.addStretch()
        layout.addLayout(pref_row)
        layout.addStretch()
        return widget   

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("stats_tabs")

        self.tabs.addTab(self._build_overall_tab(), "Overall")
        

        for name in ["Daily", "Weekly", "Monthly"]:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(10, 10, 10, 10)
            lbl = QLabel(f"{name} stats coming soon...")
            lbl.setObjectName("stats_placeholder_label")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tab_layout.addWidget(lbl)
            tab_layout.addStretch()
            self.tabs.addTab(tab, name)

        self.tabs.addTab(self._build_options_tab(), "Options")

        layout.addWidget(self.tabs)
        self.refresh_overall()
