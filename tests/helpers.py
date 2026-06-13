"""
helpers.py
==========
Shared building blocks for the test suite: small config builders so each test
only has to switch on the technologies it actually exercises, plus a mixed
multi-technology system used for the balance-invariant checks.
"""

import data_io as D
import build_model as B

TOL = 1e-5


def base_cfg():
    """A config with every technology switched OFF (capacity 0).

    Each test turns on just what it needs, which keeps the expected result
    simple enough to verify by hand.
    """
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
    """Switch on a lossless battery (easy to reason about by hand)."""
    cfg["battery"] = {"E_cap": E_cap, "p_ch_max": p, "p_dis_max": p,
                      "eta_ch": 1.0, "eta_dis": 1.0, "self_disch": 0.0, "soc_init": 0.0}
    return cfg


def mixed_system():
    """A six-hour system with every technology active and lossy storages.

    Returns (data, results). Used by the balance-invariant tests, which must
    hold for *any* feasible solution regardless of the specific dispatch.
    """
    cfg = with_battery(base_cfg(), 10.0, 5.0)
    cfg["rod"] = {"q_max": 50.0, "eta": 0.99}
    cfg["heatpump"] = {"q_max": 50.0}
    cfg["chp"] = {"p_el_max": 30.0, "eta_el": 0.4, "htp_ratio": 1.5, "min_load": 0.3}
    cfg["heat_storage"] = {"E_cap": 15.0, "p_ch_max": 10.0, "p_dis_max": 10.0,
                           "eta_ch": 0.95, "eta_dis": 0.95, "self_disch": 0.01,
                           "soc_init": 0.0}
    data = D.make_data(
        list(range(6)),
        [0.20, 0.35, 0.10, 0.40, 0.15, 0.30],
        [0.05] * 6,
        [0, 2, 8, 0, 6, 1],
        [3, 3, 3, 5, 2, 4],
        [4, 5, 6, 3, 2, 7],
        cop=[3.0, 3.2, 3.5, 2.8, 2.5, 3.1],
    )
    m = B.build_model(data, cfg)
    B.solve(m)
    return data, B.extract_results(m)
