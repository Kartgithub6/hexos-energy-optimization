"""Closed-loop MPC simulation: correctness of the loop and the plant simulator."""
import pytest
from engine import make_data, build_model, solve, extract_results
from engine.control.mpc import run_mpc, perfect_forecaster
from engine.control.forecasters import noisy_factory
from engine.control.simulator import advance_one_hour
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
    # The simulator's one-step storage update must equal the model's own SOC
    # dynamics, so that perfect-forecast MPC tracks the optimiser exactly.
    cfg = _cfg()
    state = {"batt_soc": 5.0, "hstor_soc": 2.0}
    applied = {"charge": 4.0, "discharge": 0.0, "h_charge": 3.0, "h_discharge": 0.0}
    new = advance_one_hour(state, applied, cfg)
    # lossless battery: 5 + 4 = 9 ; heat store: 2 + 3 = 5
    assert new["batt_soc"] == pytest.approx(9.0)
    assert new["hstor_soc"] == pytest.approx(5.0)


def test_perfect_forecast_mpc_matches_perfect_foresight_cost():
    # With a perfect forecaster and a 1-step commit, closed-loop MPC over the
    # whole horizon should achieve (within tolerance) the same realised cost as
    # the single full-horizon optimal solve -- because the forecast IS the truth
    # and the simulator mirrors the model dynamics.
    cfg = _cfg()
    data = _data(12)

    # Full-horizon perfect-foresight optimum (no cyclic boundary, to match MPC
    # which carries state forward without a closing constraint).
    m = build_model(data, cfg, cyclic=False); solve(m); ref = extract_results(m)

    mpc = run_mpc(data, cfg, forecaster=perfect_forecaster, horizon_h=12)
    # Long horizon == full data, so perfect-foresight MPC == the optimum.
    assert mpc["cost"] == pytest.approx(ref["cost"], rel=1e-4)


def test_noisy_forecast_costs_at_least_perfect_foresight():
    # Deciding on imperfect forecasts cannot beat knowing the future: realised
    # cost under a noisy forecaster must be >= the perfect-foresight cost.
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
