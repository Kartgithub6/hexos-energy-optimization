"""
hexos.model.build
=================
Assemble the model from core + technologies + objective, enabling each
technology by its config presence/capacity.
"""
import pyomo.environ as pyo

from engine.model import core, objective
from engine.technologies import (balances, grid, pv, battery, chp, boiler,
                                 heatpump, rod, heat_storage, ev, curtail)


def _disabled(cfg):
    off = set()
    if cfg.get("battery", {}).get("E_cap", 0) <= 0:
        off.add("battery")
    if cfg.get("woodchip", {}).get("q_max", 0) <= 0:
        off.add("woodchip")
    if cfg.get("gas_boiler", {}).get("q_max", 0) <= 0:
        off.add("gas_boiler")
    if cfg.get("heatpump", {}).get("q_max", 0) <= 0:
        off.add("heatpump")
    if cfg.get("rod", {}).get("q_max", 0) <= 0:
        off.add("rod")
    if cfg.get("heat_storage", {}).get("E_cap", 0) <= 0:
        off.add("heat_storage")
    return off


def build_model(data, cfg, dt_hours=1.0, cyclic=True):
    m = pyo.ConcreteModel(name="HEXOS")
    core.declare_sets_params(m, data, cfg, dt_hours)
    core.declare_variables(m)

    off = _disabled(cfg)

    balances.add_electricity_balance(m)
    balances.add_heat_balance(m)
    balances.add_peak_tracking(m)
    pv.add_pv(m)

    if "grid" in cfg:
        grid.add_grid(m, cfg["grid"])
    if len(m.CHP) > 0:
        chp.add_chp(m)
    if len(m.EV) > 0:
        ev.add_ev(m)
    if "battery" not in off:
        battery.add_battery(m, cfg["battery"], cyclic=cyclic)
    if "woodchip" not in off:
        boiler.add_woodchip(m, cfg["woodchip"])
    if "gas_boiler" not in off:
        boiler.add_gas_boiler(m, cfg["gas_boiler"])
    if "heatpump" not in off:
        heatpump.add_heatpump(m, cfg["heatpump"])
    if "rod" not in off:
        rod.add_rod(m, cfg["rod"])
    if "heat_storage" not in off:
        heat_storage.add_heat_storage(m, cfg["heat_storage"], cyclic=cyclic)

    curtail.add_curtail_lock(m)
    curtail.add_disabled_locks(m, off)

    objective.add_objective(m)
    return m
