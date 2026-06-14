"""Start-up cost (discourages CHP cycling) and peak-demand charge (Lastspitze)."""
import pytest
from engine import make_data, build_model, solve, extract_results
from helpers import base_cfg


def _chp_cfg(startup_cost=0.0):
    c = base_cfg()
    c.pop("chp", None)
    c["allow_heat_dump"] = True
    c["chps"] = [{"name": "A", "p_el_max": 100.0, "eta_el": 0.4, "htp_ratio": 1.0,
                  "min_load": 0.2, "startup_cost": startup_cost}]
    c["heat_storage"] = {"E_cap": 1000.0, "p_ch_max": 500.0, "p_dis_max": 500.0,
                         "eta_ch": 1.0, "eta_dis": 1.0, "self_disch": 0.0, "soc_init": 0.0}
    return c


def test_startup_cost_discourages_cycling():
    # Heat needed in hours 0 and 2 but not 1. With no start-up cost the CHP may
    # switch off in hour 1 and restart. With a large start-up cost, it is cheaper
    # to stay on (and dump/curtail the hour-1 heat) than to pay to restart.
    data = make_data([0, 1, 2], [0.30] * 3, [0.0] * 3, [0.0] * 3,
                     [0.0] * 3, [30.0, 0.0, 30.0], cop=3.0)

    r_free = extract_results(_solve(_chp_cfg(startup_cost=0.0), data))
    r_costly = extract_results(_solve(_chp_cfg(startup_cost=1000.0), data))

    starts_free = _count_starts(r_free["chp_units"]["A"]["on"])
    starts_costly = _count_starts(r_costly["chp_units"]["A"]["on"])
    assert starts_costly <= starts_free, "start-up cost should not increase cycling"


def test_demand_charge_lowers_peak_import():
    # A flat load met purely by grid import. With a demand charge the model has
    # incentive to flatten the peak using the battery; without it, it does not.
    def cfg(dc):
        c = base_cfg()
        c["battery"] = {"E_cap": 50.0, "p_ch_max": 25.0, "p_dis_max": 25.0,
                        "eta_ch": 1.0, "eta_dis": 1.0, "self_disch": 0.0, "soc_init": 25.0}
        c["grid"] = {"import_max": 1000.0, "export_max": 1000.0}
        c["demand_charge"] = dc
        return c
    # Demand spikes in hour 1; flat prices so only the demand charge motivates
    # peak-shaving.
    data = make_data([0, 1, 2], [0.20] * 3, [0.05] * 3, [0.0] * 3,
                     [10.0, 40.0, 10.0], [0.0] * 3, cop=3.0)
    r_no = extract_results(_solve(cfg(0.0), data))
    r_dc = extract_results(_solve(cfg(5.0), data))
    assert r_dc["peak_import"] <= r_no["peak_import"] + 1e-6


# --- small helpers ---
def _solve(cfg, data):
    m = build_model(data, cfg); solve(m); return m


def _count_starts(on):
    starts = 0
    prev = 0
    for v in on:
        if v > 0.5 and prev < 0.5:
            starts += 1
        prev = v
    return starts
