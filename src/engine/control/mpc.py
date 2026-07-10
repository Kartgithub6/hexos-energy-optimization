"""
engine.control.mpc
==================
Closed-loop Model Predictive Control SIMULATION -- an offline test of a
real-time control strategy, not a deployed controller and not connected to
hardware. It replays historical data to measure how the strategy would have
performed.

The loop, generalised over a configurable re-planning cadence `commit_h`:
  1. FORECAST the next `horizon_h` hours (what the controller "sees"). The
     forecast may differ from reality -- that is the whole point of MPC.
  2. OPTIMISE the schedule over that horizon, starting from the current TRUE
     storage state.
  3. APPLY the first `commit_h` hours of the plan (not just one).
  4. ADVANCE the plant simulator through those `commit_h` hours using the TRUE
     conditions, updating the true storage state hour by hour.
  5. ACCRUE the realised cost of those hours, priced at TRUE prices.
  6. Move `commit_h` hours ahead and repeat.

commit_h is the re-planning cadence -- how often the controller re-forecasts
and re-optimises:
  - commit_h=1  : classic hourly MPC (re-plan every single hour). This is the
                  default and matches a fully reactive controller.
  - commit_h=24, horizon_h=48: a ROLLING-HORIZON MPC -- it re-plans once a day
                  on a 48h forecast window and commits 24h of the plan, exactly
                  mirroring the cadence of engine.solve.rolling.solve_rolling,
                  but driven by (possibly imperfect) forecasts instead of
                  perfect foresight.

This is not a coincidence: with a PERFECT forecaster, run_mpc(horizon_h=48,
commit_h=24) is mathematically equivalent to solve_rolling(window_h=48,
commit_h=24) -- the annual rolling-horizon solver is the special case of this
MPC framework where the forecast equals the truth. A test proves this
equivalence (test_rolling_horizon_mpc_matches_solve_rolling).
"""
from __future__ import annotations
import copy

from engine.model.build import build_model
from engine.solve.single import solve
from engine.postprocess.extract import extract_results
from engine.control.simulator import advance_one_hour


def _window(data, k, h):
    n = len(data["T"])
    end = min(k + h, n)
    return {"T": list(range(end - k)), "price_el": data["price_el"][k:end],
            "price_exp": data["price_exp"][k:end], "pv_avail": data["pv_avail"][k:end],
            "dem_el": data["dem_el"][k:end], "dem_heat": data["dem_heat"][k:end],
            "cop": data["cop"][k:end]}


def perfect_forecaster(data, k, h):
    return _window(data, k, h)


def run_mpc(data, cfg, forecaster=perfect_forecaster, horizon_h=24, commit_h=1,
            dt=1.0, verbose=False):
    """Run the closed-loop MPC simulation over the whole `data` horizon.

    commit_h: hours of each optimised plan applied before the next re-forecast
    and re-optimisation (see module docstring). Must be <= horizon_h.
    """
    n = len(data["T"])
    state = {"batt_soc": cfg.get("battery", {}).get("soc_init", 0.0),
             "hstor_soc": cfg.get("heat_storage", {}).get("soc_init", 0.0)}
    applied_keys = ["import", "export", "pv_used", "charge", "discharge",
                    "chp_el", "chp_heat", "hp_heat", "rod_heat",
                    "h_charge", "h_discharge", "wood_heat", "gas_heat"]
    out = {k: [] for k in applied_keys}
    out["batt_soc"], out["hstor_soc"] = [], []
    realised_cost = 0.0
    wood_price = cfg.get("woodchip", {}).get("fuel_price", 0.0)
    gasb_price = cfg.get("gas_boiler", {}).get("fuel_price", 0.0)

    k = 0
    while k < n:
        h = min(horizon_h, n - k)
        commit = min(commit_h, h)
        fc = forecaster(data, k, h)

        wcfg = copy.deepcopy(cfg)
        if "battery" in wcfg: wcfg["battery"]["soc_init"] = state["batt_soc"]
        if "heat_storage" in wcfg: wcfg["heat_storage"]["soc_init"] = state["hstor_soc"]
        m = build_model(fc, wcfg, dt, cyclic=False)
        solve(m)
        r = extract_results(m)

        for i in range(commit):
            applied = {kk: r[kk][i] for kk in applied_keys}
            for kk in applied_keys:
                out[kk].append(applied[kk])
            out["batt_soc"].append(state["batt_soc"])
            out["hstor_soc"].append(state["hstor_soc"])
            realised_cost += (
                data["price_el"][k + i] * applied["import"]
                - data["price_exp"][k + i] * applied["export"]
                + cfg["price_gas"] * r["chp_gas"][i]
                + wood_price * r["wood_fuel"][i]
                + gasb_price * r["gas_fuel"][i]
            ) * dt
            state = advance_one_hour(state, applied, cfg, dt)

        k += commit
        if verbose and k % 1000 == 0:
            print(f"  ...MPC hour {k}/{n}")

    out["cost"] = realised_cost
    out["t"] = list(range(n))
    return out
