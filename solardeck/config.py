"""Application settings (persisted with QSettings) as a plain dataclass."""
from __future__ import annotations

from dataclasses import dataclass, fields

ORG = "solardeck"
APP = "solardeck"

# SunSpec meter blocks: the common block of meter N starts at METER_BASE[N]; its model block 67 registers later.
METER_BASE = {1: 40121, 2: 40295, 3: 40469}


@dataclass
class Config:
    # connection
    host: str = "192.168.1.100"
    port: int = 1502                # SolarEdge default Modbus TCP port (enable it in the inverter menu)
    unit: int = 1                   # Modbus unit/slave id
    timeout: float = 3.0            # seconds
    poll_interval: float = 5.0      # seconds between reads
    auto_connect: bool = True
    # meter
    use_meter: bool = True          # Export+Import meter: needed for consumption and feed-in/withdrawal
    meter_index: int = 1            # 1..3
    grid_positive_export: bool = True   # SolarEdge meters report + when exporting; untick if your values are inverted
    # plant
    peak_kwp: float = 6.0           # installed PV power: full scale of the panel gauge
    inverter_kw: float = 6.0        # inverter rated AC power
    # display / history
    show_splash: bool = True
    chart_range_h: int = 24         # default chart span (hours); 0 = since midnight
    history_days: int = 14          # how long samples are kept on disk
    log_interval: float = 10.0      # seconds between samples written to history
    smooth_flow: bool = True        # animated energy-flow dots

    # ------------------------------------------------------------------
    def meter_base(self) -> int:
        return METER_BASE.get(self.meter_index, METER_BASE[1])

    def load(self, qs) -> "Config":
        for f in fields(self):
            if not qs.contains(f.name):
                continue
            v = qs.value(f.name)
            cur = getattr(self, f.name)
            try:
                if isinstance(cur, bool):
                    v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")
                elif isinstance(cur, int):
                    v = int(float(v))
                elif isinstance(cur, float):
                    v = float(v)
                else:
                    v = str(v)
            except (TypeError, ValueError):
                continue
            setattr(self, f.name, v)
        return self

    def save(self, qs) -> None:
        for f in fields(self):
            qs.setValue(f.name, getattr(self, f.name))
        qs.sync()
