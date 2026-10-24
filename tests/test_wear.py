"""Battery wear: the optimiser-side cost models (throughput, cycle-depth) and
the after-the-fact rainflow evaluator."""
import pytest

from engine import make_data, build_model, solve, extract_results, solve_rolling
from engine.technologies.wear import (wear_cfg, throughput_cost, segment_costs,
                                      initial_split, phi)
from engine.postprocess.wear import rainflow, turning_points, evaluate_wear
from helpers import base_cfg, with_battery, run, TOL


def _arbitrage(spread_hi, n_pairs=1, low=0.10):
    """Cheap hour then expensive hour, repeated. Battery-only site with a flat
    1 kW load, so every discharged kWh displaces a kWh of import."""
    prices = []
    for _ in range(n_pairs):
        prices += [low, low + spread_hi]
    n = len(prices)
    return make_data(list(range(n)), prices, [0.0] * n, [0] * n, [5.0] * n, [0] * n,
                     cop=[3.0] * n)


def _batt(wear=None, E=10.0, p=10.0, eta=1.0):
    cfg = with_battery(base_cfg(), E, p)
    cfg["battery"]["eta_ch"] = cfg["battery"]["eta_dis"] = eta
    if wear:
        cfg["battery"]["wear"] = wear
    return cfg


TH = {"model": "throughput", "capex_eur_per_kwh": 200.0, "cycle_life_efc": 4000}


# ------------------------------------------------------------------ config
def test_wear_off_by_default_changes_nothing():
    data = _arbitrage(0.05, 3)
    a = run(data, _batt())
    b = run(data, _batt(wear=None))
    assert abs(a["cost"] - b["cost"]) < TOL
    assert wear_cfg({}) is None


def test_bad_wear_config_raises():
    with pytest.raises(ValueError):
        wear_cfg({"wear": {"model": "magic", "capex_eur_per_kwh": 1, "cycle_life_efc": 1}})
    with pytest.raises(ValueError):
        wear_cfg({"wear": {"model": "throughput", "cycle_life_efc": 1000}})


# -------------------------------------------------------------- throughput
def test_throughput_cost_formula():
    # 200 EUR/kWh over 4000 cycles, 2 kWh of throughput per kWh of capacity per cycle
    assert abs(throughput_cost(TH) - 0.025) < 1e-12


def test_throughput_wear_stops_unprofitable_cycling():
    """Round trip costs 2 * 0.025 = 0.05 EUR/kWh. A 0.04 spread no longer pays."""
    data = _arbitrage(0.04, 2)
    blind = run(data, _batt())
    aware = run(data, _batt(TH))
    assert sum(blind["discharge"]) > 1.0
    assert sum(aware["discharge"]) < 1e-6


def test_throughput_wear_keeps_profitable_cycling():
    data = _arbitrage(0.08, 2)
    aware = run(data, _batt(TH))
    assert sum(aware["discharge"]) > 1.0


def test_throughput_objective_includes_wear():
    data = _arbitrage(0.08, 1)
    r = run(data, _batt(TH))
    thr = sum(r["charge"]) + sum(r["discharge"])
    energy = sum(p * i for p, i in zip(data["price_el"], r["import"]))
    assert abs(r["cost"] - (energy + throughput_cost(TH) * thr)) < 1e-6


# ------------------------------------------------------------- cycle depth
CD = {"model": "cycle_depth", "capex_eur_per_kwh": 200.0, "cycle_life_efc": 4000,
      "dod_exponent": 2.0, "segments": 4}


def test_segment_costs_rise_with_depth_and_sum_to_full_cycle():
    c = segment_costs(wear_cfg({"wear": CD}), eta_dis=1.0)
    assert all(b > a for a, b in zip(c, c[1:]))
    # discharging the whole battery once (E/J from each segment) = one full cycle
    E = 10.0
    full = sum(cj * E / 4 for cj in c)
    assert abs(full - 200.0 * E * phi(1.0, CD)) < 1e-9


def test_initial_split_fills_shallow_first():
    assert initial_split(6.0, 10.0, 4) == [2.5, 2.5, 1.0, 0.0]


def test_segments_add_up_to_soc():
    data = _arbitrage(0.20, 2)
    cfg = _batt(CD)
    m = build_model(data, cfg)
    solve(m)
    import pyomo.environ as pyo
    for t in m.T:
        tot = sum(pyo.value(m.seg_e[j, t]) for j in m.SEG)
        assert abs(tot - pyo.value(m.soc[t])) < 1e-6
        for j in m.SEG:
            assert pyo.value(m.seg_e[j, t]) <= 10.0 / 4 + 1e-6


def test_cycle_depth_prefers_shallow_cycles():
    """With b = 2 the four segments cost 1, 3, 5, 7 x 0.0125 EUR/kWh. A spread of
    0.02 pays for the shallowest segment only, so the battery makes one
    quarter-depth cycle. A throughput model with the same full-cycle cost
    charges 0.025 per kWh each way and does not cycle at all."""
    data = _arbitrage(0.02, 1)
    r = run(data, _batt(CD))
    assert abs(sum(r["discharge"]) - 2.5) < 1e-4
    th = run(data, _batt(dict(TH)))
    assert sum(th["discharge"]) < 1e-6


def test_wear_works_in_rolling_horizon():
    data = _arbitrage(0.20, 30)
    cfg = _batt(CD)
    r = solve_rolling(data, cfg, window_h=12, commit_h=6, verbose=False)
    assert len(r["soc"]) == len(data["T"])
    assert sum(r["discharge"]) > 1.0


# -------------------------------------------------------------- evaluator
def test_turning_points():
    assert turning_points([0, 1, 2, 2, 1, 0, 3]) == [0, 2, 0, 3]


def test_rainflow_astm_example():
    got = {}
    for r, c in rainflow([-2, 1, -3, 5, -1, 3, -4, 4, -2]):
        got[r] = got.get(r, 0) + c
    assert got == {3: 0.5, 4: 1.5, 6: 0.5, 8: 1.0, 9: 0.5}


def test_rainflow_daily_full_cycles():
    soc = [0, 10, 0] * 5
    cyc = rainflow(soc)
    full = sum(c for r, c in cyc if abs(r - 10) < 1e-9)
    assert abs(full - 5.0) < 1e-9          # five charge/discharge swings


def test_evaluate_wear_full_cycles_life():
    E = 10.0
    days = 365
    soc = []
    for _ in range(days):
        soc += [0.0] * 11 + [10.0] * 13     # one full cycle a day
    ch = [0.0] * len(soc)
    w = {"capex_eur_per_kwh": 200.0, "cycle_life_efc": 3650, "dod_exponent": 2.0}
    r = evaluate_wear(soc, ch, ch, E, w)
    # ~365 full cycles out of 3650 -> ~10 years, ~10 % of the cells per year
    assert 9.5 < r["years_to_eol"] < 10.5
    assert abs(r["wear_eur"] - 0.1 * 200 * E) < 0.01 * 200 * E


def test_evaluate_wear_calendar_only():
    soc = [5.0] * 8760
    z = [0.0] * 8760
    r = evaluate_wear(soc, z, z, 10.0, {"capex_eur_per_kwh": 200.0, "cycle_life_efc": 5000},
                      calendar_life_years=15)
    assert r["cycle_ageing"] == 0.0
    assert abs(r["years_to_eol"] - 15.0) < 1e-6
