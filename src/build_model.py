"""
build_model.py
==============
Assemble, solve, and read back the HEXOS model.

The config dict drives everything. A technology is "disabled" when its key
capacity is 0 (or its sub-dict is absent); disabled technologies get their
variables locked to zero so they cannot be used.

Config shape (see scenarios/ for full examples):
    cfg = {
      "price_gas": 0.07,
      "battery":      {... or E_cap=0 to disable},
      "chp":          {... or p_el_max=0 to disable},
      "heatpump":     {... or q_max=0 to disable},
      "rod":          {... or q_max=0 to disable},
      "heat_storage": {... or E_cap=0 to disable},
    }
"""

from __future__ import annotations
import pyomo.environ as pyo

import model_core
import constraints as C
import objective


def _is_disabled(cfg: dict) -> set:
    """Return the set of technology names that are switched off."""
    off = set()
    if cfg.get("battery", {}).get("E_cap", 0) <= 0:
        off.add("battery")
    if cfg.get("chp", {}).get("p_el_max", 0) <= 0:
        off.add("chp")
    if cfg.get("heatpump", {}).get("q_max", 0) <= 0:
        off.add("heatpump")
    if cfg.get("rod", {}).get("q_max", 0) <= 0:
        off.add("rod")
    if cfg.get("heat_storage", {}).get("E_cap", 0) <= 0:
        off.add("heat_storage")
    return off


def build_model(data: dict, cfg: dict, dt_hours: float = 1.0,
                cyclic: bool = True) -> pyo.ConcreteModel:
    m = pyo.ConcreteModel(name="HEXOS")

    model_core.declare_sets_params(m, data, cfg, dt_hours)
    model_core.declare_variables(m)

    disabled = _is_disabled(cfg)

    # Always-present bus balances.
    C.add_electricity_balance(m)
    C.add_heat_balance(m)
    C.add_pv(m)

    # Optional grid capacity limit (recommended for realistic price data).
    if "grid" in cfg:
        C.add_grid(m, cfg["grid"])

    # Technology blocks: add the relation/limits when enabled.
    if "battery" not in disabled:
        C.add_battery(m, cfg["battery"], cyclic=cyclic)
    if "chp" not in disabled:
        C.add_chp(m, cfg["chp"])
    if "heatpump" not in disabled:
        C.add_heatpump(m, cfg["heatpump"])
    if "rod" not in disabled:
        C.add_rod(m, cfg["rod"])
    if "heat_storage" not in disabled:
        C.add_heat_storage(m, cfg["heat_storage"], cyclic=cyclic)

    # Lock the disabled ones to zero.
    C.add_disabled_locks(m, disabled)

    objective.add_objective(m)
    return m


def solve(m: pyo.ConcreteModel, tee: bool = False):
    """Solve with HiGHS. Uses the plain SolverFactory interface (handles MILP)."""
    solver = pyo.SolverFactory("appsi_highs")
    return solver.solve(m, tee=tee)


def extract_results(m: pyo.ConcreteModel) -> dict:
    T = list(m.T)
    g = lambda v: [pyo.value(v[t]) for t in T]
    return {
        "t": T,
        "import": g(m.p_import), "export": g(m.p_export),
        "pv_used": g(m.pv_used),
        "charge": g(m.p_ch), "discharge": g(m.p_dis), "soc": g(m.soc),
        "chp_gas": g(m.chp_gas), "chp_el": g(m.chp_el), "chp_heat": g(m.chp_heat),
        "chp_on": g(m.chp_on),
        "hp_el": g(m.hp_el), "hp_heat": g(m.hp_heat),
        "rod_el": g(m.rod_el), "rod_heat": g(m.rod_heat),
        "h_charge": g(m.h_ch), "h_discharge": g(m.h_dis), "h_soc": g(m.h_soc),
        "cost": pyo.value(m.cost),
    }
