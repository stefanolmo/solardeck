"""Production / consumption chart (custom painted, same look as the rest of the app)."""
from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme
from .history import History, midnight

MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 52, 14, 10, 24
STEPS_S = [60, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400]
GAP_FACTOR = 6          # a hole longer than GAP_FACTOR * median step breaks the line


def nice_ceiling(v: float) -> float:
    """Round v (W) up to a 'nice' axis maximum: 1, 2, 2.5, 5 x 10^n."""
    if v <= 0:
        return 1000.0
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * e:
            return m * e
    return 10 * e


class ChartView(QWidget):
    def __init__(self, history: History, parent=None):
        super().__init__(parent)
        self.history = history
        self.range_h = 24                # 0 = since midnight (24 h wide window)
        self.show_pv = True
        self.show_load = True
        self.show_grid = False
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._hover: Optional[float] = None
        self._win = (0.0, 1.0)
        self._series: list[tuple] = []

    def set_range(self, hours: int) -> None:
        self.range_h = hours
        self.update()

    def window(self) -> tuple[float, float]:
        now = time.time()
        if self.range_h == 0:
            t0 = midnight(now)
            return t0, t0 + 86400
        return now - self.range_h * 3600, now

    # ------------------------------------------------------------------ data preparation
    def _prepare(self, t0: float, t1: float, plot_w: int) -> list[tuple]:
        pts = [p for p in self.history.since(t0) if p[0] <= t1]
        if len(pts) <= plot_w * 2:
            return pts
        # bucket by pixel column (mean) so long ranges stay cheap and smooth
        span = (t1 - t0) / max(plot_w, 1)
        out, acc, cur = [], None, None
        for p in pts:
            k = int((p[0] - t0) / span)
            if k != cur:
                if acc:
                    out.append(self._mean(acc))
                acc, cur = [], k
            acc.append(p)
        if acc:
            out.append(self._mean(acc))
        return out

    @staticmethod
    def _mean(acc: list[tuple]) -> tuple:
        n = len(acc)
        ts = sum(a[0] for a in acc) / n
        pv = sum(a[1] for a in acc) / n
        ld = [a[2] for a in acc if a[2] is not None]
        gd = [a[3] for a in acc if a[3] is not None]
        return (ts, pv, sum(ld) / len(ld) if ld else None, sum(gd) / len(gd) if gd else None)

    # ------------------------------------------------------------------ painting
    def _plot_rect(self) -> QRectF:
        return QRectF(MARGIN_L, MARGIN_T, max(10, self.width() - MARGIN_L - MARGIN_R), max(10, self.height() - MARGIN_T - MARGIN_B))

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot_rect()
        t0, t1 = self.window()
        self._win = (t0, t1)
        pts = self._prepare(t0, t1, int(r.width()))
        self._series = pts
        vals = []
        for q in pts:
            if self.show_pv:
                vals.append(q[1])
            if self.show_load and q[2] is not None:
                vals.append(q[2])
            if self.show_grid and q[3] is not None:
                vals += [q[3]]
        vmax = nice_ceiling(max(vals + [800.0]))
        vmin = 0.0
        if self.show_grid:
            gmin = min([q[3] for q in pts if q[3] is not None] + [0.0])
            vmin = -nice_ceiling(-gmin) if gmin < 0 else 0.0

        def X(t): return r.left() + (t - t0) / (t1 - t0) * r.width()
        def Y(v): return r.bottom() - (v - vmin) / (vmax - vmin) * r.height()

        self._draw_axes(p, r, t0, t1, vmin, vmax, X, Y)
        if not pts:
            p.setPen(QColor(theme.MUTED))
            p.drawText(r, Qt.AlignCenter, "Nessun dato ancora: lo storico si riempie man mano che l'inverter risponde")
            p.end()
            return
        p.setClipRect(r.adjusted(-1, -2, 1, 2))
        gap = self._gap_limit(pts)
        if self.show_pv:
            self._series_path(p, pts, 1, X, Y, theme.PV, fill=True, base=Y(0), gap=gap, width=2.0)
        if self.show_load:
            self._series_path(p, pts, 2, X, Y, theme.LOAD, fill=True, base=Y(0), gap=gap, width=2.0)
        if self.show_grid:
            self._series_path(p, pts, 3, X, Y, "#a78bfa", fill=False, base=Y(0), gap=gap, width=1.4)
        p.setClipping(False)
        # "now" marker for the since-midnight view
        if self.range_h == 0:
            nx = X(time.time())
            p.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.DashLine))
            p.drawLine(QPointF(nx, r.top()), QPointF(nx, r.bottom()))
        if self._hover is not None:
            self._draw_hover(p, r, X, Y)
        p.end()

    @staticmethod
    def _gap_limit(pts: list[tuple]) -> float:
        if len(pts) < 3:
            return 300.0
        d = sorted(b[0] - a[0] for a, b in zip(pts, pts[1:]))
        return max(120.0, d[len(d) // 2] * GAP_FACTOR)

    def _series_path(self, p, pts, idx, X, Y, color, fill, base, gap, width) -> None:
        segs, cur = [], []
        last = None
        for q in pts:
            v = q[idx]
            if v is None or (last is not None and q[0] - last > gap):
                if cur:
                    segs.append(cur)
                cur = []
            if v is not None:
                cur.append(QPointF(X(q[0]), Y(v)))
                last = q[0]
        if cur:
            segs.append(cur)
        col = QColor(color)
        for seg in segs:
            if len(seg) == 1:
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawEllipse(seg[0], 2, 2)
                continue
            path = QPainterPath(seg[0])
            for pt in seg[1:]:
                path.lineTo(pt)
            if fill:
                area = QPainterPath(path)
                area.lineTo(seg[-1].x(), base)
                area.lineTo(seg[0].x(), base)
                area.closeSubpath()
                g = QLinearGradient(0, self._plot_rect().top(), 0, base)
                top, bot = QColor(col), QColor(col)
                top.setAlpha(95)
                bot.setAlpha(6)
                g.setColorAt(0, top)
                g.setColorAt(1, bot)
                p.setPen(Qt.NoPen)
                p.fillPath(area, g)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(col, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)

    def _draw_axes(self, p, r, t0, t1, vmin, vmax, X, Y) -> None:
        f = QFont("monospace", 8)
        f.setStyleHint(QFont.Monospace)
        p.setFont(f)
        # horizontal grid + labels (kW)
        n = 4
        for i in range(n + 1):
            v = vmin + (vmax - vmin) * i / n
            y = Y(v)
            p.setPen(QPen(QColor(255, 255, 255, 28 if abs(v) > 1e-9 else 60), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(theme.MUTED))
            lab = f"{v / 1000:g} kW"
            p.drawText(QRectF(0, y - 8, MARGIN_L - 6, 16), Qt.AlignRight | Qt.AlignVCenter, lab)
        # vertical grid + time labels
        span = t1 - t0
        step = next((s for s in STEPS_S if span / s <= max(3, r.width() / 78)), STEPS_S[-1])
        t = math.ceil(t0 / step) * step
        # align to local midnight so labels land on round local hours
        off = datetime.fromtimestamp(t0).astimezone().utcoffset()
        off_s = off.total_seconds() if off else 0.0
        t = math.ceil((t0 + off_s) / step) * step - off_s
        while t <= t1:
            x = X(t)
            p.setPen(QPen(QColor(255, 255, 255, 18), 1))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.setPen(QColor(theme.MUTED))
            d = datetime.fromtimestamp(t)
            lab = d.strftime("%H:%M") if not (d.hour == 0 and d.minute == 0) else d.strftime("%d/%m")
            p.drawText(QRectF(x - 30, r.bottom() + 4, 60, 16), Qt.AlignCenter, lab)
            t += step

    # ------------------------------------------------------------------ hover
    def mouseMoveEvent(self, ev) -> None:
        r = self._plot_rect()
        x = ev.position().x()
        if r.left() <= x <= r.right():
            t0, t1 = self._win
            self._hover = t0 + (x - r.left()) / r.width() * (t1 - t0)
        else:
            self._hover = None
        self.update()

    def leaveEvent(self, _ev) -> None:
        self._hover = None
        self.update()

    def nearest(self, t: float) -> Optional[tuple]:
        pts = self._series
        if not pts:
            return None
        best = min(pts, key=lambda q: abs(q[0] - t))
        gap = self._gap_limit(pts)
        return best if abs(best[0] - t) <= gap else None

    def _draw_hover(self, p, r, X, Y) -> None:
        q = self.nearest(self._hover)
        if q is None:
            return
        x = X(q[0])
        p.setPen(QPen(QColor(255, 255, 255, 80), 1))
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        rows = [(datetime.fromtimestamp(q[0]).strftime("%d/%m %H:%M:%S"), theme.MUTED)]
        if self.show_pv:
            rows.append((f"Produzione  {q[1] / 1000:.2f} kW", theme.PV))
        if self.show_load and q[2] is not None:
            rows.append((f"Consumo     {q[2] / 1000:.2f} kW", theme.LOAD))
        if q[3] is not None:
            rows.append((("Immissione  " if q[3] >= 0 else "Prelievo    ") + f"{abs(q[3]) / 1000:.2f} kW",
                         theme.EXPORT if q[3] >= 0 else theme.IMPORT))
        f = QFont("monospace", 9)
        f.setStyleHint(QFont.Monospace)
        p.setFont(f)
        fm = p.fontMetrics()
        w = max(fm.horizontalAdvance(t) for t, _ in rows) + 20
        h = len(rows) * (fm.height() + 2) + 12
        bx = x + 12 if x + 12 + w < r.right() else x - 12 - w
        by = r.top() + 6
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.CARD_HI))
        p.drawRoundedRect(QRectF(bx, by, w, h), 6, 6)
        y = by + 6 + fm.ascent()
        for text, col in rows:
            p.setPen(QColor(col))
            p.drawText(QPointF(bx + 10, y), text)
            y += fm.height() + 2
        # dots on the series
        for idx, col, on in ((1, theme.PV, self.show_pv), (2, theme.LOAD, self.show_load)):
            if on and q[idx] is not None:
                p.setPen(QPen(QColor(theme.BG), 2))
                p.setBrush(QColor(col))
                p.drawEllipse(QPointF(x, Y(q[idx])), 4, 4)
