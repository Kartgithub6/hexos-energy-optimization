"""
run_baselines.py
================
What does the optimiser add, and against what?

The battery value from run_flex_value.py compares an optimised battery against
no battery at all. That is the right comparison for someone deciding whether to
BUY a battery. For someone who already OWNS one, the fair comparison is the
battery left in its built-in "maximise self-consumption" mode, which already
saves money without any optimisation. This script runs all three on the same
year, with everything else identical:

  A  no battery
  B  battery on a self-consumption rule (charge from solar surplus, cover own
     load, never charge from the grid, never look at prices)
  C  battery optimised together with the rest of the site

and reports every saving in both EUR and percent.

Optional realism switches, all off by default so the plain run reproduces the
existing configuration:

  --demand-charge  EUR per kW of annual peak import (German "Leistungspreis").
                   Tariffs vary a lot by grid operator and voltage level, so
                   take the value from your operator's price sheet.
  --chp-start-cost EUR per CHP start, standing in for wear on the engine.
  --max-starts     cap on CHP starts in any rolling 24 h.
  --capex          battery cost in EUR/kWh, to report a simple payback period
                   (no degradation, no discounting, so treat it as optimistic).

Run:
    python scenarios/run_baselines.py --data 2024
    python scenarios/run_baselines.py --data 2024 --demand-charge 100 --capex 400
    python scenarios/run_baselines.py --data 2024 --chp-start-cost 15 --max-starts 1
    python scenarios/run_baselines.py --data 2024 --days 14 --start-day 180   # quick check
"""
import _paths  # noqa

import argparse
import copy
import csv
import os
import sys
import time

from engine import load_timeseries, solve_rolling
from engine.data.io import make_data
from engine.control.rules import self_consumption_schedule
import demo_plant

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "data")


def resolve_dataset(arg):
    cands = [arg, os.path.join(DATA_DIR, arg), os.path.join(DATA_DIR, f"{arg}.csv"),
             os.path.join(DATA_DIR, f"year_DE_{arg}.csv"),
             os.path.join(DATA_DIR, f"year_{arg}.csv")]
    for c in cands:
        if os.path.isfile(c):
            return c, os.path.splitext(os.path.basename(c))[0].replace("year_", "")
    have = sorted(f for f in os.listdir(DATA_DIR) if f.startswith("year_"))
    sys.exit(f"No dataset matching '{arg}'. Available in data/: {have}")


def window_of(data, start, hours):
    idx = range(start, min(start + hours, len(data["T"])))
    return make_data(list(range(len(idx))), *[[data[k][i] for i in idx] for k in
                     ("price_el", "price_exp", "pv_avail", "dem_el", "dem_heat", "cop")])


def site_cfg(args, hours):
    cfg = demo_plant.demo_plant_cfg()
    if args.demand_charge:
        # The charge is annual: EUR per kW of the year's peak. A partial run
        # only gets its share, or two weeks would carry a whole year's charge.
        cfg["demand_charge"] = args.demand_charge * min(1.0, hours / 8760.0)
    if args.chp_start_cost:
        cfg["chp"]["startup_cost"] = args.chp_start_cost
    if args.max_starts is not None:
        cfg["chp"]["max_starts_per_day"] = args.max_starts
    return cfg


def run_case(label, data, cfg, args):
    t0 = time.time()
    r = solve_rolling(data, cfg, window_h=args.window, commit_h=args.commit,
                      verbose=False)
    e_cap = cfg.get("battery", {}).get("E_cap", 0.0)
    r["cycles"] = sum(r["charge"]) / e_cap if e_cap else 0.0
    r["label"] = label
    print(f"  {label:26s} {r['cost']:>11,.0f} EUR   starts {r['chp_starts']:>4d}   "
          f"peak {r['peak_import']:>6.0f} kW   [{time.time() - t0:.0f}s]")
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="2019")
    ap.add_argument("--days", type=int, default=None,
                    help="run only N days (quick check). Default: the full year")
    ap.add_argument("--start-day", type=int, default=0,
                    help="day of year to start a partial run, e.g. 180 for July")
    ap.add_argument("--window", type=int, default=48)
    ap.add_argument("--commit", type=int, default=24)
    ap.add_argument("--demand-charge", type=float, default=0.0)
    ap.add_argument("--chp-start-cost", type=float, default=0.0)
    ap.add_argument("--max-starts", type=int, default=None)
    ap.add_argument("--capex", type=float, default=None,
                    help="battery cost in EUR/kWh, for a simple payback period")
    args = ap.parse_args()

    path, tag = resolve_dataset(args.data)
    data = load_timeseries(path)
    if args.days:
        data = window_of(data, args.start_day * 24, args.days * 24)
    hours = len(data["T"])
    scale = 8760.0 / hours        # annualise a partial run

    base = site_cfg(args, hours)
    batt = base["battery"]
    print(f"Battery baselines on {os.path.basename(path)}  ({hours} h)\n"
          f"  rolling {args.window} h window, {args.commit} h commit · "
          f"demand charge {args.demand_charge} EUR/kW · "
          f"CHP start cost {args.chp_start_cost} EUR · "
          f"max starts/24h {args.max_starts}\n")
    if args.demand_charge and hours < 8700:
        print(f"  Partial run: demand charge prorated to {hours}/8760 of the "
              f"annual rate. Peak shaving value is only indicative until you "
              f"run the full year.\n")

    no_batt = copy.deepcopy(base)
    no_batt["battery"]["E_cap"] = 0.0

    rule = copy.deepcopy(base)
    ch, dis = self_consumption_schedule(data, batt)
    rule["battery"]["fixed_ch"], rule["battery"]["fixed_dis"] = ch, dis

    A = run_case("A  no battery", data, no_batt, args)
    B = run_case("B  self-consumption rule", data, rule, args)
    C = run_case("C  optimised", data, base, args)

    def save(x, ref):
        eur = ref["cost"] - x["cost"]
        pct = 100.0 * eur / ref["cost"] if ref["cost"] else 0.0
        return eur, pct

    b_eur, b_pct = save(B, A)
    c_eur, c_pct = save(C, A)
    add_eur, add_pct = save(C, B)

    print("\n=== Savings (scaled to a full year where the run is shorter) ===")
    print(f"  Rule vs no battery          : {b_eur * scale:>9,.0f} EUR/yr  ({b_pct:.2f}%)")
    print(f"  Optimised vs no battery     : {c_eur * scale:>9,.0f} EUR/yr  ({c_pct:.2f}%)")
    print(f"  Optimised vs rule           : {add_eur * scale:>9,.0f} EUR/yr  ({add_pct:.2f}%)"
          "   <- what the optimiser adds for a site that already has a battery")
    print(f"\n  Battery cycles per year     : rule {B['cycles'] * scale:.0f}, "
          f"optimised {C['cycles'] * scale:.0f}")
    print(f"  CHP starts per year         : A {A['chp_starts'] * scale:.0f}, "
          f"B {B['chp_starts'] * scale:.0f}, C {C['chp_starts'] * scale:.0f}")
    if args.demand_charge:
        print(f"  Demand charge share of cost : A {100*A['demand_cost']/A['cost']:.1f}%, "
              f"C {100*C['demand_cost']/C['cost']:.1f}%")

    payback = {}
    if args.capex:
        invest = args.capex * batt["E_cap"]
        for name, eur in (("rule", b_eur), ("optimised", c_eur)):
            yearly = eur * scale
            payback[name] = invest / yearly if yearly > 0 else float("inf")
        print(f"\n  Simple payback at {args.capex:.0f} EUR/kWh "
              f"(EUR {invest:,.0f}): rule {payback['rule']:.1f} yr, "
              f"optimised {payback['optimised']:.1f} yr")
        print("  No degradation and no discounting, so the real figure is longer.")

    # Settings go into the file name, so runs with different options never
    # overwrite each other.
    name = f"baselines_{tag}"
    if args.days:
        name += f"_d{args.days}s{args.start_day}"
    if args.demand_charge:
        name += f"_dc{args.demand_charge:g}"
    if args.chp_start_cost:
        name += f"_sc{args.chp_start_cost:g}"
    if args.max_starts is not None:
        name += f"_ms{args.max_starts}"
    out = os.path.join(ROOT, "results", f"{name}.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case", "cost_eur", "energy_eur", "startup_eur", "demand_eur",
                    "chp_starts", "peak_import_kw", "batt_cycles",
                    "saving_vs_A_eur", "saving_vs_A_pct"])
        for r in (A, B, C):
            eur, pct = save(r, A)
            w.writerow([r["label"], f"{r['cost']:.2f}", f"{r['energy_cost']:.2f}",
                        f"{r['startup_cost']:.2f}", f"{r['demand_cost']:.2f}",
                        r["chp_starts"], f"{r['peak_import']:.1f}",
                        f"{r['cycles']:.2f}", f"{eur:.2f}", f"{pct:.4f}"])
        w.writerow(["settings", f"hours={hours}", f"demand_charge={args.demand_charge}",
                    f"chp_start_cost={args.chp_start_cost}",
                    f"max_starts={args.max_starts}", f"capex={args.capex}",
                    f"window={args.window}", f"commit={args.commit}", "", ""])
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
