"""Energy-flow diagram: panels -> inverter -> house, with the grid on the other side.

Animated dots run along the links, in the direction of the energy; thickness and speed follow the power.
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme
from .modbus import Sample
from .widgets import fmt_power

NODE_R = 46


class FlowView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(520, 250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.sample: Optional[Sample] = None
        self.peak_w = 6000.0
        self.inverter_w = 6000.0
        self.animate = True
        self.online = False
        self.phase = 0.0
        self._timer = QTimer(self, interval=33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._icons: dict[tuple, QPixmap] = {}

    # ------------------------------------------------------------------ data
    def set_plant(self, peak_kw: float, inverter_kw: float) -> None:
        self.peak_w = max(100.0, peak_kw * 1000)
        self.inverter_w = max(100.0, inverter_kw * 1000)
        self.update()

    def set_sample(self, s: Optional[Sample], online: bool = True) -> None:
        self.sample = s
        self.online = online
        self.update()

    def flows(self) -> dict:
        """Power balance at the inverter bus (all values >= 0)."""
        s = self.sample
        if s is None or not self.online:
            return {"pv": 0.0, "load": None, "export": 0.0, "import": 0.0, "to_house_from_pv": 0.0}
        grid = s.grid_w
        load = s.load_w
        exp = max(grid, 0.0) if grid is not None else 0.0
        imp = max(-grid, 0.0) if grid is not None else 0.0
        return {"pv": s.pv_w, "load": load, "export": exp, "import": imp,
                "to_house_from_pv": max(0.0, min(s.pv_w, load)) if load is not None else 0.0}

    # ------------------------------------------------------------------ animation
    def _tick(self) -> None:
        if not (self.animate and self.online and self.sample and self.isVisible()):
            return
        f = self.flows()
        if f["pv"] <= 1 and f["export"] <= 1 and f["import"] <= 1 and not f["load"]:
            return
        self.phase = (self.phase + 1.6) % 1000.0
        self.update()

    # ------------------------------------------------------------------ layout
    def _nodes(self) -> dict[str, QPointF]:
        w, h = self.width(), self.height()
        top = max(NODE_R + 14, h * 0.2)
        mid = min(h - NODE_R - 40, h * 0.66)
        return {"pv": QPointF(w * 0.5, top), "inv": QPointF(w * 0.5, mid),
                "grid": QPointF(w * 0.14, mid), "house": QPointF(w * 0.86, mid)}

    def _pix(self, name: str, color: str, size: int) -> QPixmap:
        key = (name, color, size)
        if key not in self._icons:
            self._icons[key] = theme.pixmap(name, color, size * 2)
        return self._icons[key]

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = self._nodes()
        f = self.flows()
        s = self.sample
        pv, load = f["pv"], f["load"]
        on = self.online and s is not None
        scale = max(self.peak_w, self.inverter_w)

        # links ---------------------------------------------------------
        self._link(p, n["pv"], n["inv"], pv, theme.PV, scale, 1)
        if load is not None:
            self._link(p, n["inv"], n["house"], load, theme.LOAD, scale, 1)
        else:
            self._link(p, n["inv"], n["house"], 0, theme.LOAD, scale, 1)
        if f["export"] > 1:
            self._link(p, n["inv"], n["grid"], f["export"], theme.EXPORT, scale, 1)
        elif f["import"] > 1:
            self._link(p, n["grid"], n["inv"], f["import"], theme.IMPORT, scale, 1)
        else:
            self._link(p, n["grid"], n["inv"], 0, theme.MUTED, scale, 1)

        # nodes ---------------------------------------------------------
        self._node(p, n["pv"], "panel", "FOTOVOLTAICO", fmt_power(pv) if on else "—", theme.PV,
                   (pv / self.peak_w) if on else 0.0, sub=self._sub_pv(s) if on else "", label_right=True)
        inv_frac = (pv / self.inverter_w) if on else 0.0
        self._node(p, n["inv"], "inverter", "INVERTER", s.status_text if on and s else "—", theme.ACCENT, inv_frac,
                   value_font=11, sub=(f"{inv_frac * 100:.0f}% della potenza nominale" if on else ""))
        # grid ring colour follows direction
        if on and s.grid_w is not None:
            g = s.grid_w
            col = theme.EXPORT if g >= 0 else theme.IMPORT
            title = "IMMISSIONE IN RETE" if g >= 0 else "PRELIEVO DA RETE"
            self._node(p, n["grid"], "pylon", title, fmt_power(abs(g)), col,
                       min(1.0, abs(g) / scale), sub=self._sub_grid(s))
        else:
            self._node(p, n["grid"], "pylon", "RETE", "—", theme.MUTED, 0.0,
                       sub="contatore non disponibile" if on else "")
        # house ring: share of the load covered by the panels (blue) vs the grid
        frac = 0.0
        if on and load:
            frac = min(1.0, f["to_house_from_pv"] / load)
        self._node(p, n["house"], "home", "CONSUMO CASA", fmt_power(load) if (on and load is not None) else "—",
                   theme.LOAD, frac, sub=(f"{frac * 100:.0f}% coperto dai pannelli" if on and load else ""),
                   track=theme.IMPORT if (on and load) else None)
        if not self.online:
            p.setPen(QColor(theme.MUTED))
            p.setFont(QFont("sans", 10))
            p.drawText(QRectF(0, self.height() - 26, self.width(), 20), Qt.AlignCenter,
                       "In attesa di dati dall'inverter…")
        p.end()

    @staticmethod
    def _sub_pv(s: Sample) -> str:
        if s.dc_w is None:
            return ""
        return f"DC {fmt_power(s.dc_w)}" + (f" · {s.dc_v:.0f} V" if s.dc_v else "")

    @staticmethod
    def _sub_grid(s: Sample) -> str:
        return "vendi energia" if s.grid_w is not None and s.grid_w > 20 else ("compri energia" if s.grid_w is not None and s.grid_w < -20 else "bilancio in pareggio")

    def _link(self, p: QPainter, a: QPointF, b: QPointF, watts: float, color: str, scale: float, _dir: int) -> None:
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        a2 = QPointF(a.x() + math.cos(ang) * (NODE_R + 6), a.y() + math.sin(ang) * (NODE_R + 6))
        b2 = QPointF(b.x() - math.cos(ang) * (NODE_R + 6), b.y() - math.sin(ang) * (NODE_R + 6))
        active = watts > 1 and self.online
        col = QColor(color)
        width = 2.0 + 4.0 * min(1.0, math.sqrt(max(watts, 0) / scale)) if active else 2.0
        base = QColor(col)
        base.setAlpha(60 if active else 40)
        p.setPen(QPen(base if active else QColor(theme.BORDER), width, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(a2, b2)
        if not active:
            return
        length = math.hypot(b2.x() - a2.x(), b2.y() - a2.y())
        if length < 4:
            return
        spacing = 34.0
        speed = 0.6 + 1.4 * min(1.0, math.sqrt(watts / scale))
        off = (self.phase * speed) % spacing if self.animate else 0.0
        p.setPen(Qt.NoPen)
        d = off
        while d < length:
            t = d / length
            x, y = a2.x() + (b2.x() - a2.x()) * t, a2.y() + (b2.y() - a2.y()) * t
            fade = min(1.0, t * 8, (1 - t) * 8)
            c = QColor(col)
            c.setAlpha(int(235 * fade))
            halo = QRadialGradient(QPointF(x, y), 9)
            hc = QColor(col)
            hc.setAlpha(int(90 * fade))
            halo.setColorAt(0, hc)
            halo.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
            p.setBrush(QBrush(halo))
            p.drawEllipse(QPointF(x, y), 9, 9)
            p.setBrush(c)
            p.drawEllipse(QPointF(x, y), 3.2 + width * 0.12, 3.2 + width * 0.12)
            d += spacing

    def _node(self, p: QPainter, c: QPointF, icon: str, title: str, value: str, color: str, frac: float,
              value_font: int = 15, sub: str = "", track: Optional[str] = None, label_right: bool = False) -> None:
        r = NODE_R
        glow = QRadialGradient(c, r * 1.9)
        gc = QColor(color)
        gc.setAlpha(34 if frac > 0.001 else 12)
        glow.setColorAt(0, gc)
        glow.setColorAt(1, QColor(gc.red(), gc.green(), gc.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(c, r * 1.9, r * 1.9)
        g = QLinearGradient(c.x(), c.y() - r, c.x(), c.y() + r)
        g.setColorAt(0, QColor(theme.CARD_HI))
        g.setColorAt(1, QColor(theme.CARD))
        p.setBrush(QBrush(g))
        p.setPen(QPen(QColor(theme.BORDER), 1.5))
        p.drawEllipse(c, r, r)
        # gauge ring
        rr = QRectF(c.x() - r - 5, c.y() - r - 5, 2 * r + 10, 2 * r + 10)
        tr = QColor(track) if track else QColor(theme.BORDER)
        tr.setAlpha(120 if track else 255)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(tr, 4, Qt.SolidLine, Qt.FlatCap))
        p.drawArc(rr, 0, 360 * 16)
        if frac > 0.001:
            p.setPen(QPen(QColor(color), 4, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rr, 90 * 16, -int(min(frac, 1.0) * 360 * 16))
        # icon
        isz = 40
        p.drawPixmap(QRectF(c.x() - isz / 2, c.y() - isz / 2, isz, isz), self._pix(icon, color if frac > 0.001 or icon == "inverter" else theme.MUTED, isz), QRectF(0, 0, isz * 2, isz * 2))
        # texts: below the node, or to its right when the node has a link running underneath it
        if label_right:
            x, al, y0 = c.x() + r + 18, Qt.AlignLeft | Qt.AlignVCenter, c.y() - 28
            rects = [QRectF(x, y0, 260, 16), QRectF(x, y0 + 16, 260, 24), QRectF(x, y0 + 40, 260, 16)]
        else:
            x, al, y0 = c.x() - 130, Qt.AlignCenter, c.y() + r + 10
            rects = [QRectF(x, y0, 260, 16), QRectF(x, y0 + 16, 260, 24), QRectF(x, y0 + 40, 260, 16)]
        p.setPen(QColor(theme.MUTED))
        f = QFont("sans", 8, QFont.Bold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        p.setFont(f)
        p.drawText(rects[0], al, title)
        vf = QFont("monospace", value_font, QFont.Bold)
        vf.setStyleHint(QFont.Monospace)
        p.setFont(vf)
        p.setPen(QColor(theme.TEXT))
        p.drawText(rects[1], al, value)
        if sub:
            p.setFont(QFont("sans", 8))
            p.setPen(QColor(theme.MUTED))
            p.drawText(rects[2], al, sub)
