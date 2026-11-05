"""Animated splash screen: the day's production curve drawn by a rising sun, title, credits and version."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

from . import theme

W, H = 780, 440
CREDITS = "Stefano Ciurleo & Claude Code - 2026"


def _ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


class SplashScreen(QWidget):
    finished = Signal()

    def __init__(self, version: str, duration_ms: int = 3000, parent=None):
        super().__init__(parent)
        self.version = version
        self.duration = duration_ms
        self.t = 0.0                       # elapsed milliseconds (set_time() overrides it for stills)
        self.setWindowFlags(Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self._clock = QElapsedTimer()
        self._tick = QTimer(self, interval=16)
        self._tick.timeout.connect(self._advance)
        self._build_art()

    # ------------------------------------------------------------------ geometry of the artwork
    def _build_art(self) -> None:
        """Production (bell) and consumption (two meals + evening) curves over a 24 h axis."""
        self.x0, self.x1 = W * 0.47, W - 52.0           # plot box
        self.yb, self.yt = H * 0.70, H * 0.20
        n = 360
        h = np.linspace(0, 24, n)
        sun = np.clip(np.sin(np.pi * (h - 6.0) / 13.5), 0, None) ** 1.3
        ripple = 1 - 0.10 * np.sin(h * 2.3) * (sun > 0)
        self.pv = sun * ripple
        self.load = (0.16 + 0.30 * np.exp(-((h - 7.5) / 0.9) ** 2) + 0.38 * np.exp(-((h - 13.0) / 1.2) ** 2)
                     + 0.62 * np.exp(-((h - 20.3) / 1.6) ** 2))
        self.hx = self.x0 + (self.x1 - self.x0) * h / 24.0

    def _y(self, v: np.ndarray) -> np.ndarray:
        return self.yb - v * (self.yb - self.yt)

    # ------------------------------------------------------------------ control
    def start(self) -> None:
        scr = QApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            self.move(g.center().x() - W // 2, g.center().y() - H // 2)
        self.show()
        self.raise_()
        self._clock.start()
        self._tick.start()

    def _advance(self) -> None:
        self.t = float(self._clock.elapsed())
        if self.t >= self.duration:
            self._tick.stop()
            self.close()
            self.finished.emit()
            return
        self.update()

    def set_time(self, ms: float) -> None:
        """Freeze the animation at `ms` (used for screenshots and tests)."""
        self.t = ms
        self.update()

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        k = self.t / max(self.duration, 1)
        fade_in = _ease(self.t / 350.0)
        fade_out = 1.0 - _ease((self.t - (self.duration - 300)) / 300.0)
        p.setOpacity(max(0.0, min(fade_in, fade_out)))
        self._paint_card(p)
        self._paint_grid(p)
        self._paint_curves(p, _ease(k / 0.8))
        self._paint_text(p)
        self._paint_progress(p, k)
        p.end()

    def _paint_card(self, p: QPainter) -> None:
        rect = QRectF(8, 8, W - 16, H - 16)
        path = QPainterPath()
        path.addRoundedRect(rect, 22, 22)
        glow = QRadialGradient(QPointF(W * 0.68, H * 0.45), W * 0.62)
        glow.setColorAt(0, QColor(45, 212, 191, 38))
        glow.setColorAt(1, QColor(45, 212, 191, 0))
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0, QColor("#141b24"))
        g.setColorAt(1, QColor("#0a0e13"))
        p.fillPath(path, g)
        p.fillPath(path, QBrush(glow))
        p.setPen(QPen(QColor(theme.BORDER), 1.5))
        p.drawPath(path)
        p.setClipPath(path)

    def _paint_grid(self, p: QPainter) -> None:
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        for i in range(5):
            y = self.yb - (self.yb - self.yt) * i / 4
            p.drawLine(QPointF(self.x0, y), QPointF(self.x1, y))
        for hh in range(0, 25, 4):
            x = self.x0 + (self.x1 - self.x0) * hh / 24
            p.drawLine(QPointF(x, self.yt), QPointF(x, self.yb))
        p.setFont(QFont("sans", 7))
        p.setPen(QColor(255, 255, 255, 85))
        for hh in range(0, 25, 6):
            x = self.x0 + (self.x1 - self.x0) * hh / 24
            p.drawText(QRectF(x - 20, self.yb + 6, 40, 14), Qt.AlignCenter, f"{hh:02d}:00")

    def _curve(self, p: QPainter, vals: np.ndarray, m: int, color: str, width: float, fill: bool) -> None:
        if m < 2:
            return
        ys = self._y(vals[:m])
        path = QPainterPath(QPointF(self.hx[0], ys[0]))
        for x, y in zip(self.hx[1:m], ys[1:]):
            path.lineTo(x, y)
        col = QColor(color)
        if fill:
            area = QPainterPath(path)
            area.lineTo(self.hx[m - 1], self.yb)
            area.lineTo(self.hx[0], self.yb)
            area.closeSubpath()
            g = QLinearGradient(0, self.yt, 0, self.yb)
            top, bot = QColor(col), QColor(col)
            top.setAlpha(110)
            bot.setAlpha(4)
            g.setColorAt(0, top)
            g.setColorAt(1, bot)
            p.fillPath(area, g)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(col, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)

    def _paint_curves(self, p: QPainter, prog: float) -> None:
        n = len(self.hx)
        m = max(2, int(n * prog))
        self._curve(p, self.load, m, theme.LOAD, 2.2, False)
        self._curve(p, self.pv, m, theme.PV, 2.8, True)
        # the sun rides the production curve
        tip = QPointF(self.hx[m - 1], float(self._y(self.pv[m - 1:m])[0]))
        halo = QRadialGradient(tip, 46)
        halo.setColorAt(0, QColor(251, 191, 36, 190))
        halo.setColorAt(1, QColor(251, 191, 36, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(tip, 46, 46)
        p.setPen(QPen(QColor(251, 191, 36, 200), 1.8, Qt.SolidLine, Qt.RoundCap))
        spin = self.t / 900.0
        for i in range(10):
            a = spin + i * math.pi / 5
            p.drawLine(QPointF(tip.x() + 12 * math.cos(a), tip.y() + 12 * math.sin(a)),
                       QPointF(tip.x() + 17 * math.cos(a), tip.y() + 17 * math.sin(a)))
        p.setPen(QPen(QColor("#2b1d02"), 2))
        p.setBrush(QColor(theme.PV))
        p.drawEllipse(tip, 8, 8)
        # legend
        p.setFont(QFont("sans", 8, QFont.DemiBold))
        for i, (txt, col) in enumerate((("Produzione", theme.PV), ("Consumo", theme.LOAD))):
            x = self.x0 + 6 + i * 96
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(x, self.yt - 30, 14, 4), 2, 2)
            p.setPen(QColor(theme.MUTED))
            p.drawText(QPointF(x + 20, self.yt - 24), txt)

    def _paint_text(self, p: QPainter) -> None:
        x = 58
        f = QFont("sans", 46, QFont.Black)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        p.setFont(f)
        p.setPen(QColor("#f1f5f9"))
        p.drawText(QPointF(x, H * 0.47), "Solar")
        w = p.fontMetrics().horizontalAdvance("Solar ")
        p.setPen(QColor(theme.ACCENT))
        p.drawText(QPointF(x + w, H * 0.47), "Deck")
        p.setPen(Qt.NoPen)
        g = QLinearGradient(x, 0, x + 230, 0)
        g.setColorAt(0, QColor(theme.ACCENT))
        g.setColorAt(1, QColor(45, 212, 191, 0))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(x, H * 0.47 + 16, 230, 3), 1.5, 1.5)
        p.setFont(QFont("sans", 11))
        p.setPen(QColor(theme.MUTED))
        p.drawText(QPointF(x + 2, H * 0.47 + 50), CREDITS)
        p.setFont(QFont("sans", 10, QFont.DemiBold))
        p.setPen(QColor(theme.ACCENT))
        p.drawText(QPointF(x + 2, H * 0.47 + 76), f"Version {self.version}")
        p.setFont(QFont("sans", 8))
        p.setPen(QColor(255, 255, 255, 70))
        p.drawText(QPointF(x + 2, H - 38), "SolarEdge HD-Wave monitor  ·  Modbus TCP")

    def _paint_progress(self, p: QPainter, k: float) -> None:
        x0, x1, y = 58.0, W - 58.0, H - 24.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(x0, y, x1 - x0, 3), 1.5, 1.5)
        g = QLinearGradient(x0, 0, x1, 0)
        g.setColorAt(0, QColor(theme.ACCENT))
        g.setColorAt(1, QColor("#38bdf8"))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(x0, y, (x1 - x0) * min(k, 1.0), 3), 1.5, 1.5)
