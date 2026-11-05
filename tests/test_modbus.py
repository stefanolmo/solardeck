import pytest

from solardeck import modbus, simulator
from solardeck.config import Config
from solardeck.modbus import ModbusError, ModbusTcpClient


@pytest.fixture
def sim():
    s = simulator.SimulatedSolarEdge(start_hour=12.5).start()
    yield s
    s.stop()


def make(sim, **kw):
    cfg = Config(host="127.0.0.1", port=sim.port, **kw)
    cli = ModbusTcpClient(cfg.host, cfg.port, cfg.unit, 2.0)
    cli.connect()
    return cfg, cli


def test_scale_and_decode_helpers():
    assert modbus.scaled(1234, 0xFFFE) == pytest.approx(12.34)          # SF -2
    assert modbus.scaled(0x8000, 0) is None                              # int16 "not implemented"
    assert modbus.scaled(0xFFFF, 0, signed=False) is None
    assert modbus.scaled(65535, 0) == -1                                 # signed
    assert modbus.scaled(10, 0x8000) is None                             # scale factor not implemented
    assert modbus.scaled_acc32(0x0001, 0x0000, 0) == 65536
    assert modbus.scaled_acc32(0xFFFF, 0xFFFF, 0) is None
    assert modbus.regs_to_str([0x536F, 0x6C61, 0x7200, 0]) == "Solar"


def test_identify_three_phase_with_meter(sim):
    cfg, cli = make(sim)
    info = modbus.identify(cli, cfg)
    assert info.manufacturer == "SolarEdge"
    assert info.inverter_model_id == 103 and info.phases == 3
    assert info.meter_model_id == 203
    assert info.serial.startswith("7E")


def test_read_sample_matches_the_physics(sim):
    cfg, cli = make(sim)
    info = modbus.identify(cli, cfg)
    s = modbus.read_sample(cli, cfg, info)
    assert 0 < s.pv_w < simulator.PEAK_W
    assert s.dc_w > s.pv_w                                               # inverter efficiency < 1
    assert s.grid_w is not None and s.load_w is not None
    assert s.load_w == pytest.approx(s.pv_w - s.grid_w, abs=1.0)
    assert 225 < s.ac_v < 235 and 49.5 < s.hz < 50.5
    assert s.status_text == "In produzione"
    assert s.e_total_wh > 1e7 and s.e_export_wh > 1e6 and s.e_import_wh > 1e6


def test_grid_sign_inversion(sim):
    cfg, cli = make(sim)
    info = modbus.identify(cli, cfg)
    a = modbus.read_sample(cli, cfg, info)
    cfg.grid_positive_export = False        # simulator still reports + = export: inverted view must flip
    b = modbus.read_sample(cli, cfg, info)
    assert a.grid_w * b.grid_w < 0 or abs(a.grid_w) < 5
    assert b.e_export_wh == pytest.approx(a.e_import_wh, rel=1e-3)


def test_night_no_production():
    s = simulator.SimulatedSolarEdge(start_hour=2.0).start()
    try:
        cfg, cli = make(s)
        info = modbus.identify(cli, cfg)
        smp = modbus.read_sample(cli, cfg, info)
        assert smp.pv_w == 0 and smp.status_text == "In standby (notte)"
        assert smp.grid_w < 0 and smp.load_w > 100                      # importing at night
    finally:
        s.stop()


def test_no_meter():
    s = simulator.SimulatedSolarEdge(start_hour=12, with_meter=False, three_phase=False).start()
    try:
        cfg, cli = make(s)
        info = modbus.identify(cli, cfg)
        assert info.phases == 1 and info.meter_model_id == 0 and info.notes
        smp = modbus.read_sample(cli, cfg, info)
        assert smp.grid_w is None and smp.load_w is None and smp.pv_w > 0
    finally:
        s.stop()


def test_meter_2_address():
    s = simulator.SimulatedSolarEdge(start_hour=12, meter_index=2).start()
    try:
        cfg, cli = make(s, meter_index=2)
        assert modbus.identify(cli, cfg).meter_model_id == 203
        cfg1 = Config(host="127.0.0.1", port=s.port, meter_index=1)
        assert modbus.identify(cli, cfg1).meter_model_id == 0
    finally:
        s.stop()


def test_errors(sim):
    cfg, cli = make(sim)
    with pytest.raises(ModbusError, match="exception 2"):
        cli.read_registers(100, 2)                                       # outside the map
    cli.close()
    with pytest.raises(ModbusError, match="not connected"):
        cli.read_registers(40000, 2)
    dead = ModbusTcpClient("127.0.0.1", 1, 1, 0.5)
    with pytest.raises(ModbusError, match="cannot connect"):
        dead.connect()


def test_not_a_solaredge():
    class Stub(ModbusTcpClient):
        def read_registers(self, a, n):
            return [0] * n
    with pytest.raises(ModbusError, match="SunSpec"):
        modbus.identify(Stub("x"), Config())


def test_reads_longer_than_125_registers_are_split(sim):
    cfg, cli = make(sim)
    regs = cli.read_registers(40000, 300)
    assert len(regs) == 300 and regs[0] == 0x5375
