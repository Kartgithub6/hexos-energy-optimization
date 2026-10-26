"""
animate_wear_value.py
=====================
A short looping animation for posts and slides: as the value of the battery
cells rises, the wear-blind battery's net value collapses while wear-aware
dispatch holds on.

Reads results/wear_value_<tag>.csv (run_wear_value.py with a capex sweep) and
writes results/wear_value_anim.gif (1200 x 1200 px, LinkedIn's square format).

    python scenarios/animate_wear_value.py --tags DE_2019,DE_2024
"""
import _paths  # noqa

import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RES = os.path.join(ROOT, "results")
C = {"B  wear-blind": "#eb6834", "C  throughput": "#1baf7a", "D  cycle-depth": "#6250d6"}
NAME = {"B  wear-blind": "Wear-blind", "C  throughput": "Wear-aware\nthroughput",
        "D  cycle-depth": "Wear-aware\ncycle depth"}
TITLE = {"DE_2019": "2019 prices · retail tariff", "DE_2024": "2024 prices · spot-linked",
         "DE_2024_retail": "2024 prices · retail tariff", "DE_2025": "2025 prices · spot-linked"}
INK, MUTED, GRID, BG = "#1b1b3a", "#52514e", "#e6e5e0", "#fdfcf9"


def eur(v):
    sign = "−" if v < 0 else ""
    return f"{sign}€{abs(v)/1000:.1f}k"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", default="DE_2019,DE_2024")
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--out", default=os.path.join(RES, "wear_value_anim.gif"))
    a = ap.parse_args()
    tags = a.tags.split(",")
    data = {t: pd.read_csv(os.path.join(RES, f"wear_value_{t}.csv")) for t in tags}
    capex = sorted(data[tags[0]].capex_eur_per_kwh.unique())
    cases = list(C)

    def at(t, case, col, cx):
        d = data[t][data[t].case == case].sort_values("capex_eur_per_kwh")
        return float(np.interp(cx, d.capex_eur_per_kwh, d[col]))

    lo = min(min(d.net_value_eur.min() for d in data.values()), 0) * 1.15
    hi = max(d.gross_saving_eur.max() for d in data.values()) * 1.18

    # sweep up, hold, sweep back, hold: a seamless loop
    up = np.linspace(capex[0], capex[-1], a.fps * 4)
    frames = np.concatenate([up, [capex[-1]] * a.fps, up[::-1], [capex[0]] * a.fps])

    fig = plt.figure(figsize=(6, 6), dpi=200, facecolor=BG)
    axes = [fig.add_axes([0.08 + i * 0.47, 0.17, 0.42, 0.6]) for i in range(len(tags))]
    head = fig.text(0.04, 0.93, "", fontsize=15, color=INK, fontweight="bold")
    fig.text(0.04, 0.885, "What a 400 kWh battery earns per year once its wear is priced",
             fontsize=9.5, color=MUTED)
    fig.text(0.04, 0.035, "Light bar: saving, energy only. Solid: after wear. HEXOS · Pyomo/HiGHS · "
             "illustrative cell ageing (6,000 cycles, depth^1.5)", fontsize=6.5, color=MUTED)

    def draw(cx):
        head.set_text(f"Cells worth €{cx:.0f} per kWh")
        for ax, t in zip(axes, tags):
            ax.clear()
            ax.set_facecolor(BG)
            for i, case in enumerate(cases):
                g, n = at(t, case, "gross_saving_eur", cx), at(t, case, "net_value_eur", cx)
                ax.bar(i, g, width=0.62, color=C[case], alpha=0.22, lw=0)
                ax.bar(i, n, width=0.62, color=C[case], lw=0)
                ax.text(i, max(g, 0) + hi * 0.025, eur(n), ha="center", va="bottom", fontsize=8.5,
                        color=INK, fontweight="bold")
            ax.axhline(0, color=MUTED, lw=0.8)
            ax.set_ylim(lo, hi)
            ax.set_xticks(range(3), [NAME[c] for c in cases], fontsize=7, color=INK)
            ax.set_yticks([])
            for s in ("top", "right", "left"):
                ax.spines[s].set_visible(False)
            ax.spines["bottom"].set_color(GRID)
            ax.set_title(TITLE.get(t, t), fontsize=9, color=INK, loc="left")
        return []

    anim = FuncAnimation(fig, lambda i: draw(frames[i]), frames=len(frames), blit=False)
    anim.save(a.out, writer=PillowWriter(fps=a.fps))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
