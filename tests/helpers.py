"""Shared test helpers and config builders."""
from engine import make_data, build_model, solve, extract_results

TOL = 1e-5


def base_cfg():
    """Every technology OFF; tests switch on only what they need."""
    return {
        "price_gas": 0.07,
        "battery": {"E_cap": 0, "p_ch_max": 0, "p_dis_max": 0,
                    "eta_ch": 1, "eta_dis": 1, "self_disch": 0, "soc_init": 0},
        "chp": {"p_el_max": 0, "eta_el": 0.4, "htp_ratio": 1.5, "min_load": 0.5},
        "heatpump": {"q_max": 0},
        "rod": {"q_max": 0, "eta": 0.99},
        "heat_storage": {"E_cap": 0, "p_ch_max": 0, "p_dis_max": 0,
                         "eta_ch": 1, "eta_dis": 1, "self_disch": 0, "soc_init": 0},
    }


def with_battery(cfg, E_cap=10.0, p=5.0):
    cfg["battery"] = {"E_cap": E_cap, "p_ch_max": p, "p_dis_max": p,
                      "eta_ch": 1.0, "eta_dis": 1.0, "self_disch": 0.0, "soc_init": 0.0}
    return cfg


def run(data, cfg):
    m = build_model(data, cfg)
    solve(m)
    return extract_results(m)


def mixed_system():
    cfg = with_battery(base_cfg(), 10.0, 5.0)
    cfg["rod"] = {"q_max": 50.0, "eta": 0.99}
    cfg["heatpump"] = {"q_max": 50.0}
    cfg["chp"] = {"p_el_max": 30.0, "eta_el": 0.4, "htp_ratio": 1.5, "min_load": 0.3}
    cfg["heat_storage"] = {"E_cap": 15.0, "p_ch_max": 10.0, "p_dis_max": 10.0,
                           "eta_ch": 0.95, "eta_dis": 0.95, "self_disch": 0.01, "soc_init": 0.0}
    data = make_data(list(range(6)),
                     [0.20, 0.35, 0.10, 0.40, 0.15, 0.30], [0.05] * 6,
                     [0, 2, 8, 0, 6, 1], [3, 3, 3, 5, 2, 4], [4, 5, 6, 3, 2, 7],
                     cop=[3.0, 3.2, 3.5, 2.8, 2.5, 3.1])
    m = build_model(data, cfg); solve(m)
    return data, extract_results(m)
