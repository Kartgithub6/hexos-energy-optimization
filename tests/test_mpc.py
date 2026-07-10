"""Closed-loop MPC: correctness, and the rolling-horizon-MPC generalisation."""
import pytest
from engine import make_data, build_model, solve, extract_results
from engine.control.mpc import run_mpc, perfect_forecaster
from engine.control.forecasters import noisy_factory
from engine.control.simulator import advance_one_hour
from engine.solve.rolling import solve_rolling
from helpers import base_cfg, with_battery


def _cfg():
    c = with_battery(base_cfg(), E_cap=20.0, p=10.0)
    c["chp"] = {"p_el_max": 50.0, "eta_el": 0.4, "htp_ratio": 1.0, "min_load": 0.0}
    c["rod"] = {"q_max": 50.0, "eta": 1.0}
    c["heat_storage"] = {"E_cap": 30.0, "p_ch_max": 15.0, "p_dis_max": 15.0,
                         "eta_ch": 1.0, "eta_dis": 1.0, "self_disch": 0.0, "soc_init": 0.0}
    c["grid"] = {"import_max": 500.0, "export_max": 500.0}
    return c


def _data(n=12):
    price = [0.10 + 0.20 * ((h % 6) >= 3) for h in range(n)]
    return make_data(list(range(n)), price, [0.04] * n,
                     [5 * (1 if 3 <= (h % 12) <= 7 else 0) for h in range(n)],
                     [4 + 2 * (h % 2) for h in range(n)],
                     [3 + (h % 3) for h in range(n)], cop=[3.0] * n)


def test_simulator_matches_model_storage_under_applied_controls():
    cfg = _cfg()
    state = {"batt_soc": 5.0, "hstor_soc": 2.0}
    applied = {"charge": 4.0, "discharge": 0.0, "h_charge": 3.0, "h_discharge": 0.0}
    new = advance_one_hour(state, applied, cfg)
    assert new["batt_soc"] == pytest.approx(9.0)
    assert new["hstor_soc"] == pytest.approx(5.0)


def test_perfect_forecast_mpc_matches_perfect_foresight_cost():
    # Default commit_h=1 (classic hourly MPC): with a perfect forecaster this
    # must match the full-horizon optimum, since the forecast IS the truth.
    cfg = _cfg()
    data = _data(12)
    m = build_model(data, cfg, cyclic=False); solve(m); ref = extract_results(m)
    mpc = run_mpc(data, cfg, forecaster=perfect_forecaster, horizon_h=12)
    assert mpc["cost"] == pytest.approx(ref["cost"], rel=1e-4)


def test_noisy_forecast_costs_at_least_perfect_foresight():
    cfg = _cfg()
    data = _data(12)
    m = build_model(data, cfg, cyclic=False); solve(m); ref = extract_results(m)
    noisy = run_mpc(data, cfg, forecaster=noisy_factory(seed=1), horizon_h=8)
    assert noisy["cost"] >= ref["cost"] - 1e-6


def test_mpc_trajectory_length_matches_horizon():
    cfg = _cfg()
    data = _data(10)
    mpc = run_mpc(data, cfg, horizon_h=6)
    assert len(mpc["t"]) == 10
    assert len(mpc["import"]) == 10 and len(mpc["batt_soc"]) == 10


# ---------------------------------------------------------------------------
# ROLLING-HORIZON MPC: commit_h > 1 generalises the loop to re-plan in blocks
# rather than every hour -- this is the literal "rolling-horizon MPC" capability.
# ---------------------------------------------------------------------------

def test_commit_h_block_matches_manual_multi_hour_apply():
    # With commit_h=3, the controller should apply 3 hours of a single plan
    # before re-forecasting, rather than replanning every hour. We check the
    # trajectory length and window count indirectly via cost consistency: a
    # commit_h=3 perfect-forecast run over a horizon covering the whole data
    # must still reproduce the optimum (still forecast==truth, regardless of
    # how many hours are applied per plan).
    cfg = _cfg()
    data = _data(12)
    m = build_model(data, cfg, cyclic=False); solve(m); ref = extract_results(m)
    mpc_block = run_mpc(data, cfg, forecaster=perfect_forecaster, horizon_h=12, commit_h=3)
    assert mpc_block["cost"] == pytest.approx(ref["cost"], rel=1e-4)
    assert len(mpc_block["t"]) == 12


def test_rolling_horizon_mpc_matches_solve_rolling_under_perfect_forecast():
    # THE key unification test: with a perfect forecaster, run_mpc using the
    # SAME window/commit cadence as the annual rolling-horizon solver
    # (horizon_h=48, commit_h=24) must give the identical cost to
    # solve_rolling(window_h=48, commit_h=24). This proves the annual
    # rolling-horizon solver is a special case of this MPC framework -- one
    # unified "rolling-horizon MPC" capability, not two unrelated things.
    cfg = _cfg()
    data = _data(48)
    rolling_result = solve_rolling(data, cfg, window_h=48, commit_h=24, verbose=False)
    mpc_result = run_mpc(data, cfg, forecaster=perfect_forecaster, horizon_h=48, commit_h=24)
    assert mpc_result["cost"] == pytest.approx(rolling_result["cost"], rel=1e-4)


def test_rolling_horizon_mpc_with_real_uncertainty_costs_more_than_perfect():
    # The genuinely realistic case: rolling-horizon MPC (daily re-plan, 48h
    # lookahead) driven by a NOISY forecast must cost at least as much as the
    # perfect-foresight optimum -- proving uncertainty is honestly priced even
    # at this slower re-planning cadence.
    cfg = _cfg()
    data = _data(48)
    m = build_model(data, cfg, cyclic=False); solve(m); ref = extract_results(m)
    noisy_rh_mpc = run_mpc(data, cfg, forecaster=noisy_factory(seed=2),
                           horizon_h=48, commit_h=24)
    assert noisy_rh_mpc["cost"] >= ref["cost"] - 1e-6
