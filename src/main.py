# -*- coding: utf-8 -*-
"""
Screenshot Translator - Main Application

A high-performance desktop OCR + translation suite featuring:
  - Global F1 hotkey for instant region capture
  - Multi-monitor virtual desktop support with DPI awareness
  - Floating toolbar with one-click actions
  - Cloud Vision-Language Model OCR pipeline
  - Live translation overlay rendered as Markdown-styled HTML
  - Red-pen annotation with undo support
  - Pin-to-screen always-on-top window with drag/resize
  - System tray integration with context menu
  - Clipboard-first workflow (double-click to copy)

UI: dark translucent toolbar with cyan accent borders.
"""

import sys
import traceback
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QHBoxLayout,
    QSystemTrayIcon, QMenu, QAction, QFileDialog, QLabel,
)
from PyQt5.QtCore import Qt, QRect, QRectF, QPoint, QBuffer, QByteArray, QThread, pyqtSignal, QTimer, QSizeF
from PyQt5.QtGui import (
    QPainter, QPen, QColor, QPixmap, QCursor,
    QIcon, QFont, QFontMetrics, QBrush, QTextDocument, QPalette,
    QAbstractTextDocumentLayout,
)

from config import PEN_COLOR, PEN_WIDTH, HOTKEY_VK, HOTKEY_MOD

# Theme colors
CYAN = QColor(0, 220, 220)
DARK_BG = QColor(20, 20, 20, 220)
HANDLE_COLOR = QColor(0, 220, 220)

OVERLAY_FONT_PX = 21
OVERLAY_WRAP_MIN_W = 140


# ──────────────────────────────────────────────
#  Background workers
# ──────────────────────────────────────────────
class OcrWorker(QThread):
    """Async OCR pipeline. Emits the raw structured response (with bounding boxes)."""
    finished = pyqtSignal(object)  # dict
    text_only = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, image_bytes):
        super().__init__()
        self.image_bytes = image_bytes

    def run(self):
        try:
            from ocr_client import ocr_image, ocr_image_text
            raw = ocr_image(self.image_bytes)
            text = ocr_image_text(self.image_bytes)
            self.finished.emit(raw)
            self.text_only.emit(text)
        except Exception as e:
            self.error.emit(f"OCR failed: {e}")


class TranslateWorker(QThread):
    """Single-string translation worker (kept for backward compatibility)."""
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, text, from_lang="auto", to_lang="zh"):
        super().__init__()
        self.text = text
        self.from_lang = from_lang
        self.to_lang = to_lang

    def run(self):
        try:
            from translator import translate
            result = translate(self.text, self.from_lang, self.to_lang)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(f"Translate failed: {e}")


class BatchTranslateWorker(QThread):
    """Batch translation preserving 1:1 input/output line mapping (required by Markdown renderer)."""
    finished = pyqtSignal(list)  # list[str], len == input
    error = pyqtSignal(str)

    def __init__(self, lines, from_lang="auto", to_lang="zh"):
        super().__init__()
        self.lines = lines
        self.from_lang = from_lang
        self.to_lang = to_lang

    def run(self):
        try:
            from translator import translate_lines
            self.finished.emit(translate_lines(self.lines, self.from_lang, self.to_lang))
        except Exception as e:
            self.error.emit(f"Translate failed: {e}")


# ──────────────────────────────────────────────
#  Pin-to-screen floating window
# ──────────────────────────────────────────────
class PinWindow(QWidget):
    """Always-on-top floating window pinning a screenshot to the desktop."""
    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self.pixmap = pixmap
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(pixmap.size())
        self.setCursor(Qt.OpenHandCursor)
        self._drag_pos = None

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(CYAN, 2))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)
        painter.drawPixmap(1, 1, self.pixmap)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, event):
        """Mouse-wheel zoom."""
        factor = 1.1 if event.angleDelta().y() > 0 else 0.9
        new_w = max(50, int(self.width() * factor))
        new_h = max(50, int(self.height() * factor))
        self.setFixedSize(new_w, new_h)
        self.update()

    def _show_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background: #222; color: #ddd; } QMenu::item:selected { background: #00AACC; }")
        act_copy = menu.addAction("Copy to clipboard")
        act_close = menu.addAction("Close")
        action = menu.exec_(self.mapToGlobal(pos))
        if action == act_copy:
            QApplication.clipboard().setPixmap(self.pixmap)
        elif action == act_close:
            self.close()


# ──────────────────────────────────────────────
#  Screenshot capture overlay
# ──────────────────────────────────────────────
class ScreenshotOverlay(QWidget):
    """Full-screen translucent overlay for rubber-band region selection."""

    _pin_windows = []

    def __init__(self, pixmap: QPixmap, virtual_geometry=None):
        super().__init__()
        self.full_pixmap = pixmap
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        if virtual_geometry:
            self.setGeometry(virtual_geometry)
        else:
            self.setWindowState(Qt.WindowFullScreen)
        self.setCursor(Qt.CrossCursor)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setFocusPolicy(Qt.StrongFocus)

        self.origin = QPoint()
        self.selection = QRect()
        self.is_selecting = False
        self.selection_done = False

        self.drawing = False
        self.pen_mode = False
        self.pen_lines = []
        self.current_pen_points = []

        # list of (selection-relative QRect, translated line); layout collision-resolved at paint time
        self.overlay_texts = []
        # rendered translation overlay QPixmap (scaled to selection size)
        self.overlay_pixmap = None

        self.toolbar = None
        self._workers = []

        self._status_msg = ""
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._clear_status)

        # Selection drag / resize state
        self._resize_edge = None   # 'tl','t','tr','l','r','bl','b','br' or None
        self._dragging_sel = False  # whole-selection drag
        self._drag_offset = QPoint()

    def showEvent(self, event):
        super().showEvent(event)
        self.activateWindow()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)

    def _show_status(self, msg, duration=2000):
        self._status_msg = msg
        self._status_timer.start(duration)
        self.update()

    def _clear_status(self):
        self._status_msg = ""
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Screenshot background
        painter.drawPixmap(0, 0, self.full_pixmap)

        # Translucent mask outside selection
        painter.setBrush(QBrush(QColor(0, 0, 0, 100)))
        painter.setPen(Qt.NoPen)
        painter.drawRect(self.rect())

        if not self.selection.isNull():
            # Draw original image inside selection
            painter.drawPixmap(self.selection, self.full_pixmap, self.selection)

            # Prefer the rendered translation overlay if available
            if self.overlay_pixmap is not None:
                painter.drawPixmap(self.selection, self.overlay_pixmap)
            elif self.overlay_texts:
                self._paint_overlay_translations(painter)

            # Selection border
            pen = QPen(CYAN, 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.selection)

            # Size indicator
            info = f"  {self.selection.x()},{self.selection.y()}  {self.selection.width()} × {self.selection.height()} px  "
            painter.setFont(QFont("Consolas", 10))
            fm = painter.fontMetrics()
            info_w = fm.horizontalAdvance(info) + 8
            info_h = fm.height() + 6
            info_x = self.selection.left()
            info_y = self.selection.top() - info_h - 2
            if info_y < 0:
                info_y = self.selection.top() + 2
            bg_rect = QRect(info_x, info_y, info_w, info_h)
            painter.fillRect(bg_rect, DARK_BG)
            painter.setPen(CYAN)
            painter.drawText(bg_rect, Qt.AlignCenter, info)

            # 8 resize handles
            hs = 8
            painter.setBrush(QBrush(HANDLE_COLOR))
            painter.setPen(QPen(QColor(0, 0, 0), 1))
            s = self.selection
            handles = [
                s.topLeft(), s.topRight(), s.bottomLeft(), s.bottomRight(),
                QPoint(s.center().x(), s.top()),
                QPoint(s.center().x(), s.bottom()),
                QPoint(s.left(), s.center().y()),
                QPoint(s.right(), s.center().y()),
            ]
            for h in handles:
                painter.drawEllipse(h, hs // 2, hs // 2)

        # Annotation strokes
        pen = QPen(QColor(PEN_COLOR), PEN_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        for p1, p2 in self.pen_lines:
            painter.drawLine(p1, p2)
        if self.current_pen_points:
            for i in range(len(self.current_pen_points) - 1):
                painter.drawLine(self.current_pen_points[i], self.current_pen_points[i + 1])

        # Status toast
        if self._status_msg:
            painter.setFont(QFont("Microsoft YaHei", 12))
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(self._status_msg) + 20
            th = fm.height() + 12
            cx = self.selection.center().x() - tw // 2 if not self.selection.isNull() else self.width() // 2 - tw // 2
            cy = self.selection.center().y() - th // 2 if not self.selection.isNull() else self.height() // 2 - th // 2
            painter.fillRect(QRect(cx, cy, tw, th), QColor(0, 0, 0, 180))
            painter.setPen(QColor(0, 220, 220))
            painter.drawText(QRect(cx, cy, tw, th), Qt.AlignCenter, self._status_msg)

        painter.end()

    @staticmethod
    def _align_translation_lines(parts, n_target):
        """Align translator output line count with merged OCR lines (pad with blanks or fold tail)."""
        if n_target <= 0:
            return []
        parts = list(parts) if parts else []
        if len(parts) < n_target:
            return parts + [""] * (n_target - len(parts))
        if len(parts) == n_target:
            return parts
        return parts[: n_target - 1] + ["\n".join(parts[n_target - 1 :])]

    def _paint_overlay_translations(self, painter):
        """Per-line translation rendering: black background sized to OCR bbox, adaptive font size, auto-shift on collision."""
        flags = Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap
        sel = self.selection

        items = [(QRect(r), (t or "").strip()) for r, t in self.overlay_texts]
        items = [(r, t) for r, t in items if t]
        if not items:
            return
        items.sort(key=lambda it: (it[0].top(), it[0].left()))

        placed = []  # already-drawn rects for collision detection
        painter.setPen(QColor(255, 255, 255))

        for ocr_r, text in items:
            x = sel.x() + ocr_r.x()
            y = sel.y() + ocr_r.y()
            w = ocr_r.width()
            h = ocr_r.height()
            rect = QRect(x, y, w, h)

            # Collision check: shift down if overlapping a previously placed block
            bump_gap = 2
            while True:
                conflicts = [p for p in placed if p.intersects(rect)]
                if not conflicts:
                    break
                delta = max(p.bottom() - rect.top() + bump_gap for p in conflicts)
                rect.translate(0, delta)

            # Adaptive font size based on source-bbox height
            font_px = max(10, int(h * 0.75))
            font = QFont("Microsoft YaHei")
            font.setPixelSize(font_px)
            painter.setFont(font)

            # Shrink font until text fits
            fm = painter.fontMetrics()
            text_w = fm.horizontalAdvance(text)
            while text_w > w and font_px > 8:
                font_px -= 1
                font.setPixelSize(font_px)
                painter.setFont(font)
                fm = painter.fontMetrics()
                text_w = fm.horizontalAdvance(text)

            # Paint black background + white text
            placed.append(QRect(rect))
            painter.fillRect(rect, QColor(0, 0, 0))
            pad = max(2, (h - fm.height()) // 2)
            inner = QRect(rect.x() + 2, rect.y() + pad, w - 4, h - 2 * pad)
            painter.drawText(inner, flags, text)

    EDGE_MARGIN = 8  # px hit-test margin for edges

    def _hit_test_edge(self, pos):
        """Hit-test the cursor against the selection edges/corners. Returns one of 'tl','t','tr','l','r','bl','b','br', 'inside' or None."""
        if self.selection.isNull() or not self.selection_done:
            return None
        s = self.selection
        m = self.EDGE_MARGIN
        x, y = pos.x(), pos.y()
        in_x = s.left() - m <= x <= s.right() + m
        in_y = s.top() - m <= y <= s.bottom() + m
        if not (in_x and in_y):
            return None
        on_left = abs(x - s.left()) <= m
        on_right = abs(x - s.right()) <= m
        on_top = abs(y - s.top()) <= m
        on_bottom = abs(y - s.bottom()) <= m
        if on_top and on_left: return 'tl'
        if on_top and on_right: return 'tr'
        if on_bottom and on_left: return 'bl'
        if on_bottom and on_right: return 'br'
        if on_top: return 't'
        if on_bottom: return 'b'
        if on_left: return 'l'
        if on_right: return 'r'
        # Inside selection
        if s.contains(pos):
            return 'inside'
        return None

    _EDGE_CURSORS = {
        'tl': Qt.SizeFDiagCursor, 'br': Qt.SizeFDiagCursor,
        'tr': Qt.SizeBDiagCursor, 'bl': Qt.SizeBDiagCursor,
        't': Qt.SizeVerCursor, 'b': Qt.SizeVerCursor,
        'l': Qt.SizeHorCursor, 'r': Qt.SizeHorCursor,
        'inside': Qt.SizeAllCursor,
    }

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.pen_mode and self.selection_done:
                self.drawing = True
                self.current_pen_points = [event.pos()]
            elif self.selection_done:
                edge = self._hit_test_edge(event.pos())
                if edge and edge != 'inside':
                    self._resize_edge = edge
                    self._drag_origin = event.pos()
                    self._drag_sel_origin = QRect(self.selection)
                elif edge == 'inside':
                    self._dragging_sel = True
                    self._drag_offset = event.pos() - self.selection.topLeft()
            elif not self.selection_done:
                self.is_selecting = True
                self.origin = event.pos()
                self.selection = QRect(self.origin, self.origin)
        elif event.button() == Qt.RightButton:
            if self.selection_done:
                self.selection_done = False
                self.selection = QRect()
                self.pen_lines.clear()
                self.current_pen_points.clear()
                self.overlay_texts.clear()
                self.overlay_pixmap = None
                self.pen_mode = False
                self._resize_edge = None
                self._dragging_sel = False
                if self.toolbar:
                    self.toolbar.hide()
                    self.toolbar.deleteLater()
                    self.toolbar = None
                self.setCursor(Qt.CrossCursor)
                self.update()
            else:
                self.close()

    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.selection = QRect(self.origin, event.pos()).normalized()
            self.update()
        elif self._resize_edge:
            self._do_resize(event.pos())
            self.update()
        elif self._dragging_sel:
            new_tl = event.pos() - self._drag_offset
            self.selection.moveTopLeft(new_tl)
            self._reposition_toolbar()
            self.update()
        elif self.drawing and self.pen_mode:
            self.current_pen_points.append(event.pos())
            self.update()
        elif self.selection_done and not self.pen_mode:
            # Update cursor shape
            edge = self._hit_test_edge(event.pos())
            if edge:
                self.setCursor(self._EDGE_CURSORS.get(edge, Qt.ArrowCursor))
            else:
                self.setCursor(Qt.CrossCursor)

    def _do_resize(self, pos):
        """Resize selection by dragging edges or corners."""
        s = QRect(self._drag_sel_origin)
        dx = pos.x() - self._drag_origin.x()
        dy = pos.y() - self._drag_origin.y()
        e = self._resize_edge
        if 'l' in e:
            s.setLeft(self._drag_sel_origin.left() + dx)
        if 'r' in e:
            s.setRight(self._drag_sel_origin.right() + dx)
        if 't' in e:
            s.setTop(self._drag_sel_origin.top() + dy)
        if 'b' in e:
            s.setBottom(self._drag_sel_origin.bottom() + dy)
        self.selection = s.normalized()
        self._reposition_toolbar()

    def _hide_toolbar(self):
        """Hide the bottom toolbar (after translation starts, only Esc closes the overlay)."""
        if self.toolbar:
            self.toolbar.hide()

    def _reposition_toolbar(self):
        """Reposition the toolbar (right-aligned to selection)."""
        if self.toolbar:
            tx = self.selection.right() - self.toolbar.width()
            ty = self.selection.bottom() + 6
            if ty + self.toolbar.height() > self.height():
                ty = self.selection.top() - self.toolbar.height() - 6
            tx = max(4, min(tx, self.width() - self.toolbar.width() - 4))
            self.toolbar.move(tx, ty)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.is_selecting:
                self.is_selecting = False
                self.selection = QRect(self.origin, event.pos()).normalized()
                if self.selection.width() > 5 and self.selection.height() > 5:
                    self.selection_done = True
                    self._show_toolbar()
                self.update()
            elif self._resize_edge:
                self._resize_edge = None
                self._reposition_toolbar()
                self.update()
            elif self._dragging_sel:
                self._dragging_sel = False
                self._reposition_toolbar()
                self.update()
            elif self.drawing and self.pen_mode:
                self.drawing = False
                for i in range(len(self.current_pen_points) - 1):
                    self.pen_lines.append((self.current_pen_points[i], self.current_pen_points[i + 1]))
                self.current_pen_points.clear()
                self.update()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self.selection_done:
            pixmap = self._get_selection_pixmap()
            self.hide()  # restore desktop immediately
            QApplication.clipboard().setPixmap(pixmap)
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_Z and event.modifiers() & Qt.ControlModifier:
            if self.pen_lines:
                self.pen_lines.pop()
                self.update()

    # ── Toolbar ──
    def _show_toolbar(self):
        if self.toolbar:
            self.toolbar.deleteLater()

        self.toolbar = QWidget(self)
        self.toolbar.setStyleSheet("""
            QWidget#toolbar {
                background: rgba(15, 15, 15, 230);
                border: 1px solid rgba(0, 220, 220, 150);
                border-radius: 4px;
            }
            QPushButton {
                color: rgba(0, 220, 220, 230);
                background: transparent;
                border: 1px solid rgba(0, 220, 220, 80);
                border-radius: 4px;
                padding: 10px 18px;
                font-size: 22px;
                font-family: "Segoe UI", "Microsoft YaHei";
                min-width: 48px;
                min-height: 36px;
            }
            QPushButton:hover {
                background: rgba(0, 220, 220, 40);
                border-color: rgba(0, 220, 220, 200);
            }
            QPushButton:pressed {
                background: rgba(0, 220, 220, 80);
            }
            QPushButton[active="true"] {
                background: rgba(0, 220, 220, 100);
                color: white;
            }
        """)
        self.toolbar.setObjectName("toolbar")

        layout = QHBoxLayout(self.toolbar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)

        self.btn_pen = QPushButton("✏")
        self.btn_pen.setToolTip("Red pen annotation")
        self.btn_pen.setCheckable(True)
        self.btn_pen.clicked.connect(self._toggle_pen)

        btn_ocr = QPushButton("T")
        btn_ocr.setToolTip("OCR: extract text to clipboard")
        btn_ocr.clicked.connect(self._do_ocr)

        btn_translate = QPushButton("Tr")
        btn_translate.setToolTip("OCR + translate, render overlay")
        btn_translate.clicked.connect(self._do_translate)

        sep2 = QLabel("│")
        sep2.setStyleSheet("color: rgba(0,220,220,60); font-size:26px;")

        btn_pin = QPushButton("📌")
        btn_pin.setToolTip("Pin to screen")
        btn_pin.clicked.connect(self._pin_to_screen)

        btn_copy = QPushButton("C")
        btn_copy.setToolTip("Copy screenshot to clipboard")
        btn_copy.clicked.connect(self._copy_and_close)

        btn_save = QPushButton("💾")
        btn_save.setToolTip("Save as PNG")
        btn_save.clicked.connect(self._save_to_file)

        btn_close = QPushButton("✕")
        btn_close.setToolTip("Cancel (Esc)")
        btn_close.clicked.connect(self.close)

        layout.addWidget(self.btn_pen)
        layout.addWidget(btn_pin)
        layout.addWidget(btn_copy)
        layout.addWidget(btn_save)
        layout.addWidget(btn_close)
        layout.addWidget(sep2)
        layout.addWidget(btn_translate)
        layout.addWidget(btn_ocr)

        self.toolbar.adjustSize()
        tx = self.selection.right() - self.toolbar.width()
        ty = self.selection.bottom() + 6
        if ty + self.toolbar.height() > self.height():
            ty = self.selection.top() - self.toolbar.height() - 6
        tx = max(4, min(tx, self.width() - self.toolbar.width() - 4))
        self.toolbar.move(tx, ty)
        self.toolbar.show()

    # ── Internal methods ──

    def _get_selection_pixmap(self) -> QPixmap:
        cropped = self.full_pixmap.copy(self.selection)
        if self.pen_lines:
            painter = QPainter(cropped)
            pen = QPen(QColor(PEN_COLOR), PEN_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            offset = self.selection.topLeft()
            for p1, p2 in self.pen_lines:
                painter.drawLine(p1 - offset, p2 - offset)
            painter.end()
        return cropped

    def _get_image_bytes(self) -> bytes:
        pixmap = self._get_selection_pixmap()
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.WriteOnly)
        pixmap.save(buf, "PNG")
        return bytes(ba.data())

    def _copy_to_clipboard(self):
        QApplication.clipboard().setPixmap(self._get_selection_pixmap())

    def _copy_and_close(self):
        self._copy_to_clipboard()
        self._show_status("✓ Copied", 600)
        QTimer.singleShot(600, self.close)

    def _toggle_pen(self):
        self.pen_mode = self.btn_pen.isChecked()
        if self.pen_mode:
            self.setCursor(Qt.CrossCursor)
            self.btn_pen.setProperty("active", "true")
        else:
            self.setCursor(Qt.ArrowCursor)
            self.btn_pen.setProperty("active", "false")
        self.btn_pen.style().unpolish(self.btn_pen)
        self.btn_pen.style().polish(self.btn_pen)

    def _do_ocr(self):
        """OCR -> close UI immediately, run extraction in the background, drop text into clipboard."""
        image_bytes = self._get_image_bytes()
        self.close()

        worker = OcrWorker(image_bytes)

        def on_text(text):
            QApplication.clipboard().setText(text)

        worker.text_only.connect(on_text)
        # Keep a reference to prevent GC
        if not hasattr(QApplication.instance(), '_bg_workers'):
            QApplication.instance()._bg_workers = []
        QApplication.instance()._bg_workers.append(worker)
        worker.finished.connect(lambda _: None)
        worker.start()

    def _do_translate(self):
        """OCR -> translate -> render Markdown-styled HTML overlay over the selection."""
        self._hide_toolbar()
        image_bytes = self._get_image_bytes()
        self._show_status("Running OCR...")

        worker = OcrWorker(image_bytes)

        def on_ocr_done(raw_result):
            boxes_texts = self._extract_boxes_and_texts(raw_result)
            if not boxes_texts:
                self._show_status("✗ No text detected", 2000)
                return
            boxes_texts.sort(key=lambda bt: (bt[0].y(), bt[0].x()))
            merged = self._merge_line_boxes(boxes_texts)
            merged = [(b, t) for b, t in merged if t.strip()]
            if not merged:
                self._show_status("✗ No text detected", 2000)
                return
            # Structurize: split OCR lines into text/code blocks
            blocks = self._build_blocks(merged)
            to_translate = []
            translate_indices = []
            for i, blk in enumerate(blocks):
                if blk["type"] == "text":
                    to_translate.append(blk["text"])
                    translate_indices.append(i)
            if not to_translate:
                self._pending_blocks = blocks
                _render_from_blocks(blocks, [])
                return
            self._pending_blocks = blocks
            self._pending_translate_indices = translate_indices
            self._show_status("Translating...")
            tw = BatchTranslateWorker(to_translate)
            tw.finished.connect(on_translate_done)
            tw.error.connect(lambda msg: self._show_status(f"✗ {msg}", 3000))
            self._workers.append(tw)
            tw.start()

        def on_translate_done(translated_lines):
            """translated_lines: list[str], length aligned with to_translate."""
            indices = getattr(self, "_pending_translate_indices", [])
            blocks = getattr(self, "_pending_blocks", [])
            if len(translated_lines) != len(indices):
                # Should not happen, defensive padding/truncation
                translated_lines = list(translated_lines) + [""] * max(0, len(indices) - len(translated_lines))
                translated_lines = translated_lines[: len(indices)]
            _render_from_blocks(blocks, list(zip(indices, translated_lines)))

        def _render_from_blocks(blocks, translated_pairs):
            # Inject translations back into their blocks
            for idx, tr in translated_pairs:
                if 0 <= idx < len(blocks):
                    blocks[idx]["translated"] = tr
            html = self._blocks_to_html(blocks)
            pm = self._render_markdown_pixmap(html, self.selection.size())
            self.overlay_pixmap = pm
            self.overlay_texts.clear()
            self._show_status("✓ Translation done", 1200)
            self.update()

        worker.finished.connect(on_ocr_done)
        worker.error.connect(lambda msg: self._show_status(f"✗ {msg}", 3000))
        self._workers.append(worker)
        worker.start()

    # ──────────────────────────────────────────────
    # Structurization: split OCR lines into text / code blocks
    # ──────────────────────────────────────────────
    @staticmethod
    def _is_code_line(text: str) -> bool:
        """Heuristically classify a line as code / command / path."""
        import re
        if not text.strip():
            return False
        s = text.strip()
        # Typical shell prompts
        if s.startswith(("$ ", "> ", "# ", "sudo ", "./", "../", "C:\\", "D:\\", "/")):
            pass  # don't decide yet, keep checking other evidence
        # Keyword prefixes
        code_prefixes = (
            "def ", "class ", "function ", "const ", "let ", "var ",
            "public ", "private ", "protected ", "static ",
            "import ", "from ", "require(", "#include", "#define",
            "async ", "await ", "return ", "if (", "for (", "while (",
            "switch ", "case ", "try:", "except ", "finally:",
            "@", "print(", "console.",
        )
        if any(s.startswith(k) for k in code_prefixes):
            return True
        # Symbol density: {}[]()<>=;:*/\\| etc.
        symbols = sum(1 for c in s if c in "{}[]()<>=;:*/\\|#$&~`")
        if len(s) > 0 and symbols / len(s) > 0.18:
            return True
        # Assignment / function-call patterns
        if re.search(r"\b\w+\s*=\s*[\w\"'\[\{]", s) and "=" in s:
            return True
        if re.search(r"\b\w+\([^)]*\)", s) and ("(" in s and ")" in s):
            # Exclude natural-language parens (long content inside)
            inside = re.findall(r"\(([^)]*)\)", s)
            if any(len(x) <= 30 for x in inside):
                return True
        # Typical path / CLI command patterns
        if re.search(r"[A-Za-z]:\\[\\\w\.-]+", s):
            return True
        if re.search(r"^(pip|npm|git|docker|ssh|curl|wget|python|node)\s", s):
            return True
        return False

    def _build_blocks(self, merged):
        """Group merged lines into typed blocks:
          - consecutive code lines -> 1 code block
          - consecutive text lines within the same paragraph -> 1 text block (space-joined)
          - paragraphs separated by Y-gap become separate blocks (rendered with \\n\\n)
        """
        if not merged:
            return []
        breaks = self._detect_paragraph_breaks(merged)
        blocks = []
        i = 0
        n = len(merged)
        while i < n:
            _, text = merged[i]
            if self._is_code_line(text):
                code_lines = [text]
                j = i + 1
                while j < n and self._is_code_line(merged[j][1]):
                    code_lines.append(merged[j][1])
                    j += 1
                blocks.append({
                    "type": "code",
                    "text": "\n".join(code_lines),
                    "translated": "",
                })
                i = j
            else:
                # Collect consecutive non-code lines until paragraph break or a code line
                para_lines = [text]
                j = i + 1
                while j < n and not breaks[j - 1] and not self._is_code_line(merged[j][1]):
                    para_lines.append(merged[j][1])
                    j += 1
                blocks.append({
                    "type": "text",
                    "text": " ".join(para_lines),
                    "translated": "",
                })
                i = j
        return blocks

    @staticmethod
    def _detect_bullet_pattern(blocks):
        """Relaxed bullet detection: if the document has >= 3 text blocks matching 'Title: content',
        treat all matching blocks as list items (no need to be consecutive).
        Whitespace after the colon is optional. Both ASCII ':' and full-width '：' accepted."""
        import re
        pat = re.compile(r"^(.{2,40}?)[:：]\s*\S")
        matched = []
        for idx, blk in enumerate(blocks):
            if blk["type"] != "text":
                continue
            txt = (blk.get("translated") or blk["text"]).strip()
            if pat.match(txt):
                matched.append(idx)
        return set(matched) if len(matched) >= 3 else set()

    @staticmethod
    def _escape_html(s: str) -> str:
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace('"', "&quot;"))

    def _blocks_to_html(self, blocks) -> str:
        """Build HTML with all colors / spacing as inline styles. Qt's QTextDocument has unreliable external CSS support."""
        import re
        bullet_set = self._detect_bullet_pattern(blocks)
        out = ['<body style="color:#EBEBEB; font-family:\'Microsoft YaHei\';">']
        list_buf = []

        def flush_list():
            if list_buf:
                out.append(
                    '<ul style="margin-top:1em; margin-bottom:1em; padding-left:24px;">'
                    + "".join(f'<li style="margin-top:1em; margin-bottom:1em;">{x}</li>' for x in list_buf)
                    + "</ul>"
                )
                list_buf.clear()

        for idx, blk in enumerate(blocks):
            if blk["type"] == "code":
                flush_list()
                code_h = self._escape_html(blk["text"])
                out.append(
                    '<pre style="background-color:#1E1E1E; color:#D4D4D4; '
                    'padding:6px 8px; margin-top:10px; margin-bottom:10px; '
                    'font-family:Consolas, \'Courier New\', monospace; white-space:pre-wrap;">'
                    + code_h + '</pre>'
                )
                continue

            txt = (blk.get("translated") or blk["text"]).strip()
            if not txt:
                continue

            if idx in bullet_set:
                m = re.match(r"^(.{2,40}?)[:：]\s*(.+)$", txt, re.DOTALL)
                if m:
                    title = self._escape_html(m.group(1).strip())
                    rest = self._escape_html(m.group(2).strip())
                    list_buf.append(
                        f'<span style="color:#FFFFFF;"><b>{title}</b></span>：{rest}'
                    )
                else:
                    list_buf.append(self._escape_html(txt))
            else:
                flush_list()
                out.append(
                    '<p style="margin-top:1em; margin-bottom:1em;">'
                    + self._escape_html(txt) + '</p>'
                )

        flush_list()
        out.append('</body>')
        return "".join(out)

    def _render_markdown_pixmap(self, html: str, size) -> QPixmap:
        """Render the prepared HTML through QTextDocument into a QPixmap, with binary-search font sizing to fit the selection."""
        padding = 10
        inner_w = max(1, size.width() - padding * 2)
        inner_h = max(1, size.height() - padding * 2)

        def build_doc(font_px):
            doc = QTextDocument()
            # Default QTextDocument palette is black text. We use CSS + paint-time palette as belt-and-suspenders.
            doc.setDefaultStyleSheet(f"""
                * {{ color: #EBEBEB; }}
                p {{ margin-top: 8px; margin-bottom: 8px; }}
                h1, h2, h3, h4 {{ color: #FFFFFF; margin-top: 10px; margin-bottom: 6px; }}
                code {{
                    font-family: Consolas, "Courier New", monospace;
                    background-color: #1E1E1E; color: #D4D4D4;
                    padding: 1px 4px;
                }}
                pre {{
                    font-family: Consolas, "Courier New", monospace;
                    background-color: #1E1E1E; color: #D4D4D4;
                    padding: 6px 8px; margin: 6px 0;
                }}
                table {{ border-collapse: collapse; margin: 6px 0; }}
                td, th {{ border: 1px solid #555; padding: 2px 6px; color: #EBEBEB; }}
                ul, ol {{ margin: 6px 0; padding-left: 22px; }}
                li {{ margin-top: 4px; margin-bottom: 4px; color: #EBEBEB; }}
                strong {{ color: #FFFFFF; font-weight: bold; }}
                em {{ color: #EBEBEB; }}
            """)
            font = QFont("Microsoft YaHei")
            font.setPixelSize(font_px)
            doc.setDefaultFont(font)
            doc.setTextWidth(inner_w)
            doc.setHtml(html)
            return doc

        # Binary search for max font size that fits
        low, high = 9, 28
        best_doc = None
        while low <= high:
            mid = (low + high) // 2
            doc = build_doc(mid)
            h = doc.size().height()
            if h <= inner_h:
                best_doc = doc
                low = mid + 1
            else:
                high = mid - 1
        if best_doc is None:
            best_doc = build_doc(9)

        pm = QPixmap(size)
        pm.fill(QColor(18, 18, 18))
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.translate(padding, padding)
        # Use PaintContext with a custom palette to force light default text color
        ctx = QAbstractTextDocumentLayout.PaintContext()
        palette = ctx.palette
        palette.setColor(QPalette.Text, QColor(235, 235, 235))
        palette.setColor(QPalette.WindowText, QColor(235, 235, 235))
        palette.setColor(QPalette.Base, QColor(18, 18, 18))
        palette.setColor(QPalette.Window, QColor(18, 18, 18))
        ctx.palette = palette
        ctx.clip = QRectF(0, 0, inner_w, inner_h)
        # Last-resort fallback: white default pen on the painter
        painter.setPen(QColor(235, 235, 235))
        best_doc.documentLayout().draw(painter, ctx)
        painter.end()
        return pm

    # ──────────────────────────────────────────────
    # Paragraph detection: based on OCR bbox Y-gap
    # ──────────────────────────────────────────────
    @staticmethod
    def _detect_paragraph_breaks(merged):
        """Mark a paragraph break when the Y-gap between two consecutive lines exceeds 1.0 x average line height.
        Threshold raised from 0.6 to 1.0 to prevent intra-paragraph line wraps being mis-classified as paragraph breaks."""
        n = len(merged)
        if n <= 1:
            return [False] * n
        heights = [b.height() for b, _ in merged if b.height() > 0]
        avg_h = max(sum(heights) / len(heights), 1) if heights else 1
        breaks = [False] * n
        for i in range(n - 1):
            b1 = merged[i][0]
            b2 = merged[i + 1][0]
            gap = b2.top() - b1.bottom()
            if gap > avg_h * 1.0:
                breaks[i] = True
        return breaks

    # ──────────────────────────────────────────────
    # Black-bg white-text full-block rendering (legacy fallback path)
    # ──────────────────────────────────────────────
    def _render_black_translation(self, items, size) -> QPixmap:
        """items: list of (text, is_paragraph_end_after)"""
        pm = QPixmap(size)
        pm.fill(QColor(10, 10, 10))
        if not items:
            return pm

        padding = 14
        inner_w = max(1, size.width() - padding * 2)
        inner_h = max(1, size.height() - padding * 2)

        def measure(font_size):
            f = QFont("Microsoft YaHei")
            f.setPixelSize(font_size)
            fm = QFontMetrics(f)
            line_h = fm.lineSpacing()
            small_gap = max(1, int(line_h * 0.15))
            para_gap = line_h  # blank line between paragraphs
            total_h = 0
            for idx, (text, is_para_end) in enumerate(items):
                wrapped = self._wrap_to_lines(text, fm, inner_w) if text.strip() else [""]
                total_h += len(wrapped) * line_h
                if idx < len(items) - 1:
                    total_h += para_gap if is_para_end else small_gap
            return total_h, f, fm

        low, high = 8, 60
        best_font = None
        best_fm = None
        while low <= high:
            mid = (low + high) // 2
            total_h, f, fm = measure(mid)
            if total_h <= inner_h:
                best_font, best_fm = f, fm
                low = mid + 1
            else:
                high = mid - 1
        if best_font is None:
            _, best_font, best_fm = measure(8)

        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setFont(best_font)
        painter.setPen(QColor(235, 235, 235))

        line_h = best_fm.lineSpacing()
        small_gap = max(1, int(line_h * 0.15))
        para_gap = line_h
        y = padding + best_fm.ascent()
        max_y = size.height() - padding
        for idx, (text, is_para_end) in enumerate(items):
            if text.strip():
                for wrapped in self._wrap_to_lines(text, best_fm, inner_w):
                    if y > max_y:
                        break
                    painter.drawText(padding, y, wrapped)
                    y += line_h
            else:
                y += line_h
            if idx < len(items) - 1:
                y += para_gap if is_para_end else small_gap
            if y > max_y:
                break
        painter.end()
        return pm

    @staticmethod
    def _wrap_to_lines(text, fm, max_w):
        """Wrap by pixel width. CJK + Latin friendly: split by spaces first, fall back to per-char split."""
        if not text:
            return [""]
        out = []
        # First split by spaces; for CJK, continue splitting per character inside each token
        tokens = []
        buf = ""
        for ch in text:
            if ch == " ":
                if buf:
                    tokens.append(buf)
                    buf = ""
                tokens.append(" ")
            else:
                buf += ch
        if buf:
            tokens.append(buf)

        cur = ""
        for tk in tokens:
            cand = cur + tk
            if fm.horizontalAdvance(cand) <= max_w:
                cur = cand
                continue
            # Doesn't fit -> flush cur, then sub-split tk
            if cur.strip():
                out.append(cur)
            # Per-character split of the over-long token
            piece = ""
            for ch in tk:
                tentative = piece + ch
                if fm.horizontalAdvance(tentative) <= max_w:
                    piece = tentative
                else:
                    if piece:
                        out.append(piece)
                    piece = ch
            cur = piece
        if cur.strip():
            out.append(cur)
        return out or [""]

    def _extract_boxes_and_texts(self, raw):
        """Extract (QRect, text) pairs from the OCR response. Coordinates are selection-relative."""
        if not isinstance(raw, dict) or raw.get("errorCode") != 0:
            return []
        try:
            pruned = raw["result"]["ocrResults"][0]["prunedResult"]
            texts = pruned.get("rec_texts", [])
            polys = pruned.get("dt_polys", [])
            result = []
            for poly, txt in zip(polys, texts):
                if not txt.strip():
                    continue
                # poly: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
                x = int(min(xs))
                y = int(min(ys))
                w = int(max(xs) - x)
                h = int(max(ys) - y)
                result.append((QRect(x, y, w, h), str(txt)))
            return result
        except (KeyError, IndexError):
            return []

    def _merge_line_boxes(self, boxes_texts):
        """Merge per-token bboxes belonging to the same visual line, so we render whole sentences instead of word fragments."""
        if not boxes_texts:
            return []
        merged = []
        cur_group = [boxes_texts[0]]
        for i in range(1, len(boxes_texts)):
            box, text = boxes_texts[i]
            prev_box = cur_group[-1][0]
            # Same-line if vertical overlap > 50% of the shorter box height
            overlap_y = min(prev_box.bottom(), box.bottom()) - max(prev_box.top(), box.top())
            min_h = min(prev_box.height(), box.height())
            if min_h > 0 and overlap_y > min_h * 0.5:
                cur_group.append(boxes_texts[i])
            else:
                merged.append(self._merge_box_group(cur_group))
                cur_group = [boxes_texts[i]]
        if cur_group:
            merged.append(self._merge_box_group(cur_group))
        return merged

    def _merge_box_group(self, group):
        """Merge a group of same-line bboxes into one bounding rect with concatenated text."""
        min_x = min(b.x() for b, _ in group)
        min_y = min(b.y() for b, _ in group)
        max_x = max(b.x() + b.width() for b, _ in group)
        max_y = max(b.y() + b.height() for b, _ in group)
        text = " ".join(t for _, t in group)
        return (QRect(min_x, min_y, max_x - min_x, max_y - min_y), text)

    def _extract_text_from_raw(self, raw):
        """Extract plain text from the raw OCR response."""
        if not isinstance(raw, dict):
            return str(raw)
        if raw.get("errorCode") != 0:
            return ""
        try:
            pruned = raw["result"]["ocrResults"][0]["prunedResult"]
            texts = pruned.get("rec_texts", [])
            return "\n".join(str(t) for t in texts)
        except (KeyError, IndexError):
            return str(raw)

    def _pin_to_screen(self):
        pixmap = self._get_selection_pixmap()
        pin = PinWindow(pixmap)
        pin.move(self.mapToGlobal(self.selection.topLeft()))
        pin.show()
        ScreenshotOverlay._pin_windows.append(pin)
        self.close()

    def _save_to_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save screenshot", "screenshot.png", "PNG (*.png)"
        )
        if path:
            self._get_selection_pixmap().save(path, "PNG")
            self.close()


# ──────────────────────────────────────────────
#  System tray
# ──────────────────────────────────────────────
class TrayApp(QSystemTrayIcon):
    def __init__(self, app: QApplication):
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(0, 200, 200)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(2, 2, 28, 28, 6, 6)
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Arial", 15, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "S")
        painter.end()

        super().__init__(QIcon(pixmap))
        self.app = app
        self.overlay = None

        menu = QMenu()
        menu.setStyleSheet("QMenu{background:#222;color:#ccc;}QMenu::item:selected{background:#00AACC;}")
        act_capture = QAction("Capture (F1)", menu)
        act_capture.triggered.connect(self.start_capture)
        menu.addAction(act_capture)
        menu.addSeparator()
        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self.setToolTip("Screenshot Translator\nLeft-click: capture | Right-click: menu")
        self.show()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.start_capture()

    def start_capture(self):
        try:
            screens = QApplication.screens()
            if not screens:
                return
            virtual_rect = QRect()
            for s in screens:
                virtual_rect = virtual_rect.united(s.geometry())

            pixmap = QPixmap(virtual_rect.size())
            pixmap.fill(Qt.black)
            painter = QPainter(pixmap)
            for s in screens:
                geo = s.geometry()
                try:
                    shot = s.grabWindow(0)
                except Exception:
                    traceback.print_exc()
                    continue
                target = QRect(
                    geo.x() - virtual_rect.x(),
                    geo.y() - virtual_rect.y(),
                    geo.width(), geo.height(),
                )
                painter.drawPixmap(target, shot)
            painter.end()

            self.overlay = ScreenshotOverlay(pixmap, virtual_rect)
            self.overlay.show()
        except Exception:
            traceback.print_exc()

    def _quit(self):
        for w in ScreenshotOverlay._pin_windows:
            try:
                w.close()
            except Exception:
                pass
        ScreenshotOverlay._pin_windows.clear()
        self.hide()
        self.app.quit()


# ──────────────────────────────────────────────
#  Global hotkey (F1) - background thread
# ──────────────────────────────────────────────
class HotkeyThread(QThread):
    """Global hotkey listener using Win32 RegisterHotKey.
    On Windows, the system F1 help may swallow the key; disable it via registry first if needed.
    """
    capture_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._hotkey_id = 1
        self._thread_id = None

    def run(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, self._hotkey_id, HOTKEY_MOD, HOTKEY_VK):
            print(f"[hotkey] register failed (VK=0x{HOTKEY_VK:02X})")
            return
        print(f"[hotkey] global hotkey registered: VK=0x{HOTKEY_VK:02X}")
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                self.capture_signal.emit()
        user32.UnregisterHotKey(None, self._hotkey_id)

    def stop(self):
        import ctypes
        tid = self._thread_id
        if tid:
            ctypes.windll.user32.PostThreadMessageW(tid, 0x0012, 0, 0)  # WM_QUIT


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    tray = TrayApp(app)

    hotkey_thread = HotkeyThread()
    hotkey_thread.capture_signal.connect(tray.start_capture)
    hotkey_thread.start()

    tray.showMessage(
        "Screenshot Translator",
        "Started. Press F1 or left-click the tray icon to capture.\n"
        "Double-click selection -> copy to clipboard.\n"
        "Toolbar: OCR | Translate | Annotate | Pin | Save",
        QSystemTrayIcon.Information,
        3000,
    )

    ret = app.exec_()
    hotkey_thread.stop()
    hotkey_thread.wait(2000)
    sys.exit(ret)


if __name__ == "__main__":
    main()
