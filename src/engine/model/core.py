"""
engine.model.core
================
Declares model structure: sets (time, CHP units, EV chargers), parameters, and
all decision variables, including the step-6/7 additions:
  - gas boiler (alongside woodchip boiler)
  - EV charging (controllable loads with energy-by-deadline)
  - peak-demand tracking (for the demand charge)
  - CHP start-up flags (for min-runtime and start-up cost)
"""

from __future__ import annotations
import pyomo.environ as pyo


def normalize_chp_units(cfg: dict) -> list:
    if "chps" in cfg:
        raw = cfg["chps"]
    elif cfg.get("chp", {}).get("p_el_max", 0) > 0:
        raw = [cfg["chp"]]
    else:
        raw = []
    out = []
    for i, u in enumerate(raw):
        if u.get("p_el_max", 0) <= 0:
            continue
        v = dict(u)
        v.setdefault("name", f"CHP{i + 1}")
        v.setdefault("min_runtime_h", 1)
        v.setdefault("max_grad", None)
        v.setdefault("startup_cost", 0.0)
        out.append(v)
    return out


def ev_chargers(cfg: dict) -> list:
    """EV charging sessions. Each: name, p_max [kW], energy_need [kWh],
    window [start_t, end_t] (inclusive) within which the energy must be met.
    """
    out = []
    for i, e in enumerate(cfg.get("evs", [])):
        v = dict(e)
        v.setdefault("name", f"EV{i + 1}")
        out.append(v)
    return out


def declare_sets_params(m, data, cfg, dt_hours):
    m.T = pyo.Set(initialize=data["T"], ordered=True)
    m.dt = dt_hours

    units = normalize_chp_units(cfg)
    m.chp_units = units
    m.chp_par = {u["name"]: u for u in units}
    m.CHP = pyo.Set(initialize=[u["name"] for u in units], ordered=True)

    evs = ev_chargers(cfg)
    m.ev_list = evs
    m.ev_par = {e["name"]: e for e in evs}
    m.EV = pyo.Set(initialize=[e["name"] for e in evs], ordered=True)

    m.price_el = pyo.Param(m.T, initialize=dict(enumerate(data["price_el"])))
    m.price_exp = pyo.Param(m.T, initialize=dict(enumerate(data["price_exp"])))
    m.pv_avail = pyo.Param(m.T, initialize=dict(enumerate(data["pv_avail"])))
    m.dem_el = pyo.Param(m.T, initialize=dict(enumerate(data["dem_el"])))
    m.dem_heat = pyo.Param(m.T, initialize=dict(enumerate(data["dem_heat"])))
    m.cop = pyo.Param(m.T, initialize=dict(enumerate(data["cop"])))

    m.cfg = cfg
    m.price_gas = cfg["price_gas"]


def declare_variables(m):
    NN = pyo.NonNegativeReals
    UB01 = dict(domain=NN, bounds=(0, 1))

    m.p_import = pyo.Var(m.T, domain=NN)
    m.p_export = pyo.Var(m.T, domain=NN)
    m.pv_used = pyo.Var(m.T, domain=NN)

    m.p_ch = pyo.Var(m.T, domain=NN)
    m.p_dis = pyo.Var(m.T, domain=NN)
    m.soc = pyo.Var(m.T, domain=NN)

    m.chp_gas = pyo.Var(m.CHP, m.T, domain=NN)
    m.chp_el = pyo.Var(m.CHP, m.T, domain=NN)
    m.chp_heat = pyo.Var(m.CHP, m.T, domain=NN)
    m.chp_on = pyo.Var(m.CHP, m.T, domain=pyo.Binary)
    m.chp_su = pyo.Var(m.CHP, m.T, **UB01)

    # Boilers: woodchip and gas (fuel -> heat).
    m.wood_fuel = pyo.Var(m.T, domain=NN)
    m.wood_heat = pyo.Var(m.T, domain=NN)
    m.gas_fuel = pyo.Var(m.T, domain=NN)
    m.gas_heat = pyo.Var(m.T, domain=NN)

    m.hp_el = pyo.Var(m.T, domain=NN)
    m.hp_heat = pyo.Var(m.T, domain=NN)

    m.rod_el = pyo.Var(m.T, domain=NN)
    m.rod_heat = pyo.Var(m.T, domain=NN)

    m.h_ch = pyo.Var(m.T, domain=NN)
    m.h_dis = pyo.Var(m.T, domain=NN)
    m.h_soc = pyo.Var(m.T, domain=NN)
    m.h_curtail = pyo.Var(m.T, domain=NN)

    # EV charging power per charger per time.
    m.ev_p = pyo.Var(m.EV, m.T, domain=NN)

    # Peak electrical demand (kW) for the demand charge: tracks the highest
    # grid import over the horizon.
    m.peak_import = pyo.Var(domain=NN)
