"""
key_hours.py
============
Exact numbers behind the horizon-sweep dispatch figure, for talking through it.

Reads the per-run dispatch CSVs written by run_horizon_sweep.py (nothing is
re-solved) and prints, per season and horizon:

  * the tariff line from the year file header, so you know which mode built it
  * a weekly tally: battery cycles, CHP hours, export, PV used
  * the battery's charge / discharge windows day by day, with the price paid
    and earned, so "it charges cheap and discharges dear" has numbers on it
  * an hour-by-hour table for the hours you name (--hours) or, by default, the
    hours around the most expensive hour of the week
  * a 24 h vs 48 h comparison: cost gap from summary.csv and where the battery
    trajectories actually differ

Run (from the repo root):
    python scenarios/key_hours.py --tag DE_2024
    python scenarios/key_hours.py --tag DE_2024 --season summer --hours 106-116
    python scenarios/key_hours.py --tag DE_2024 --md results/key_hours_DE_2024.md

All hours are hour-of-week, counted from the week's start in UTC (the year file
indexes hours from 1 January 00:00 UTC).
"""
import _paths  # noqa

import argparse
import csv
import json
import os
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SWEEP_ROOT = os.path.join(ROOT, "results", "horizon_sweep")
DATA_DIR = os.path.join(ROOT, "data")

# Must match base_cfg() in run_horizon_sweep.py.
E_CAP, ETA_CH, ETA_DIS, ROD_ETA = 400.0, 0.96, 0.96, 0.99
PRICE_GAS, CHP_ETA_EL, CHP_HTP = 0.07, 0.40, 1.5
ON = 1.0  # kW threshold below which a flow counts as off


def load(sweep, season, case):
    p = os.path.join(sweep, season, case, "dispatch.csv")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        rd = csv.DictReader(f)
        rows = list(rd)
    d = {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}
    for k in ("import", "export", "pv_used", "charge", "discharge", "chp_el",
              "hp_heat", "rod_heat", "batt_soc"):
        d[k] = np.maximum(d[k], 0.0)          # solver noise like -1e-9
    cop = np.where(d["cop"] > 0.01, d["cop"], 1.0)
    d["hp_el"] = d["hp_heat"] / cop
    d["rod_el"] = d["rod_heat"] / ROD_ETA
    d["px"] = d["price_el"] * 1000.0                       # EUR/MWh
    d["chp_be"] = (PRICE_GAS / CHP_ETA_EL) / (1 + CHP_HTP / cop) * 1000.0
    return d


def tariff_line(meta):
    p = os.path.join(DATA_DIR, meta.get("dataset", ""))
    if not os.path.isfile(p):
        return f"(year file {meta.get('dataset')} not found in data/)"
    with open(p) as f:
        for line in f:
            if not line.startswith("#"):
                break
            if "tariff" in line:
                return line.strip("# \n")
    return "(no tariff line in header -- built by prepare_year.py?)"


def runs(mask):
    """Contiguous True runs as (start, end_inclusive)."""
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        if not v and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


def fmt_span(a, b):
    return f"h{a}" if a == b else f"h{a}-{b}"


def tally(d):
    n = len(d["t"])
    cyc = d["charge"].sum() / E_CAP
    chp_on = d["chp_el"] > ON
    lines = [
        f"  battery: {cyc:.2f} full-equivalent cycles "
        f"({cyc / (n / 24):.2f}/day), charged {d['charge'].sum():.0f} kWh, "
        f"discharged {d['discharge'].sum():.0f} kWh",
        f"  CHP: on {chp_on.sum()} of {n} h, {d['chp_el'].sum():.0f} kWh_el; "
        f"price above break-even in {(chp_on & (d['px'] > d['chp_be'])).sum()} "
        f"of those hours",
        f"  export: {d['export'].sum():.0f} kWh in {(d['export'] > ON).sum()} h",
        f"  PV used: {d['pv_used'].sum():.0f} of {d['pv_avail'].sum():.0f} kWh "
        f"available",
        f"  heat pump: {d['hp_el'].sum():.0f} kWh_el, rod: "
        f"{d['rod_el'].sum():.0f} kWh_el",
        f"  import price: {d['px'].min():.0f} to {d['px'].max():.0f} €/MWh, "
        f"mean {d['px'].mean():.0f}",
    ]
    return lines


def battery_windows(d):
    """Day-by-day charge and discharge windows with energy-weighted prices."""
    out = []
    for kind, key in (("charge", "charge"), ("discharge", "discharge")):
        for a, b in runs(d[key] > ON):
            e = d[key][a:b + 1]
            px = (e * d["px"][a:b + 1]).sum() / e.sum()
            out.append((a, b, kind, e.sum(), px))
    out.sort()
    lines = []
    for a, b, kind, e, px in out:
        day, hod0, hod1 = a // 24, a % 24, b % 24
        lines.append(f"  day {day}  {fmt_span(a, b):9s} ({hod0:02d}-{hod1 + 1:02d} "
                     f"UTC)  {kind:9s} {e:5.0f} kWh at {px:5.0f} €/MWh")
    return lines


HDR = ("  hour  UTC  price  CHPbe | demand   PV  import  dis  CHP | "
       "  chg  exp  HPel rodel |  SOC")


def row(d, i):
    return (f"  {i:4d}  {i % 24:02d}h  {d['px'][i]:5.0f}  {d['chp_be'][i]:5.0f} | "
            f"{d['dem_el'][i]:6.0f} {d['pv_used'][i]:4.0f} {d['import'][i]:7.0f} "
            f"{d['discharge'][i]:4.0f} {d['chp_el'][i]:4.0f} | "
            f"{d['charge'][i]:5.0f} {d['export'][i]:4.0f} {d['hp_el'][i]:5.0f} "
            f"{d['rod_el'][i]:5.0f} | {d['batt_soc'][i]:4.0f}")


def parse_hours(spec, n):
    if not spec:
        return None
    hs = []
    for part in spec.split(","):
        if "-" in part:
            a, b = (int(x) for x in part.split("-"))
            hs += list(range(a, b + 1))
        else:
            hs.append(int(part))
    return [h for h in hs if 0 <= h < n]


def compare(d24, d48):
    diff = d48["batt_soc"] - d24["batt_soc"]
    rms = float(np.sqrt(np.mean(diff ** 2)))
    lines = [f"  battery SOC, 48 h minus 24 h: RMS {rms:.1f} kWh, "
             f"max |diff| {np.abs(diff).max():.1f} kWh"]
    spans = runs(np.abs(diff) > 10.0)
    if not spans:
        lines.append("  no hour where the two trajectories differ by more than "
                     "10 kWh")
    for a, b in spans[:8]:
        k = a + int(np.argmax(np.abs(diff[a:b + 1])))
        lines.append(f"  {fmt_span(a, b):9s} differ, largest at h{k}: "
                     f"24 h {d24['batt_soc'][k]:.0f} kWh vs 48 h "
                     f"{d48['batt_soc'][k]:.0f} kWh (price {d24['px'][k]:.0f} €/MWh)")
    chp_diff = int(((d24["chp_el"] > ON) != (d48["chp_el"] > ON)).sum())
    lines.append(f"  CHP on/off decisions differ in {chp_diff} hours")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="e.g. DE_2024")
    ap.add_argument("--season", default="winter,summer",
                    help="comma-separated seasons")
    ap.add_argument("--hours", default=None,
                    help="hours to tabulate, e.g. 106-116 or 30,31,40-44 "
                         "(default: 6 h either side of the dearest hour)")
    ap.add_argument("--md", default=None,
                    help="also write everything to this markdown file")
    args = ap.parse_args()

    sweep = os.path.join(SWEEP_ROOT, args.tag)
    mp = os.path.join(sweep, "meta.json")
    if not os.path.exists(mp):
        sys.exit(f"Missing {mp}. Run run_horizon_sweep.py --data <year> first.")
    meta = json.load(open(mp))
    horizons = meta["horizons"]
    summary = {}
    sp = os.path.join(sweep, "summary.csv")
    if os.path.exists(sp):
        for r in csv.DictReader(open(sp)):
            summary[(r["season"], r["case"])] = r

    out = [f"# Key hours -- {args.tag}",
           f"tariff: {tariff_line(meta)}",
           f"commit {meta['commit_h']} h, forecast {meta['forecast']}, "
           f"horizons {horizons}", ""]
    for season in [s.strip() for s in args.season.split(",")]:
        runs_ = {h: load(sweep, season, f"h{h:02d}") for h in horizons}
        runs_ = {h: v for h, v in runs_.items() if v is not None}
        if not runs_:
            out.append(f"## {season}: no results\n")
            continue
        start = meta["seasons"].get(season, "?")
        out.append(f"## {season} (week starts at year hour {start})")
        ss = summary.get((season, "single_shot"))
        for h, d in runs_.items():
            r = summary.get((season, f"h{h:02d}"))
            gap = (f"cost {float(r['cost']):.2f} EUR, {float(r['gap_pct']):+.4f}% "
                   f"vs single-shot {float(ss['cost']):.2f} EUR" if r and ss
                   else "(no summary row)")
            out += [f"### {h} h horizon -- {gap}"] + tally(d) + [""]
            out += ["  battery windows:"] + battery_windows(d) + [""]
            hours = parse_hours(args.hours, len(d["t"]))
            if hours is None:
                k = int(np.argmax(d["px"]))
                hours = list(range(max(0, k - 6), min(len(d["t"]), k + 7)))
                out.append(f"  hours around the dearest hour (h{k}):")
            out += [HDR] + [row(d, i) for i in hours] + [""]
        if 24 in runs_ and 48 in runs_:
            out += ["### 24 h vs 48 h"] + compare(runs_[24], runs_[48]) + [""]
        out.append("")

    text = "\n".join(out)
    print(text)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(text.replace("\n  ", "\n    ") + "\n")
        print(f"Wrote {args.md}")


if __name__ == "__main__":
    main()
