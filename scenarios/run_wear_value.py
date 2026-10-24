"""
run_wear_value.py
=================
Does the battery still pay once its wear is priced?

run_baselines.py reports the optimised battery's saving with every kWh of
cycling treated as free. This script asks the next question: how much of that
saving is eaten by the capacity the cycling uses up, and how much better does
dispatch get when the optimiser KNOWS about wear?

Same site, same year, same rolling-horizon settings; only the battery's
objective changes:

  A   no battery                       (reference cost)
  B   wear-blind optimiser             (today's HEXOS: cycles whenever spreads cover losses)
  C   wear-aware, throughput cost      (every kWh cycled costs the same)
  D   wear-aware, cycle-depth cost     (deep cycles cost more than shallow ones)

Every schedule is then scored by ONE yardstick (engine.postprocess.wear:
rainflow counting + the same cycle-depth stress function + calendar ageing),
so B, C and D are judged identically:

  gross saving  = cost(A) - energy cost of the case
  wear          = cells used up, in EUR (capex x fraction of life consumed)
  net value     = gross saving - wear

Wear parameters are ILLUSTRATIVE (LFP-like order of magnitude), not fitted to
a cell, and are printed with every run. Change them on the command line.

Run:
    python scenarios/run_wear_value.py --data 2024
    python scenarios/run_wear_value.py --data 2019
    python scenarios/run_wear_value.py --data 2024 --capex 100,200,300   # sensitivity
    python scenarios/run_wear_value.py --data 2024 --days 14 --start-day 180  # quick check
"""
import _paths  # noqa

import argparse
import copy
import csv
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from engine import load_timeseries, solve_rolling
from engine.data.io import make_data
from engine.postprocess.wear import evaluate_wear
import demo_plant

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "data")


def resolve_dataset(arg):
    for c in (arg, os.path.join(DATA_DIR, arg), os.path.join(DATA_DIR, f"{arg}.csv"),
              os.path.join(DATA_DIR, f"year_DE_{arg}.csv"), os.path.join(DATA_DIR, f"year_{arg}.csv")):
        if os.path.isfile(c):
            return c, os.path.splitext(os.path.basename(c))[0].replace("year_", "")
    sys.exit(f"No dataset matching '{arg}' in data/")


def window_of(data, start, hours):
    idx = range(start, min(start + hours, len(data["T"])))
    return make_data(list(range(len(idx))), *[[data[k][i] for i in idx] for k in
                     ("price_el", "price_exp", "pv_avail", "dem_el", "dem_heat", "cop")])


def _solve(job):
    label, data, cfg, window, commit = job
    t0 = time.time()
    r = solve_rolling(data, cfg, window_h=window, commit_h=commit, verbose=False)
    keep = {k: r[k] for k in ("soc", "charge", "discharge", "import", "export", "cost")}
    keep["label"], keep["secs"] = label, time.time() - t0
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="2024")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--start-day", type=int, default=0)
    ap.add_argument("--window", type=int, default=48)
    ap.add_argument("--commit", type=int, default=24)
    ap.add_argument("--capex", default="200",
                    help="cell replacement value, EUR/kWh; comma list for a sweep")
    ap.add_argument("--cycle-life", type=float, default=6000.0,
                    help="equivalent full cycles to end of life at 100%% depth")
    ap.add_argument("--dod-exponent", type=float, default=1.5)
    ap.add_argument("--segments", type=int, default=5)
    ap.add_argument("--calendar-life", type=float, default=15.0,
                    help="years to end of life from calendar ageing alone (0 = off)")
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    path, tag = resolve_dataset(args.data)
    data = load_timeseries(path)
    if args.days:
        data = window_of(data, args.start_day * 24, args.days * 24)
    hours = len(data["T"])
    scale = 8760.0 / hours
    capexes = [float(x) for x in args.capex.split(",")]

    base = demo_plant.demo_plant_cfg()
    E = base["battery"]["E_cap"]

    def wear(model, capex):
        return {"model": model, "capex_eur_per_kwh": capex, "cycle_life_efc": args.cycle_life,
                "dod_exponent": args.dod_exponent, "segments": args.segments}

    jobs = []
    nb = copy.deepcopy(base); nb["battery"]["E_cap"] = 0.0
    jobs.append(("A  no battery", data, nb, args.window, args.commit))
    jobs.append(("B  wear-blind", data, copy.deepcopy(base), args.window, args.commit))
    for cx in capexes:
        c = copy.deepcopy(base); c["battery"]["wear"] = wear("throughput", cx)
        jobs.append((f"C  throughput @{cx:g}", data, c, args.window, args.commit))
        d = copy.deepcopy(base); d["battery"]["wear"] = wear("cycle_depth", cx)
        jobs.append((f"D  cycle-depth @{cx:g}", data, d, args.window, args.commit))

    print(f"Battery wear value on {os.path.basename(path)} ({hours} h), battery {E:g} kWh / "
          f"{base['battery']['p_dis_max']:g} kW")
    print(f"  wear yardstick: cycle life {args.cycle_life:g} EFC, depth exponent "
          f"{args.dod_exponent:g}, calendar life {args.calendar_life:g} yr, capex {capexes} EUR/kWh"
          f"  (illustrative, not fitted to a cell)\n")

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        res = {r["label"]: r for r in ex.map(_solve, jobs)}

    A = res["A  no battery"]
    rows = []
    cal = args.calendar_life or None
    for cx in capexes:
        yard = {"capex_eur_per_kwh": cx, "cycle_life_efc": args.cycle_life,
                "dod_exponent": args.dod_exponent}
        for label in ("B  wear-blind", f"C  throughput @{cx:g}", f"D  cycle-depth @{cx:g}"):
            r = res[label]
            w = evaluate_wear(r["soc"], r["charge"], r["discharge"], E, yard,
                              calendar_life_years=cal, soc0=base["battery"]["soc_init"])
            gross = (A["cost"] - r["cost"]) * scale
            wear_eur = w["cycle_wear_eur"] * scale     # dispatch-driven part
            cal_eur = (w["wear_eur"] - w["cycle_wear_eur"]) * scale
            rows.append({
                "dataset": tag, "capex_eur_per_kwh": cx, "case": label.split("@")[0].strip(),
                "gross_saving_eur": gross, "cycle_wear_eur": wear_eur,
                "calendar_wear_eur": cal_eur, "net_value_eur": gross - wear_eur,
                "efc_per_year": w["efc"] * scale, "mean_cycle_depth": w["mean_depth"],
                "years_to_eol": w["years_to_eol"], "solve_s": r["secs"],
            })

    print(f"{'capex':>6} {'case':22s} {'gross':>9} {'wear':>8} {'net':>9} {'EFC/yr':>7} "
          f"{'depth':>6} {'life yr':>7}")
    for x in rows:
        print(f"{x['capex_eur_per_kwh']:>6.0f} {x['case']:22s} {x['gross_saving_eur']:>9,.0f} "
              f"{x['cycle_wear_eur']:>8,.0f} {x['net_value_eur']:>9,.0f} {x['efc_per_year']:>7.0f} "
              f"{x['mean_cycle_depth']:>6.2f} {x['years_to_eol']:>7.1f}")
    print("\n  gross = saving vs no battery (energy only); wear = cycle ageing in EUR;"
          " net = gross - wear.\n  Calendar ageing is the same order for every case and is"
          " left out of net; it is in the CSV.")

    name = f"wear_value_{tag}" + (f"_d{args.days}s{args.start_day}" if args.days else "")
    out = os.path.join(ROOT, "results", f"{name}.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for x in rows:
            w.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v) for k, v in x.items()})
    # dispatch traces for plotting (SoC and price)
    traces = {"price_el": data["price_el"], "price_exp": data["price_exp"],
              **{lab: res[lab]["soc"] for lab in res if not lab.startswith("A")}}
    with open(os.path.join(ROOT, "results", f"{name}_soc.json"), "w") as f:
        json.dump({"meta": vars(args) | {"E_cap": E, "hours": hours}, "traces": traces}, f)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
