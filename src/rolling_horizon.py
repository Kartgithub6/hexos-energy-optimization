"""
rolling_horizon.py
==================
Solve a long horizon (e.g. a full year, 8757 hours) by stepping through it in
overlapping windows instead of one giant MILP.

Why
---
A full-year model has one CHP on/off binary per hour (~8760 binaries). Handing
that to a MILP solver in a single shot is slow or intractable. Rolling horizon
is the standard remedy: solve a short window, commit only its first part, slide
forward, and carry storage state across the seam.

Window scheme (defaults): solve `window_h` = 48 hours of foresight, commit the
first `commit_h` = 24 hours, then move the window forward by `commit_h`. The
24-hour lookahead beyond the committed day stops the solver from draining
storage to zero at the window's end just because it cannot see tomorrow.

Limitation (stated plainly): rolling horizon APPROXIMATES the true full-horizon
optimum. No window sees the whole year, so the stitched solution can be slightly
more expensive than an ideal single solve. This is a deliberate, well-understood
trade for tractability. To gauge the gap, solve one representative week with
build_model(cyclic=True) and compare against the same week here.

State carried across windows: battery SOC and heat-storage SOC. Each new window
starts from the committed end-state of the previous one (soc_init), and windows
are built with cyclic=False so they do not force end==start.
"""

from __future__ import annotations
import copy

import build_model as B

# The per-hour result keys we stitch together across windows.
_SERIES_KEYS = [
    "import", "export", "pv_used", "charge", "discharge", "soc",
    "chp_gas", "chp_el", "chp_heat", "chp_on",
    "hp_el", "hp_heat", "rod_el", "rod_heat",
    "h_charge", "h_discharge", "h_soc",
]


def _slice(data: dict, start: int, end: int) -> dict:
    """Return a window of the data with its time index reset to 0..k-1."""
    return {
        "T": list(range(end - start)),
        "price_el": data["price_el"][start:end],
        "price_exp": data["price_exp"][start:end],
        "pv_avail": data["pv_avail"][start:end],
        "dem_el": data["dem_el"][start:end],
        "dem_heat": data["dem_heat"][start:end],
        "cop": data["cop"][start:end],
    }


def solve_rolling(data: dict, cfg: dict, window_h: int = 48, commit_h: int = 24,
                  dt_hours: float = 1.0, verbose: bool = True) -> dict:
    """Solve `data` by rolling horizon. Returns stitched full-length results
    plus the total cost summed over committed hours.
    """
    n = len(data["T"])
    out = {k: [] for k in _SERIES_KEYS}
    total_cost = 0.0

    # Initial carried storage state comes from the config.
    batt_soc = cfg.get("battery", {}).get("soc_init", 0.0)
    hstor_soc = cfg.get("heat_storage", {}).get("soc_init", 0.0)

    start = 0
    n_windows = 0
    while start < n:
        end = min(start + window_h, n)
        commit = min(commit_h, end - start)

        window_data = _slice(data, start, end)

        # Seed this window with the carried storage state, no cyclic constraint.
        wcfg = copy.deepcopy(cfg)
        if "battery" in wcfg:
            wcfg["battery"]["soc_init"] = batt_soc
        if "heat_storage" in wcfg:
            wcfg["heat_storage"]["soc_init"] = hstor_soc

        m = B.build_model(window_data, wcfg, dt_hours, cyclic=False)
        B.solve(m)
        r = B.extract_results(m)

        # Commit only the first `commit` hours of this window.
        for k in _SERIES_KEYS:
            out[k].extend(r[k][:commit])

        # Cost of the committed hours only.
        for i in range(commit):
            total_cost += (
                data["price_el"][start + i] * r["import"][i]
                - data["price_exp"][start + i] * r["export"][i]
                + cfg["price_gas"] * r["chp_gas"][i]
            ) * dt_hours

        # Carry the storage state at the end of the committed block forward.
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
