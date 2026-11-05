"""Reusable widgets: cards, state badge, key/value rows, formatting helpers."""
from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QColor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from . import theme


def fmt_power(w: Optional[float]) -> str:
    if w is None:
        return "—"
    w = abs(w) if abs(w) < 0.5 else w
    return f"{w:,.0f} W".replace(",", ".") if abs(w) < 1000 else f"{w / 1000:.2f} kW"


def fmt_kwh(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:.1f} kWh" if v < 100 else f"{v:,.0f} kWh".replace(",", ".")


def fmt_pct(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.0f} %"


class Card(QFrame):
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(14, 12, 14, 14)
        self._lay.setSpacing(10)
        self.title_label = None
        if title:
            self.title_label = QLabel(title.upper())
            self.title_label.setObjectName("cardTitle")
            self._lay.addWidget(self.title_label)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        self._lay.addLayout(self.body)


class StateBadge(QLabel):
    LABELS = {"disconnected": "Non connesso", "connecting": "Connessione…", "online": "Connesso",
              "offline": "Nessuna risposta", "sim": "Simulatore"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(130)
        self.set_state("disconnected")

    def set_state(self, state: str, text: Optional[str] = None) -> None:
        col = theme.STATE_COLORS.get(state, theme.MUTED)
        self.setText(text or self.LABELS.get(state, state))
        c = QColor(col)
        self.setStyleSheet(
            f"background: rgba({c.red()},{c.green()},{c.blue()},38); color: {col}; border: 1px solid {col};"
            f"border-radius: 13px; padding: 5px 14px; font-weight: 700; letter-spacing: 0.5px;")


class KVGrid(QWidget):
    """Rows of `label ........ value` with muted labels and monospaced values."""

    def __init__(self, keys: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(5)
        self.values: dict[str, QLabel] = {}
        for r, (key, label) in enumerate(keys):
            a = QLabel(label)
            a.setObjectName("muted")
            b = QLabel("—")
            b.setObjectName("kv")
            b.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            g.addWidget(a, r, 0)
            g.addWidget(b, r, 1)
            self.values[key] = b
        g.setColumnStretch(0, 1)

    def set(self, key: str, text: str, color: Optional[str] = None) -> None:
        lab = self.values[key]
        lab.setText(text)
        lab.setStyleSheet(f"color: {color};" if color else "")
