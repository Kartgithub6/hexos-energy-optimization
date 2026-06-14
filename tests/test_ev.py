"""EV charging as a controllable load: energy-by-deadline, timing flexible."""
import pytest
from engine import make_data, build_model, solve, extract_results
from helpers import base_cfg, TOL


def test_ev_meets_energy_need_within_window():
    # One EV needs 10 kWh over hours 0..3, max 5 kW. Total charge must equal 10.
    c = base_cfg()
    c["evs"] = [{"name": "EVa", "p_max": 5.0, "energy_need": 10.0, "start_t": 0, "end_t": 3}]
    data = make_data([0, 1, 2, 3], [0.30, 0.10, 0.50, 0.40], [0.0] * 4,
                     [0.0] * 4, [0.0] * 4, [0.0] * 4, cop=3.0)
    m = build_model(data, c); solve(m); r = extract_results(m)
    assert sum(r["ev_units"]["EVa"]) == pytest.approx(10.0, abs=1e-3)


def test_ev_charges_in_cheapest_hours():
    # Same EV; hour 1 is cheapest. It should charge as much as possible then.
    c = base_cfg()
    c["evs"] = [{"name": "EVa", "p_max": 5.0, "energy_need": 8.0, "start_t": 0, "end_t": 3}]
    data = make_data([0, 1, 2, 3], [0.30, 0.05, 0.50, 0.40], [0.0] * 4,
                     [0.0] * 4, [0.0] * 4, [0.0] * 4, cop=3.0)
    m = build_model(data, c); solve(m); r = extract_results(m)
    ev = r["ev_units"]["EVa"]
    assert ev[1] == pytest.approx(5.0, abs=1e-3), "should max out the cheapest hour"


def test_ev_zero_outside_window():
    c = base_cfg()
    c["evs"] = [{"name": "EVa", "p_max": 5.0, "energy_need": 5.0, "start_t": 1, "end_t": 2}]
    data = make_data([0, 1, 2, 3], [0.30] * 4, [0.0] * 4,
                     [0.0] * 4, [0.0] * 4, [0.0] * 4, cop=3.0)
    m = build_model(data, c); solve(m); r = extract_results(m)
    ev = r["ev_units"]["EVa"]
    assert ev[0] == pytest.approx(0.0, abs=TOL)
    assert ev[3] == pytest.approx(0.0, abs=TOL)
    assert ev[1] + ev[2] == pytest.approx(5.0, abs=1e-3)
