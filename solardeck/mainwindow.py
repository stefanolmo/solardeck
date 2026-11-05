"""Main window: energy-flow diagram, daily totals, inverter details and the production / consumption chart."""
from __future__ import annotations

import os
import time
from dataclasses import replace
from typing import Optional

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QProgressBar, QSizePolicy,
                               QSplitter, QToolBar, QToolButton, QVBoxLayout, QWidget)

from . import theme
from .chartview import ChartView
from .config import APP, ORG, Config
from .flowview import FlowView
from .history import History, midnight
from .modbus import DeviceInfo, Sample
from .poller import Poller
from .settings_dialog import SettingsDialog
from .widgets import Card, KVGrid, StateBadge, fmt_kwh, fmt_pct, fmt_power

APP_NAME = "SolarDeck"
RANGES = [(1, "1 h"), (6, "6 h"), (12, "12 h"), (24, "24 h"), (48, "48 h"), (0, "Oggi")]


def default_history_path() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "solardeck", "history.csv")


class MainWindow(QMainWindow):
    def __init__(self, qs: Optional[QSettings] = None, history_path: Optional[str] = None, sim=None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 860)
        self.sim = sim                                   # SimulatedSolarEdge or None
        self.persist = sim is None
        self.qs = qs or QSettings(ORG, APP)
        self.cfg = Config().load(self.qs)
        if sim is not None:
            self.cfg = replace(self.cfg, host="127.0.0.1", port=sim.port, unit=1, use_meter=True, meter_index=sim.meter_index,
                               grid_positive_export=sim.export_positive, poll_interval=min(self.cfg.poll_interval, 2.0))
        if sim is not None or history_path == ":memory:":
            self.history = History(None, self.cfg.history_days, self.cfg.log_interval)
            if sim is not None:
                from .simulator import synthetic_history
                self.history.extend(synthetic_history(sim.clock, with_meter=sim.with_meter))
        else:
            self.history = History(history_path or default_history_path(), self.cfg.history_days, self.cfg.log_interval)
        self.poller: Optional[Poller] = None
        self.info: Optional[DeviceInfo] = None
        self.last: Optional[Sample] = None
        self.last_ok = 0.0
        self.state = "disconnected"
        self._running = True
        self._build_ui()
        self._apply_cfg()
        self._clock = QTimer(self, interval=1000)
        self._clock.timeout.connect(self._tick)
        self._clock.start()
        self._update_totals()
        if self.cfg.auto_connect or sim is not None:
            QTimer.singleShot(0, self.connect_inverter)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        tb = QToolBar()
        tb.setMovable(False)
        tb.setFloatable(False)
        self.addToolBar(tb)
        title = QLabel(f"<span style='font-size:17px;font-weight:800;color:#f1f5f9'>Solar</span>"
                       f"<span style='font-size:17px;font-weight:800;color:{theme.ACCENT}'>Deck</span>")
        title.setContentsMargins(4, 0, 14, 0)
        tb.addWidget(title)
        self.badge = StateBadge()
        tb.addWidget(self.badge)
        self.act_conn = QAction(theme.icon("plug"), "Connetti", self)
        self.act_conn.setShortcut(QKeySequence("F5"))
        self.act_conn.triggered.connect(self.toggle_connection)
        tb.addAction(self.act_conn)
        self.host_label = QLabel("")
        self.host_label.setObjectName("muted")
        self.host_label.setContentsMargins(10, 0, 0, 0)
        tb.addWidget(self.host_label)
        spacer = QWidget()
        spacer.setObjectName("spacer")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.age_label = QLabel("")
        self.age_label.setObjectName("muted")
        tb.addWidget(self.age_label)
        self.act_settings = QAction(theme.icon("gear"), "Impostazioni", self)
        self.act_settings.setShortcut(QKeySequence("Ctrl+,"))
        self.act_settings.triggered.connect(self.open_settings)
        tb.addAction(self.act_settings)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(10)
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        # ---- top: flow + side panels --------------------------------------
        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(10)
        self.flow_card = Card("Flusso di energia")
        self.flow = FlowView()
        self.flow_card.body.addWidget(self.flow, 1)
        tl.addWidget(self.flow_card, 1)

        side = QWidget()
        side.setFixedWidth(310)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(10)
        today = Card("Oggi")
        self.today = KVGrid([("produced", "Produzione"), ("consumed", "Consumo"), ("exported", "Immesso in rete"),
                             ("imported", "Prelevato dalla rete")])
        today.body.addWidget(self.today)
        self.bar_self = self._meter_row(today, "Autoconsumo", theme.PV)
        self.bar_auto = self._meter_row(today, "Autosufficienza", theme.LOAD)
        sl.addWidget(today)
        inv = Card("Inverter")
        self.inv = KVGrid([("status", "Stato"), ("ac", "Potenza AC"), ("dc", "Potenza DC"), ("vac", "Tensione AC"),
                           ("hz", "Frequenza"), ("vdc", "Tensione DC"), ("temp", "Temperatura"),
                           ("etot", "Produzione totale"), ("eexp", "Totale immesso"), ("eimp", "Totale prelevato"),
                           ("model", "Modello")])
        inv.body.addWidget(self.inv)
        sl.addWidget(inv)
        sl.addStretch(1)
        tl.addWidget(side)
        split.addWidget(top)

        # ---- bottom: chart --------------------------------------------------
        chart_card = Card("Andamento produzione / consumo")
        head = QHBoxLayout()
        head.setSpacing(6)
        self.legend_btns: dict[str, QToolButton] = {}
        for key, text, col in (("pv", "Produzione", theme.PV), ("load", "Consumo", theme.LOAD), ("grid", "Rete", "#a78bfa")):
            b = QToolButton()
            b.setText("● " + text)
            b.setCheckable(True)
            b.setChecked(key != "grid")
            b.setObjectName("range")
            b.setStyleSheet(f"QToolButton {{ color: {col}; }} QToolButton:!checked {{ color: {theme.MUTED}; }}")
            b.toggled.connect(self._legend_changed)
            head.addWidget(b)
            self.legend_btns[key] = b
        head.addStretch(1)
        self.range_group = QButtonGroup(self)
        self.range_group.setExclusive(True)
        self.range_btns: dict[int, QToolButton] = {}
        for h, lab in RANGES:
            b = QToolButton()
            b.setText(lab)
            b.setCheckable(True)
            b.setObjectName("range")
            self.range_group.addButton(b)
            b.clicked.connect(lambda _=False, hh=h: self.set_chart_range(hh))
            head.addWidget(b)
            self.range_btns[h] = b
        chart_card.body.addLayout(head)
        self.chart = ChartView(self.history)
        chart_card.body.addWidget(self.chart, 1)
        split.addWidget(chart_card)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 3)
        split.setSizes([520, 300])

        self.statusBar().showMessage("Pronto.")
        self.status_right = QLabel("")
        self.status_right.setObjectName("muted")
        self.statusBar().addPermanentWidget(self.status_right)

    def _meter_row(self, card: Card, label: str, color: str) -> QProgressBar:
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setObjectName("muted")
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setFormat("—")
        bar.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; }}")
        row.addWidget(lab, 1)
        row.addWidget(bar, 1)
        card.body.addLayout(row)
        return bar

    # ------------------------------------------------------------------ config
    def _apply_cfg(self) -> None:
        c = self.cfg
        self.flow.set_plant(c.peak_kwp, c.inverter_kw)
        self.flow.animate = c.smooth_flow
        self.history.keep_days, self.history.interval = c.history_days, c.log_interval
        rng = int(self.qs.value("chart_range", c.chart_range_h)) if self.persist else c.chart_range_h
        self.set_chart_range(rng if rng in self.range_btns else 24, save=False)
        for k, b in self.legend_btns.items():
            if k == "grid" and self.persist and self.qs.contains("show_grid"):
                b.setChecked(str(self.qs.value("show_grid")).lower() == "true")
        self.host_label.setText("simulatore integrato" if self.sim else f"{c.host}:{c.port}")

    def set_chart_range(self, hours: int, save: bool = True) -> None:
        self.range_btns[hours].setChecked(True)
        self.chart.set_range(hours)
        if save and self.persist:
            self.qs.setValue("chart_range", hours)

    def _legend_changed(self) -> None:
        self.chart.show_pv = self.legend_btns["pv"].isChecked()
        self.chart.show_load = self.legend_btns["load"].isChecked()
        self.chart.show_grid = self.legend_btns["grid"].isChecked()
        if self.persist:
            self.qs.setValue("show_grid", self.chart.show_grid)
        self.chart.update()

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self, simulated=self.sim is not None)
        if dlg.exec():
            self.apply_config(dlg.result_config())

    def apply_config(self, new: Config) -> None:
        conn_changed = any(getattr(new, k) != getattr(self.cfg, k) for k in
                           ("host", "port", "unit", "timeout", "poll_interval", "use_meter", "meter_index", "grid_positive_export"))
        if self.sim is not None:                       # never overwrite the real connection settings from --sim
            for k in ("host", "port", "unit", "use_meter", "meter_index", "grid_positive_export", "poll_interval"):
                setattr(new, k, getattr(self.cfg, k))
            conn_changed = False
        self.cfg = new
        if self.persist:
            new.save(self.qs)
        self._apply_cfg()
        self.chart.update()
        self._update_totals()
        if conn_changed and self.poller is not None:
            self.disconnect_inverter()
            self.connect_inverter()

    # ------------------------------------------------------------------ connection
    def toggle_connection(self) -> None:
        if self.poller is None:
            self.connect_inverter()
        else:
            self.disconnect_inverter()

    def connect_inverter(self) -> None:
        if self.poller is not None or not self._running:
            return
        self.poller = Poller(self.cfg, self)
        self.poller.sample.connect(self.on_sample)
        self.poller.info.connect(self.on_info)
        self.poller.stateChanged.connect(self.on_state)
        self.poller.start()
        self.act_conn.setText("Disconnetti")
        self.act_conn.setIcon(theme.icon("unplug"))
        self.on_state("connecting", f"{self.cfg.host}:{self.cfg.port}")

    def disconnect_inverter(self) -> None:
        p, self.poller = self.poller, None
        if p is not None:
            for sig in (p.sample, p.info, p.stateChanged):
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError):
                    pass
            p.stop()
            p.deleteLater()
        self.act_conn.setText("Connetti")
        self.act_conn.setIcon(theme.icon("plug"))
        self.state = "disconnected"
        self.badge.set_state("disconnected")
        self.flow.set_sample(self.last, online=False)
        self.statusBar().showMessage("Disconnesso.")

    # ------------------------------------------------------------------ data
    def on_state(self, state: str, msg: str) -> None:
        if self.poller is None:
            return
        self.state = state
        if state == "online":
            self.badge.set_state("sim" if self.sim else "online")
            self.statusBar().showMessage("")
        elif state == "connecting":
            self.badge.set_state("connecting")
            self.statusBar().showMessage(f"Connessione a {msg}…")
        else:
            self.badge.set_state("offline")
            self.statusBar().showMessage(f"{msg} — nuovo tentativo in corso")
            self.flow.set_sample(self.last, online=False)

    def on_info(self, info: DeviceInfo) -> None:
        self.info = info
        parts = [info.model or "inverter"]
        if info.serial:
            parts.append(f"S/N {info.serial}")
        self.inv.set("model", info.model or "—")
        self.status_right.setText(" · ".join(parts) + ("" if info.meter_model_id else " · nessun contatore"))
        if info.notes:
            self.statusBar().showMessage("; ".join(info.notes), 8000)

    def on_sample(self, s: Sample) -> None:
        self.last, self.last_ok = s, time.time()
        self.flow.set_sample(s, online=True)
        self.history.add(s)
        self.chart.update()
        self._update_inverter(s)
        self._update_totals()
        self._tick()

    def _update_inverter(self, s: Sample) -> None:
        ok = theme.OK if s.status in (4, 5) else (theme.WARN if s.status in (2, 3, 6, 8) else (theme.DANGER if s.status == 7 else None))
        self.inv.set("status", s.status_text, ok)
        self.inv.set("ac", fmt_power(s.pv_w))
        self.inv.set("dc", fmt_power(s.dc_w))
        self.inv.set("vac", f"{s.ac_v:.1f} V" if s.ac_v is not None else "—")
        self.inv.set("hz", f"{s.hz:.2f} Hz" if s.hz is not None else "—")
        self.inv.set("vdc", f"{s.dc_v:.0f} V" if s.dc_v else "—")
        self.inv.set("temp", f"{s.temp_c:.1f} °C" if s.temp_c is not None else "—")
        self.inv.set("etot", fmt_kwh(s.e_total_wh / 1000) if s.e_total_wh is not None else "—")
        self.inv.set("eexp", fmt_kwh(s.e_export_wh / 1000) if s.e_export_wh is not None else "—")
        self.inv.set("eimp", fmt_kwh(s.e_import_wh / 1000) if s.e_import_wh is not None else "—")

    def _update_totals(self) -> None:
        e = self.history.energy_since(midnight(time.time()))
        has = e["has_meter"]
        self.today.set("produced", fmt_kwh(e["produced"]), theme.PV)
        self.today.set("consumed", fmt_kwh(e["consumed"]) if has else "—", theme.LOAD)
        self.today.set("exported", fmt_kwh(e["exported"]) if has else "—", theme.EXPORT)
        self.today.set("imported", fmt_kwh(e["imported"]) if has else "—", theme.IMPORT)
        self_pct = auto_pct = None
        if has and e["produced"] > 0.05:
            self_pct = max(0.0, min(100.0, (e["produced"] - e["exported"]) / e["produced"] * 100))
        if has and e["consumed"] > 0.05:
            auto_pct = max(0.0, min(100.0, (e["consumed"] - e["imported"]) / e["consumed"] * 100))
        for bar, v in ((self.bar_self, self_pct), (self.bar_auto, auto_pct)):
            bar.setValue(int(v) if v is not None else 0)
            bar.setFormat(fmt_pct(v))

    def _tick(self) -> None:
        if self.last_ok and self.state == "online":
            age = int(time.time() - self.last_ok)
            self.age_label.setText(f"aggiornato {age} s fa  ")
        elif self.last_ok:
            self.age_label.setText(f"ultimo dato {time.strftime('%H:%M:%S', time.localtime(self.last_ok))}  ")
        else:
            self.age_label.setText("")
        if time.localtime().tm_min % 5 == 0 and time.localtime().tm_sec == 0:
            self.chart.update()                         # keep the time axis moving when the inverter is silent

    # ------------------------------------------------------------------ lifecycle
    def closeEvent(self, ev) -> None:
        self._running = False
        if self.persist:
            self.qs.setValue("geometry", self.saveGeometry())
        self.disconnect_inverter()
        super().closeEvent(ev)
