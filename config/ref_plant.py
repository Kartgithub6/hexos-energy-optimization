"""
config/ref_plant.py
===================
A FICTIONAL reference industrial site for realistic HEXOS runs.

Values are invented to be plausible for the category (a mid-size German
industrial site) and are not taken from any real plant. They exist so the model
can be exercised on something realistic.

Components: PV, 3 CHP units, woodchip boiler, gas (condensing) boiler, heating
rods, battery, heat storage. EV chargers are provided separately (EV scheduling
uses a single-horizon solve, not the rolling year solve).
"""


def ref_plant_cfg():
    return {
        "price_gas": 0.065,
        "allow_heat_dump": True,
        "demand_charge": 90.0,                 # EUR per kW of annual peak (Lastspitze)
        "grid": {"import_max": 2500.0, "export_max": 2500.0},
        "chps": [
            {"name": "CHP1", "p_el_max": 500.0, "eta_el": 0.42, "htp_ratio": 1.05,
             "min_load": 0.50, "min_runtime_h": 8, "max_grad": 150.0, "startup_cost": 20.0},
            {"name": "CHP2", "p_el_max": 500.0, "eta_el": 0.42, "htp_ratio": 1.05,
             "min_load": 0.55, "min_runtime_h": 8, "max_grad": 150.0, "startup_cost": 20.0},
            {"name": "CHP3", "p_el_max": 250.0, "eta_el": 0.38, "htp_ratio": 1.20,
             "min_load": 0.65, "min_runtime_h": 8, "max_grad": 80.0, "startup_cost": 12.0},
        ],
        "woodchip": {"q_max": 900.0, "eta": 0.88, "fuel_price": 0.028},
        "gas_boiler": {"q_max": 600.0, "eta": 0.92, "fuel_price": 0.065},
        "heatpump": {"q_max": 0.0},
        "rod": {"q_max": 300.0, "eta": 0.99},
        "battery": {"E_cap": 1000.0, "p_ch_max": 350.0, "p_dis_max": 350.0,
                    "eta_ch": 0.96, "eta_dis": 0.96, "self_disch": 0.0005, "soc_init": 0.0},
        "heat_storage": {"E_cap": 2500.0, "p_ch_max": 1000.0, "p_dis_max": 1000.0,
                         "eta_ch": 0.98, "eta_dis": 0.98, "self_disch": 0.002, "soc_init": 0.0},
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
