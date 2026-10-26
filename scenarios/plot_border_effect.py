"""
plot_border_effect.py
=====================
Shows WHY a 24 h horizon loses money when the plan is made once a day.

Top: day-ahead import price. Bottom: battery energy content for three
controllers over the same days, all with perfect price knowledge:

  * the full-week optimum (sees every hour of the week at once)
  * 48 h horizon, re-planned once a day
  * 24 h horizon, re-planned once a day

Each daily plan ends at midnight. The 24 h controller sees no value in energy
left after that, so it sells it all off the evening before and starts the next
day empty. The 48 h controller can see tomorrow and keeps what it needs.

Reads the dispatch files written by
    python scenarios/run_horizon_sweep.py --data 2024 --commit 24

Run:
    python scenarios/plot_border_effect.py
    python scenarios/plot_border_effect.py --season winter --days 4
"""
import _paths  # noqa

import argparse
import csv
import datetime as dt
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SWEEP = os.path.join(ROOT, "results", "horizon_sweep")

NAVY, INDIGO, AMBER, SLATE, GREY = "#1B1B3A", "#3D348B", "#E9C46A", "#7D8597", "#6B6B7B"
PRICE = "#4A4E69"


def load(path):
    if not os.path.isfile(path):
        sys.exit(f"Missing {path}\n  Run: python scenarios/run_horizon_sweep.py "
                 f"--data 2024 --commit 24")
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return {k: [float(r[k]) for r in rows] for k in rows[0]}


def gap_pct(folder, season, case):
    p = os.path.join(folder, "summary.csv")
    if not os.path.isfile(p):
        return None
    with open(p) as f:
        for r in csv.DictReader(f):
            if r["season"] == season and r["case"] == case:
                return float(r["gap_pct"])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="DE_2024_c24")
    ap.add_argument("--season", default="summer")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--start-day", type=int, default=None,
                    help="first day of the week to show (0-6). Default: the "
                         "stretch where 24 h and 48 h differ most")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    folder = os.path.join(SWEEP, args.tag)
    base = os.path.join(folder, args.season)
    full = load(os.path.join(base, "single_shot", "dispatch.csv"))
    h48 = load(os.path.join(base, "h48", "dispatch.csv"))
    h24 = load(os.path.join(base, "h24", "dispatch.csv"))

    n = len(full["t"])
    span = min(args.days * 24, n)
    if args.start_day is None:
        diff = [abs(a - b) for a, b in zip(h24["batt_soc"], h48["batt_soc"])]
        starts = range(0, n - span + 1, 24)
        s0 = max(starts, key=lambda s: sum(diff[s:s + span]))
    else:
        s0 = min(args.start_day * 24, n - span)
    sl = slice(s0, s0 + span)
    hrs = list(range(span))

    # Calendar labels, if the sweep recorded where the week starts.
    year = next((int(p) for p in args.tag.split("_") if p.isdigit() and len(p) == 4), None)
    start_h = None
    meta = os.path.join(folder, "meta.json")
    if os.path.isfile(meta):
        start_h = json.load(open(meta)).get("seasons", {}).get(args.season)
    day0 = (dt.datetime(year, 1, 1) + dt.timedelta(hours=start_h + s0)
            if year and start_h is not None else None)

    fig, (axp, axs) = plt.subplots(2, 1, figsize=(12, 7.2), dpi=150, sharex=True,
                                   gridspec_kw={"height_ratios": [1, 2.1]})
    fig.subplots_adjust(left=0.08, right=0.97, top=0.89, bottom=0.11, hspace=0.08)

    price = [p * 1000 for p in full["price_el"][sl]]
    axp.step(hrs, price, where="post", color=PRICE, lw=1.4)
    axp.fill_between(hrs, price, min(0, min(price)), step="post", color=PRICE, alpha=0.10)
    axp.set_ylabel("price\n[€/MWh]", fontsize=10, color=GREY)

    g24 = gap_pct(folder, args.season, "h24")
    g48 = gap_pct(folder, args.season, "h48")
    lab24 = "24 h horizon, planned once a day" + (f"  (+{g24:.2f}% cost)" if g24 is not None else "")
    g48 = None if g48 is None else (g48 if g48 > 0 else 0.0)
    lab48 = "48 h horizon, planned once a day" + (f"  (+{g48:.2f}% cost)" if g48 is not None else "")

    soc24, soc48, socf = h24["batt_soc"][sl], h48["batt_soc"][sl], full["batt_soc"][sl]
    axs.fill_between(hrs, soc24, soc48, where=[b > a + 1 for a, b in zip(soc24, soc48)],
                     color=AMBER, alpha=0.28, lw=0, label="charge the 24 h plan is missing")
    axs.plot(hrs, soc48, color=INDIGO, lw=2.0, label=lab48)
    axs.plot(hrs, soc24, color=AMBER, lw=2.2, label=lab24)
    axs.set_ylabel("battery energy [kWh]", fontsize=10, color=GREY)
    top = max(socf + soc48 + soc24 + [1.0])
    axs.set_ylim(0, top * 1.32)

    # Point at the hour where the 24 h plan falls furthest behind.
    gaps = [b - a for a, b in zip(soc24, soc48)]
    k = max(range(span), key=lambda i: gaps[i])
    if gaps[k] > 1:
        axs.annotate("the 24 h plan cannot see\npast midnight",
                     xy=(k, (soc24[k] + soc48[k]) / 2), xytext=(k + 7, top * 0.62),
                     fontsize=9.5, color=NAVY,
                     arrowprops=dict(arrowstyle="->", color=NAVY, lw=1))

    for d in range(1, args.days):
        for ax in (axp, axs):
            ax.axvline(d * 24, color=GREY, lw=0.8, ls=":")
    axp.text(24, axp.get_ylim()[1], " daily re-plan", fontsize=8.5, color=GREY, va="top")

    ticks = list(range(0, span + 1, 6))
    axs.set_xticks(ticks)
    if day0:
        labels = []
        for h in ticks:
            t = day0 + dt.timedelta(hours=h)
            labels.append(t.strftime("%a %d %b") if t.hour == 0 else t.strftime("%H:%M"))
        axs.set_xticklabels(labels, fontsize=9)
    else:
        axs.set_xlabel("hour", fontsize=10, color=GREY)

    for ax in (axp, axs):
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(labelsize=9, colors=GREY)
        ax.grid(axis="y", alpha=0.2)
    axs.legend(frameon=False, fontsize=9, loc="upper left", ncol=1)

    fig.text(0.08, 0.935, "Planning once a day: 24 h vs 48 h horizon",
             fontsize=15, fontweight="bold", color=NAVY)
    fig.text(0.08, 0.025, f"{args.days} {args.season} days, German day-ahead prices"
             f"{f' {year}' if year else ''}, perfect price knowledge. Cost is for the "
             "whole week, against the full-week optimum. Prices: Fraunhofer ISE "
             "Energy-Charts (CC BY 4.0).", fontsize=8, color=GREY)

    out = args.out or os.path.join(ROOT, "results", f"border_effect_{args.tag}_{args.season}.png")
    fig.savefig(out, dpi=150, facecolor="white")
    print(f"Wrote {out}  (days {s0 // 24}-{s0 // 24 + args.days - 1} of the week)")


if __name__ == "__main__":
    main()
