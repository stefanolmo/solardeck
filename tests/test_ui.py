import time

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from solardeck import simulator, theme
from solardeck.chartview import nice_ceiling
from solardeck.config import Config
from solardeck.flowview import FlowView
from solardeck.mainwindow import MainWindow
from solardeck.modbus import Sample
from solardeck.settings_dialog import SettingsDialog
from solardeck.splash import SplashScreen


def pump(cond, timeout=15.0):
    app = QApplication.instance()
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.STYLESHEET)
    return a


@pytest.fixture
def sim():
    s = simulator.SimulatedSolarEdge(start_hour=12.5).start()
    yield s
    s.stop()


@pytest.fixture
def win(app, sim, tmp_path):
    w = MainWindow(qs=QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat), sim=sim)
    w.show()
    assert pump(lambda: w.last is not None)
    yield w
    w.close()


def test_sim_window_shows_live_data(win):
    s = win.last
    assert win.state == "online" and win.badge.text() == "Simulatore"
    assert 0 < s.pv_w and s.load_w is not None
    assert win.inv.values["ac"].text() != "—"
    assert win.inv.values["model"].text().startswith("SE")
    assert win.history.points and win.history.points[-1][0] >= win.history.points[0][0]
    assert win.today.values["produced"].text().endswith("kWh")
    assert 0 <= win.bar_self.value() <= 100 and 0 <= win.bar_auto.value() <= 100
    img = win.grab()                                  # full paint of flow + chart must not raise
    assert img.width() > 800


def test_flow_balance_and_directions(app):
    f = FlowView()
    f.set_sample(Sample(pv_w=4000, load_w=1000, grid_w=3000))
    fl = f.flows()
    assert fl["export"] == 3000 and fl["import"] == 0 and fl["to_house_from_pv"] == 1000
    f.set_sample(Sample(pv_w=0, load_w=800, grid_w=-800))
    fl = f.flows()
    assert fl["import"] == 800 and fl["export"] == 0 and fl["to_house_from_pv"] == 0
    f.set_sample(Sample(pv_w=1500), online=True)       # no meter
    assert f.flows()["load"] is None
    f.set_sample(Sample(pv_w=1500), online=False)      # offline: nothing flows
    assert f.flows()["pv"] == 0
    f.resize(900, 420)
    f.grab()


def test_chart_ranges_and_hover(app, win):
    c = win.chart
    for h in (1, 6, 12, 24, 48, 0):
        win.set_chart_range(h)
        c.resize(900, 220)
        c.grab()
    assert win.range_btns[0].isChecked()
    c.show_grid = True
    c.grab()
    c._hover = time.time() - 600
    c.update()
    c.grab()
    assert c.nearest(time.time() - 600) is not None


def test_nice_ceiling():
    assert nice_ceiling(0) == 1000
    assert nice_ceiling(5300) == 6000 and nice_ceiling(950) == 1000 and nice_ceiling(10_001) == 15_000


def test_legend_toggle(win):
    win.legend_btns["load"].setChecked(False)
    assert not win.chart.show_load
    win.legend_btns["load"].setChecked(True)


def test_disconnect_and_reconnect(win):
    win.toggle_connection()
    assert win.poller is None and win.badge.text() == "Non connesso"
    win.toggle_connection()
    assert pump(lambda: win.state == "online")


def test_offline_then_recovery(app, tmp_path):
    srv = simulator.SimulatedSolarEdge(start_hour=12).start()
    port = srv.port
    qs = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    Config(host="127.0.0.1", port=port, timeout=0.5, poll_interval=1, auto_connect=True).save(qs)
    w = MainWindow(qs=qs, history_path=":memory:")
    w.show()
    try:
        assert pump(lambda: w.last is not None)
        srv.stop()                                      # inverter disappears
        assert pump(lambda: w.state == "offline", 10)
        assert w.badge.text() == "Nessuna risposta"
        assert w.flow.online is False                   # diagram stops animating stale values
        srv2 = simulator.SimulatedSolarEdge(port=port, start_hour=12).start()
        try:
            assert pump(lambda: w.state == "online", 40)
        finally:
            srv2.stop()
    finally:
        w.close()


def test_settings_dialog_roundtrip_and_apply(app, win, sim):
    dlg = SettingsDialog(win.cfg, win, simulated=True)
    dlg.peak.setValue(8.5)
    dlg.range.setCurrentIndex(dlg.range.findData(6))
    dlg.pos_export.setCurrentIndex(1)
    dlg.splash.setChecked(False)
    c = dlg.result_config()
    assert c.peak_kwp == 8.5 and c.chart_range_h == 6 and c.grid_positive_export is False and c.show_splash is False
    win.apply_config(c)
    assert win.flow.peak_w == 8500 and win.range_btns[6].isChecked()
    # simulator mode keeps its own connection parameters and never touches the saved connection settings
    assert win.cfg.port == sim.port and win.cfg.grid_positive_export is True
    assert not win.qs.contains("host")


def test_settings_dialog_connection_test(app, sim):
    cfg = Config(host="127.0.0.1", port=sim.port, timeout=2.0)
    dlg = SettingsDialog(cfg)
    dlg._test()
    assert pump(lambda: dlg.btn_test.isEnabled())
    assert dlg.probe_out.text().startswith("✔") and "SolarEdge" in dlg.probe_out.text() and "Contatore 1" in dlg.probe_out.text()
    dlg.port.setValue(1)
    dlg._test()
    assert pump(lambda: dlg.btn_test.isEnabled())
    assert dlg.probe_out.text().startswith("✘")
    dlg.host.setText("   ")
    dlg._accept()
    assert dlg.result() == 0                              # empty host is rejected


def test_apply_real_config_persists_and_reconnects(app, sim, tmp_path):
    qs = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    Config(host="127.0.0.1", port=sim.port, timeout=1.0, poll_interval=1, auto_connect=False).save(qs)
    w = MainWindow(qs=qs, history_path=str(tmp_path / "hist.csv"))
    w.show()
    try:
        assert w.poller is None
        w.connect_inverter()
        assert pump(lambda: w.last is not None)
        new = Config(**{**w.cfg.__dict__, "poll_interval": 2.0, "peak_kwp": 3.3})
        w.apply_config(new)
        assert pump(lambda: w.state == "online" and w.poller is not None)
        assert w.poller.cfg.poll_interval == 2.0
        assert Config().load(qs).peak_kwp == 3.3
    finally:
        w.close()
    assert (tmp_path / "hist.csv").exists()


def test_splash_paints_all_phases(app):
    s = SplashScreen("0.1.0")
    done = []
    s.finished.connect(lambda: done.append(1))
    s.show()
    for ms in (0, 400, 1500, 2300, 2900):
        s.set_time(ms)
        s.grab()
    s.close()
