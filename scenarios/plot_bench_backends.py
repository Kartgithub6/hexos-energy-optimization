"""plot_bench_backends.py — chart for bench_backends.py.

    python scenarios/plot_bench_backends.py --data 2024
    -> results/bench_backends_2024.png
"""
import _paths  # noqa

import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
C = {"pyomo": "#eb6834", "linopy": "#6250d6", "pypsa": "#1baf7a"}
LABEL = {"pyomo": "Pyomo", "linopy": "Linopy", "pypsa": "PyPSA (on Linopy)"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e0"


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=10)
    ax.yaxis.grid(True, color=GRID, lw=1)
    ax.set_axisbelow(True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="2024")
    a = ap.parse_args()
    df = pd.read_csv(os.path.join(ROOT, "results", f"bench_backends_{a.data}.csv"))
    single = df[df["mode"] == "single"]
    year = df[df["mode"] != "single"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1.6, 1]})
    for b, d in single.groupby("backend"):
        d = d.sort_values("hours")
        ax1.plot(d.hours, d.total_s, color=C[b], lw=2, marker="o", ms=6,
                 markeredgecolor="white", markeredgewidth=1.5)
        last = d.iloc[-1]
        ax1.annotate(f"{LABEL[b]}  {last.total_s:.1f} s", (last.hours, last.total_s),
                     xytext=(8, 0), textcoords="offset points", va="center", fontsize=10, color=INK)
    ax1.set_xscale("log")
    ax1.set_xticks([48, 168, 720, 2184, 8760], ["48 h", "1 week", "1 month", "1 quarter", "1 year"])
    ax1.set_xlim(35, 30000)
    ax1.set_ylabel("build + solve, seconds", color=MUTED)
    ax1.set_title("One model, growing horizon (same MILP, same HiGHS)", loc="left", fontsize=11.5, color=INK)
    style(ax1)

    if len(year):
        xs = range(len(year))
        for x, (_, r) in zip(xs, year.iterrows()):
            ax2.bar(x, r.total_s, width=0.5, color=C[r.backend], lw=0)
            ax2.text(x, r.total_s + 6, f"{r.total_s:.0f} s", ha="center", va="bottom", fontsize=11,
                     color=INK, fontweight="bold")
        ax2.set_xticks(list(xs), [LABEL[b] for b in year.backend], fontsize=10.5)
        ax2.set_ylabel("seconds for the full year", color=MUTED)
        ax2.set_title("365 small 48 h windows (rolling year)", loc="left", fontsize=11.5, color=INK)
        ax2.set_ylim(0, year.total_s.max() * 1.18)
        style(ax2)
    fig.text(0.01, -0.03, "Demo plant on 2024 prices; every run in a fresh process; objectives agree "
             "to HiGHS's 1e-4 MIP gap. Linopy pays ~0.6 s of fixed set-up per model, so it wins on "
             "one big model and loses on many tiny ones.", fontsize=9, color=MUTED)
    fig.tight_layout()
    out = os.path.join(ROOT, "results", f"bench_backends_{a.data}.png")
    fig.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    print("wrote", out)


if __name__ == "__main__":
    main()
