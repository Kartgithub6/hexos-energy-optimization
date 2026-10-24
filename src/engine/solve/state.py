"""
engine.solve.state
==================
State that has to survive from one optimisation window to the next.

Storage levels were always carried. This adds the rest:

  * CHP on/off  -- without it, every window assumes each unit starts cold, so a
                   unit running across a seam is billed a start-up it never made.
  * start log   -- the last 23 hours of start-ups, so a 24 h start cap holds
                   across seams instead of resetting each window.
  * peak import -- the highest grid draw so far, so a demand charge only bills a
                   window for raising the peak, not for re-reaching it.
  * fixed battery schedules -- sliced to the window when a baseline pins the
                   battery to a precomputed rule.

Used identically by solve_rolling and run_mpc, so the two stay equivalent under
perfect foresight (a test checks this).
"""
from __future__ import annotations


def _unit_cfgs(cfg):
    """The CHP unit dicts inside a config, in model order, with their names."""
    if "chps" in cfg:
        raw = cfg["chps"]
    elif cfg.get("chp", {}).get("p_el_max", 0) > 0:
        raw = [cfg["chp"]]
    else:
        raw = []
    return [(u.get("name", f"CHP{i + 1}"), u) for i, u in enumerate(raw)
            if u.get("p_el_max", 0) > 0]


def initial_state(cfg):
    return {
        "batt_soc": cfg.get("battery", {}).get("soc_init", 0.0),
        "hstor_soc": cfg.get("heat_storage", {}).get("soc_init", 0.0),
        "chp_on": {name: int(u.get("on_init", 0)) for name, u in _unit_cfgs(cfg)},
        "chp_su_hist": {name: list(u.get("su_hist", [])) for name, u in _unit_cfgs(cfg)},
        "peak": cfg.get("peak_so_far", 0.0),
        "starts": 0,
        "startup_cost": 0.0,
    }


def window_cfg(wcfg, state, start, end, n=None):
    """Write the carried state into a deep-copied config for one window.

    n is the length of the whole simulated period. A window that reaches its
    end drops any battery terminal value: there is no "later" left to save
    energy for, and the full-horizon benchmark knows that too. Keeping the
    credit there would strand bought energy in the battery and make the
    terminal value look worse than it is.
    """
    if n is not None and end >= n and "battery" in wcfg:
        wcfg["battery"].pop("terminal_value", None)
    if "battery" in wcfg:
        wcfg["battery"]["soc_init"] = state["batt_soc"]
        b = wcfg["battery"]
        if "fixed_ch" in b and "fixed_dis" in b:
            b["fixed_ch"] = b["fixed_ch"][start:end]
            b["fixed_dis"] = b["fixed_dis"][start:end]
    if "heat_storage" in wcfg:
        wcfg["heat_storage"]["soc_init"] = state["hstor_soc"]
    for name, u in _unit_cfgs(wcfg):
        u["on_init"] = state["chp_on"].get(name, 0)
        u["su_hist"] = list(state["chp_su_hist"].get(name, []))
    if state["peak"] > 0:
        wcfg["peak_so_far"] = state["peak"]
    return wcfg


def advance(state, r, cfg, commit):
    """Record the committed hours of a solved window into the carried state.

    Counts start-ups from the committed on/off sequence (on now, off the hour
    before) and prices them at each unit's start-up cost.
    """
    for name, u in _unit_cfgs(cfg):
        on_seq = r["chp_units"].get(name, {}).get("on", [])
        prev = state["chp_on"].get(name, 0)
        hist = state["chp_su_hist"].setdefault(name, [])
        for i in range(commit):
            on = int(round(on_seq[i])) if i < len(on_seq) else 0
            start = 1 if (on == 1 and prev == 0) else 0
            if start:
                state["starts"] += 1
                state["startup_cost"] += u.get("startup_cost", 0.0)
            hist.append(start)
            prev = on
        state["chp_on"][name] = prev
        del hist[:-23]
    if commit > 0:
        state["peak"] = max(state["peak"], max(r["import"][:commit]))
    return state
