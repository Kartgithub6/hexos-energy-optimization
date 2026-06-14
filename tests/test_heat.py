"""
test_heat.py
============
Validation of the heat side and the sector coupling: heating rod, heat pump,
CHP, and thermal storage. Every case has a hand-checkable answer.
"""
import pytest
from engine import make_data, build_model, solve, extract_results, solve_rolling
from engine.postprocess.cop_variants import make_cop_variants
from helpers import base_cfg, mixed_system, TOL


def test_rod_converts_electricity_to_heat():
    # Only the rod can serve heat. eta=0.99, heat demand 9.9 -> rod_el = 10.0.
    cfg = base_cfg()
    cfg["rod"] = {"q_max": 100.0, "eta": 0.99}
    data = make_data([0], [0.30], [0.0], [0.0], [0.0], [9.9], cop=3.0)
    m = build_model(data, cfg); solve(m); r = extract_results(m)
    assert r["rod_heat"][0] == pytest.approx(9.9, abs=TOL)
    assert r["rod_el"][0] == pytest.approx(10.0, abs=TOL)
    assert r["cost"] == pytest.approx(3.0, abs=TOL)    # 0.30 * 10


def test_heatpump_applies_cop():
    # Only the heat pump. COP=3, heat demand 9 -> hp_el = 3.
    cfg = base_cfg()
    cfg["heatpump"] = {"q_max": 100.0}
    data = make_data([0], [0.30], [0.0], [0.0], [0.0], [9.0], cop=3.0)
    m = build_model(data, cfg); solve(m); r = extract_results(m)
    assert r["hp_heat"][0] == pytest.approx(9.0, abs=TOL)
    assert r["hp_el"][0] == pytest.approx(3.0, abs=TOL)
    assert r["cost"] == pytest.approx(0.90, abs=TOL)   # 0.30 * 3


def test_heatpump_preferred_over_rod():
    # With COP=3 the heat pump uses a third of the electricity of the rod, so
    # the optimum serves all heat with the pump and leaves the rod idle.
    cfg = base_cfg()
    cfg["rod"] = {"q_max": 100.0, "eta": 0.99}
    cfg["heatpump"] = {"q_max": 100.0}
    data = make_data([0], [0.30], [0.0], [0.0], [0.0], [9.0], cop=3.0)
    m = build_model(data, cfg); solve(m); r = extract_results(m)
    assert r["hp_heat"][0] == pytest.approx(9.0, abs=TOL)
    assert r["rod_heat"][0] == pytest.approx(0.0, abs=TOL)


def test_chp_couples_heat_and_power():
    # Force the CHP to serve heat. heat = ratio*el and gas = el/eta_el:
    # heat 30 -> el = 30/1.5 = 20 -> gas = 20/0.4 = 50.
    cfg = base_cfg()
    cfg["chp"] = {"p_el_max": 100.0, "eta_el": 0.4, "htp_ratio": 1.5, "min_load": 0.0}
    data = make_data([0], [0.30], [0.0], [0.0], [20.0], [30.0], cop=3.0)
    m = build_model(data, cfg); solve(m); r = extract_results(m)
    assert r["chp_heat"][0] == pytest.approx(30.0, abs=TOL)
    assert r["chp_el"][0] == pytest.approx(20.0, abs=TOL)
    assert r["chp_gas"][0] == pytest.approx(50.0, abs=TOL)


def test_chp_respects_minimum_load():
    # min_load 0.5 of 100 kW -> if ON it must make >=50 kW elec (>=75 kW heat),
    # but heat demand is only 10 and a cheap rod exists. Running the CHP would
    # hugely overproduce, so the optimum keeps it OFF and uses the rod.
    cfg = base_cfg()
    cfg["chp"] = {"p_el_max": 100.0, "eta_el": 0.4, "htp_ratio": 1.5, "min_load": 0.5}
    cfg["rod"] = {"q_max": 100.0, "eta": 0.99}
    data = make_data([0], [0.30], [0.0], [0.0], [0.0], [10.0], cop=3.0)
    m = build_model(data, cfg); solve(m); r = extract_results(m)
    assert r["chp_on"][0] == pytest.approx(0.0, abs=TOL)
    assert r["chp_heat"][0] == pytest.approx(0.0, abs=TOL)
    assert r["rod_heat"][0] == pytest.approx(10.0, abs=TOL)


def test_heat_storage_shifts_across_hours():
    # Cheap power in hour 0, expensive in hour 1; heat needed only in hour 1.
    # The store should be filled cheaply in hour 0 and discharged in hour 1.
    cfg = base_cfg()
    cfg["rod"] = {"q_max": 100.0, "eta": 1.0}
    cfg["heat_storage"] = {"E_cap": 20.0, "p_ch_max": 20.0, "p_dis_max": 20.0,
                           "eta_ch": 1.0, "eta_dis": 1.0, "self_disch": 0.0, "soc_init": 0.0}
    data = make_data([0, 1], [0.10, 0.90], [0, 0], [0, 0], [0, 0], [0, 10], cop=3.0)
    m = build_model(data, cfg); solve(m); r = extract_results(m)
    assert r["h_charge"][0] > TOL
    assert r["h_discharge"][1] == pytest.approx(10.0, abs=TOL)
    assert r["rod_heat"][0] == pytest.approx(10.0, abs=TOL)
    assert r["rod_heat"][1] == pytest.approx(0.0, abs=TOL)


def test_heat_balance_invariant():
    # Sources == sinks on the heat bus, every hour, for any solution.
    data, r = mixed_system()
    for i, t in enumerate(r["t"]):
        src = r["chp_heat"][i] + r["hp_heat"][i] + r["rod_heat"][i] + r["h_discharge"][i]
        snk = data["dem_heat"][i] + r["h_charge"][i]
        assert src == pytest.approx(snk, abs=1e-4), f"heat balance broke at t={t}"
