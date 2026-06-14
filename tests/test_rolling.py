"""
test_rolling.py
===============
Validation for the rolling-horizon solver. The hard part to get right is the
seam between windows: storage state must carry forward, and the stitched
result must still satisfy both energy balances at every hour.
"""
import pytest
from engine import make_data, build_model, solve, extract_results, solve_rolling
from engine.postprocess.cop_variants import make_cop_variants
from helpers import base_cfg, TOL


def _full_system_cfg():
    cfg = base_cfg()
    cfg["battery"] = {"E_cap": 10.0, "p_ch_max": 5.0, "p_dis_max": 5.0,
                      "eta_ch": 0.97, "eta_dis": 0.97, "self_disch": 0.0, "soc_init": 0.0}
    cfg["rod"] = {"q_max": 50.0, "eta": 0.99}
    cfg["heatpump"] = {"q_max": 50.0}
    cfg["chp"] = {"p_el_max": 30.0, "eta_el": 0.4, "htp_ratio": 1.5, "min_load": 0.3}
    cfg["heat_storage"] = {"E_cap": 20.0, "p_ch_max": 10.0, "p_dis_max": 10.0,
                           "eta_ch": 0.98, "eta_dis": 0.98, "self_disch": 0.0, "soc_init": 0.0}
    return cfg


def _data(n):
    # A repeating daily price/demand pattern over n hours.
    price = [0.10 + 0.30 * ((h % 24) >= 17) for h in range(n)]   # pricey evenings
    return make_data(
        list(range(n)),
        price,
        [0.05] * n,
        [200 * (1 if 8 <= (h % 24) <= 16 else 0) for h in range(n)],  # midday PV
        [3 + 2 * ((h % 24) >= 17) for h in range(n)],                 # evening elec peak
        [5 + 3 * ((h % 24) < 8) for h in range(n)],                   # morning heat
        cop=[3.0] * n,
    )


def test_stitched_length_matches_horizon():
    data = _data(72)
    r = solve_rolling(data, _full_system_cfg(), window_h=48, commit_h=24, verbose=False)
    assert len(r["t"]) == 72
    assert all(len(r[k]) == 72 for k in ["import", "soc", "h_soc", "chp_on"])
    assert r["n_windows"] == 3   # 72h committed in 24h steps


def test_electricity_balance_holds_across_seams():
    data = _data(72)
    r = solve_rolling(data, _full_system_cfg(), window_h=48, commit_h=24, verbose=False)
    for i in range(72):
        src = r["import"][i] + r["pv_used"][i] + r["discharge"][i] + r["chp_el"][i]
        snk = (data["dem_el"][i] + r["export"][i] + r["charge"][i]
               + r["hp_el"][i] + r["rod_el"][i])
        assert src == pytest.approx(snk, abs=1e-4), f"elec balance broke at hour {i}"


def test_heat_balance_holds_across_seams():
    data = _data(72)
    r = solve_rolling(data, _full_system_cfg(), window_h=48, commit_h=24, verbose=False)
    for i in range(72):
        src = r["chp_heat"][i] + r["hp_heat"][i] + r["rod_heat"][i] + r["h_discharge"][i]
        snk = data["dem_heat"][i] + r["h_charge"][i]
        assert src == pytest.approx(snk, abs=1e-4), f"heat balance broke at hour {i}"


def test_storage_state_is_continuous_across_seam():
    # The carried SOC at the start of a committed window must equal the SOC at
    # the end of the previous committed window, with the model's own dynamics
    # applied in the first hour. We verify continuity by checking the SOC
    # trajectory has no impossible jump at the 24h seam (hour 23 -> 24).
    cfg = _full_system_cfg()
    cfg["battery"]["self_disch"] = 0.0
    cfg["battery"]["eta_ch"] = 1.0
    cfg["battery"]["eta_dis"] = 1.0
    data = _data(48)
    r = solve_rolling(data, cfg, window_h=48, commit_h=24, verbose=False)
    # Reconstruct hour-24 SOC from hour-23 SOC and the committed hour-24 flows.
    soc23 = r["soc"][23]
    expected_soc24 = soc23 + r["charge"][24] - r["discharge"][24]
    assert r["soc"][24] == pytest.approx(expected_soc24, abs=1e-4), \
        "battery SOC is discontinuous across the window seam"


def test_lookahead_beats_no_lookahead_on_storage():
    # With evening price spikes and morning heat demand, a daily-only horizon
    # (commit=window=24) tends to empty storage at midnight, while a 48/24
    # lookahead preserves useful state. The lookahead cost should be <= the
    # no-lookahead cost (never worse).
    data = _data(96)
    cfg = _full_system_cfg()
    no_look = solve_rolling(data, cfg, window_h=24, commit_h=24, verbose=False)
    look = solve_rolling(data, cfg, window_h=48, commit_h=24, verbose=False)
    assert look["cost"] <= no_look["cost"] + TOL
