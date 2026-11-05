"""Minimal Modbus TCP client (function 3) and SunSpec decoding for SolarEdge inverters / meters.

SolarEdge HD-Wave register map (SunSpec, 0-based protocol addresses as printed in the SolarEdge documentation):

    40000        "SunS" marker (2 regs)
    40002..40068 common block: manufacturer, model, version, serial number
    40069        inverter model id (101 single phase / 102 split phase / 103 three phase), 40070 length
    40071..      inverter data (AC current/voltage/power, frequency, energy counter, DC, temperature, status)
    40121..      meter 1 common block, meter model (201..204) at 40188
"""
from __future__ import annotations

import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Optional

from .config import Config

SUNS = 0x53756E53                   # "SunS"
INV_BASE = 40069                    # inverter model id register
METER_MODEL_OFF = 67                # meter model block starts this many registers after its common block
INVERTER_MODELS = (101, 102, 103)
METER_MODELS = (201, 202, 203, 204)
NOT_IMPL_S16, NOT_IMPL_U16, NOT_IMPL_U32 = -32768, 0xFFFF, 0xFFFFFFFF

INVERTER_STATUS = {1: "Spento", 2: "In standby (notte)", 3: "Avvio", 4: "In produzione", 5: "Produzione limitata",
                   6: "Spegnimento", 7: "Guasto", 8: "Standby"}


class ModbusError(Exception):
    pass


class ModbusTcpClient:
    """Blocking Modbus TCP master. One request in flight at a time (SolarEdge accepts a single connection)."""

    def __init__(self, host: str, port: int = 1502, unit: int = 1, timeout: float = 3.0):
        self.host, self.port, self.unit, self.timeout = host, int(port), int(unit), float(timeout)
        self._sock: Optional[socket.socket] = None
        self._tid = 0

    # ---------------------------------------------------------------- connection
    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        self.close()
        try:
            s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise ModbusError(f"cannot connect to {self.host}:{self.port} ({e.strerror or e})") from e
        s.settimeout(self.timeout)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = s

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            try:
                chunk = self._sock.recv(n - len(buf))
            except socket.timeout as e:
                raise ModbusError("timeout waiting for the inverter") from e
            except OSError as e:
                raise ModbusError(f"connection error ({e.strerror or e})") from e
            if not chunk:
                raise ModbusError("connection closed by the inverter")
            buf += chunk
        return buf

    # ---------------------------------------------------------------- function 3
    def read_registers(self, address: int, count: int) -> list[int]:
        if self._sock is None:
            raise ModbusError("not connected")
        out: list[int] = []
        while count > 0:                                  # Modbus limit: 125 registers per request
            n = min(count, 125)
            out += self._read_chunk(address, n)
            address += n
            count -= n
        return out

    def _read_chunk(self, address: int, count: int) -> list[int]:
        self._tid = (self._tid + 1) & 0xFFFF
        pdu = struct.pack(">BHH", 3, address, count)
        req = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, self.unit) + pdu
        try:
            self._sock.sendall(req)
        except OSError as e:
            self.close()
            raise ModbusError(f"connection error ({e.strerror or e})") from e
        try:
            hdr = self._recv_exact(7)
            tid, proto, length, _unit = struct.unpack(">HHHB", hdr)
            if proto != 0 or length < 2 or length > 260:
                raise ModbusError("invalid Modbus TCP response")
            body = self._recv_exact(length - 1)
        except ModbusError:
            self.close()                                  # stream may be desynchronised: reconnect next time
            raise
        if tid != self._tid:
            self.close()
            raise ModbusError("mismatched transaction id")
        fc = body[0]
        if fc & 0x80:
            code = body[1] if len(body) > 1 else 0
            names = {1: "illegal function", 2: "illegal data address", 3: "illegal data value",
                     4: "device failure", 6: "device busy"}
            raise ModbusError(f"Modbus exception {code}: {names.get(code, 'unknown')} (reg {address})")
        if fc != 3 or len(body) < 2 or body[1] != count * 2 or len(body) < 2 + count * 2:
            self.close()
            raise ModbusError("malformed read response")
        return list(struct.unpack(f">{count}H", body[2:2 + count * 2]))


# ---------------------------------------------------------------------------- decoding helpers
def s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def u32(hi: int, lo: int) -> int:
    return (hi << 16) | lo


def scaled(raw: int, sf: int, signed: bool = True) -> Optional[float]:
    """Apply a SunSpec scale factor; None when the register is 'not implemented'."""
    if signed:
        raw = s16(raw)
        if raw == NOT_IMPL_S16:
            return None
    elif raw == NOT_IMPL_U16:
        return None
    sf = s16(sf)
    if sf == NOT_IMPL_S16 or not -10 <= sf <= 10:
        return None
    return raw * (10.0 ** sf)


def scaled_acc32(hi: int, lo: int, sf: int) -> Optional[float]:
    v = u32(hi, lo)
    sf = s16(sf)
    if v == NOT_IMPL_U32 or sf == NOT_IMPL_S16 or not -10 <= sf <= 10:
        return None
    return v * (10.0 ** sf)


def regs_to_str(regs: list[int]) -> str:
    b = b"".join(struct.pack(">H", r) for r in regs)
    return b.split(b"\x00", 1)[0].decode("ascii", "replace").strip()


# ---------------------------------------------------------------------------- data
@dataclass
class Sample:
    ts: float = 0.0
    pv_w: float = 0.0                 # AC power produced by the inverter
    dc_w: Optional[float] = None      # DC power from the panels
    grid_w: Optional[float] = None    # + export to the grid / - import from the grid (None without meter)
    load_w: Optional[float] = None    # house consumption (None without meter)
    ac_v: Optional[float] = None
    ac_a: Optional[float] = None
    hz: Optional[float] = None
    dc_v: Optional[float] = None
    temp_c: Optional[float] = None
    status: int = 0
    status_text: str = ""
    e_total_wh: Optional[float] = None    # inverter lifetime production
    e_export_wh: Optional[float] = None   # meter lifetime export
    e_import_wh: Optional[float] = None   # meter lifetime import


@dataclass
class DeviceInfo:
    manufacturer: str = ""
    model: str = ""
    version: str = ""
    serial: str = ""
    inverter_model_id: int = 0
    phases: int = 1
    meter_model_id: int = 0           # 0 = no meter found
    meter_name: str = ""
    notes: list[str] = field(default_factory=list)


def identify(cli: ModbusTcpClient, cfg: Config) -> DeviceInfo:
    """Check the SunSpec marker, read the common block and look for the inverter and meter models."""
    head = cli.read_registers(40000, 2)
    if u32(head[0], head[1]) != SUNS:
        raise ModbusError("no SunSpec marker at register 40000: is this a SolarEdge inverter with Modbus TCP enabled?")
    c = cli.read_registers(40002, 67)             # common block header (2) + 65 registers of data
    info = DeviceInfo(manufacturer=regs_to_str(c[2:18]), model=regs_to_str(c[18:34]),
                      version=regs_to_str(c[42:50]), serial=regs_to_str(c[50:66]))
    mid = cli.read_registers(INV_BASE, 1)[0]
    if mid not in INVERTER_MODELS:
        raise ModbusError(f"unexpected inverter SunSpec model {mid} (expected 101/102/103)")
    info.inverter_model_id = mid
    info.phases = 3 if mid == 103 else 1
    if cfg.use_meter:
        try:
            cid = cli.read_registers(cfg.meter_base(), 1)[0]
            m = cli.read_registers(cfg.meter_base() + METER_MODEL_OFF, 1)[0] if cid == 1 else 0
        except ModbusError as e:
            m = 0
            info.notes.append(f"meter {cfg.meter_index} not readable: {e}")
        if m in METER_MODELS:
            info.meter_model_id = m
            info.meter_name = {201: "single phase", 202: "split phase", 203: "three phase", 204: "three phase (wye)"}[m]
        else:
            info.notes.append(f"no meter found as meter {cfg.meter_index}: consumption and feed-in will not be shown")
    return info


def read_sample(cli: ModbusTcpClient, cfg: Config, info: DeviceInfo) -> Sample:
    """One poll: inverter block (and meter block when present) -> Sample."""
    r = cli.read_registers(INV_BASE, 40)          # model id .. St_Vnd
    g = lambda reg: r[reg - INV_BASE]             # noqa: E731  (absolute register -> value)
    s = Sample(ts=time.time())
    w = scaled(g(40083), g(40084))
    s.pv_w = max(0.0, w) if w is not None else 0.0
    s.dc_w = scaled(g(40100), g(40101))
    if s.dc_w is not None:
        s.dc_w = max(0.0, s.dc_w)
    s.ac_a = scaled(g(40072), g(40075), signed=False)
    s.ac_v = scaled(g(40079), g(40082), signed=False)        # phase A to neutral
    s.hz = scaled(g(40085), g(40086), signed=False)
    s.dc_v = scaled(g(40098), g(40099), signed=False)
    s.temp_c = scaled(g(40103), g(40106))         # heat sink temperature
    s.status = g(40107)
    s.status_text = INVERTER_STATUS.get(s.status, f"Status {s.status}")
    s.e_total_wh = scaled_acc32(g(40093), g(40094), g(40095))
    if info.meter_model_id:
        base = cfg.meter_base() + METER_MODEL_OFF
        m = cli.read_registers(base, 56)          # id .. Wh_SF
        mw = scaled(m[18], m[22])
        if mw is not None:
            export_pos = cfg.grid_positive_export
            s.grid_w = mw if export_pos else -mw
            s.load_w = max(0.0, s.pv_w - s.grid_w)
        exp = scaled_acc32(m[38], m[39], m[54])
        imp = scaled_acc32(m[46], m[47], m[54])
        if cfg.grid_positive_export:
            s.e_export_wh, s.e_import_wh = exp, imp
        else:
            s.e_export_wh, s.e_import_wh = imp, exp
    return s
