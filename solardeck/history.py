"""Sample history: in-memory ring + CSV file on disk, and energy integration (kWh)."""
from __future__ import annotations

import csv
import os
import time
from datetime import datetime
from typing import Iterable, Optional

from .modbus import Sample

MAX_GAP_S = 120.0       # gaps longer than this (app closed, inverter offline) are not integrated


def midnight(ts: float) -> float:
    d = datetime.fromtimestamp(ts)
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class History:
    def __init__(self, path: Optional[str] = None, keep_days: int = 14, interval: float = 10.0):
        self.path = path
        self.keep_days = keep_days
        self.interval = interval
        self.points: list[tuple] = []                 # (ts, pv_w, load_w|None, grid_w|None) ordered by ts
        self._last_logged = 0.0
        if path:
            self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        cutoff = time.time() - self.keep_days * 86400
        pts = []
        try:
            with open(self.path, newline="") as fh:
                for row in csv.reader(fh):
                    try:
                        ts = float(row[0])
                    except (ValueError, IndexError):
                        continue                       # header or corrupt line
                    if ts < cutoff:
                        continue
                    pts.append((ts, float(row[1]), _opt(row[2]), _opt(row[3])))
        except OSError:
            return
        pts.sort(key=lambda p: p[0])
        self.points = pts
        if pts:
            self._last_logged = pts[-1][0]
        try:                                           # rewrite the file without the expired lines
            with open(self.path, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["ts", "pv_w", "load_w", "grid_w"])
                for p in pts:
                    w.writerow(_row(p))
        except OSError:
            pass

    def add(self, s: Sample, force: bool = False) -> bool:
        """Store a sample if `interval` seconds have passed since the previous one. Returns True if stored."""
        if not force and s.ts - self._last_logged < self.interval:
            return False
        p = (s.ts, s.pv_w, s.load_w, s.grid_w)
        self.points.append(p)
        self._last_logged = s.ts
        if self.path:
            try:
                new = not os.path.exists(self.path) or os.path.getsize(self.path) == 0
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, "a", newline="") as fh:
                    w = csv.writer(fh)
                    if new:
                        w.writerow(["ts", "pv_w", "load_w", "grid_w"])
                    w.writerow(_row(p))
            except OSError:
                pass
        horizon = s.ts - self.keep_days * 86400       # keep memory bounded
        if self.points and self.points[0][0] < horizon:
            self.points = [q for q in self.points if q[0] >= horizon]
        return True

    def extend(self, pts: Iterable[tuple]) -> None:
        """Bulk insert without writing to disk (simulator seed)."""
        self.points = sorted(list(self.points) + list(pts), key=lambda p: p[0])

    def since(self, t0: float) -> list[tuple]:
        # points are ordered: bisect on ts
        lo, hi = 0, len(self.points)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.points[mid][0] < t0:
                lo = mid + 1
            else:
                hi = mid
        return self.points[lo:]

    # ------------------------------------------------------------------ energy
    def energy_since(self, t0: float, t1: Optional[float] = None) -> dict:
        """Trapezoidal integration of the power curves. Returns kWh: produced, consumed, exported, imported."""
        t1 = t1 if t1 is not None else time.time()
        pts = [p for p in self.since(t0) if p[0] <= t1]
        out = {"produced": 0.0, "consumed": 0.0, "exported": 0.0, "imported": 0.0, "has_meter": False}
        for a, b in zip(pts, pts[1:]):
            dt = b[0] - a[0]
            if dt <= 0 or dt > MAX_GAP_S:
                continue
            h = dt / 3600.0
            out["produced"] += (a[1] + b[1]) / 2 * h
            if a[2] is not None and b[2] is not None:
                out["has_meter"] = True
                out["consumed"] += (a[2] + b[2]) / 2 * h
            if a[3] is not None and b[3] is not None:
                ga, gb = a[3], b[3]
                out["exported"] += (max(ga, 0) + max(gb, 0)) / 2 * h
                out["imported"] += (max(-ga, 0) + max(-gb, 0)) / 2 * h
        for k in ("produced", "consumed", "exported", "imported"):
            out[k] /= 1000.0
        return out


def _opt(x: str) -> Optional[float]:
    return float(x) if x not in ("", "None") else None


def _row(p: tuple) -> list:
    return [f"{p[0]:.1f}", f"{p[1]:.1f}", "" if p[2] is None else f"{p[2]:.1f}", "" if p[3] is None else f"{p[3]:.1f}"]
