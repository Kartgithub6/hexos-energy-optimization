"""
animate_dispatch.py
===================
Turn one week of dispatch into a short video.

Why this exists
---------------
The season x horizon grid is eight panels of a full week each. It is the right
figure for a report, where someone can sit with it — and the wrong one for a
feed, where nobody zooms in. Animation fixes that without dumbing anything
down: a rolling window moves across the week, so the viewer sees one day at a
time at readable scale, and the battery trajectory plays out rather than
sitting there as a dense line.

What it draws
-------------
Top panel  — the electricity balance as a stacked area. Sources above the axis
             (PV used, grid import, battery discharge, CHP), sinks below
             (battery charge, grid export, heat pump, heating rod), with
             electricity demand as a dotted line and battery energy content on
             the right axis.
Bottom     — the day-ahead price, with a marker tracking the current hour, so
             you can see the battery charging into the dips and discharging
             into the peaks as it happens.

Output is MP4 by default (best for LinkedIn native video) or GIF.

Run after run_horizon_sweep.py:
    python scenarios/animate_dispatch.py
    python scenarios/animate_dispatch.py --tag DE_2024 --season summer --case h24
    python scenarios/animate_dispatch.py --format gif --window 36 --fps 12
"""
import _paths  # noqa

import argparse
import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation, FFMpegWriter, PillowWriter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SWEEP_ROOT = os.path.join(ROOT, "results", "horizon_sweep")

# Same palette as plot_horizon_sweep.py -- indigo/slate/plum with amber for PV.
C_PV, C_IMP, C_DIS, C_CHP = "#E9C46A", "#7D8597", "#3D348B", "#A288E3"
C_CHG, C_EXP, C_HP, C_ROD = "#5C6784", "#B8B3D9", "#6D597A", "#C3B5CE"
C_SOC, C_PRICE = "#1B1B3A", "#4A4E69"
ROD_ETA = 0.99


def load_run(sweep, season, case):
    p = os.path.join(sweep, season, case, "dispatch.csv")
    if not os.path.exists(p):
        sys.exit(f"Missing {p}\n  Run run_horizon_sweep.py first.")
    cols = {}
    with open(p) as f:
        rd = csv.DictReader(f)
        for k in rd.fieldnames:
            cols[k] = []
        for r in rd:
            for k in rd.fieldnames:
                cols[k].append(float(r[k]))
    return {k: np.array(v) for k, v in cols.items()}


def pick_tag(explicit):
    if explicit:
        return explicit
    if not os.path.isdir(SWEEP_ROOT):
        sys.exit("No sweep results. Run run_horizon_sweep.py first.")
    tags = [d for d in os.listdir(SWEEP_ROOT)
            if os.path.isfile(os.path.join(SWEEP_ROOT, d, "meta.json"))]
    if not tags:
        sys.exit("No sweep results. Run run_horizon_sweep.py first.")
    return sorted(tags, key=lambda d: os.path.getmtime(
        os.path.join(SWEEP_ROOT, d, "meta.json")))[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=None, help="dataset, e.g. DE_2024")
    ap.add_argument("--season", default="summer",
                    choices=["winter", "spring", "summer", "autumn"])
    ap.add_argument("--case", default="h24", help="h24, h48 or single_shot")
    ap.add_argument("--window", type=int, default=48,
                    help="hours visible at once. 48 shows two days, which is "
                         "enough context to see a cycle without crowding.")
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--step", type=int, default=1,
                    help="hours advanced per frame. 2 halves the runtime.")
    ap.add_argument("--format", choices=["mp4", "gif"], default="mp4")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    tag = pick_tag(args.tag)
    sweep = os.path.join(SWEEP_ROOT, tag)
    d = load_run(sweep, args.season, args.case)

    t = d["t"]
    n = len(t)
    win = min(args.window, n)
    cop = np.where(d["cop"] > 0.01, d["cop"], 1.0)
    hp_el = d["hp_heat"] / cop
    rod_el = d["rod_heat"] / ROD_ETA
    price = d["price_el"] * 1000.0

    # Fixed axis limits across every frame. If the axes rescaled as the window
    # moved, the viewer would read the rescaling as a change in the data.
    up_max = float((d["pv_used"] + d["import"] + d["discharge"] + d["chp_el"]).max())
    dn_max = float((d["charge"] + d["export"] + hp_el + rod_el).max())
    ylim = (-dn_max * 1.08 - 1, up_max * 1.08 + 1)
    soc_lim = (0, float(max(d["batt_soc"].max(), 1.0)) * 1.08)
    p_lim = (min(0.0, price.min()) * 1.1 - 1, price.max() * 1.12 + 1)

    fig, (ax, pax) = plt.subplots(
        2, 1, figsize=(12.8, 7.6), sharex=True,
        gridspec_kw={"height_ratios": [3.1, 1]})
    fig.subplots_adjust(top=0.82, bottom=0.09, left=0.07, right=0.92, hspace=0.12)
    ax2 = ax.twinx()

    def draw(frame):
        s = frame * args.step
        e = min(s + win, n)
        sl = slice(s, e)
        x = t[sl]

        ax.clear(); ax2.clear(); pax.clear()

        ax.stackplot(x, d["pv_used"][sl], d["import"][sl], d["discharge"][sl],
                     d["chp_el"][sl], colors=[C_PV, C_IMP, C_DIS, C_CHP],
                     alpha=0.93,
                     labels=["PV used", "grid import", "battery discharge", "CHP"])
        ax.stackplot(x, -d["charge"][sl], -d["export"][sl], -hp_el[sl],
                     -rod_el[sl], colors=[C_CHG, C_EXP, C_HP, C_ROD], alpha=0.93,
                     labels=["battery charge", "grid export", "heat pump",
                             "heating rod"])
        ax.plot(x, d["dem_el"][sl], lw=1.2, color="#222", ls=":",
                label="electricity demand")
        ax.axhline(0, lw=0.8, color="#444")
        ax.set_ylim(*ylim)
        ax.set_xlim(x[0], x[0] + win - 1)
        ax.set_ylabel("kW", fontsize=11)
        ax.tick_params(labelsize=9)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.16), ncol=5,
                  frameon=False, fontsize=8.8)

        # twinx loses its right-side placement after clear(); restore it or the
        # label and ticks render on top of the left axis.
        ax2.yaxis.set_label_position("right")
        ax2.yaxis.tick_right()
        ax2.plot(x, d["batt_soc"][sl], lw=2.1, color=C_SOC)
        ax2.set_ylim(*soc_lim)
        ax2.set_xlim(x[0], x[0] + win - 1)
        ax2.set_ylabel("battery energy content [kWh]", fontsize=10, color=C_SOC)
        ax2.tick_params(labelsize=9, colors=C_SOC)

        pax.plot(x, price[sl], lw=1.6, color=C_PRICE)
        pax.fill_between(x, price[sl], p_lim[0], alpha=0.15, color=C_PRICE)
        # Marker on the newest hour, so the eye has something to follow.
        pax.plot([x[-1]], [price[e - 1]], "o", ms=9, color=C_PV,
                 markeredgecolor=C_SOC, markeredgewidth=1.2, zorder=5)
        pax.annotate(f"{price[e-1]:.0f} €/MWh", xy=(x[-1], price[e - 1]),
                     xytext=(-10, 12), textcoords="offset points",
                     ha="right", fontsize=10, fontweight="bold", color=C_SOC)
        pax.set_ylim(*p_lim)
        pax.set_xlim(x[0], x[0] + win - 1)
        pax.set_ylabel("€/MWh", fontsize=11)
        pax.set_xlabel("hour of week", fontsize=11)
        pax.tick_params(labelsize=9)
        pax.grid(alpha=0.2)

        for a in (ax, pax):
            for sp in ("top", "right"):
                a.spines[sp].set_visible(False)
        ax2.spines["top"].set_visible(False)

        fig.suptitle(f"HEXOS — one week of optimised dispatch  ·  {args.season}"
                     f"  ·  {tag.replace('_', ' ')}  ·  {args.case} horizon",
                     fontsize=14, fontweight="bold", y=0.985)

    frames = max(1, (n - win) // args.step + 1)
    anim = FuncAnimation(fig, draw, frames=frames, interval=1000 / args.fps)

    out = args.out or os.path.join(
        ROOT, "results", f"dispatch_{tag}_{args.season}_{args.case}.{args.format}")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    if args.format == "mp4":
        try:
            writer = FFMpegWriter(fps=args.fps, bitrate=2400)
            anim.save(out, writer=writer, dpi=110)
        except (FileNotFoundError, RuntimeError):
            out = out[:-4] + ".gif"
            print("  ffmpeg not found — writing GIF instead.")
            anim.save(out, writer=PillowWriter(fps=args.fps), dpi=95)
    else:
        anim.save(out, writer=PillowWriter(fps=args.fps), dpi=95)

    plt.close(fig)
    size_mb = os.path.getsize(out) / 1e6
    print(f"Wrote {out}")
    print(f"  {frames} frames at {args.fps} fps "
          f"= {frames/args.fps:.0f}s · {size_mb:.1f} MB")
    if size_mb > 200:
        print("  Note: LinkedIn caps native video around 200 MB. "
              "Lower --fps or raise --step.")


if __name__ == "__main__":
    main()
