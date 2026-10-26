"""Tests for features added after the LinkedIn comment thread: CHP start-up
state and caps, terminal value on the battery, peak carry for demand charges,
and the rule-based self-consumption baseline."""
import pyomo.environ as pyo

from engine import make_data, build_model, solve, extract_results, solve_rolling
from engine.control.mpc import run_mpc
from engine.control.rules import self_consumption_schedule
from engine.model.objective import _terminal_value
from helpers import base_cfg, with_battery, TOL


def _chp_only(startup_cost=0.0, **extra):
    cfg = base_cfg()
    cfg["chp"] = {"p_el_max": 30.0, "eta_el": 0.4, "htp_ratio": 1.5,
                  "min_load": 0.5, "startup_cost": startup_cost, **extra}
    return cfg


def _starts(on, prev=0):
    n = 0
    for x in on:
        x = int(round(x))
        n += 1 if (x == 1 and prev == 0) else 0
        prev = x
    return n


# ---------------------------------------------------------------- CHP state
def test_on_init_avoids_phantom_startup():
    """A unit already running before the window is not billed a start-up."""
    data = make_data(list(range(4)), [0.40] * 4, [0.0] * 4,
                     [0] * 4, [30] * 4, [45] * 4, cop=[3.0] * 4)
    cold = run_cost(data, _chp_only(startup_cost=100.0))
    warm = run_cost(data, _chp_only(startup_cost=100.0, on_init=1))
    assert abs((cold - warm) - 100.0) < 1e-4


def _cycling_day():
    """Heat needed in two blocks with a gap: without a cap the CHP starts twice."""
    cfg = _chp_only()
    cfg["rod"] = {"q_max": 50.0, "eta": 0.99}
    data = make_data(list(range(6)), [0.50] * 6, [0.0] * 6, [0] * 6,
                     [10] * 6, [45, 45, 0, 0, 45, 45], cop=[3.0] * 6)
    return data, cfg


def test_uncapped_chp_starts_twice():
    data, cfg = _cycling_day()
    r = run_results(data, cfg)
    assert _starts(r["chp_on"]) == 2


def test_max_starts_per_day_caps_cycling():
    data, cfg = _cycling_day()
    cfg["chp"]["max_starts_per_day"] = 1
    r = run_results(data, cfg)
    assert _starts(r["chp_on"]) <= 1


def test_start_history_counts_toward_cap():
    """A start in the hour before the window uses up the daily allowance."""
    data, cfg = _cycling_day()
    cfg["chp"]["max_starts_per_day"] = 1
    cfg["chp"]["su_hist"] = [1]
    r = run_results(data, cfg)
    assert sum(round(x) for x in r["chp_on"]) == 0


# ---------------------------------------------------------- terminal value
def _arbitrage_day():
    cfg = with_battery(base_cfg(), 10.0, 5.0)
    data = make_data(list(range(4)), [0.10, 0.10, 0.50, 0.50], [0.0] * 4,
                     [0] * 4, [5] * 4, [0] * 4, cop=[3.0] * 4)
    return data, cfg


def test_without_terminal_value_battery_ends_empty():
    data, cfg = _arbitrage_day()
    r = run_results(data, cfg, cyclic=False)
    assert r["soc"][-1] < TOL


def test_terminal_value_keeps_energy_in_battery():
    data, cfg = _arbitrage_day()
    cfg["battery"]["terminal_value"] = 1.0
    r = run_results(data, cfg, cyclic=False)
    assert r["soc"][-1] > 1.0


def test_terminal_value_auto_is_median_price_times_efficiency():
    data, cfg = _arbitrage_day()
    cfg["battery"]["terminal_value"] = "auto"
    cfg["battery"]["eta_dis"] = 0.9
    m = build_model(data, cfg, cyclic=False)
    assert abs(_terminal_value(m) - 0.9 * 0.30) < 1e-9


def test_terminal_value_ignored_without_battery():
    data, _ = _arbitrage_day()
    cfg = base_cfg()
    cfg["battery"]["terminal_value"] = 5.0
    m = build_model(data, cfg, cyclic=False)
    solve(m)
    assert _terminal_value(m) == 0.0


# ------------------------------------------------------------- demand peak
def test_peak_so_far_sets_a_floor():
    cfg = base_cfg()
    cfg["peak_so_far"] = 50.0
    data = make_data(list(range(3)), [0.2] * 3, [0.0] * 3, [0] * 3,
                     [10] * 3, [0] * 3, cop=[3.0] * 3)
    r = run_results(data, cfg)
    assert r["peak_import"] >= 50.0 - TOL


# --------------------------------------------------- self-consumption rule
def test_self_consumption_rule_charges_only_from_surplus():
    batt = {"E_cap": 10.0, "p_ch_max": 5.0, "p_dis_max": 5.0, "eta_ch": 1.0,
            "eta_dis": 1.0, "self_disch": 0.0, "soc_init": 0.0}
    data = {"pv_avail": [0, 10, 10, 0, 0, 0], "dem_el": [5, 2, 2, 5, 5, 5]}
    ch, dis = self_consumption_schedule(data, batt)
    soc = 0.0
    for c, d, pv, load in zip(ch, dis, data["pv_avail"], data["dem_el"]):
        assert c <= max(0.0, pv - load) + TOL
        assert d <= max(0.0, load - pv) + TOL
        assert not (c > TOL and d > TOL)
        soc += c - d
        assert -TOL <= soc <= batt["E_cap"] + TOL
    assert abs(sum(ch) - 10.0) < 1e-4
    assert abs(sum(dis) - 10.0) < 1e-4


def test_fixed_schedule_is_respected_by_the_model():
    cfg = with_battery(base_cfg(), 10.0, 5.0)
    cfg["battery"]["fixed_ch"] = [5, 5, 0, 0]
    cfg["battery"]["fixed_dis"] = [0, 0, 5, 5]
    data = make_data(list(range(4)), [0.5, 0.5, 0.1, 0.1], [0.0] * 4,
                     [0] * 4, [5] * 4, [0] * 4, cop=[3.0] * 4)
    r = run_results(data, cfg, cyclic=False)
    assert r["charge"] == [5, 5, 0, 0]
    assert r["discharge"] == [0, 0, 5, 5]


# --------------------------------------------------- carry across windows
def test_shrinking_horizon_mpc_matches_single_solve_with_startups():
    """With the full remaining horizon visible at every step, re-planning must
    reproduce the single-solve optimum. That only holds if the CHP on/off state
    is carried between windows."""
    data, cfg = _cycling_day()
    # 30 is deliberate: more than one hour of CHP running saves, less than two.
    # A phantom start at a window seam then flips the decision, so this test
    # fails if on/off state is not carried. At 20 it would pass either way.
    cfg["chp"]["startup_cost"] = 30.0
    single = run_cost(data, cfg, cyclic=False)
    mpc = run_mpc(data, cfg, horizon_h=6, commit_h=1)
    assert abs(mpc["cost"] - single) < 1e-4


def test_rolling_reports_starts_and_peak_consistently():
    data, cfg = _cycling_day()
    cfg["chp"]["startup_cost"] = 20.0
    cfg["demand_charge"] = 3.0
    r = solve_rolling(data, cfg, window_h=3, commit_h=3, verbose=False)
    assert r["chp_starts"] == _starts(r["chp_on"])
    assert abs(r["peak_import"] - max(r["import"])) < 1e-6
    assert abs(r["cost"] - (r["energy_cost"] + r["startup_cost"]
                            + r["demand_cost"])) < 1e-9


# ----------------------------------------------------------------- helpers
def run_results(data, cfg, cyclic=True):
    m = build_model(data, cfg, cyclic=cyclic)
    solve(m)
    return extract_results(m)


def run_cost(data, cfg, cyclic=True):
    m = build_model(data, cfg, cyclic=cyclic)
    solve(m)
    return pyo.value(m.cost)
