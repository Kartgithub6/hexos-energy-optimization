"""
engine.market.bidding
=====================
Turn the HEXOS dispatch optimiser into a price-responsive day-ahead bidder.

Until now HEXOS has been a PRICE TAKER: you hand it a price series, it returns
the cheapest way to serve demand. That implicitly assumes you already know
tomorrow's prices. In a real day-ahead auction you do not -- you must submit
your bid BEFORE the price is known, and the auction then tells you the price
and how much of your bid was accepted.
"""
from __future__ import annotations

import pyomo.environ as pyo

from engine.model.build import build_model
from engine.solve.single import solve
from engine.postprocess.extract import extract_results

# Net position sign convention, used everywhere in this module:
#   positive = the site is a NET IMPORTER  (buying from the grid)
#   negative = the site is a NET EXPORTER  (selling to the grid)
# In kW, matching the rest of the engine.

_TOL = 1e-6


# ---------------------------------------------------------------------------
# Price grids
# ---------------------------------------------------------------------------
def price_grid_from_quantiles(p_low, p_mid, p_high, n_points=7, widen=0.0):
    """Build the candidate price grid for one hour from forecast quantiles.

    The grid spans the forecast uncertainty band rather than an arbitrary
    range: there is no point bidding at prices the forecaster says are
    essentially impossible, and no point leaving the band unbid.

    p_low / p_mid / p_high : the P10 / P50 / P90 forecast for that hour.
    n_points               : how many steps the submitted curve has.
    widen                  : fractional widening of the band, e.g. 0.2 extends
                             it 20% either side. Guards against the forecaster
                             being over-confident -- if the price clears
                             outside your grid you are stuck with the end point.

    Returns a sorted list of candidate prices, always including p_mid.
    """
    if n_points < 2:
        raise ValueError("n_points must be at least 2")
    lo, hi = float(p_low), float(p_high)
    if hi < lo:
        lo, hi = hi, lo
    if hi - lo < _TOL:                      # degenerate band: fabricate a small one
        span = max(abs(lo) * 0.1, 1.0)
        lo, hi = lo - span, hi + span
    if widen:
        pad = (hi - lo) * widen
        lo, hi = lo - pad, hi + pad

    step = (hi - lo) / (n_points - 1)
    grid = [lo + i * step for i in range(n_points)]

    mid = float(p_mid)
    if all(abs(g - mid) > _TOL for g in grid):
        grid.append(mid)
    return sorted(grid)


# ---------------------------------------------------------------------------
# Parametric solve: the site's optimal net position at a given price
# ---------------------------------------------------------------------------
def _data_with_price(data, hour, price, move_export=True):
    """Copy `data` with the price at `hour` overridden.

    move_export=True keeps the import/export SPREAD constant, i.e. if the
    day-ahead price moves +10 EUR/MWh the export remuneration moves with it.
    That is the right default for a site remunerated at a spot-linked tariff.
    Set False if the export price is fixed (a feed-in tariff), in which case
    only the buy side responds.
    """
    d = {k: (list(v) if isinstance(v, list) else v) for k, v in data.items()}
    delta = float(price) - float(data["price_el"][hour])
    d["price_el"][hour] = float(price)
    if move_export:
        d["price_exp"][hour] = max(0.0, float(data["price_exp"][hour]) + delta)
    return d


def net_position_at_price(data, cfg, hour, price, dt_hours=1.0,
                          move_export=True, cyclic=False):
    """Optimal net grid position [kW] at `hour` when the price there is `price`.

    Everything else -- demand, PV, COP, all other hours' prices -- is held at
    the values in `data`. One MILP solve.
    """
    d = _data_with_price(data, hour, price, move_export=move_export)
    m = build_model(d, cfg, dt_hours=dt_hours, cyclic=cyclic)
    solve(m)
    r = extract_results(m)
    return r["import"][hour] - r["export"][hour]


def _monotone_clamp(points):
    """Running-minimum clamp. Correct for INDEPENDENT per-hour parametric
    curves, where a point asking for more energy at a higher price -- other
    prices held fixed -- is economically impossible and almost always MILP
    degeneracy. Clamping such a point down to the running minimum is the right
    repair there.

    It is the WRONG repair for scenario-derived curves: see _isotonic_decreasing.
    """
    out, repairs, running_min = [], 0, None
    for p, q in points:
        if running_min is not None and q > running_min + _TOL:
            repairs += 1
            q = running_min
        running_min = q if running_min is None else min(running_min, q)
        out.append((p, q))
    return out, repairs


def _isotonic_decreasing(points):
    """Least-squares projection onto non-increasing curves (pool-adjacent-
    violators). Returns (points, n_pooled).

    Why this and not the clamp: scenario-derived points are not an own-price
    demand curve. Each comes from a different state of the world, in which the
    WHOLE day's prices moved, so the site's position at a given hour genuinely
    can rise with that hour's price -- the relative arbitrage opportunities
    changed too. Those points carry real information.

    The auction, however, only accepts monotone curves. So the points must be
    projected onto the monotone set, and the projection should be the gentlest
    one that satisfies the rule. The clamp is not gentle: one low point drags
    every point above it down to the minimum, which in testing collapsed the
    curve and forced expensive on-site generation. PAVA instead averages only
    the violating runs, leaving the rest untouched.
    """
    if not points:
        return [], 0
    prices = [p for p, _ in points]
    vals, wts = [], []
    pooled = 0
    for _, q in points:
        vals.append(float(q))
        wts.append(1.0)
        while len(vals) > 1 and vals[-2] < vals[-1] - _TOL:
            v2, w2 = vals.pop(), wts.pop()
            v1, w1 = vals.pop(), wts.pop()
            vals.append((v1 * w1 + v2 * w2) / (w1 + w2))
            wts.append(w1 + w2)
            pooled += 1
    out_q = []
    for v, w in zip(vals, wts):
        out_q.extend([v] * int(round(w)))
    return list(zip(prices, out_q)), pooled


def _project_monotone(points, method):
    if method in (None, False, "none"):
        return list(points), 0
    if method in (True, "clamp"):
        return _monotone_clamp(points)
    if method == "isotonic":
        return _isotonic_decreasing(points)
    raise ValueError(f"unknown monotone method: {method!r}")


def build_bid_curve(data, cfg, hour, price_grid, dt_hours=1.0,
                    move_export=True, enforce_monotone="clamp", cyclic=False):
    """Build the stepwise bid curve for one hour.

    Returns a dict:
      hour                  : the hour index the curve applies to
      points                : [(price, quantity_kW), ...] sorted by price
      monotonicity_repairs  : how many raw points violated non-increasingness
      raw_points            : the unrepaired parametric result, for inspection
    """
    grid = sorted(float(p) for p in price_grid)
    raw = [(p, net_position_at_price(data, cfg, hour, p, dt_hours=dt_hours,
                                     move_export=move_export, cyclic=cyclic))
           for p in grid]
    pts, repairs = _project_monotone(raw, enforce_monotone)
    return {"hour": hour, "points": pts,
            "monotonicity_repairs": repairs, "raw_points": raw}


def build_day_bid_curves(data, cfg, price_grids, hours=None, dt_hours=1.0,
                         move_export=True, enforce_monotone="clamp",
                         cyclic=False, progress=None):
    """Build one bid curve per hour of the horizon.

    price_grids : dict {hour: [candidate prices]} or a single list applied to
                  every hour.
    hours       : which hours to build curves for. Default: all of them.
    progress    : optional callable(hour_index, total) for a progress line.
    """
    hours = list(data["T"]) if hours is None else list(hours)
    curves = {}
    for i, h in enumerate(hours):
        grid = price_grids[h] if isinstance(price_grids, dict) else price_grids
        curves[h] = build_bid_curve(data, cfg, h, grid, dt_hours=dt_hours,
                                    move_export=move_export,
                                    enforce_monotone=enforce_monotone,
                                    cyclic=cyclic)
        if progress:
            progress(i + 1, len(hours))
    return curves


# ---------------------------------------------------------------------------
# Scenario-based curves: the fix for intertemporal coupling
# ---------------------------------------------------------------------------
# Building each hour's curve independently (above) has a defect that only shows
# up once you clear a whole day at once. Perturbing hour h alone and holding
# the rest at forecast asks: "given the day goes as forecast, what do I want at
# h?" Every hour answers that question in isolation. But the battery and heat
# store COUPLE the hours: the auction can clear a combination of independently
# reasonable points that no single feasible schedule can deliver -- e.g. every
# cheap hour says "charge", and together they overfill the battery.
#
# The fix is to derive the curve from a set of COHERENT PRICE PATHS. Solve the
# day once per path; each solve returns a jointly feasible schedule. Hour h's
# curve is then the set of (price_at_h, quantity_at_h) pairs ACROSS paths, so
# every point on it belongs to a schedule that actually works.
#
# Bonus: this is S solves per day instead of 24*S.

def _data_with_price_path(data, path, move_export=True):
    """Copy `data` with the entire price vector replaced by `path`."""
    d = {k: (list(v) if isinstance(v, list) else v) for k, v in data.items()}
    for i in range(len(d["price_el"])):
        delta = float(path[i]) - float(data["price_el"][i])
        d["price_el"][i] = float(path[i])
        if move_export:
            d["price_exp"][i] = max(0.0, float(data["price_exp"][i]) + delta)
    return d


def quantile_price_paths(quantiles_by_hour, levels=(0.05, 0.25, 0.5, 0.75, 0.95)):
    """Build coherent day-long price paths by interpolating the hourly
    P10/P50/P90 forecast onto a set of quantile levels.

    A "path" here means: the whole day sits at the same quantile level. That is
    a deliberate simplification -- prices do not move in lockstep -- but it
    spans the band with a small number of internally consistent scenarios,
    which is what the curve needs.

    quantiles_by_hour : list of (p10, p50, p90), one per hour, in hour order.
    Returns a list of price vectors, one per level.
    """
    paths = []
    for lv in levels:
        path = []
        for p10, p50, p90 in quantiles_by_hour:
            if lv <= 0.10:
                v = p10 - (p50 - p10) * (0.10 - lv) / 0.40
            elif lv <= 0.50:
                v = p10 + (p50 - p10) * (lv - 0.10) / 0.40
            elif lv <= 0.90:
                v = p50 + (p90 - p50) * (lv - 0.50) / 0.40
            else:
                v = p90 + (p90 - p50) * (lv - 0.90) / 0.40
            path.append(max(0.0, float(v)))
        paths.append(path)
    return paths


def bootstrap_price_paths(p50_day, residual_blocks, n_paths=8, seed=0,
                          include_p50=True):
    """Build hour-varying price paths by adding historical forecast-error
    blocks to the point forecast.

    Why this exists
    ---------------
    `quantile_price_paths` moves the whole day to the same quantile level. That
    is coherent but crude: it only ever describes a uniformly cheap or
    uniformly expensive day. In testing it caused a specific, repeatable
    failure -- the site would commit to a whole-day response (self-supplying on
    CHP gas) on the strength of a single expensive hour, because the only
    scenario in which that hour was expensive was one in which every hour was.

    Bootstrapping past 24 h residual blocks fixes that. Each block is a real
    shape the forecast error actually took, so a path can be expensive at 18:00
    and cheap at 03:00 the way real days are. The blocks are used whole, not
    resampled hour by hour, which preserves the autocorrelation of the error.

    p50_day         : list of 24 point forecasts for the day being bid into.
    residual_blocks : list of 24-length lists of past (actual - forecast).
    """
    import random
    rng = random.Random(seed)
    paths = []
    if include_p50:
        paths.append([max(0.0, float(v)) for v in p50_day])
    if not residual_blocks:
        return paths
    k = n_paths - (1 if include_p50 else 0)
    for _ in range(max(0, k)):
        blk = rng.choice(residual_blocks)
        paths.append([max(0.0, float(p) + float(b))
                      for p, b in zip(p50_day, blk)])
    return paths


def build_scenario_bid_curves(data, cfg, price_paths, dt_hours=1.0,
                              move_export=True, enforce_monotone="isotonic",
                              cyclic=False):
    """Build all hourly bid curves from a set of coherent price paths.

    Returns {hour: curve_dict}, same shape as build_day_bid_curves, so the
    clearing and settlement functions are interchangeable between the two
    construction methods.
    """
    n = len(data["T"])
    schedules = []
    for path in price_paths:
        d = _data_with_price_path(data, path, move_export=move_export)
        m = build_model(d, cfg, dt_hours=dt_hours, cyclic=cyclic)
        solve(m)
        r = extract_results(m)
        schedules.append((list(path),
                          [r["import"][i] - r["export"][i] for i in range(n)]))

    curves = {}
    for i, h in enumerate(data["T"]):
        raw = sorted((path[i], sched[i]) for path, sched in schedules)
        pts, repairs = _project_monotone(raw, enforce_monotone)
        curves[h] = {"hour": h, "points": pts,
                     "monotonicity_repairs": repairs, "raw_points": raw}
    return curves


# ---------------------------------------------------------------------------
# Clearing: what the auction accepts once the price is known
# ---------------------------------------------------------------------------
def clear_curve(curve, realised_price):
    """Accepted quantity [kW] when the auction clears at `realised_price`.

    Stepwise semantics, as for a simple hourly step bid: take the quantity at
    the highest grid price that is at or below the clearing price. Below the
    grid you get the first step; above it you get the last. That end-point
    behaviour is exactly why `widen` exists in price_grid_from_quantiles.
    """
    pts = curve["points"]
    if not pts:
        raise ValueError("empty bid curve")
    q = pts[0][1]
    for p, qq in pts:
        if realised_price >= p - _TOL:
            q = qq
        else:
            break
    return q


def clear_day(curves, realised_prices):
    """Clear every hourly curve against the realised price series.

    Returns {hour: accepted_quantity_kW}.
    """
    return {h: clear_curve(c, realised_prices[h]) for h, c in curves.items()}


# ---------------------------------------------------------------------------
# Settlement: what the committed position actually costs
# ---------------------------------------------------------------------------
def cost_of_committed_position(data, cfg, net_target, dt_hours=1.0,
                               deviation_penalty=1000.0, cyclic=False):
    """Re-dispatch the site to honour a committed net position, and cost it.

    `data` here must carry the REALISED prices -- this is settlement, after the
    fact. `net_target` is {hour: kW} the site is committed to.

    A committed position may not be physically deliverable once reality lands
    (demand or PV came in different from forecast). Rather than declare the
    problem infeasible, deviation variables absorb the mismatch at
    `deviation_penalty` per kWh. Reporting the deviation volume honestly is the
    point: a strategy that only looks cheap because it quietly deviates is not
    actually cheap.

    Returns:
      cost           : true operating cost at realised prices, penalty excluded
      penalty        : deviation_penalty * total deviation energy
      deviation_kwh  : absolute deviation from the committed position
      results        : the full extract_results dict for the re-dispatch
    """
    m = build_model(data, cfg, dt_hours=dt_hours, cyclic=cyclic)

    m.dev_up = pyo.Var(m.T, domain=pyo.NonNegativeReals)
    m.dev_dn = pyo.Var(m.T, domain=pyo.NonNegativeReals)

    def _match(m, t):
        return (m.p_import[t] - m.p_export[t]
                == float(net_target[t]) + m.dev_up[t] - m.dev_dn[t])
    m.match_position = pyo.Constraint(m.T, rule=_match)

    base_expr = m.cost.expr
    m.cost.deactivate()
    m.cost_committed = pyo.Objective(
        expr=base_expr + deviation_penalty * sum(
            (m.dev_up[t] + m.dev_dn[t]) * m.dt for t in m.T),
        sense=pyo.minimize)

    solve(m)

    dev_kwh = sum((pyo.value(m.dev_up[t]) + pyo.value(m.dev_dn[t])) * m.dt
                  for t in m.T)
    res = extract_results(m)
    return {"cost": pyo.value(base_expr),
            "penalty": deviation_penalty * dev_kwh,
            "deviation_kwh": dev_kwh,
            "results": res}


def self_schedule_position(forecast_data, cfg, dt_hours=1.0, cyclic=False):
    """The baseline strategy: optimise against the point forecast, commit that
    schedule as a fixed volume, and live with it.

    This is what a site does when it submits a single number per hour instead
    of a curve. Returns {hour: kW}.
    """
    m = build_model(forecast_data, cfg, dt_hours=dt_hours, cyclic=cyclic)
    solve(m)
    r = extract_results(m)
    return {h: r["import"][i] - r["export"][i] for i, h in enumerate(forecast_data["T"])}


def perfect_foresight_cost(realised_data, cfg, dt_hours=1.0, cyclic=False):
    """Lower bound: what the day would have cost with the realised prices known
    in advance and no commitment constraint at all. Nothing can beat this, so
    it is the yardstick both strategies are measured against.
    """
    m = build_model(realised_data, cfg, dt_hours=dt_hours, cyclic=cyclic)
    solve(m)
    return pyo.value(m.cost)
