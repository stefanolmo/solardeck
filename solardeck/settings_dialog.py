"""Configuration window: connection, meter, plant and display settings."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from .config import Config
from .poller import ProbeThread


def _hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setObjectName("muted")
    return lab


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None, simulated: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Impostazioni")
        self.resize(560, 520)
        self.cfg = replace(cfg)
        self._probe: ProbeThread | None = None
        lay = QVBoxLayout(self)
        if simulated:
            lay.addWidget(_hint("Modalità simulatore: le impostazioni di connessione non vengono salvate."))
        tabs = QTabWidget()
        lay.addWidget(tabs, 1)

        # ---- connection -------------------------------------------------
        t = QWidget()
        f = QFormLayout(t)
        f.setLabelAlignment(Qt.AlignRight)
        self.host = QLineEdit(cfg.host)
        self.host.setPlaceholderText("es. 192.168.1.50 o solaredge.local")
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(cfg.port)
        self.unit = QSpinBox(); self.unit.setRange(1, 247); self.unit.setValue(cfg.unit)
        self.timeout = QDoubleSpinBox(); self.timeout.setRange(0.5, 30); self.timeout.setSuffix(" s"); self.timeout.setValue(cfg.timeout)
        self.poll = QDoubleSpinBox(); self.poll.setRange(1, 600); self.poll.setSuffix(" s"); self.poll.setDecimals(0); self.poll.setValue(cfg.poll_interval)
        self.auto = QCheckBox("Connetti automaticamente all'avvio"); self.auto.setChecked(cfg.auto_connect)
        f.addRow("Indirizzo inverter", self.host)
        f.addRow("Porta Modbus TCP", self.port)
        f.addRow("ID unità (slave)", self.unit)
        f.addRow("Timeout", self.timeout)
        f.addRow("Intervallo di lettura", self.poll)
        f.addRow("", self.auto)
        f.addRow(_hint("Sull'inverter abilita Modbus TCP da SetApp: Commissioning → Site Communication → "
                       "Modbus TCP (porta predefinita 1502). L'inverter accetta una sola connessione alla volta: "
                       "chiudi altri software Modbus (Home Assistant, ecc.) o usa un intervallo adeguato."))
        probe_row = QHBoxLayout()
        self.btn_test = QPushButton("Prova connessione")
        probe_row.addWidget(self.btn_test)
        probe_row.addStretch()
        f.addRow("", probe_row)
        self.probe_out = QLabel("")
        self.probe_out.setWordWrap(True)
        self.probe_out.setObjectName("kv")
        self.probe_out.setTextInteractionFlags(Qt.TextSelectableByMouse)
        f.addRow("", self.probe_out)
        tabs.addTab(t, "Connessione")

        # ---- meter ------------------------------------------------------
        t = QWidget()
        f = QFormLayout(t)
        self.use_meter = QCheckBox("Leggi il contatore Export+Import"); self.use_meter.setChecked(cfg.use_meter)
        self.meter_idx = QComboBox()
        for i in (1, 2, 3):
            self.meter_idx.addItem(f"Contatore {i}", i)
        self.meter_idx.setCurrentIndex(max(0, cfg.meter_index - 1))
        self.pos_export = QComboBox()
        self.pos_export.addItem("Positivo = immissione in rete (standard SolarEdge)", True)
        self.pos_export.addItem("Positivo = prelievo dalla rete (invertito)", False)
        self.pos_export.setCurrentIndex(0 if cfg.grid_positive_export else 1)
        f.addRow("", self.use_meter)
        f.addRow("Contatore", self.meter_idx)
        f.addRow("Segno potenza di rete", self.pos_export)
        f.addRow(_hint("Il consumo di casa è calcolato come produzione − immissione + prelievo e richiede il "
                       "contatore. Senza contatore vedrai solo la produzione. Se di notte l'app mostra "
                       "«immissione» mentre stai consumando, scegli il segno invertito."))
        tabs.addTab(t, "Contatore")

        # ---- plant ------------------------------------------------------
        t = QWidget()
        f = QFormLayout(t)
        self.peak = QDoubleSpinBox(); self.peak.setRange(0.5, 100); self.peak.setDecimals(2); self.peak.setSuffix(" kWp"); self.peak.setValue(cfg.peak_kwp)
        self.inv_kw = QDoubleSpinBox(); self.inv_kw.setRange(0.5, 100); self.inv_kw.setDecimals(2); self.inv_kw.setSuffix(" kW"); self.inv_kw.setValue(cfg.inverter_kw)
        f.addRow("Potenza pannelli installata", self.peak)
        f.addRow("Potenza nominale inverter", self.inv_kw)
        f.addRow(_hint("Servono solo per la scala degli indicatori ad anello e lo spessore dei flussi."))
        tabs.addTab(t, "Impianto")

        # ---- display ----------------------------------------------------
        t = QWidget()
        f = QFormLayout(t)
        self.range = QComboBox()
        for h, lab in ((1, "Ultima ora"), (6, "Ultime 6 ore"), (12, "Ultime 12 ore"), (24, "Ultime 24 ore"), (48, "Ultime 48 ore"), (0, "Oggi (da mezzanotte)")):
            self.range.addItem(lab, h)
        self.range.setCurrentIndex(max(0, self.range.findData(cfg.chart_range_h)))
        self.log_int = QSpinBox(); self.log_int.setRange(1, 300); self.log_int.setSuffix(" s"); self.log_int.setValue(int(cfg.log_interval))
        self.days = QSpinBox(); self.days.setRange(1, 365); self.days.setSuffix(" giorni"); self.days.setValue(cfg.history_days)
        self.splash = QCheckBox("Mostra la splash screen all'avvio"); self.splash.setChecked(cfg.show_splash)
        self.anim = QCheckBox("Anima i flussi di energia"); self.anim.setChecked(cfg.smooth_flow)
        f.addRow("Intervallo grafico predefinito", self.range)
        f.addRow("Campionamento storico", self.log_int)
        f.addRow("Conserva lo storico per", self.days)
        f.addRow("", self.splash)
        f.addRow("", self.anim)
        f.addRow(_hint("Lo storico è salvato in ~/.local/share/solardeck/history.csv e serve per il grafico "
                       "e i totali di oggi."))
        tabs.addTab(t, "Aspetto e storico")

        row = QHBoxLayout()
        self.btn_defaults = QPushButton("Ripristina predefiniti")
        self.btn_cancel = QPushButton("Annulla")
        self.btn_ok = QPushButton("Salva")
        self.btn_ok.setObjectName("primary")
        row.addWidget(self.btn_defaults)
        row.addStretch()
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_ok)
        lay.addLayout(row)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._accept)
        self.btn_test.clicked.connect(self._test)
        self.btn_defaults.clicked.connect(self._defaults)

    # ------------------------------------------------------------------
    def result_config(self) -> Config:
        c = replace(self.cfg)
        c.host = self.host.text().strip() or c.host
        c.port, c.unit = self.port.value(), self.unit.value()
        c.timeout, c.poll_interval = self.timeout.value(), self.poll.value()
        c.auto_connect = self.auto.isChecked()
        c.use_meter = self.use_meter.isChecked()
        c.meter_index = self.meter_idx.currentData()
        c.grid_positive_export = bool(self.pos_export.currentData())
        c.peak_kwp, c.inverter_kw = self.peak.value(), self.inv_kw.value()
        c.chart_range_h = self.range.currentData()
        c.log_interval, c.history_days = float(self.log_int.value()), self.days.value()
        c.show_splash, c.smooth_flow = self.splash.isChecked(), self.anim.isChecked()
        return c

    def _accept(self) -> None:
        if not self.host.text().strip():
            self.host.setFocus()
            self.host.setStyleSheet("border-color: #f87171;")
            return
        self.accept()

    def _defaults(self) -> None:
        d = Config(host=self.host.text() or Config.host)
        self.port.setValue(d.port); self.unit.setValue(d.unit); self.timeout.setValue(d.timeout)
        self.poll.setValue(d.poll_interval); self.auto.setChecked(d.auto_connect)
        self.use_meter.setChecked(d.use_meter); self.meter_idx.setCurrentIndex(0); self.pos_export.setCurrentIndex(0)
        self.peak.setValue(d.peak_kwp); self.inv_kw.setValue(d.inverter_kw)
        self.range.setCurrentIndex(self.range.findData(d.chart_range_h)); self.log_int.setValue(int(d.log_interval))
        self.days.setValue(d.history_days); self.splash.setChecked(d.show_splash); self.anim.setChecked(d.smooth_flow)

    def _test(self) -> None:
        if self._probe is not None and self._probe.isRunning():
            return
        self.btn_test.setEnabled(False)
        self.probe_out.setStyleSheet("")
        self.probe_out.setText("Connessione in corso…")
        self._probe = ProbeThread(self.result_config(), self)
        self._probe.done.connect(self._probe_done)
        self._probe.start()

    def _probe_done(self, ok: bool, text: str) -> None:
        self.btn_test.setEnabled(True)
        self.probe_out.setStyleSheet(f"color: {'#34d399' if ok else '#f87171'};")
        self.probe_out.setText(("✔ " if ok else "✘ ") + text)

    def done(self, r: int) -> None:
        if self._probe is not None and self._probe.isRunning():
            self._probe.wait(int(self.timeout.value() * 1000) + 2000)
        super().done(r)
