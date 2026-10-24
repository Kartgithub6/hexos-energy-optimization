"""
hexos_linopy.model
==================
The HEXOS site model written with Linopy instead of Pyomo.

Same variables, same constraints, same objective as engine.model.build, so the
two must reach the same optimum (tests/test_linopy_parity.py checks this on
every technology). What changes is HOW the model is built:

  Pyomo   one Python object per variable and per constraint, built in a loop
          over hours with rule functions.
  Linopy  one labelled n-dimensional array per variable (dims: time, unit,
          segment), constraints written as array expressions; time-coupling
          via .shift(). The arrays are handed to HiGHS in one block.

Reference: Hofmann, F. (2023). Linopy: Linear optimization with n-dimensional
labeled variables. Journal of Open Source Software 8(84), 4823.
doi:10.21105/joss.04823

Not ported (raises): EV charging sessions. Everything else in the demo plant
and the test configs is covered, including the wear models.
"""
from __future__ import annotations

import statistics

import numpy as np
import pandas as pd
import linopy

from engine.model.core import normalize_chp_units
from engine.model.build import _disabled
from engine.technologies.wear import wear_cfg, throughput_cost, segment_costs, initial_split


def _lag(x, k=1):
    """x[t-k], with the k slots before the window contributing nothing."""
    return x.shift(T=k).fillna(0)


def _arr(x, T):
    return pd.Series(np.asarray(x, dtype=float), index=T)


def build_linopy(data, cfg, dt_hours=1.0, cyclic=True):
    """Return (model, handles) where handles maps names to linopy Variables."""
    if cfg.get("evs"):
        raise NotImplementedError("EV sessions are not ported to the Linopy backend yet")
    dt = dt_hours
    T = pd.RangeIndex(len(data["T"]), name="T")
    m = linopy.Model(force_dim_names=True)
    off = _disabled(cfg)
    units = normalize_chp_units(cfg)
    U = pd.Index([u["name"] for u in units], name="U")
    par = {u["name"]: u for u in units}

    price_el, price_exp = _arr(data["price_el"], T), _arr(data["price_exp"], T)
    pv_avail, dem_el = _arr(data["pv_avail"], T), _arr(data["dem_el"], T)
    dem_heat, cop = _arr(data["dem_heat"], T), _arr(data["cop"], T)

    def var(name, ub=np.inf, coords=(T,), binary=False):
        if binary:
            return m.add_variables(coords=list(coords), name=name, binary=True)
        return m.add_variables(lower=0, upper=ub, coords=list(coords), name=name)

    g = cfg.get("grid", {})
    p_import = var("p_import", g.get("import_max", np.inf))
    p_export = var("p_export", g.get("export_max", np.inf))
    pv_used = var("pv_used", pv_avail)

    b = cfg.get("battery", {})
    batt_on = "battery" not in off
    E = b.get("E_cap", 0.0) if batt_on else 0.0
    p_ch = var("p_ch", b.get("p_ch_max", 0.0) if batt_on else 0.0)
    p_dis = var("p_dis", b.get("p_dis_max", 0.0) if batt_on else 0.0)
    soc = var("soc", E)

    s = cfg.get("heat_storage", {})
    hs_on = "heat_storage" not in off
    h_ch = var("h_ch", s.get("p_ch_max", 0.0) if hs_on else 0.0)
    h_dis = var("h_dis", s.get("p_dis_max", 0.0) if hs_on else 0.0)
    h_soc = var("h_soc", s.get("E_cap", 0.0) if hs_on else 0.0)
    h_curtail = var("h_curtail", np.inf if cfg.get("allow_heat_dump", False) else 0.0)

    hp = cfg.get("heatpump", {})
    hp_el = var("hp_el", np.inf if "heatpump" not in off else 0.0)
    hp_heat = var("hp_heat", hp.get("q_max", 0.0) if "heatpump" not in off else 0.0)
    rod = cfg.get("rod", {})
    rod_el = var("rod_el", np.inf if "rod" not in off else 0.0)
    rod_heat = var("rod_heat", rod.get("q_max", 0.0) if "rod" not in off else 0.0)
    wd = cfg.get("woodchip", {})
    wood_fuel = var("wood_fuel", np.inf if "woodchip" not in off else 0.0)
    wood_heat = var("wood_heat", wd.get("q_max", 0.0) if "woodchip" not in off else 0.0)
    gb = cfg.get("gas_boiler", {})
    gas_fuel = var("gas_fuel", np.inf if "gas_boiler" not in off else 0.0)
    gas_heat = var("gas_heat", gb.get("q_max", 0.0) if "gas_boiler" not in off else 0.0)

    peak = m.add_variables(lower=0, name="peak_import")

    has_chp = len(units) > 0
    if has_chp:
        chp_gas = var("chp_gas", coords=(U, T))
        chp_el = var("chp_el", coords=(U, T))
        chp_heat = var("chp_heat", coords=(U, T))
        chp_on = var("chp_on", coords=(U, T), binary=True)
        chp_su = m.add_variables(lower=0, upper=1, coords=[U, T], name="chp_su")
        el_sum, heat_sum, gas_sum = chp_el.sum("U"), chp_heat.sum("U"), chp_gas.sum("U")
    else:
        el_sum = heat_sum = gas_sum = 0

    # ---- balances
    m.add_constraints(p_import + pv_used + p_dis + el_sum - p_export - p_ch - hp_el - rod_el
                      == dem_el, name="elec_balance")
    m.add_constraints(heat_sum + wood_heat + gas_heat + hp_heat + rod_heat + h_dis
                      - h_ch - h_curtail == dem_heat, name="heat_balance")
    m.add_constraints(peak - p_import >= 0, name="peak_track")
    floor = cfg.get("peak_so_far", 0.0)
    if floor > 0:
        m.add_constraints(peak >= floor, name="peak_floor")

    # ---- conversion units
    m.add_constraints(hp_heat - cop * hp_el == 0, name="hp_conv")
    m.add_constraints(rod_heat - rod.get("eta", 1.0) * rod_el == 0, name="rod_conv")
    m.add_constraints(wood_heat - wd.get("eta", 1.0) * wood_fuel == 0, name="wood_conv")
    m.add_constraints(gas_heat - gb.get("eta", 1.0) * gas_fuel == 0, name="gas_conv")

    # ---- CHP units (per unit: few units, many hours)
    if has_chp:
        eta = pd.Series({c: par[c]["eta_el"] for c in U}, index=U)
        htp = pd.Series({c: par[c]["htp_ratio"] for c in U}, index=U)
        pmax = pd.Series({c: par[c]["p_el_max"] for c in U}, index=U)
        pmin = pd.Series({c: par[c]["min_load"] * par[c]["p_el_max"] for c in U}, index=U)
        m.add_constraints(chp_el - eta * chp_gas == 0, name="chp_el_eff")
        m.add_constraints(chp_heat - htp * chp_el == 0, name="chp_coupling")
        m.add_constraints(chp_el - pmax * chp_on <= 0, name="chp_max")
        m.add_constraints(chp_el - pmin * chp_on >= 0, name="chp_min")
        for c in U:
            on, su, el = chp_on.sel(U=c), chp_su.sel(U=c), chp_el.sel(U=c)
            u = par[c]
            # start-up flag: su[t] >= on[t] - on[t-1], with on[-1] = on_init
            m.add_constraints((su - on + _lag(on)).isel(T=slice(1, None)) >= 0,
                              name=f"chp_startup_{c}")
            m.add_constraints(su.isel(T=0) - on.isel(T=0) >= -float(u.get("on_init", 0)),
                              name=f"chp_startup0_{c}")
            L = int(u.get("min_runtime_h", 1))
            if L > 1:
                window = sum(_lag(su, k) for k in range(L))
                m.add_constraints(window - on <= 0, name=f"chp_minrun_{c}")
            cap = u.get("max_starts_per_day", None)
            if cap is not None:
                hist = list(u.get("su_hist", []))
                before = np.array([sum(hist[-(23 - i):]) if (23 - i) > 0 and hist else 0
                                   for i in range(len(T))], dtype=float)
                window = sum(_lag(su, k) for k in range(24))
                m.add_constraints(window <= cap - pd.Series(before, index=T),
                                  name=f"chp_max_starts_{c}")
            gmax = u.get("max_grad", None)
            if gmax is not None:
                d = (el - _lag(el)).isel(T=slice(1, None))
                m.add_constraints(d <= gmax, name=f"chp_ramp_up_{c}")
                m.add_constraints(d >= -gmax, name=f"chp_ramp_dn_{c}")

    # ---- battery
    def storage(e, ch, dis, p, prefix, cyc):
        sd, eta_c, eta_d, e0 = p["self_disch"], p["eta_ch"], p["eta_dis"], p["soc_init"]
        rest = e - (1 - sd) * _lag(e) - eta_c * dt * ch + (dt / eta_d) * dis
        m.add_constraints(rest.isel(T=slice(1, None)) == 0, name=f"{prefix}_dynamics")
        m.add_constraints((e - eta_c * dt * ch + (dt / eta_d) * dis).isel(T=0)
                          == (1 - sd) * e0, name=f"{prefix}_dynamics0")
        if cyc:
            m.add_constraints(e.isel(T=-1) == e0, name=f"{prefix}_cyclic")

    wear_terms = 0
    if batt_on:
        storage(soc, p_ch, p_dis, b, "soc", cyclic)
        if "fixed_ch" in b and "fixed_dis" in b:
            m.add_constraints(p_ch == _arr(b["fixed_ch"], T), name="fix_ch")
            m.add_constraints(p_dis == _arr(b["fixed_dis"], T), name="fix_dis")
        w = wear_cfg(b)
        if w is not None and w["model"] == "throughput":
            wear_terms = throughput_cost(w) * dt * (p_ch.sum() + p_dis.sum())
        elif w is not None:
            J = int(w["segments"])
            S = pd.RangeIndex(1, J + 1, name="S")
            seg_e = m.add_variables(lower=0, upper=E / J, coords=[S, T], name="seg_e")
            seg_ch = m.add_variables(lower=0, coords=[S, T], name="seg_ch")
            seg_dis = m.add_variables(lower=0, coords=[S, T], name="seg_dis")
            e0 = pd.Series(initial_split(b.get("soc_init", 0.0), E, J), index=S)
            sd, eta_c, eta_d = b["self_disch"], b["eta_ch"], b["eta_dis"]
            rest = seg_e - (1 - sd) * _lag(seg_e) - eta_c * dt * seg_ch + (dt / eta_d) * seg_dis
            m.add_constraints(rest.isel(T=slice(1, None)) == 0, name="seg_dynamics")
            m.add_constraints((seg_e - eta_c * dt * seg_ch + (dt / eta_d) * seg_dis).isel(T=0)
                              == (1 - sd) * e0, name="seg_dynamics0")
            m.add_constraints(p_ch - seg_ch.sum("S") == 0, name="seg_ch_sum")
            m.add_constraints(p_dis - seg_dis.sum("S") == 0, name="seg_dis_sum")
            m.add_constraints(soc - seg_e.sum("S") == 0, name="seg_soc_sum")
            cj = pd.Series(segment_costs(w, eta_d), index=S)
            wear_terms = (dt * cj * seg_dis).sum()
    if hs_on:
        storage(h_soc, h_ch, h_dis, s, "h_soc", cyclic)

    # ---- objective
    wood_price = wd.get("fuel_price", 0.0)
    gasb_price = gb.get("fuel_price", 0.0)
    obj = (dt * (price_el * p_import - price_exp * p_export)).sum()
    if has_chp:
        obj = obj + dt * cfg["price_gas"] * gas_sum.sum()
        su_cost = pd.Series({c: par[c].get("startup_cost", 0.0) for c in U}, index=U)
        if (su_cost != 0).any():
            obj = obj + dt * (su_cost * chp_su).sum()
    if wood_price:
        obj = obj + dt * wood_price * wood_fuel.sum()
    if gasb_price:
        obj = obj + dt * gasb_price * gas_fuel.sum()
    dc = cfg.get("demand_charge", 0.0)
    if dc:
        obj = obj + dc * peak
    tv = b.get("terminal_value", None) if batt_on else None
    if tv is not None:
        tvv = b.get("eta_dis", 1.0) * statistics.median(data["price_el"]) if tv == "auto" else float(tv)
        if tvv:
            obj = obj - tvv * soc.isel(T=-1)
    if not isinstance(wear_terms, int):
        obj = obj + wear_terms
    m.add_objective(obj)
    return m


def solve_linopy(m, **opts):
    status, cond = m.solve(solver_name="highs", io_api="direct", output_flag=False, **opts)
    if status != "ok":
        raise RuntimeError(f"Linopy/HiGHS failed: {status} {cond}")
    return m


def extract_linopy(m):
    """Same keys as engine.postprocess.extract.extract_results."""
    sol = lambda n: m.variables[n].solution.values.tolist()
    n = len(m.variables["p_import"].solution)
    has_chp = "chp_el" in m.variables
    if has_chp:
        U = list(m.variables["chp_el"].solution.coords["U"].values)
        csum = lambda v: m.variables[v].solution.sum("U").values.tolist()
    else:
        U = []
        csum = lambda v: [0.0] * n
    res = {
        "t": list(range(n)),
        "import": sol("p_import"), "export": sol("p_export"), "pv_used": sol("pv_used"),
        "charge": sol("p_ch"), "discharge": sol("p_dis"), "soc": sol("soc"),
        "chp_gas": csum("chp_gas"), "chp_el": csum("chp_el"),
        "chp_heat": csum("chp_heat"), "chp_on": csum("chp_on"),
        "wood_fuel": sol("wood_fuel"), "wood_heat": sol("wood_heat"),
        "gas_fuel": sol("gas_fuel"), "gas_heat": sol("gas_heat"),
        "hp_el": sol("hp_el"), "hp_heat": sol("hp_heat"),
        "rod_el": sol("rod_el"), "rod_heat": sol("rod_heat"),
        "h_charge": sol("h_ch"), "h_discharge": sol("h_dis"), "h_soc": sol("h_soc"),
        "h_curtail": sol("h_curtail"), "ev_p": [0.0] * n,
        "peak_import": float(m.variables["peak_import"].solution),
        "cost": float(m.objective.value),
    }
    res["chp_units"] = {
        c: {k: m.variables[v].solution.sel(U=c).values.tolist()
            for k, v in (("el", "chp_el"), ("heat", "chp_heat"), ("on", "chp_on"))}
        for c in U
    }
    res["ev_units"] = {}
    return res


def run_linopy(data, cfg, dt_hours=1.0, cyclic=True):
    m = build_linopy(data, cfg, dt_hours, cyclic)
    solve_linopy(m)
    return extract_linopy(m)
