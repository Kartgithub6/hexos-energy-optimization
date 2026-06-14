"""
engine.control.mpc
==================
Closed-loop Model Predictive Control (MPC) SIMULATION.

This is an OFFLINE test of a real-time control strategy -- not a deployed
controller and not connected to any hardware. It replays historical data to
measure how the strategy would have performed.

The loop, at each hour k:
  1. Build a FORECAST of the next `horizon_h` hours (what the controller "sees").
     The forecast may differ from reality (that is the whole point of MPC).
  2. Optimise the schedule over that horizon with the MILP, starting from the
     current TRUE storage state.
  3. Apply only the FIRST hour's decisions.
  4. Advance the plant simulator by one hour using the TRUE conditions, updating
     the true storage state.
  5. Accrue the realised cost of that hour (priced at the TRUE prices).
  6. Move to hour k+1 and repeat.

Compared against a perfect-foresight optimum (the ordinary full-horizon solve),
the gap is the realistic "cost of not knowing the future".

Forecast sources are pluggable: pass a `forecaster(actual_data, k, horizon)`
function that returns the forecast dict for the window. A perfect forecaster
(returns the true future) recovers the perfect-foresight behaviour and is used
in tests to check the loop and simulator agree exactly.
"""

from __future__ import annotations

from engine.model.build import build_model
from engine.solve.single import solve
from engine.postprocess.extract import extract_results
from engine.control.simulator import advance_one_hour


def _window(data, k, h):
    """Slice the true data for hours [k, k+h), time-reindexed to 0..h-1."""
    n = len(data["T"])
    end = min(k + h, n)
    return {
        "T": list(range(end - k)),
        "price_el": data["price_el"][k:end],
        "price_exp": data["price_exp"][k:end],
        "pv_avail": data["pv_avail"][k:end],
        "dem_el": data["dem_el"][k:end],
        "dem_heat": data["dem_heat"][k:end],
        "cop": data["cop"][k:end],
    }


def perfect_forecaster(data, k, h):
    """Forecast == truth (used to validate the loop)."""
    return _window(data, k, h)


def run_mpc(data, cfg, forecaster=perfect_forecaster, horizon_h=24, dt=1.0,
            verbose=False):
    """Run the closed-loop MPC simulation over the whole `data` horizon.

    Returns a dict with the realised per-hour control trajectory, the realised
    total cost (priced at TRUE prices), and the true storage trajectories.
    """
    import copy
    n = len(data["T"])
    state = {
        "batt_soc": cfg.get("battery", {}).get("soc_init", 0.0),
        "hstor_soc": cfg.get("heat_storage", {}).get("soc_init", 0.0),
    }
    applied_keys = ["import", "export", "pv_used", "charge", "discharge",
                    "chp_el", "chp_heat", "hp_heat", "rod_heat",
                    "h_charge", "h_discharge", "wood_heat", "gas_heat"]
    out = {k: [] for k in applied_keys}
    out["batt_soc"], out["hstor_soc"] = [], []
    realised_cost = 0.0
    wood_price = cfg.get("woodchip", {}).get("fuel_price", 0.0)
    gasb_price = cfg.get("gas_boiler", {}).get("fuel_price", 0.0)

    for k in range(n):
        h = min(horizon_h, n - k)
        fc = forecaster(data, k, h)               # what the controller sees

        # Optimise over the forecast, starting from the TRUE current state.
        wcfg = copy.deepcopy(cfg)
        if "battery" in wcfg:
            wcfg["battery"]["soc_init"] = state["batt_soc"]
        if "heat_storage" in wcfg:
            wcfg["heat_storage"]["soc_init"] = state["hstor_soc"]
        m = build_model(fc, wcfg, dt, cyclic=False)
        solve(m)
        r = extract_results(m)

        # Apply only hour 0 of the plan.
        applied = {kk: r[kk][0] for kk in applied_keys}
        for kk in applied_keys:
            out[kk].append(applied[kk])
        out["batt_soc"].append(state["batt_soc"])
        out["hstor_soc"].append(state["hstor_soc"])

        # Realised cost of this hour, priced at the TRUE prices.
        realised_cost += (
            data["price_el"][k] * applied["import"]
            - data["price_exp"][k] * applied["export"]
            + cfg["price_gas"] * r["chp_gas"][0]
            + wood_price * r["wood_fuel"][0]
            + gasb_price * r["gas_fuel"][0]
        ) * dt

        # Advance the plant by one hour using the TRUE conditions.
        state = advance_one_hour(state, applied, cfg, dt)

        if verbose and (k + 1) % 1000 == 0:
            print(f"  ...MPC hour {k+1}/{n}")

    out["cost"] = realised_cost
    out["t"] = list(range(n))
    return out
