"""Dark theme (same look as CNC Deck) and procedurally drawn vector icons."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

BG = "#0e1217"
PANEL = "#141a21"
CARD = "#1a222c"
CARD_HI = "#222c38"
BORDER = "#2a3544"
TEXT = "#d9e1ea"
MUTED = "#7f8d9f"
ACCENT = "#2dd4bf"
ACCENT_DIM = "#14766b"
OK = "#34d399"
RUN = "#4aa8ff"
WARN = "#fbbf24"
DANGER = "#f87171"
# energy colours
PV = "#fbbf24"          # production (amber)
LOAD = "#4aa8ff"        # consumption (blue)
EXPORT = "#34d399"      # feed-in to the grid (green)
IMPORT = "#f87171"      # withdrawal from the grid (red)
MONO = "'JetBrains Mono','Ubuntu Mono','DejaVu Sans Mono','Liberation Mono',monospace"

STATE_COLORS = {"online": OK, "connecting": WARN, "offline": DANGER, "disconnected": MUTED, "sim": "#a78bfa"}

STYLESHEET = f"""
* {{ font-size: 13px; }}
QWidget {{ background: {BG}; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QToolTip {{ background: {CARD_HI}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#card QLabel, QFrame#card QCheckBox, QFrame#card QSlider {{ background: transparent; }}
QLabel#cardTitle {{ color: {MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 1.5px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#mono {{ font-family: {MONO}; }}
QPushButton, QToolButton {{
    background: {CARD_HI}; border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 12px; color: {TEXT};
}}
QPushButton:hover, QToolButton:hover {{ background: #2c3847; border-color: #3c4b5f; }}
QPushButton:pressed, QToolButton:pressed {{ background: {ACCENT_DIM}; border-color: {ACCENT}; }}
QPushButton:disabled, QToolButton:disabled {{ color: #4d5866; background: #171e26; border-color: #202a36; }}
QPushButton#primary {{ background: {ACCENT}; color: #04211d; border: none; font-weight: 700; }}
QPushButton#primary:hover {{ background: #5eead4; }}
QPushButton#primary:disabled {{ background: #1c3a37; color: #4b7a74; }}
QPushButton#danger {{ background: #5b1f24; border-color: #8f3038; }}
QPushButton#danger:hover {{ background: #7a2a31; }}
QPushButton:checked, QToolButton:checked {{ background: {ACCENT_DIM}; border-color: {ACCENT}; }}
QToolButton#run {{ background: #14532d; border-color: #1f7a45; }}
QToolButton#run:hover {{ background: #1a6b3b; }}
QToolButton#run:disabled {{ background: #17221d; border-color: #1f2d26; }}
QToolButton#stopb {{ background: #5b1f24; border-color: #8f3038; }}
QToolButton#stopb:hover {{ background: #7a2a31; }}
QToolButton#stopb:disabled {{ background: #231a1c; border-color: #31232a; }}
QToolButton#jog {{ padding: 0; border-radius: 9px; background: #232e3b; }}
QToolButton#jog:pressed {{ background: {ACCENT}; }}
QComboBox, QLineEdit, QDoubleSpinBox, QSpinBox {{
    background: #10161d; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 8px;
    selection-background-color: {ACCENT_DIM};
}}
QComboBox:focus, QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {BORDER}; selection-background-color: {ACCENT_DIM}; outline: 0; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QPlainTextEdit, QTextEdit, QTableWidget {{
    background: #0b0f14; border: 1px solid {BORDER}; border-radius: 8px;
    font-family: {MONO}; font-size: 12px; selection-background-color: {ACCENT_DIM};
}}
QListWidget {{ background: #0b0f14; border: 1px solid {BORDER}; border-radius: 8px; padding: 3px; outline: 0; }}
QListWidget::item {{ padding: 4px 6px; border-radius: 5px; }}
QListWidget::item:selected {{ background: {ACCENT_DIM}; color: {TEXT}; }}
QListWidget::item:hover {{ background: #18212b; }}
QListWidget::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1px solid {BORDER}; background: #10161d; }}
QListWidget::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 7px 16px; border: none; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QHeaderView::section {{ background: {CARD}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER}; padding: 5px; }}
QTableWidget {{ gridline-color: #1c2530; alternate-background-color: #0e141a; }}
QProgressBar {{ background: #10161d; border: 1px solid {BORDER}; border-radius: 6px; text-align: center; height: 16px; color: {TEXT}; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}
QToolBar {{ background: {PANEL}; border: none; border-bottom: 1px solid {BORDER}; spacing: 6px; padding: 6px 8px; }}
QToolBar QToolButton {{ padding: 6px 10px; }}
QToolBar QLabel, QToolBar QWidget#spacer, QStatusBar QLabel {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #2c3847; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3d4d60; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: #2c3847; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {BORDER}; background: #10161d; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QMenu {{ background: {CARD}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QLabel#big {{ font-family: {MONO}; font-size: 22px; font-weight: 700; }}
QLabel#kv {{ font-family: {MONO}; font-size: 12px; }}
QToolButton#range {{ padding: 3px 10px; border-radius: 6px; }}
QSplitter::handle {{ background: {BG}; }}
QMessageBox {{ background: {CARD}; }}
"""


def _icon(draw, color: str = TEXT, size: int = 64) -> QIcon:
    icon = QIcon()
    for col, mode in ((color, QIcon.Normal), ("#4d5866", QIcon.Disabled)):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(col), size / 11, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.scale(size / 24, size / 24)
        pen.setWidthF(2.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        draw(p, QColor(col))
        p.end()
        icon.addPixmap(pm, mode)
    return icon


def _poly(p, pts, close=False, fill=None):
    path = QPainterPath(QPointF(*pts[0]))
    for pt in pts[1:]:
        path.lineTo(*pt)
    if close:
        path.closeSubpath()
    if fill is not None:
        p.fillPath(path, fill)
    else:
        p.drawPath(path)


def _sun(p, c):
    p.drawEllipse(QPointF(12, 12), 4.2, 4.2)
    for i in range(8):
        a = i * math.pi / 4
        p.drawLine(QPointF(12 + 7 * math.cos(a), 12 + 7 * math.sin(a)), QPointF(12 + 9.6 * math.cos(a), 12 + 9.6 * math.sin(a)))


def _home(p, c):
    _poly(p, [(3, 12), (12, 4), (21, 12)])
    _poly(p, [(6, 10.5), (6, 20), (18, 20), (18, 10.5)])
    _poly(p, [(10, 20), (10, 14), (14, 14), (14, 20)])


def _panel(p, c):
    _poly(p, [(5.5, 4.5), (18.5, 4.5), (21.5, 14.5), (2.5, 14.5)], True)
    _poly(p, [(9.8, 4.5), (8.4, 14.5)])
    _poly(p, [(14.2, 4.5), (15.6, 14.5)])
    _poly(p, [(4.0, 9.5), (20.0, 9.5)])
    _poly(p, [(12, 14.5), (12, 19.5)])
    _poly(p, [(8, 19.5), (16, 19.5)])


def _pylon(p, c):
    # narrow lattice tower: two legs, two cross-arms, a brace bar and an X
    _poly(p, [(12, 2), (8.2, 22)])
    _poly(p, [(12, 2), (15.8, 22)])
    _poly(p, [(4.5, 6.5), (19.5, 6.5)])
    _poly(p, [(7, 11.5), (17, 11.5)])
    _poly(p, [(9.6, 16.5), (14.4, 16.5)])
    _poly(p, [(10.0, 11.5), (14.4, 16.5)])
    _poly(p, [(14.0, 11.5), (9.6, 16.5)])


def _inverter(p, c):
    # box split by a diagonal: DC ("=") top-left, AC ("~") bottom-right
    p.drawRoundedRect(QRectF(3, 4, 18, 16), 2.5, 2.5)
    _poly(p, [(3.4, 19.6), (20.6, 4.4)])
    _poly(p, [(6.2, 8.2), (10.2, 8.2)])
    _poly(p, [(6.2, 10.8), (10.2, 10.8)])
    w = QPainterPath(QPointF(13.2, 16.2))
    w.cubicTo(14.2, 13.6, 15.7, 13.6, 16.6, 16.2)
    w.cubicTo(17.5, 18.8, 19.0, 18.8, 19.9, 16.2)
    p.drawPath(w)


def _gear(p, c):
    p.drawEllipse(QPointF(12, 12), 3, 3)
    for i in range(8):
        a = i * math.pi / 4
        p.drawLine(QPointF(12 + 6.5 * math.cos(a), 12 + 6.5 * math.sin(a)), QPointF(12 + 9 * math.cos(a), 12 + 9 * math.sin(a)))
    p.drawEllipse(QPointF(12, 12), 6.5, 6.5)


def _plug(p, c):
    _poly(p, [(9, 3), (9, 8)])
    _poly(p, [(15, 3), (15, 8)])
    p.drawRoundedRect(QRectF(6, 8, 12, 6), 2, 2)
    p.drawArc(QRectF(8, 8, 8, 12), 180 * 16, 180 * 16)
    _poly(p, [(12, 20), (12, 22)])


def _unplug(p, c):
    _plug(p, c)
    _poly(p, [(3, 3), (21, 21)])


def _reload(p, c):
    p.drawArc(QRectF(4, 4, 16, 16), 30 * 16, 300 * 16)
    _poly(p, [(17.5, 1.5), (20, 7), (14.5, 7.5)], True, c)


def _bolt(p, c):
    _poly(p, [(13, 2), (5, 13.5), (11, 13.5), (10, 22), (19, 9.5), (13, 9.5)], True)


def _check(p, c):
    _poly(p, [(4, 12.5), (9.5, 18), (20, 6)])


def _save(p, c):
    _poly(p, [(5, 4), (17, 4), (20, 7), (20, 20), (5, 20)], True)
    _poly(p, [(8, 4), (8, 9), (16, 9), (16, 4)])
    _poly(p, [(8, 20), (8, 14), (16, 14), (16, 20)])


_FUNCS = {n[1:]: f for n, f in globals().items() if n.startswith("_") and callable(f) and n[1:] in (
    "sun home panel pylon inverter gear plug unplug reload bolt check save").split()}


def icon(name: str, color: str = TEXT) -> QIcon:
    return _icon(_FUNCS[name], color)


def pixmap(name: str, color: str = TEXT, size: int = 64) -> QPixmap:
    return icon(name, color).pixmap(size, size)


def glyph(name: str, color: str, size: int, fill: float = 0.92, dpr: int = 2) -> QPixmap:
    """Crisp icon for custom painting: rendered large, cropped to its real bounding box, scaled to fit
    `size` x `size` (logical px) and centred, so every glyph is optically centred in a circle."""
    from PySide6.QtGui import QImage
    big = 384
    img = QImage(big, big, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), 2.1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.scale(big / 24, big / 24)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    _FUNCS[name](p, QColor(color))
    p.end()
    # bounding box of the non-transparent pixels
    x0, y0, x1, y1 = big, big, -1, -1
    for y in range(big):
        row = img.constScanLine(y)
        buf = memoryview(row)[: big * 4]
        for x in range(big):
            if buf[x * 4 + 3]:
                if x < x0: x0 = x
                if x > x1: x1 = x
                if y < y0: y0 = y
                if y > y1: y1 = y
    if x1 < 0:
        return QPixmap()
    crop = img.copy(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    target = int(size * dpr)
    k = min(target * fill / crop.width(), target * fill / crop.height())
    scaled = crop.scaled(max(1, int(crop.width() * k)), max(1, int(crop.height() * k)),
                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    out = QPixmap(target, target)
    out.fill(Qt.transparent)
    q = QPainter(out)
    q.drawImage((target - scaled.width()) // 2, (target - scaled.height()) // 2, scaled)
    q.end()
    out.setDevicePixelRatio(dpr)
    return out
