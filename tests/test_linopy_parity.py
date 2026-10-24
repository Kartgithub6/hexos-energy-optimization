"""The Linopy backend must reach the same optimum as the Pyomo model, feature by
feature. Both hand the same MILP to HiGHS, which stops inside its default 1e-4
relative MIP gap, so objectives are compared to that gap. Pure LPs agree far
tighter in practice."""
import copy
import os

import pytest

linopy = pytest.importorskip("linopy")

from engine import make_data, build_model, solve, extract_results, solve_rolling  # noqa: E402
from hexos_linopy import run_linopy, build_linopy  # noqa: E402
from helpers import base_cfg, with_battery  # noqa: E402

REL = 1e-4     # HiGHS default mip_rel_gap


def _pyomo(data, cfg, cyclic=True):
    m = build_model(data, cfg, cyclic=cyclic)
    solve(m)
    return extract_results(m)


def _same(data, cfg, cyclic=True):
    a = _pyomo(data, cfg, cyclic)
    b = run_linopy(data, cfg, cyclic=cyclic)
    assert abs(a["cost"] - b["cost"]) <= REL * max(1.0, abs(a["cost"])), (a["cost"], b["cost"])
    return a, b


def _day(n=24, seed=0):
    import math
    price = [0.20 + 0.12 * math.sin(2 * math.pi * (t - 6) / 24) for t in range(n)]
    pv = [max(0.0, 8 * math.sin(math.pi * (t % 24 - 6) / 12)) for t in range(n)]
    return make_data(list(range(n)), price, [0.05] * n, pv, [6.0 + (t % 5) for t in range(n)],
                     [10.0 + 4 * math.cos(2 * math.pi * t / 24) for t in range(n)],
                     cop=[3.0 + 0.3 * math.sin(t / 3) for t in range(n)])


def _site():
    cfg = with_battery(base_cfg(), 20.0, 8.0)
    cfg["battery"].update(eta_ch=0.95, eta_dis=0.95, self_disch=0.001)
    cfg["chp"] = {"p_el_max": 10.0, "eta_el": 0.38, "htp_ratio": 1.4, "min_load": 0.4}
    cfg["heatpump"] = {"q_max": 12.0}
    cfg["rod"] = {"q_max": 10.0, "eta": 0.99}
    cfg["heat_storage"] = {"E_cap": 30.0, "p_ch_max": 10.0, "p_dis_max": 10.0,
                           "eta_ch": 0.98, "eta_dis": 0.98, "self_disch": 0.002, "soc_init": 5.0}
    cfg["grid"] = {"import_max": 40.0, "export_max": 20.0}
    return cfg


def test_full_site_day():
    a, b = _same(_day(), _site())
    assert abs(sum(a["import"]) - sum(b["import"])) < 1e-3 * max(1, sum(a["import"]))


def test_non_cyclic():
    _same(_day(), _site(), cyclic=False)


def test_battery_only():
    d = _day()
    d["dem_heat"] = [0.0] * len(d["T"])       # no heat units in this config
    _same(d, with_battery(base_cfg(), 10.0, 5.0))


@pytest.mark.parametrize("extra", [
    {"startup_cost": 5.0},
    {"min_runtime_h": 4},
    {"max_grad": 3.0},
    {"max_starts_per_day": 1},
    {"on_init": 1, "startup_cost": 5.0},
    {"max_starts_per_day": 1, "su_hist": [0] * 20 + [1, 0, 0]},
])
def test_chp_features(extra):
    cfg = _site()
    cfg["chp"].update(extra)
    _same(_day(36), cfg, cyclic=False)


def test_multi_chp():
    cfg = _site()
    cfg.pop("chp")
    cfg["chps"] = [
        {"name": "big", "p_el_max": 10.0, "eta_el": 0.40, "htp_ratio": 1.2, "min_load": 0.5,
         "min_runtime_h": 3, "startup_cost": 4.0},
        {"name": "small", "p_el_max": 4.0, "eta_el": 0.33, "htp_ratio": 1.6, "min_load": 0.3},
    ]
    _same(_day(), cfg)


def test_boilers_and_heat_dump():
    cfg = _site()
    cfg["woodchip"] = {"q_max": 8.0, "eta": 0.85, "fuel_price": 0.03}
    cfg["gas_boiler"] = {"q_max": 8.0, "eta": 0.92, "fuel_price": 0.06}
    cfg["allow_heat_dump"] = True
    _same(_day(), cfg)


def test_demand_charge_peak_floor_terminal_value():
    cfg = _site()
    cfg["demand_charge"] = 2.0
    cfg["peak_so_far"] = 12.0
    cfg["battery"]["terminal_value"] = "auto"
    _same(_day(), cfg, cyclic=False)


def test_fixed_battery_schedule():
    cfg = _site()
    n = 24
    cfg["battery"]["fixed_ch"] = [4.0 if 10 <= t < 14 else 0.0 for t in range(n)]
    cfg["battery"]["fixed_dis"] = [3.0 if 18 <= t < 22 else 0.0 for t in range(n)]
    _same(_day(n), cfg, cyclic=False)


@pytest.mark.parametrize("model", ["throughput", "cycle_depth"])
def test_wear_models(model):
    cfg = _site()
    cfg["battery"]["wear"] = {"model": model, "capex_eur_per_kwh": 150.0,
                              "cycle_life_efc": 3000, "dod_exponent": 1.7, "segments": 4}
    _same(_day(48), cfg)


def test_rolling_backends_agree():
    cfg = _site()
    data = _day(24 * 5)
    a = solve_rolling(data, cfg, window_h=36, commit_h=24, verbose=False)
    b = solve_rolling(data, cfg, window_h=36, commit_h=24, verbose=False, backend="linopy")
    assert abs(a["cost"] - b["cost"]) <= 1e-5 * abs(a["cost"])


def test_evs_not_ported():
    cfg = _site()
    cfg["evs"] = [{"name": "EV1", "p_max": 11.0, "energy_need": 20.0, "start_t": 0, "end_t": 7}]
    with pytest.raises(NotImplementedError):
        build_linopy(_day(), cfg)


DATA = os.path.join(os.path.dirname(__file__), "..", "data", "year_DE_2024.csv")


@pytest.mark.slow
@pytest.mark.skipif(not os.path.exists(DATA), reason="needs data/year_DE_2024.csv")
def test_demo_plant_real_week():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))
    import demo_plant
    from engine import load_timeseries
    d = load_timeseries(DATA)
    w = {k: (v[4000:4168] if isinstance(v, list) else v) for k, v in d.items()}
    w["T"] = list(range(168))
    _same(w, demo_plant.demo_plant_cfg(), cyclic=False)


# ------------------------------------------------------------ PyPSA step 1
pypsa = pytest.importorskip("pypsa")


def _pypsa_same(data, cfg):
    from hexos_linopy.pypsa_site import run_pypsa
    a = _pyomo(data, cfg, cyclic=False)
    _, b = run_pypsa(data, cfg)
    # PyPSA builds a different (but equivalent) MILP, so HiGHS can stop at a
    # different point inside its default 1e-4 relative MIP gap.
    assert abs(a["cost"] - b["cost"]) <= 1e-4 * max(1.0, abs(a["cost"])), (a["cost"], b["cost"])
    return a, b


def test_pypsa_full_site():
    _pypsa_same(_day(), _site())


def test_pypsa_chp_minrun_startup_and_boilers():
    cfg = _site()
    cfg["chp"].update(min_runtime_h=4, startup_cost=5.0)
    cfg["woodchip"] = {"q_max": 8.0, "eta": 0.85, "fuel_price": 0.03}
    cfg["gas_boiler"] = {"q_max": 8.0, "eta": 0.92, "fuel_price": 0.06}
    _pypsa_same(_day(36), cfg)


def test_pypsa_demand_charge():
    cfg = _site()
    cfg["demand_charge"] = 2.0
    _pypsa_same(_day(), cfg)


def test_pypsa_refuses_what_it_does_not_cover():
    from hexos_linopy.pypsa_site import build_network
    cfg = _site()
    cfg["battery"]["wear"] = {"model": "throughput", "capex_eur_per_kwh": 1, "cycle_life_efc": 1}
    with pytest.raises(NotImplementedError):
        build_network(_day(), cfg)
