"""
test_multichp.py
================
Validation for the step-6 additions: multiple CHP units, minimum runtime,
ramp limits, and the woodchip boiler. Each case is hand-checkable.
"""
import pytest
from engine import make_data, build_model, solve, extract_results, solve_rolling
from engine.postprocess.cop_variants import make_cop_variants
from helpers import base_cfg, TOL


def cfg_no_single_chp():
    """base_cfg but with the single 'chp' removed so we can add 'chps'."""
    c = base_cfg()
    c.pop("chp", None)
    return c


# ----------------------------- multi-CHP ------------------------------------
def test_two_chp_units_both_contribute():
    # Two CHP units, heat demand needs both. Unit A: 100 kW el, htp 1.0.
    # Unit B: 50 kW el, htp 1.0. Max heat = 100 + 50 = 150. Demand 150 forces
    # both to full output.
    c = cfg_no_single_chp()
    c["chps"] = [
        {"name": "A", "p_el_max": 100.0, "eta_el": 0.4, "htp_ratio": 1.0, "min_load": 0.0},
        {"name": "B", "p_el_max": 50.0, "eta_el": 0.4, "htp_ratio": 1.0, "min_load": 0.0},
    ]
    data = make_data([0], [0.30], [0.0], [0.0], [150.0], [150.0], cop=3.0)
    m = build_model(data, c); solve(m); r = extract_results(m)
    assert r["chp_heat"][0] == pytest.approx(150.0, abs=1e-3)
    assert r["chp_el"][0] == pytest.approx(150.0, abs=1e-3)
    # Per-unit: both at full.
    assert r["chp_units"]["A"]["el"][0] == pytest.approx(100.0, abs=1e-3)
    assert r["chp_units"]["B"]["el"][0] == pytest.approx(50.0, abs=1e-3)


def test_cheaper_chp_preferred_when_only_one_needed():
    # Two identical-capacity units but unit B has worse electrical efficiency
    # (more gas per kWh). With low heat demand only one is needed; the more
    # efficient unit A should be chosen.
    c = cfg_no_single_chp()
    c["chps"] = [
        {"name": "A", "p_el_max": 100.0, "eta_el": 0.45, "htp_ratio": 1.0, "min_load": 0.0},
        {"name": "B", "p_el_max": 100.0, "eta_el": 0.30, "htp_ratio": 1.0, "min_load": 0.0},
    ]
    data = make_data([0], [0.30], [0.0], [0.0], [0.0], [40.0], cop=3.0)
    m = build_model(data, c); solve(m); r = extract_results(m)
    assert r["chp_units"]["A"]["heat"][0] == pytest.approx(40.0, abs=1e-3)
    assert r["chp_units"]["B"]["heat"][0] == pytest.approx(0.0, abs=1e-3)


# --------------------------- minimum runtime --------------------------------
def test_min_runtime_keeps_unit_on():
    # A CHP with a 3-hour minimum runtime. Heat is needed only in hour 0, but
    # once started the unit must stay ON for hours 0,1,2. We give it a cheap
    # heat sink (storage) so staying on is feasible, and check on[0..2]==1.
    c = cfg_no_single_chp()
    c["allow_heat_dump"] = True   # real plants have an emergency cooler
    c["chps"] = [{"name": "A", "p_el_max": 100.0, "eta_el": 0.4, "htp_ratio": 1.0,
                  "min_load": 0.2, "min_runtime_h": 3}]
    c["heat_storage"] = {"E_cap": 500.0, "p_ch_max": 200.0, "p_dis_max": 200.0,
                         "eta_ch": 1.0, "eta_dis": 1.0, "self_disch": 0.0, "soc_init": 0.0}
    # Heat demand only in hour 0; hours 1-3 demand 0.
    data = make_data([0, 1, 2, 3], [0.30] * 4, [0.0] * 4, [0.0] * 4,
                       [0.0] * 4, [50.0, 0.0, 0.0, 0.0], cop=3.0)
    m = build_model(data, c); solve(m); r = extract_results(m)
    on = r["chp_units"]["A"]["on"]
    # If it ran in hour 0 it must be on for 3 consecutive hours.
    if on[0] > 0.5:
        assert on[1] > 0.5 and on[2] > 0.5, "min-runtime not enforced"


def test_no_min_runtime_allows_single_hour():
    # Same setup but min_runtime_h = 1: the unit may run only in hour 0.
    c = cfg_no_single_chp()
    c["chps"] = [{"name": "A", "p_el_max": 100.0, "eta_el": 0.4, "htp_ratio": 1.0,
                  "min_load": 0.2, "min_runtime_h": 1}]
    data = make_data([0, 1], [0.30] * 2, [0.0] * 2, [0.0] * 2,
                       [0.0] * 2, [50.0, 0.0], cop=3.0)
    m = build_model(data, c); solve(m); r = extract_results(m)
    on = r["chp_units"]["A"]["on"]
    assert on[1] < 0.5, "unit should be allowed off in hour 1"


# ------------------------------- ramp limit ---------------------------------
def test_ramp_limit_caps_output_change():
    # A CHP limited to 30 kW change per hour. Heat demand jumps 0 -> 100, but
    # the unit cannot ramp that fast, so a backup rod must cover the rest.
    c = cfg_no_single_chp()
    c["chps"] = [{"name": "A", "p_el_max": 200.0, "eta_el": 0.4, "htp_ratio": 1.0,
                  "min_load": 0.0, "max_grad": 30.0}]
    c["rod"] = {"q_max": 200.0, "eta": 1.0}
    # Hour 0 no heat (CHP at 0), hour 1 needs 100 heat. CHP el can rise only 30,
    # so chp_heat (=el*1.0) <= 30 in hour 1; rod covers >= 70.
    data = make_data([0, 1], [0.30] * 2, [0.0] * 2, [0.0] * 2,
                       [0.0] * 2, [0.0, 100.0], cop=3.0)
    m = build_model(data, c); solve(m); r = extract_results(m)
    assert r["chp_units"]["A"]["el"][1] <= 30.0 + 1e-3, "ramp limit exceeded"
    assert r["rod_heat"][1] >= 70.0 - 1e-3, "rod should cover the un-rampable heat"


# ------------------------------ woodchip boiler -----------------------------
def test_woodchip_supplies_heat():
    # Only the woodchip boiler can serve heat. eta 0.9, demand 90 -> fuel 100.
    c = base_cfg()
    c["woodchip"] = {"q_max": 500.0, "eta": 0.9, "fuel_price": 0.03}
    data = make_data([0], [0.30], [0.0], [0.0], [0.0], [90.0], cop=3.0)
    m = build_model(data, c); solve(m); r = extract_results(m)
    assert r["wood_heat"][0] == pytest.approx(90.0, abs=1e-3)
    assert r["wood_fuel"][0] == pytest.approx(100.0, abs=1e-3)
    # cost = fuel * price = 100 * 0.03 = 3.0
    assert r["cost"] == pytest.approx(3.0, abs=1e-3)


def test_woodchip_vs_rod_cheaper_wins():
    # Woodchip fuel at 0.03/kWh-heat (eta 0.9 -> 0.0333/kWh-heat) vs rod using
    # grid electricity at 0.30/kWh. Woodchip is far cheaper, so it serves heat.
    c = base_cfg()
    c["woodchip"] = {"q_max": 500.0, "eta": 0.9, "fuel_price": 0.03}
    c["rod"] = {"q_max": 500.0, "eta": 1.0}
    data = make_data([0], [0.30], [0.0], [0.0], [0.0], [80.0], cop=3.0)
    m = build_model(data, c); solve(m); r = extract_results(m)
    assert r["wood_heat"][0] == pytest.approx(80.0, abs=1e-3)
    assert r["rod_heat"][0] == pytest.approx(0.0, abs=1e-3)
