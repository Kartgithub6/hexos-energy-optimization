"""Gas boiler: fuel -> heat, costed at its own fuel price."""
import pytest
from engine import make_data, build_model, solve, extract_results
from helpers import base_cfg


def test_gas_boiler_supplies_heat():
    c = base_cfg()
    c["gas_boiler"] = {"q_max": 500.0, "eta": 0.9, "fuel_price": 0.05}
    data = make_data([0], [0.30], [0.0], [0.0], [0.0], [45.0], cop=3.0)
    m = build_model(data, c); solve(m); r = extract_results(m)
    assert r["gas_heat"][0] == pytest.approx(45.0, abs=1e-3)
    assert r["gas_fuel"][0] == pytest.approx(50.0, abs=1e-3)   # 45/0.9
    assert r["cost"] == pytest.approx(2.5, abs=1e-3)           # 50*0.05


def test_cheaper_boiler_wins():
    # Woodchip (0.03 fuel, eta 0.9 -> 0.0333/kWh-heat) vs gas (0.06 fuel, eta 0.9
    # -> 0.0667/kWh-heat). Woodchip is cheaper, so it serves the heat.
    c = base_cfg()
    c["woodchip"] = {"q_max": 500.0, "eta": 0.9, "fuel_price": 0.03}
    c["gas_boiler"] = {"q_max": 500.0, "eta": 0.9, "fuel_price": 0.06}
    data = make_data([0], [0.30], [0.0], [0.0], [0.0], [60.0], cop=3.0)
    m = build_model(data, c); solve(m); r = extract_results(m)
    assert r["wood_heat"][0] == pytest.approx(60.0, abs=1e-3)
    assert r["gas_heat"][0] == pytest.approx(0.0, abs=1e-3)
