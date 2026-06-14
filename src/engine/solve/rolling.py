"""
hexos.solve.rolling
===================
Rolling-horizon solver: solve a long horizon in overlapping windows, carrying
battery and heat-storage state across seams. Commits the first `commit_h` hours
of each `window_h`-hour window.

Limitations (stated plainly):
  - Approximates the true full-horizon optimum (no window sees the whole year).
  - Min-runtime / start-up flags are enforced WITHIN a window, not across seams
    (on/off history is not carried forward).
  - EV charging is NOT supported here: EV sessions have absolute time windows
    that can straddle window seams, which needs window-aware energy accounting.
    Use a single-horizon solve (hexos.model.build + hexos.solve.single) for EV
    scheduling. This solver raises if EVs are present, rather than silently
    producing a wrong schedule.
"""
import copy

from engine.model.build import build_model
from engine.solve.single import solve
from engine.postprocess.extract import extract_results

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
    batt_soc = cfg.get("battery", {}).get("soc_init", 0.0)
    hstor_soc = cfg.get("heat_storage", {}).get("soc_init", 0.0)
    wood_price = cfg.get("woodchip", {}).get("fuel_price", 0.0)
    gasb_price = cfg.get("gas_boiler", {}).get("fuel_price", 0.0)

    start, n_windows = 0, 0
    while start < n:
        end = min(start + window_h, n)
        commit = min(commit_h, end - start)
        wdata = _slice(data, start, end)
        wcfg = copy.deepcopy(cfg)
        if "battery" in wcfg:
            wcfg["battery"]["soc_init"] = batt_soc
        if "heat_storage" in wcfg:
            wcfg["heat_storage"]["soc_init"] = hstor_soc

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

        batt_soc = r["soc"][commit - 1]
        hstor_soc = r["h_soc"][commit - 1]
        start += commit
        n_windows += 1
        if verbose and n_windows % 50 == 0:
            print(f"  ...solved {n_windows} windows, through hour {start}")

    out["cost"] = total_cost
    out["t"] = list(range(n))
    out["n_windows"] = n_windows
    return out
