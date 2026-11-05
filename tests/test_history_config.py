import time

import pytest
from PySide6.QtCore import QSettings

from solardeck.config import Config
from solardeck.history import History, midnight
from solardeck.modbus import Sample


def S(ts, pv, load=None, grid=None):
    return Sample(ts=ts, pv_w=pv, load_w=load, grid_w=grid)


def test_energy_integration_and_split(tmp_path):
    h = History(None, interval=0)
    t = 1_000_000.0
    # 1 hour, 1 sample/minute: 2 kW produced, 1 kW consumed, +1 kW exported then -1 kW imported
    for i in range(61):
        h.add(S(t + i * 60, 2000, 1000, 1000 if i <= 30 else -1000), force=True)
    e = h.energy_since(t, t + 3600)
    assert e["produced"] == pytest.approx(2.0, rel=1e-6)
    assert e["consumed"] == pytest.approx(1.0, rel=1e-6)
    assert e["exported"] == pytest.approx(0.5, abs=0.02)
    assert e["imported"] == pytest.approx(0.5, abs=0.02)
    assert e["has_meter"]


def test_gaps_are_not_integrated():
    h = History(None, interval=0)
    h.add(S(0, 1000), force=True)
    h.add(S(60, 1000), force=True)
    h.add(S(7200, 1000), force=True)        # app was closed for two hours
    h.add(S(7260, 1000), force=True)
    assert h.energy_since(0, 8000)["produced"] == pytest.approx(2 * 1000 / 60 / 1000, rel=1e-6)


def test_log_interval_and_persistence(tmp_path):
    path = str(tmp_path / "sub" / "h.csv")
    now = time.time()
    h = History(path, keep_days=1, interval=10)
    assert h.add(S(now - 100, 500, 300, 200))
    assert not h.add(S(now - 95, 510, 300, 210))          # inside the interval
    assert h.add(S(now - 80, 520, None, None))
    h2 = History(path, keep_days=1, interval=10)
    assert [p[1] for p in h2.points] == [500, 520]
    assert h2.points[1][2] is None and h2.points[0][3] == 200


def test_expired_and_corrupt_lines_are_dropped(tmp_path):
    path = tmp_path / "h.csv"
    now = time.time()
    path.write_text(f"ts,pv_w,load_w,grid_w\n{now - 5 * 86400},1,1,1\ngarbage\n{now - 10},5,,\n")
    h = History(str(path), keep_days=2)
    assert len(h.points) == 1 and h.points[0][1] == 5
    assert "garbage" not in path.read_text()


def test_since_is_ordered_and_bisect():
    h = History(None, interval=0)
    for i in range(100):
        h.add(S(i, i), force=True)
    assert [p[0] for p in h.since(95)] == [95, 96, 97, 98, 99]
    assert h.since(1000) == []


def test_midnight():
    m = midnight(time.time())
    assert m <= time.time() < m + 86400 + 3700


def test_config_roundtrip_types(tmp_path):
    qs = QSettings(str(tmp_path / "c.ini"), QSettings.IniFormat)
    c = Config(host="10.0.0.9", port=1503, grid_positive_export=False, peak_kwp=4.2, auto_connect=False, meter_index=2)
    c.save(qs)
    d = Config().load(QSettings(str(tmp_path / "c.ini"), QSettings.IniFormat))
    assert d == c
    assert isinstance(d.port, int) and isinstance(d.peak_kwp, float) and d.grid_positive_export is False


def test_config_ignores_garbage(tmp_path):
    qs = QSettings(str(tmp_path / "c.ini"), QSettings.IniFormat)
    qs.setValue("port", "abc")
    qs.setValue("host", "h")
    c = Config().load(qs)
    assert c.port == 1502 and c.host == "h"
    assert Config(meter_index=2).meter_base() == 40295 and Config(meter_index=9).meter_base() == 40121
