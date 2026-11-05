"""Built-in SolarEdge HD-Wave simulator: a real Modbus TCP server (SunSpec map) with a synthetic sunny day.

`solardeck --sim` starts it on 127.0.0.1 and connects to it, so the whole stack (client, decoding, charts)
can be tried without an inverter.
"""
from __future__ import annotations

import math
import socket
import socketserver
import struct
import threading
import time
from typing import Optional

from .config import METER_BASE
from .modbus import METER_MODEL_OFF

SUNRISE, SUNSET = 6.3, 19.2             # hours (summer day at ~42°N)
PEAK_W = 5600.0
INV_EFF = 0.975


def _clouds(t: float) -> float:
    """Deterministic cloud factor in [0.25, 1] (sum of incommensurate sines), t = seconds."""
    v = 0.55 * math.sin(t / 5400.0) + 0.3 * math.sin(t / 1300.0 + 1.3) + 0.15 * math.sin(t / 310.0 + 0.4)
    k = 0.5 + 0.5 * v
    return 0.25 + 0.75 * (k ** 0.6 if k > 0 else 0.0)


def pv_power(hour: float, t: float) -> float:
    """DC power of the array at a given hour of the day."""
    if hour <= SUNRISE or hour >= SUNSET:
        return 0.0
    x = math.sin(math.pi * (hour - SUNRISE) / (SUNSET - SUNRISE))
    return PEAK_W * (x ** 1.25) * _clouds(t)


def load_power(hour: float, t: float) -> float:
    """House consumption: base load + meals + evening peak + appliance spikes."""
    def bump(c, w, a):
        return a * math.exp(-((hour - c) / w) ** 2)
    base = 320 + bump(7.5, 0.7, 700) + bump(13.0, 0.9, 900) + bump(20.5, 1.6, 1500)
    spikes = max(0.0, math.sin(t / 2600.0) * math.sin(t / 900.0 + 2.0)) ** 2 * 1600
    return base + spikes


class SimClock:
    """Maps real time to a simulated time of day (start_hour is the hour of the day at the first call)."""

    def __init__(self, start_hour: Optional[float] = None):
        now = time.time()
        lt = time.localtime(now)
        real_hour = lt.tm_hour + lt.tm_min / 60 + lt.tm_sec / 3600
        self.offset = 0.0 if start_hour is None else ((start_hour - real_hour) * 3600.0)

    def sim_ts(self, ts: float) -> float:
        return ts + self.offset

    def hour(self, ts: float) -> float:
        lt = time.localtime(self.sim_ts(ts))
        return lt.tm_hour + lt.tm_min / 60 + lt.tm_sec / 3600


def synthetic_history(clock: SimClock, hours: float = 36.0, step: float = 30.0, with_meter: bool = True) -> list[tuple]:
    """Past `hours` of the simulated plant as history points (ts, pv, load, grid)."""
    now = time.time()
    out = []
    t = now - hours * 3600
    while t < now:
        st = clock.sim_ts(t)
        pv = pv_power(clock.hour(t), st) * INV_EFF
        ld = load_power(clock.hour(t), st) if with_meter else None
        out.append((t, pv, ld, (pv - ld) if with_meter else None))
        t += step
    return out


def _s16(v: float) -> int:
    return int(round(v)) & 0xFFFF


def _put_str(regs: dict, addr: int, text: str, n: int) -> None:
    b = text.encode("ascii")[: n * 2].ljust(n * 2, b"\x00")
    for i in range(n):
        regs[addr + i] = struct.unpack(">H", b[2 * i: 2 * i + 2])[0]


class SimulatedSolarEdge:
    def __init__(self, port: int = 0, start_hour: Optional[float] = None, with_meter: bool = True,
                 three_phase: bool = True, meter_index: int = 1, grid_positive_export: bool = True):
        self.clock = SimClock(start_hour)
        self.with_meter = with_meter
        self.three_phase = three_phase
        self.meter_index = meter_index
        self.export_positive = grid_positive_export
        self.fail_next = 0                  # test hook: drop this many connections
        self.requests = 0
        self._e_total = 12_345_000.0        # Wh counters, advanced by real elapsed time
        self._e_exp = 4_200_000.0
        self._e_imp = 3_100_000.0
        self._last = time.time()
        self._lock = threading.Lock()
        self._clients: set[socket.socket] = set()
        outer = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                outer._serve(self.request)

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._srv = Server(("127.0.0.1", port), Handler)
        self.port = self._srv.server_address[1]
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def start(self) -> "SimulatedSolarEdge":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._srv.shutdown()
        self._srv.server_close()
        with self._lock:                    # like a powered-off inverter: established sessions drop too
            clients, self._clients = list(self._clients), set()
        for c in clients:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            c.close()

    # ------------------------------------------------------------------ register map
    def _build(self) -> dict[int, int]:
        now = time.time()
        with self._lock:
            dt = now - self._last
            self._last = now
            st = self.clock.sim_ts(now)
            hr = self.clock.hour(now)
            dc = pv_power(hr, st)
            ac = dc * INV_EFF
            ld = load_power(hr, st)
            grid = ac - ld
            self._e_total += ac * dt / 3600
            if grid >= 0:
                self._e_exp += grid * dt / 3600
            else:
                self._e_imp += -grid * dt / 3600
            e_total, e_exp, e_imp = int(self._e_total), int(self._e_exp), int(self._e_imp)
        r: dict[int, int] = {}
        r[40000], r[40001] = 0x5375, 0x6E53
        r[40002], r[40003] = 1, 65
        _put_str(r, 40004, "SolarEdge", 16)
        _put_str(r, 40020, "SE6000H-RWB48BNN4" if not self.three_phase else "SE10K-RWB48BNN4", 16)
        _put_str(r, 40044, "0004.0019.0529", 8)
        _put_str(r, 40052, "7E123456-A1", 16)
        r[40068] = 1
        mid = 103 if self.three_phase else 101
        r[40069], r[40070] = mid, 50
        vac = 230.0 + 2.5 * math.sin(st / 900.0)
        amps = (ac / (vac * (3 if self.three_phase else 1))) if vac else 0.0
        r[40072] = _s16(amps * 100)
        r[40073] = _s16(amps * 100) if self.three_phase else 0xFFFF
        r[40074] = _s16(amps * 100) if self.three_phase else 0xFFFF
        r[40071] = _s16(amps * (3 if self.three_phase else 1) * 100)
        r[40075] = _s16(-2)
        for a in (40076, 40077, 40078):
            r[a] = _s16(vac * 1.732 * 10) if self.three_phase else 0xFFFF
        for a in (40079, 40080, 40081):
            r[a] = _s16(vac * 10) if (a == 40079 or self.three_phase) else 0xFFFF
        r[40082] = _s16(-1)
        r[40083], r[40084] = _s16(ac), 0
        r[40085], r[40086] = _s16(5000 + 8 * math.sin(st / 40)), _s16(-2)
        r[40087], r[40088] = _s16(ac * 1.02), 0
        r[40089], r[40090] = _s16(ac * 0.05), 0
        r[40091], r[40092] = _s16(998), _s16(-3)
        r[40093], r[40094], r[40095] = (e_total >> 16) & 0xFFFF, e_total & 0xFFFF, 0
        dcv = 0.0 if dc <= 0 else 380 + 25 * (dc / PEAK_W)
        r[40096], r[40097] = _s16((dc / dcv * 100) if dcv else 0), _s16(-2)
        r[40098], r[40099] = _s16(dcv * 10), _s16(-1)
        r[40100], r[40101] = _s16(dc), 0
        r[40102] = 0x8000
        r[40103] = _s16((24 + 22 * dc / PEAK_W) * 100)
        r[40104] = r[40105] = 0x8000
        r[40106] = _s16(-2)
        r[40107], r[40108] = (4 if dc > 30 else 2), 0
        if self.with_meter:
            base = METER_BASE[self.meter_index]
            r[base], r[base + 1] = 1, 65
            _put_str(r, base + 2, "WattNode", 16)
            _put_str(r, base + 18, "WND-3Y-400-MB", 16)
            _put_str(r, base + 50, "MTR-123456", 16)
            m = base + METER_MODEL_OFF
            r[m], r[m + 1] = 203, 105
            mw = grid if self.export_positive else -grid
            r[m + 18] = _s16(mw)
            for i in range(3):
                r[m + 19 + i] = _s16(mw / 3)
            r[m + 22] = 0
            r[m + 6] = 0
            r[m + 16], r[m + 17] = _s16(5000), _s16(-2)
            exp, imp = (e_exp, e_imp) if self.export_positive else (e_imp, e_exp)
            r[m + 38], r[m + 39] = (exp >> 16) & 0xFFFF, exp & 0xFFFF
            r[m + 46], r[m + 47] = (imp >> 16) & 0xFFFF, imp & 0xFFFF
            r[m + 54] = 0
        return r

    # ------------------------------------------------------------------ Modbus TCP
    def _serve(self, sock: socket.socket) -> None:
        sock.settimeout(30)
        with self._lock:
            self._clients.add(sock)
        if self.fail_next > 0:
            self.fail_next -= 1
            return
        try:
            while True:
                hdr = self._recv(sock, 7)
                tid, proto, length, unit = struct.unpack(">HHHB", hdr)
                pdu = self._recv(sock, length - 1)
                self.requests += 1
                fc = pdu[0]
                if fc != 3 or len(pdu) < 5:
                    resp = bytes([fc | 0x80, 1])
                else:
                    addr, cnt = struct.unpack(">HH", pdu[1:5])
                    regs = self._build()
                    if not 1 <= cnt <= 125 or addr < 40000 or addr + cnt > 40700:
                        resp = bytes([0x83, 2])
                    else:
                        vals = [regs.get(a, 0) for a in range(addr, addr + cnt)]
                        resp = struct.pack(f">BB{cnt}H", 3, cnt * 2, *vals)
                sock.sendall(struct.pack(">HHHB", tid, 0, len(resp) + 1, unit) + resp)
        except (OSError, ConnectionError, struct.error):
            return

    @staticmethod
    def _recv(sock: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            c = sock.recv(n - len(buf))
            if not c:
                raise ConnectionError
            buf += c
        return buf
