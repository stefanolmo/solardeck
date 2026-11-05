"""Background thread that keeps a Modbus TCP session to the inverter and emits one Sample per poll."""
from __future__ import annotations

import threading
import time
from dataclasses import replace

from PySide6.QtCore import QThread, Signal

from .config import Config
from .modbus import DeviceInfo, ModbusError, ModbusTcpClient, identify, read_sample


class Poller(QThread):
    sample = Signal(object)              # modbus.Sample
    info = Signal(object)                # modbus.DeviceInfo, after every (re)connection
    stateChanged = Signal(str, str)      # state ("connecting" | "online" | "offline"), message

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = replace(cfg)          # private copy: the dialog may edit the live one while we run
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()
        self.wait(int(self.cfg.timeout * 1000) + 2000)

    def run(self) -> None:
        cfg = self.cfg
        cli = ModbusTcpClient(cfg.host, cfg.port, cfg.unit, cfg.timeout)
        info: DeviceInfo | None = None
        failures = 0
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                if not cli.connected or info is None:
                    self.stateChanged.emit("connecting", f"{cfg.host}:{cfg.port}")
                    cli.connect()
                    info = identify(cli, cfg)
                    self.info.emit(info)
                s = read_sample(cli, cfg, info)
                if failures:
                    failures = 0
                self.stateChanged.emit("online", "")
                self.sample.emit(s)
                delay = max(0.5, cfg.poll_interval - (time.monotonic() - t0))
            except ModbusError as e:
                cli.close()
                info = None
                failures += 1
                self.stateChanged.emit("offline", str(e))
                delay = min(30.0, max(cfg.poll_interval, 2.0) * min(failures, 6))     # back off, never give up
            if self._stop.wait(delay):
                break
        cli.close()


class ProbeThread(QThread):
    """One-shot connection test used by the settings dialog."""
    done = Signal(bool, str)

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = replace(cfg)

    def run(self) -> None:
        c = self.cfg
        cli = ModbusTcpClient(c.host, c.port, c.unit, c.timeout)
        try:
            cli.connect()
            info = identify(cli, c)
            s = read_sample(cli, c, info)
        except ModbusError as e:
            self.done.emit(False, str(e))
            return
        finally:
            cli.close()
        lines = [f"{info.manufacturer} {info.model}  (S/N {info.serial or '?'})",
                 f"Inverter {'trifase' if info.phases == 3 else 'monofase'} · modello SunSpec {info.inverter_model_id}",
                 f"Produzione attuale: {s.pv_w:.0f} W · stato: {s.status_text}"]
        if info.meter_model_id:
            lines.append(f"Contatore {c.meter_index}: {info.meter_name} · rete {s.grid_w:+.0f} W · consumo {s.load_w:.0f} W"
                         if s.grid_w is not None else f"Contatore {c.meter_index}: {info.meter_name} (nessuna lettura)")
        elif c.use_meter:
            lines.append("Nessun contatore trovato: " + "; ".join(info.notes))
        self.done.emit(True, "\n".join(lines))
