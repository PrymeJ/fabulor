import hashlib
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QButtonGroup, QFileDialog, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QBrush, QPen

from ..library.cover_manager import (
    save_cover_image, delete_cover_file, validate_cover_file,
)


def _book_hash(book_path: str) -> str:
    return hashlib.md5(book_path.encode()).hexdigest()


_OVERLAY_HEIGHT = 17
_THUMB_SIZE = 72


class CoverThumbnail(QFrame):
    """Single 72×72 cover thumbnail with hover overlay."""

    clicked_preview    = Signal(int)   # cover_id
    clicked_set_active = Signal(int)   # cover_id
    clicked_delete     = Signal(int)   # cover_id

    def __init__(self, cover_id: int, file_path: str, is_locked: bool,
                 is_active: bool, accent_color: str = "#5A8A9F", parent=None):
        super().__init__(parent)
        self._cover_id   = cover_id
        self._file_path  = file_path
        self._is_locked  = is_locked
        self._is_active  = is_active
        self._accent     = QColor(accent_color)
        self._hovered    = False
        self._pixmap     = QPixmap()

        self._overlay_enabled = True

        self.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("CoverThumbnailActive" if is_active else "CoverThumbnail")
        self._load_pixmap()

    def _load_pixmap(self):
        try:
            raw = QPixmap(self._file_path)
            if not raw.isNull():
                self._pixmap = raw.scaled(
                    _THUMB_SIZE, _THUMB_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        except Exception:
            pass

    def set_active(self, active: bool):
        self._is_active = active
        self.setObjectName("CoverThumbnailActive" if active else "CoverThumbnail")
        self.repaint()

    def set_overlay_enabled(self, enabled: bool):
        self._overlay_enabled = enabled

    def set_accent(self, color: str):
        self._accent = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Clip image to interior — keeps it contained inside the border zone
        inner = self.rect().adjusted(1, 1, -1, -1)
        painter.save()
        painter.setClipRect(inner)
        if not self._pixmap.isNull():
            x = inner.x() + (inner.width()  - self._pixmap.width())  // 2
            y = inner.y() + (inner.height() - self._pixmap.height()) // 2
            painter.drawPixmap(x, y, self._pixmap)
        else:
            painter.fillRect(inner, QColor("#2A2A2A"))
        painter.restore()

        # Active outline — 2px accent border drawn on top of image
        if self._is_active:
            pen = QPen(self._accent, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(1, 1, -1, -1))

        # Hover overlay — suppressed when nothing is actionable
        if self._hovered and self._overlay_enabled and not (self._is_locked and self._is_active):
            overlay_rect = self.rect().adjusted(0, _THUMB_SIZE - _OVERLAY_HEIGHT, 0, 0)
            overlay_color = QColor(0, 0, 0, 160)
            painter.fillRect(overlay_rect, overlay_color)

            mid_x = _THUMB_SIZE // 2
            text_y = _THUMB_SIZE - _OVERLAY_HEIGHT // 2 + 5

            # 1px vertical separator
            painter.setPen(QColor(255, 255, 255, 80))
            painter.drawLine(mid_x, _THUMB_SIZE - _OVERLAY_HEIGHT, mid_x, _THUMB_SIZE)

            painter.setPen(QColor(255, 255, 255, 220))

            # × on left (only if not locked)
            if not self._is_locked:
                painter.drawText(
                    0, _THUMB_SIZE - _OVERLAY_HEIGHT,
                    mid_x, _OVERLAY_HEIGHT,
                    Qt.AlignmentFlag.AlignCenter, "×"
                )

            # ✓ on right (only if not already active)
            if not self._is_active:
                painter.drawText(
                    mid_x, _THUMB_SIZE - _OVERLAY_HEIGHT,
                    mid_x, _OVERLAY_HEIGHT,
                    Qt.AlignmentFlag.AlignCenter, "✓"
                )

        painter.end()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        y = event.position().y()
        x = event.position().x()
        if self._hovered and y >= (_THUMB_SIZE - _OVERLAY_HEIGHT):
            mid_x = _THUMB_SIZE // 2
            if x < mid_x:
                if not self._is_locked:
                    self.clicked_delete.emit(self._cover_id)
            else:
                if not self._is_active:
                    self.clicked_set_active.emit(self._cover_id)
        else:
            self.clicked_preview.emit(self._cover_id)
        super().mousePressEvent(event)


class CoverPanel(QWidget):
    active_cover_changed = Signal(str)  # emits file_path of new active cover

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self._db          = db
        self._book_path   = None
        self._covers      = []       # list[dict] from get_covers_for_book
        self._thumbnails  = {}       # cover_id → CoverThumbnail
        self._selected    = None     # currently previewed cover dict
        self._accent      = "#5A8A9F"
        self._preview_bg  = QColor("#000000")

        self._build_ui()

    # ── Public API ────────────────────────────────────────────────────────────

    def load_book(self, book_path: str | None):
        self._book_path = book_path
        self._covers = self._db.get_covers_for_book(book_path) if book_path else []
        self._rebuild_thumbnails()

        active = next((c for c in self._covers if c['is_active']), None)
        if not active and self._covers:
            active = self._covers[0]
        if active:
            self._select_cover(active)
        else:
            self._preview_label.clear()

    def on_theme_changed(self, theme: dict):
        from ..themes import get_cover_panel_stylesheet
        self._accent = theme.get('accent', '#5A8A9F')
        bg_str = theme.get('cover_preview_bg', theme.get('bg_deep', '#000000'))
        self._preview_bg = QColor(bg_str)
        self.setStyleSheet(get_cover_panel_stylesheet(theme))
        for thumb in self._thumbnails.values():
            thumb.set_accent(self._accent)
        self._sync_fit_button_styles()
        self._render_preview()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 10, 6, 10)
        root.setSpacing(8)

        # ── Left column ──
        self._left_col = QWidget()
        self._left_col.setFixedWidth(_THUMB_SIZE)
        self._left_col.setFixedHeight(0)   # updated explicitly after each thumb change
        self._thumb_layout = QVBoxLayout(self._left_col)
        self._thumb_layout.setContentsMargins(0, 0, 0, 0)
        self._thumb_layout.setSpacing(6)

        self._add_btn = QPushButton("+")
        self._add_btn.setObjectName("CoverAddButton")
        self._add_btn.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        self._add_btn.clicked.connect(self._on_add_cover)

        self._error_label = QLabel()
        self._error_label.setObjectName("CoverErrorLabel")
        self._error_label.setWordWrap(True)
        self._error_label.setFixedWidth(_THUMB_SIZE)
        self._error_label.hide()

        left_wrapper = QVBoxLayout()
        left_wrapper.setContentsMargins(0, 0, 0, 0)
        left_wrapper.setSpacing(6)      # same gap as between thumbs
        left_wrapper.addWidget(self._left_col)
        left_wrapper.addWidget(self._add_btn)
        left_wrapper.addWidget(self._error_label)
        left_wrapper.addStretch()

        # ── Right column ──
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(6)

        self._preview_label = QLabel()
        self._preview_label.setObjectName("CoverPreview")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setFixedSize(208, 266)

        # Fit mode buttons
        fit_row = QHBoxLayout()
        fit_row.setSpacing(4)
        self._fit_group = QButtonGroup(self)
        self._fit_group.setExclusive(True)
        self._fit_buttons = {}
        for label, key in (("Fit", "fit"), ("Stretch", "stretch"),
                           ("Top", "top"), ("Crop", "crop")):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setObjectName("FitModeButton")
            btn.setProperty("fitKey", key)
            btn.setFixedHeight(34)
            self._fit_group.addButton(btn)
            self._fit_buttons[key] = btn
            fit_row.addWidget(btn)

        self._fit_group.buttonClicked.connect(self._on_fit_mode_clicked)
        self._fit_buttons["fit"].setChecked(True)

        right_col.addWidget(self._preview_label)
        right_col.addLayout(fit_row)
        right_col.addStretch()

        root.addLayout(left_wrapper)
        root.addLayout(right_col, stretch=1)

    # ── Thumbnail management ──────────────────────────────────────────────────

    def _update_left_col_height(self):
        n = len(self._thumbnails)
        h = n * _THUMB_SIZE + max(n - 1, 0) * 6
        self._left_col.setFixedHeight(h)

    def _rebuild_thumbnails(self):
        for thumb in self._thumbnails.values():
            self._thumb_layout.removeWidget(thumb)
            thumb.deleteLater()
        self._thumbnails.clear()

        for cover in self._covers:
            thumb = CoverThumbnail(
                cover_id=cover['id'],
                file_path=cover['file_path'],
                is_locked=bool(cover['is_locked']),
                is_active=bool(cover['is_active']),
                accent_color=self._accent,
                parent=self,
            )
            thumb.clicked_preview.connect(self._on_thumb_preview)
            thumb.clicked_set_active.connect(self._on_thumb_set_active)
            thumb.clicked_delete.connect(self._on_thumb_delete)
            self._thumbnails[cover['id']] = thumb
            self._thumb_layout.addWidget(thumb)

        self._update_left_col_height()
        self._update_overlay_enabled()
        user_count = sum(1 for c in self._covers if not c['is_locked'])
        self._add_btn.setVisible(user_count < 3)

    def _update_overlay_enabled(self):
        # Overlay is hidden when the locked cover is alone (nothing to ✓ or ×)
        sole_locked = len(self._covers) == 1 and self._covers[0]['is_locked']
        for cover_id, thumb in self._thumbnails.items():
            thumb.set_overlay_enabled(not sole_locked)

    def _update_active_outlines(self):
        for cover_id, thumb in self._thumbnails.items():
            is_active = any(
                c['id'] == cover_id and c['is_active'] for c in self._covers
            )
            thumb.set_active(is_active)

    # ── Cover selection / preview ─────────────────────────────────────────────

    def _select_cover(self, cover: dict):
        self._selected = cover
        self._render_preview()
        # Sync fit mode buttons to this cover's fit_mode
        fit_key = cover.get('fit_mode', 'fit')
        btn = self._fit_buttons.get(fit_key)
        if btn:
            btn.setChecked(True)

    def _render_preview(self):
        if not self._selected:
            self._preview_label.clear()
            return

        file_path = self._selected.get('file_path', '')
        fit_mode  = self._selected.get('fit_mode', 'fit')
        w = self._preview_label.width()
        h = self._preview_label.height()

        src = QPixmap()
        try:
            src.load(file_path)
        except Exception:
            pass

        if src.isNull():
            self._preview_label.clear()
            return

        if fit_mode == 'stretch':
            result = src.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)

        elif fit_mode == 'top':
            # Scale to fit width, anchor image to top edge
            fitted = src.scaled(w, 32767, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            result = QPixmap(w, h)
            result.fill(self._preview_bg)
            painter = QPainter(result)
            painter.drawPixmap(0, 0, fitted)
            painter.end()

        elif fit_mode == 'crop':
            scaled = src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            x = (scaled.width()  - w) // 2
            y = (scaled.height() - h) // 2
            result = scaled.copy(x, y, w, h)

        else:  # fit (and unrecognised modes)
            fitted = src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            result = QPixmap(w, h)
            result.fill(self._preview_bg)
            painter = QPainter(result)
            x = (w - fitted.width())  // 2
            y = (h - fitted.height()) // 2
            painter.drawPixmap(x, y, fitted)
            painter.end()

        self._preview_label.setPixmap(result)

    # ── Fit mode ─────────────────────────────────────────────────────────────

    def _on_fit_mode_clicked(self, btn: QPushButton):
        fit_key = btn.property("fitKey")
        if self._selected:
            self._db.set_fit_mode(self._selected['id'], fit_key)
            self._selected['fit_mode'] = fit_key
            # Keep covers list in sync
            for c in self._covers:
                if c['id'] == self._selected['id']:
                    c['fit_mode'] = fit_key
                    break
        self._render_preview()
        # If the selected cover is the active one, propagate to main window
        active = next((c for c in self._covers if c['is_active']), None)
        if active and self._selected and active['id'] == self._selected['id']:
            self.active_cover_changed.emit(active['file_path'])

    def _sync_fit_button_styles(self):
        for btn in self._fit_buttons.values():
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ── Thumbnail signals ─────────────────────────────────────────────────────

    def _on_thumb_preview(self, cover_id: int):
        cover = next((c for c in self._covers if c['id'] == cover_id), None)
        if cover:
            self._select_cover(cover)

    def _on_thumb_set_active(self, cover_id: int):
        if not self._book_path:
            return
        self._db.set_active_cover(self._book_path, cover_id)
        # Update local state
        for c in self._covers:
            c['is_active'] = int(c['id'] == cover_id)
        self._update_active_outlines()
        active = next((c for c in self._covers if c['is_active']), None)
        if active:
            self._select_cover(active)
            self.active_cover_changed.emit(active['file_path'])

    def _on_thumb_delete(self, cover_id: int):
        if not self._book_path:
            return
        cover = next((c for c in self._covers if c['id'] == cover_id), None)
        if not cover or cover['is_locked']:
            return

        was_active = bool(cover['is_active'])
        self._db.delete_cover(cover_id)
        delete_cover_file(cover['file_path'])

        self._covers = [c for c in self._covers if c['id'] != cover_id]
        thumb = self._thumbnails.pop(cover_id, None)
        if thumb:
            self._thumb_layout.removeWidget(thumb)
            thumb.deleteLater()
        self._update_left_col_height()
        self._update_overlay_enabled()

        # Promote locked cover if the deleted one was active
        if was_active:
            locked = next((c for c in self._covers if c['is_locked']), None)
            if locked:
                self._db.set_active_cover(self._book_path, locked['id'])
                locked['is_active'] = 1
                self._update_active_outlines()
                self._select_cover(locked)
                self.active_cover_changed.emit(locked['file_path'])
        elif self._selected and self._selected['id'] == cover_id:
            # Deleted non-active selected → preview active cover
            active = next((c for c in self._covers if c['is_active']), None)
            if active:
                self._select_cover(active)

        user_count = sum(1 for c in self._covers if not c['is_locked'])
        self._add_btn.setVisible(user_count < 3)

    # ── Add cover ─────────────────────────────────────────────────────────────

    def _on_add_cover(self):
        if not self._book_path:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Cover Image", "",
            "Images (*.jpg *.jpeg *.png)"
        )
        if not path:
            return

        error = validate_cover_file(path)
        if error:
            self._show_error(error)
            return

        # Convert PNG to JPEG in memory for storage consistency
        img = QImage(path)
        if img.isNull():
            self._show_error("Could not read image.")
            return

        # Determine next slot index (1–3)
        used_slots = {c['sort_order'] for c in self._covers if not c['is_locked']}
        slot_index = next(i for i in range(1, 4) if i not in used_slots)

        book_hash = _book_hash(self._book_path)

        # Save as JPEG
        from ..library.cover_manager import get_covers_dir
        import tempfile, shutil
        try:
            dest_path_obj = get_covers_dir() / f"{book_hash}_{slot_index}.jpg"
            saved = img.save(str(dest_path_obj), "JPEG")
            dest_path = str(dest_path_obj) if saved else None
        except Exception:
            dest_path = None

        if not dest_path:
            self._show_error("Failed to save image.")
            return

        cover_id = self._db.upsert_cover(
            book_path=self._book_path,
            file_path=dest_path,
            is_locked=False,
            is_active=False,
            fit_mode='fit',
            sort_order=slot_index,
        )

        new_cover = {
            'id': cover_id,
            'file_path': dest_path,
            'is_locked': 0,
            'is_active': 0,
            'fit_mode': 'fit',
            'sort_order': slot_index,
        }
        self._covers.append(new_cover)

        thumb = CoverThumbnail(
            cover_id=cover_id,
            file_path=dest_path,
            is_locked=False,
            is_active=False,
            accent_color=self._accent,
            parent=self,
        )
        thumb.clicked_preview.connect(self._on_thumb_preview)
        thumb.clicked_set_active.connect(self._on_thumb_set_active)
        thumb.clicked_delete.connect(self._on_thumb_delete)
        self._thumbnails[cover_id] = thumb
        self._thumb_layout.addWidget(thumb)
        self._update_left_col_height()
        self._update_overlay_enabled()

        user_count = sum(1 for c in self._covers if not c['is_locked'])
        self._add_btn.setVisible(user_count < 3)

    # ── Error display ─────────────────────────────────────────────────────────

    def _show_error(self, message: str):
        self._error_label.setText(message)
        self._error_label.show()
        QTimer.singleShot(3000, self._error_label.hide)
