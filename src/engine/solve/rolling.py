"""
engine.solve.rolling
===================
Rolling-horizon solver: solve a long horizon in overlapping windows, carrying
battery and heat-storage state across seams. Commits the first `commit_h` hours
of each `window_h`-hour window.

Limitations (stated plainly):
  - Approximates the true full-horizon optimum (no window sees the whole year).
  - CHP on/off state, the last 23 h of start-ups and the running peak import
    ARE carried across seams (engine.solve.state). Minimum runtime is still only
    enforced within a window: a unit started near a seam is not held on into
    the next window.
  - EV charging is NOT supported here: EV sessions have absolute time windows
    that can straddle window seams, which needs window-aware energy accounting.
    Use a single-horizon solve (engine.model.build + engine.solve.single) for EV
    scheduling. This solver raises if EVs are present, rather than silently
    producing a wrong schedule.
"""
import copy

from engine.model.build import build_model
from engine.solve.single import solve
from engine.postprocess.extract import extract_results
from engine.solve import state as carry

_SERIES_KEYS = [
    "import", "export", "pv_used", "charge", "discharge", "soc",
    "chp_gas", "chp_el", "chp_heat", "chp_on",
    "wood_fuel", "wood_heat", "gas_fuel", "gas_heat",
    "hp_el", "hp_heat", "rod_el", "rod_heat",
    "h_charge", "h_discharge", "h_soc", "h_curtail", "ev_p",
]


def _slice(data, start, end):
    return {
        "T": list(range(end - start)),
        "price_el": data["price_el"][start:end],
        "price_exp": data["price_exp"][start:end],
        "pv_avail": data["pv_avail"][start:end],
        "dem_el": data["dem_el"][start:end],
        "dem_heat": data["dem_heat"][start:end],
        "cop": data["cop"][start:end],
    }


def solve_rolling(data, cfg, window_h=48, commit_h=24, dt_hours=1.0, verbose=True):
    if cfg.get("evs"):
        raise NotImplementedError(
            "Rolling horizon does not support EV charging (absolute time windows "
            "can straddle seams). Use a single-horizon solve for EV scheduling.")

    n = len(data["T"])
    out = {k: [] for k in _SERIES_KEYS}
    total_cost = 0.0
    st = carry.initial_state(cfg)
    wood_price = cfg.get("woodchip", {}).get("fuel_price", 0.0)
    gasb_price = cfg.get("gas_boiler", {}).get("fuel_price", 0.0)

    start, n_windows = 0, 0
    while start < n:
        end = min(start + window_h, n)
        commit = min(commit_h, end - start)
        wdata = _slice(data, start, end)
        wcfg = carry.window_cfg(copy.deepcopy(cfg), st, start, end, n)

        m = build_model(wdata, wcfg, dt_hours, cyclic=False)
        solve(m)
        r = extract_results(m)

        for k in _SERIES_KEYS:
            out[k].extend(r[k][:commit])
        for i in range(commit):
            total_cost += (
                data["price_el"][start + i] * r["import"][i]
                - data["price_exp"][start + i] * r["export"][i]
                + cfg["price_gas"] * r["chp_gas"][i]
                + wood_price * r["wood_fuel"][i]
                + gasb_price * r["gas_fuel"][i]
            ) * dt_hours

        st = carry.advance(st, r, cfg, commit)
        st["batt_soc"] = r["soc"][commit - 1]
        st["hstor_soc"] = r["h_soc"][commit - 1]
        start += commit
        n_windows += 1
        if verbose and n_windows % 50 == 0:
            print(f"  ...solved {n_windows} windows, through hour {start}")

    demand_cost = cfg.get("demand_charge", 0.0) * st["peak"]
    out["energy_cost"] = total_cost
    out["startup_cost"] = st["startup_cost"]
    out["demand_cost"] = demand_cost
    out["cost"] = total_cost + st["startup_cost"] + demand_cost
    out["chp_starts"] = st["starts"]
    out["peak_import"] = st["peak"]
    out["t"] = list(range(n))
    out["n_windows"] = n_windows
    return out
