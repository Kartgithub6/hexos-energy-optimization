"""
run_bidding.py
==============
Day-ahead bidding experiment: is a BID CURVE worth more than a COMMITTED
VOLUME, and how much of the perfect-foresight optimum does each capture?

The three strategies compared
-----------------------------
All three are settled at the SAME realised day-ahead prices. The only thing
that differs is what the site committed to before the price was known.

  1. SELF-SCHEDULE  Optimise the day against the P50 price forecast, commit
                    that schedule as a fixed hourly volume, deliver it. This is
                    the honest baseline: one number per hour, chosen with the
                    information available at gate closure.

  2. BID CURVE      Submit a stepwise price-quantity curve per hour, derived by
                    parametric solve over the P10-P90 forecast band. The
                    auction clears each hour at the realised price and accepts
                    the matching point on the curve.

  3. PERFECT        Solve the day with realised prices known in advance and no
     FORESIGHT      commitment at all. Unbeatable by construction, so it is the
                    yardstick, not a strategy.

Expected ordering: perfect <= curve <= self-schedule. If the curve ever beats
perfect foresight, something is wrong.
"""
import _paths  # noqa

import argparse
import csv
import os
import sys
import time

import numpy as np
import pandas as pd

from engine import load_timeseries
from engine.data.io import make_data
from engine.market import (build_day_bid_curves, build_scenario_bid_curves,
                           quantile_price_paths, bootstrap_price_paths,
                           clear_day,
                           price_grid_from_quantiles,
                           cost_of_committed_position,
                           self_schedule_position, perfect_foresight_cost)

ROOT = os.path.join(os.path.dirname(__file__), "..")
YEAR = os.path.join(ROOT, "data", "year_DE_2019.csv")
FORECASTS = os.path.join(ROOT, "results", "price_forecasts.csv")
OUT_SUMMARY = os.path.join(ROOT, "results", "bidding_summary.csv")
OUT_CURVES = os.path.join(ROOT, "results", "bid_curves.csv")
OUT_PLOT = os.path.join(ROOT, "results", "bid_curve_example.png")

H = 24  # one day per bidding round, as in the real day-ahead auction


def base_cfg():
    """Identical to run_year.py and run_flex_value.py, so costs are comparable
    across experiments. Change nothing here without changing it there."""
    return {
        "price_gas": 0.07,
        "grid": {"import_max": 1200.0, "export_max": 1200.0},
        "battery": {"E_cap": 400.0, "p_ch_max": 200.0, "p_dis_max": 200.0,
                    "eta_ch": 0.96, "eta_dis": 0.96, "self_disch": 0.0005,
                    "soc_init": 0.0},
        "chp": {"p_el_max": 200.0, "eta_el": 0.4, "htp_ratio": 1.5,
                "min_load": 0.4},
        "heatpump": {"q_max": 400.0},
        "rod": {"q_max": 300.0, "eta": 0.99},
        "heat_storage": {"E_cap": 1500.0, "p_ch_max": 400.0, "p_dis_max": 400.0,
                         "eta_ch": 0.98, "eta_dis": 0.98, "self_disch": 0.002,
                         "soc_init": 0.0},
    }


# ---------------------------------------------------------------------------
# Forecast quantiles
# ---------------------------------------------------------------------------
def load_forecast_quantiles(path):
    """Read quantile forecasts written by forecast_prices.py.

    Tolerant of column naming and of the timestamp being either an integer
    hour index (matching year_DE_2019.csv) or a datetime string.
    """
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)

    def pick(*names):
        for n in names:
            for c in df.columns:
                if c.lower().strip() == n:
                    return c
        return None

    c_t = pick("t", "hour", "index", "timestamp")
    c10 = pick("p10", "q10", "q0.1", "pred_0.1", "lo", "lower")
    c50 = pick("p50", "q50", "q0.5", "pred_0.5", "median", "point")
    c90 = pick("p90", "q90", "q0.9", "pred_0.9", "hi", "upper")
    if not all([c_t, c10, c50, c90]):
        print(f"  ! {os.path.basename(path)} found but columns not recognised "
              f"(have: {list(df.columns)}) -- using naive fallback instead.")
        return None

    # Convert timestamps to integer hour indices matching year_DE_2019.csv.
    # That file starts at 2019-01-01 00:00 as hour 0, so anchor to it.
    def to_hour(val):
        try:
            return int(val)
        except (ValueError, TypeError):
            ts = pd.to_datetime(val)
            anchor = pd.Timestamp(year=ts.year, month=1, day=1)
            return int((ts - anchor).total_seconds() // 3600)

    return {to_hour(r[c_t]): (float(r[c10]), float(r[c50]), float(r[c90]))
            for _, r in df.iterrows()}

def naive_quantiles(prices, day_start, lookback_days=30):
    """Leak-free fallback: empirical P10/P50/P90 of the same hour-of-day over
    the trailing `lookback_days`. Uses strictly past data only.
    """
    out = {}
    for i in range(H):
        h = day_start + i
        hod = h % 24
        hist = [prices[k] for k in range(max(0, h - lookback_days * 24), day_start)
                if k % 24 == hod]
        if len(hist) < 5:
            p = prices[max(0, h - 24)]
            out[h] = (p * 0.7, p, p * 1.3)
        else:
            a = np.array(hist)
            out[h] = (float(np.quantile(a, 0.10)),
                      float(np.quantile(a, 0.50)),
                      float(np.quantile(a, 0.90)))
    return out


def residual_blocks(prices, quant_lookup, start, n_days=20):
    """Past 24 h forecast-error shapes, for the bootstrap scenario paths.

    For each of the `n_days` days before `start`, the error block is
    (actual - P50) hour by hour. Strictly past data only.
    """
    blocks = []
    for d in range(1, n_days + 1):
        s0 = start - d * H
        if s0 < 0:
            break
        q = quant_lookup(s0)
        if q is None:
            continue
        blocks.append([prices[s0 + i] - q[s0 + i][1] for i in range(H)])
    return blocks


# ---------------------------------------------------------------------------
# Slicing
# ---------------------------------------------------------------------------
def day_slice(data, start, forecast_prices=None):
    """Extract a 24 h window. If forecast_prices is given, substitute it for
    the realised price series -- that is the 'what we believed at gate closure'
    version of the same day.
    """
    idx = list(range(start, start + H))
    price = ([forecast_prices[h] for h in idx] if forecast_prices
             else [data["price_el"][h] for h in idx])
    # Export remuneration keeps its realised spread to the import price.
    spread = [data["price_exp"][h] - data["price_el"][h] for h in idx]
    pexp = [max(0.0, p + s) for p, s in zip(price, spread)]
    return make_data(list(range(H)), price, pexp,
                     [data["pv_avail"][h] for h in idx],
                     [data["dem_el"][h] for h in idx],
                     [data["dem_heat"][h] for h in idx],
                     [data["cop"][h] for h in idx])


# ---------------------------------------------------------------------------
# One bidding round
# ---------------------------------------------------------------------------
def run_day(data, cfg, start, quant, n_points, widen, penalty, levels,
            blocks=None, n_paths=8, verbose=True):
    realised = day_slice(data, start)
    realised_px = [realised["price_el"][i] for i in range(H)]
    fc_mid = {h: quant[h][1] for h in range(start, start + H)}
    forecast = day_slice(data, start, forecast_prices=fc_mid)
    qh = [quant[start + i] for i in range(H)]

    # --- yardstick --------------------------------------------------------
    cost_perfect = perfect_foresight_cost(realised, cfg)

    # --- baseline: commit the P50-optimal volumes -------------------------
    sched = self_schedule_position(forecast, cfg)
    ss = cost_of_committed_position(realised, cfg, sched,
                                    deviation_penalty=penalty)

    # --- method A: independent per-hour parametric curves ------------------
    grids = {i: price_grid_from_quantiles(*qh[i], n_points=n_points,
                                          widen=widen) for i in range(H)}
    t0 = time.time()
    curves_ind = build_day_bid_curves(forecast, cfg, grids)
    acc_ind = clear_day(curves_ind, realised_px)
    ind = cost_of_committed_position(realised, cfg, acc_ind,
                                     deviation_penalty=penalty)
    t_ind = time.time() - t0

    # --- method B: coherent price-path scenarios --------------------------
    t0 = time.time()
    paths = quantile_price_paths(qh, levels=levels)
    curves_sc = build_scenario_bid_curves(forecast, cfg, paths)
    acc_sc = clear_day(curves_sc, realised_px)
    sc = cost_of_committed_position(realised, cfg, acc_sc,
                                    deviation_penalty=penalty)
    t_sc = time.time() - t0

    # --- method C: bootstrapped hour-varying scenario paths ---------------
    t0 = time.time()
    p50_day = [qh[i][1] for i in range(H)]
    bpaths = bootstrap_price_paths(p50_day, blocks or [], n_paths=n_paths,
                                   seed=start)
    curves_bs = build_scenario_bid_curves(forecast, cfg, bpaths)
    acc_bs = clear_day(curves_bs, realised_px)
    bs = cost_of_committed_position(realised, cfg, acc_bs,
                                    deviation_penalty=penalty)
    t_bs = time.time() - t0

    if verbose:
        print(f"  day @h{start:5d}  perfect {cost_perfect:8.2f} | "
              f"boot {bs['cost']:8.2f} (dev {bs['deviation_kwh']:6.1f}) | "
              f"scenario {sc['cost']:8.2f} (dev {sc['deviation_kwh']:6.1f}) | "
              f"indep {ind['cost']:8.2f} (dev {ind['deviation_kwh']:6.1f}) | "
              f"self {ss['cost']:8.2f} | {t_sc:.0f}s/{t_ind:.0f}s")

    return {"start": start,
            "cost_perfect": cost_perfect,
            "cost_bootstrap": bs["cost"], "dev_bootstrap": bs["deviation_kwh"],
            "cost_scenario": sc["cost"], "dev_scenario": sc["deviation_kwh"],
            "cost_independent": ind["cost"], "dev_independent": ind["deviation_kwh"],
            "cost_self": ss["cost"], "dev_self": ss["deviation_kwh"],
            "repairs_bootstrap": sum(c["monotonicity_repairs"] for c in curves_bs.values()),
            "repairs_scenario": sum(c["monotonicity_repairs"] for c in curves_sc.values()),
            "repairs_independent": sum(c["monotonicity_repairs"] for c in curves_ind.values()),
            "curves": curves_bs, "accepted": acc_bs}


# ---------------------------------------------------------------------------
def plot_example(curves, realised_prices, path, hour=None):
    """Plot one hour's bid curve -- the single most presentable artefact this
    script produces, and the one to put on a slide."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib not installed -- skipping plot)")
        return

    if hour is None:                       # pick the most price-responsive hour
        hour = max(curves, key=lambda h: max(q for _, q in curves[h]["points"])
                   - min(q for _, q in curves[h]["points"]))
    pts = curves[hour]["points"]
    px = [p * 1000 for p, _ in pts]        # EUR/kWh -> EUR/MWh for the axis
    qy = [q for _, q in pts]
    clearing = realised_prices[hour] * 1000

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.step(px, qy, where="post", lw=2, label="submitted bid curve")
    ax.axvline(clearing, ls="--", lw=1.4, color="crimson",
               label=f"clearing price {clearing:.0f} EUR/MWh")
    ax.axhline(0, lw=0.8, color="0.5")
    ax.set_xlabel("Day-ahead price [EUR/MWh]")
    ax.set_ylabel("Net position [kW]   (+ import / − export)")
    ax.set_title(f"HEXOS day-ahead bid curve, hour {hour}")
    ax.legend(frameon=False)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, dpi=150)
    print(f"  Wrote {path}  (hour {hour})")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7,
                    help="number of bidding rounds to run")
    ap.add_argument("--start", type=int, default=24 * 40,
                    help="hour index of the first day (default: day 40, so the "
                         "naive fallback has history)")
    ap.add_argument("--points", type=int, default=7,
                    help="steps in each submitted bid curve")
    ap.add_argument("--widen", type=float, default=0.25,
                    help="fractional widening of the P10-P90 grid")
    ap.add_argument("--penalty", type=float, default=1.0,
                    help="deviation penalty [EUR/kWh] on undeliverable commitments")
    ap.add_argument("--paths", type=int, default=8,
                    help="number of bootstrapped scenario paths per day")
    ap.add_argument("--levels", type=str, default="0.05,0.25,0.5,0.75,0.95",
                    help="quantile levels for the scenario price paths")
    args = ap.parse_args()

    if not os.path.exists(YEAR):
        sys.exit("Run prepare_year.py first (need data/year_DE_2019.csv).")
    data = load_timeseries(YEAR)
    cfg = base_cfg()

    levels = tuple(float(x) for x in args.levels.split(","))
    fc = load_forecast_quantiles(FORECASTS)
    src = "forecast_prices.py quantiles" if fc else "naive trailing-quantile fallback"
    print(f"Day-ahead bidding experiment\n  forecast source: {src}\n")

    def quant_lookup(s0):
        if fc and all(h in fc for h in range(s0, s0 + H)):
            return {h: fc[h] for h in range(s0, s0 + H)}
        if s0 < 24 * 5:
            return None
        return naive_quantiles(data["price_el"], s0)

    rows, all_curves, first_realised = [], None, None
    for d in range(args.days):
        start = args.start + d * H
        if start + H > len(data["T"]):
            break
        if fc and all(h in fc for h in range(start, start + H)):
            quant = {h: fc[h] for h in range(start, start + H)}
        else:
            quant = naive_quantiles(data["price_el"], start)
        blocks = residual_blocks(data["price_el"], quant_lookup, start)
        r = run_day(data, cfg, start, quant, args.points, args.widen,
                    args.penalty, levels, blocks=blocks, n_paths=args.paths)
        if all_curves is None:
            all_curves = r["curves"]
            first_realised = [data["price_el"][start + i] for i in range(H)]
        rows.append({k: v for k, v in r.items() if k not in ("curves", "accepted")})

    if not rows:
        sys.exit("No days ran -- check --start and --days against the data length.")

    def tot(key):
        return sum(r[key] for r in rows)

    tot_p = tot("cost_perfect")
    results = [("Bootstrap-scenario bid curve", "cost_bootstrap", "dev_bootstrap"),
               ("Parallel-shift bid curve", "cost_scenario", "dev_scenario"),
               ("Independent-hour bid curve", "cost_independent", "dev_independent"),
               ("Self-schedule on P50", "cost_self", "dev_self")]

    print(f"\n=== Bidding results over {len(rows)} days ===")
    print(f"  {'Perfect foresight (bound)':30s} : {tot_p:11.2f} EUR")
    for label, ck, dk in results:
        c = tot(ck)
        print(f"  {label:30s} : {c:11.2f} EUR  "
              f"({100*(c-tot_p)/tot_p:+6.2f}% vs bound, "
              f"dev {tot(dk):7.1f} kWh)")

    gap_self = tot("cost_self") - tot_p
    print()
    for label, ck, _ in results[:3]:
        gap = tot(ck) - tot_p
        rec = 100.0 * (gap_self - gap) / gap_self if abs(gap_self) > 1e-9 else float("nan")
        print(f"  {label:30s} recovers {rec:6.1f}% of the forecast-error gap")

    print(f"\n  Monotonicity repairs  boot / parallel / independent : "
          f"{tot('repairs_bootstrap')} / {tot('repairs_scenario')} / "
          f"{tot('repairs_independent')}")

    if tot("cost_bootstrap") < tot_p - 1e-6:
        print("\n  WARNING: a bid curve beat perfect foresight. Impossible -- "
              "check the clearing logic or the deviation penalty.")
    if tot("cost_bootstrap") > tot("cost_self") + 1e-6:
        print("\n  NOTE: the scenario curve did worse than a fixed volume. "
              "Check whether clearing prices fell outside the bid grid.")

    os.makedirs(os.path.dirname(OUT_SUMMARY), exist_ok=True)
    with open(OUT_SUMMARY, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n  Wrote {OUT_SUMMARY}")

    with open(OUT_CURVES, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["hour", "bid_price_eur_per_kwh", "bid_quantity_kw"])
        for h, c in sorted(all_curves.items()):
            for p, q in c["points"]:
                w.writerow([h, f"{p:.6f}", f"{q:.3f}"])
    print(f"  Wrote {OUT_CURVES}")

    plot_example(all_curves, first_realised, OUT_PLOT)


if __name__ == "__main__":
    main()
