"""
engine.postprocess.wear
=======================
Score a battery schedule for wear AFTER it has been solved, with one yardstick
for every run (wear-blind or wear-aware), so their numbers are comparable.

  1. Rainflow-count the state-of-charge trace (ASTM E1049 four-point method on
     turning points). Each closed cycle has a depth d = range / E_cap; what is
     left over at the end counts as half cycles.
  2. Cycle ageing   = sum over cycles of count * Phi(d), Phi(d) = d**b / N
     (the same stress function as engine.technologies.wear).
  3. Calendar ageing = hours / (calendar_life_years * 8760), optional.
  4. Wear cost      = ageing * capex * E_cap. Years to end of life follow from
     the yearly ageing rate.

This is a standard semi-empirical scoring, not a cell model: the parameters
are illustrative and the numbers are only as good as Phi(d) is for a real cell.
"""
from __future__ import annotations

from engine.technologies.wear import phi


def turning_points(x, tol=1e-9):
    """Keep only the local peaks and valleys of a series (plus the ends)."""
    pts = []
    for v in x:
        if pts and abs(v - pts[-1]) <= tol:
            continue
        if len(pts) >= 2 and (pts[-1] - pts[-2]) * (v - pts[-1]) > 0:
            pts[-1] = v          # still moving the same way: extend the run
        else:
            pts.append(v)
    return pts


def rainflow(x, tol=1e-9):
    """Return a list of (range, count) with count 1.0 for full cycles and 0.5
    for the residual half cycles."""
    stack, cycles = [], []
    for p in turning_points(x, tol):
        stack.append(p)
        while len(stack) >= 3:
            X = abs(stack[-1] - stack[-2])
            Y = abs(stack[-2] - stack[-3])
            if X < Y - tol:
                break
            if len(stack) == 3:
                cycles.append((Y, 0.5))      # Y contains the start point
                stack.pop(0)
            else:
                cycles.append((Y, 1.0))
                last = stack.pop()
                stack.pop()
                stack.pop()
                stack.append(last)
    for a, b in zip(stack[:-1], stack[1:]):
        cycles.append((abs(b - a), 0.5))
    return [(r, c) for r, c in cycles if r > tol]


def evaluate_wear(soc, charge, discharge, E_cap, wear, dt_hours=1.0,
                  calendar_life_years=None, soc0=None):
    """Wear metrics for one schedule.

    soc, charge, discharge: per-step lists from the solve (kWh, kW, kW).
    wear: dict with capex_eur_per_kwh, cycle_life_efc, dod_exponent.
    soc0: energy before the first step (prepended to the SoC trace if given).
    """
    if E_cap <= 0:
        return {"efc": 0.0, "cycles": [], "cycle_ageing": 0.0, "calendar_ageing": 0.0,
                "ageing": 0.0, "wear_eur": 0.0, "years_to_eol": float("inf"),
                "mean_depth": 0.0, "n_cycles": 0.0}
    trace = ([soc0] if soc0 is not None else []) + list(soc)
    cyc = rainflow(trace)
    w = {"dod_exponent": wear.get("dod_exponent", 1.5),
         "cycle_life_efc": wear["cycle_life_efc"]}
    cycle_ageing = sum(c * phi(r / E_cap, w) for r, c in cyc)
    hours = len(soc) * dt_hours
    cal = hours / (calendar_life_years * 8760.0) if calendar_life_years else 0.0
    ageing = cycle_ageing + cal
    years = hours / 8760.0
    per_year = ageing / years if years > 0 else 0.0
    n = sum(c for _, c in cyc)
    efc = (sum(charge) + sum(discharge)) * dt_hours / (2.0 * E_cap)
    return {
        "efc": efc,
        "cycles": cyc,
        "n_cycles": n,
        "mean_depth": (sum(c * r for r, c in cyc) / n / E_cap) if n else 0.0,
        "cycle_ageing": cycle_ageing,
        "calendar_ageing": cal,
        "ageing": ageing,
        "wear_eur": ageing * wear["capex_eur_per_kwh"] * E_cap,
        "cycle_wear_eur": cycle_ageing * wear["capex_eur_per_kwh"] * E_cap,
        "years_to_eol": (1.0 / per_year) if per_year > 0 else float("inf"),
    }
