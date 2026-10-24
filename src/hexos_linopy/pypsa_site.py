"""
hexos_linopy.pypsa_site
=======================
Step 1 of a PyPSA version of HEXOS: the demo site as a pypsa.Network.

PyPSA builds its optimisation problem with Linopy, so this is the same model
expressed with PyPSA's components instead of hand-written constraints:

  HEXOS                       PyPSA component
  --------------------------  -----------------------------------------------
  electricity / heat / fuel   Bus "el", "heat", "gas", "wood"
  grid import                 Generator, marginal cost = import price
  grid export                 Generator with p in [-export_max, 0],
                              marginal cost = export price (negative p = revenue)
  PV                          Generator, p_max_pu = availability (curtailable)
  CHP unit                    Link gas -> el (eta_el) and -> heat (bus2),
                              committable, p_min_pu, min_up_time, start-up cost
  heat pump                   Link el -> heat, time-varying efficiency = COP,
                              p_max_pu so that heat output <= q_max
  heating rod, boilers        Link
  battery, heat store         StorageUnit
  demand charge               extra_functionality (peak variable)

Why bother when hexos_linopy already exists: a PyPSA network is a standard,
shareable object. It exports to CSV/netCDF, opens in the PyPSA ecosystem, and
loads in PSA.js (the browser port of PyPSA) for a static web demo.

Covered (and parity-tested against the Pyomo model): grid limits, PV, battery,
heat storage, heat pump, rod, woodchip and gas boilers, CHP units with
min-load, minimum runtime and start-up cost, demand charge.
Not covered yet (raises): CHP ramp limits (PyPSA's committable ramp formulation
treats start-up ramps differently), max starts per day, battery wear, battery
terminal value, fixed battery schedules, cyclic storage, EVs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pypsa

from engine.model.core import normalize_chp_units
from engine.model.build import _disabled

BIG = 1e6


def _check(cfg):
    b = cfg.get("battery", {})
    bad = [k for k in ("wear", "terminal_value", "fixed_ch") if b.get(k) is not None]
    for u in normalize_chp_units(cfg):
        bad += [k for k in ("max_grad", "max_starts_per_day") if u.get(k) is not None]
    if cfg.get("evs"):
        bad.append("evs")
    if bad:
        raise NotImplementedError(f"pypsa_site step 1 does not cover: {sorted(set(bad))}")


def build_network(data, cfg, dt_hours=1.0):
    _check(cfg)
    n_t = len(data["T"])
    snaps = pd.RangeIndex(n_t, name="snapshot")
    n = pypsa.Network()
    n.set_snapshots(snaps)
    n.snapshot_weightings.loc[:, :] = dt_hours
    off = _disabled(cfg)
    S = lambda x: pd.Series(np.asarray(x, dtype=float), index=snaps)

    for bus in ("el", "heat", "gas"):
        n.add("Carrier", bus)
        n.add("Bus", bus, carrier=bus)
    n.add("Load", "site_el", bus="el", p_set=S(data["dem_el"]))
    n.add("Load", "site_heat", bus="heat", p_set=S(data["dem_heat"]))

    g = cfg.get("grid", {})
    n.add("Generator", "grid_import", bus="el", p_nom=g.get("import_max", BIG),
          marginal_cost=S(data["price_el"]))
    n.add("Generator", "grid_export", bus="el", p_nom=g.get("export_max", BIG),
          p_min_pu=-1.0, p_max_pu=0.0, marginal_cost=S(data["price_exp"]))
    pv = S(data["pv_avail"])
    if pv.max() > 0:
        n.add("Generator", "pv", bus="el", p_nom=pv.max(), p_max_pu=pv / pv.max())
    n.add("Generator", "gas_supply", bus="gas", p_nom=BIG, marginal_cost=cfg["price_gas"])

    if cfg.get("allow_heat_dump", False):
        n.add("Generator", "heat_dump", bus="heat", p_nom=BIG, p_min_pu=-1.0, p_max_pu=0.0)

    for u in normalize_chp_units(cfg):
        p_nom_gas = u["p_el_max"] / u["eta_el"]
        L = int(u.get("min_runtime_h", 1))
        n.add("Link", f"chp_{u['name']}", bus0="gas", bus1="el", bus2="heat",
              efficiency=u["eta_el"], efficiency2=u["eta_el"] * u["htp_ratio"],
              p_nom=p_nom_gas, committable=True, p_min_pu=u["min_load"],
              min_up_time=L if L > 1 else 0, start_up_cost=u.get("startup_cost", 0.0),
              up_time_before=int(u.get("on_init", 0)))

    if "heatpump" not in off:
        cop = S(data["cop"])
        q = cfg["heatpump"]["q_max"]
        p_nom = q / cop.min()
        n.add("Link", "heatpump", bus0="el", bus1="heat", p_nom=p_nom,
              efficiency=cop, p_max_pu=(q / cop) / p_nom)
    if "rod" not in off:
        r = cfg["rod"]
        n.add("Link", "rod", bus0="el", bus1="heat", p_nom=r["q_max"] / r["eta"],
              efficiency=r["eta"])
    # Boilers: each has its own fuel bus and price, as in HEXOS (gas-boiler fuel
    # is priced separately from the CHP's gas).
    for key, fuel_bus in (("woodchip", "wood"), ("gas_boiler", "gas_b")):
        if key in off:
            continue
        bc = cfg[key]
        if fuel_bus not in n.buses.index:
            n.add("Carrier", fuel_bus)
            n.add("Bus", fuel_bus, carrier=fuel_bus)
        n.add("Generator", f"{fuel_bus}_supply", bus=fuel_bus, p_nom=BIG,
              marginal_cost=bc.get("fuel_price", 0.0))
        n.add("Link", key, bus0=fuel_bus, bus1="heat", p_nom=bc["q_max"] / bc["eta"],
              efficiency=bc["eta"])

    def store(name, bus, s):
        p_nom = max(s["p_ch_max"], s["p_dis_max"])
        if p_nom <= 0 or s["E_cap"] <= 0:
            return
        n.add("StorageUnit", name, bus=bus, p_nom=p_nom, max_hours=s["E_cap"] / p_nom,
              p_max_pu=s["p_dis_max"] / p_nom, p_min_pu=-s["p_ch_max"] / p_nom,
              efficiency_store=s["eta_ch"], efficiency_dispatch=s["eta_dis"],
              standing_loss=s["self_disch"], state_of_charge_initial=s["soc_init"],
              cyclic_state_of_charge=False)

    if "battery" not in off:
        store("battery", "el", cfg["battery"])
    if "heat_storage" not in off:
        store("heat_store", "heat", cfg["heat_storage"])
    return n


def _demand_charge(cfg):
    dc = cfg.get("demand_charge", 0.0)
    floor = cfg.get("peak_so_far", 0.0)

    def extra(n, snapshots):
        if not dc:
            return
        m = n.model
        peak = m.add_variables(lower=max(floor, 0.0), name="peak_import")
        p = m["Generator-p"].sel(name="grid_import")
        m.add_constraints(peak - p >= 0, name="peak_track")
        m.objective = m.objective + dc * peak
    return extra


def solve_network(n, cfg):
    status, cond = n.optimize(solver_name="highs", extra_functionality=_demand_charge(cfg),
                              solver_options={"output_flag": False},
                              include_objective_constant=False)
    if status != "ok":
        raise RuntimeError(f"PyPSA/HiGHS failed: {status} {cond}")
    return n


def extract_network(n):
    G = n.generators_t.p
    out = {
        "import": G["grid_import"].tolist(),
        "export": (-G["grid_export"]).tolist(),
        "pv_used": G["pv"].tolist() if "pv" in G else [0.0] * len(G),
        "cost": float(n.objective),
    }
    su = n.storage_units_t
    if "battery" in n.storage_units.index:
        out["charge"] = (-su.p["battery"].clip(upper=0)).tolist()
        out["discharge"] = su.p["battery"].clip(lower=0).tolist()
        out["soc"] = su.state_of_charge["battery"].tolist()
    chp = [l for l in n.links.index if l.startswith("chp_")]
    out["chp_el"] = (-n.links_t.p1[chp].sum(axis=1)).tolist() if chp else [0.0] * len(G)
    out["chp_on"] = n.links_t.status[chp].sum(axis=1).tolist() if chp else [0.0] * len(G)
    return out


def run_pypsa(data, cfg, dt_hours=1.0):
    n = build_network(data, cfg, dt_hours)
    solve_network(n, cfg)
    return n, extract_network(n)
