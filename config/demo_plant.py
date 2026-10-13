"""demo_plant.py — the example site used across HEXOS scenarios.

Realistic but fictional. Sizes are round numbers chosen to be plausible for a
mid-sized German industrial site, not taken from any real plant.
"""


def demo_plant_cfg():
    return {
        "price_gas": 0.07,
        "grid": {"import_max": 1200.0, "export_max": 1200.0},
        "battery": {
            "E_cap": 400.0,
            "p_ch_max": 200.0,
            "p_dis_max": 200.0,
            "eta_ch": 0.96,
            "eta_dis": 0.96,
            "self_disch": 0.0005,
            "soc_init": 0.0,
        },
        "chp": {
            "p_el_max": 200.0,
            "eta_el": 0.4,
            "htp_ratio": 1.5,
            "min_load": 0.4,
        },
        "heatpump": {"q_max": 400.0},
        "rod": {"q_max": 300.0, "eta": 0.99},
        "heat_storage": {
            "E_cap": 1500.0,
            "p_ch_max": 400.0,
            "p_dis_max": 400.0,
            "eta_ch": 0.98,
            "eta_dis": 0.98,
            "self_disch": 0.002,
            "soc_init": 0.0,
        },
    }


def ev_fleet_day():
    """A small EV fleet for a single-day (24 h) demo. Each vehicle needs a set
    energy by end of day, chargeable within a window."""
    return [
        {"name": "EV1", "p_max": 11.0, "energy_need": 40.0, "start_t": 0, "end_t": 7},
        {"name": "EV2", "p_max": 11.0, "energy_need": 30.0, "start_t": 0, "end_t": 9},
        {"name": "EV3", "p_max": 22.0, "energy_need": 60.0, "start_t": 6, "end_t": 18},
        {"name": "EV4", "p_max": 11.0, "energy_need": 25.0, "start_t": 12, "end_t": 23},
    ]
