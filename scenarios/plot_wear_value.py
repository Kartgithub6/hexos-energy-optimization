"""
plot_wear_value.py
==================
Figures for the battery-wear experiment (run_wear_value.py).

  results/wear_value_summary.png  gross saving vs net value after wear, per year
  results/wear_value_sweep.png    net value vs cell cost, wear-blind vs wear-aware
  results/wear_value_week.png     one summer week: how wear-aware dispatch cycles

Run (after run_wear_value.py for the datasets you want):
    python scenarios/plot_wear_value.py --tags DE_2019,DE_2024,DE_2024_retail --capex 200
"""
import _paths  # noqa

import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RES = os.path.join(ROOT, "results")

# validated categorical trio (dataviz validator: CVD and normal-vision pass)
C = {"B  wear-blind": "#eb6834", "C  throughput": "#1baf7a", "D  cycle-depth": "#6250d6"}
NAME = {"B  wear-blind": "Wear-blind\n(today)", "C  throughput": "Wear-aware\nthroughput",
        "D  cycle-depth": "Wear-aware\ncycle-depth"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e0"
TITLE = {"DE_2019": "2019 prices · retail tariff", "DE_2024": "2024 prices · spot-linked tariff",
         "DE_2024_retail": "2024 prices · retail tariff", "DE_2025": "2025 prices · spot-linked tariff"}


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.yaxis.grid(True, color=GRID, lw=1)
    ax.set_axisbelow(True)


def eur(v):
    sign = "−" if v < 0 else ""
    v = abs(v)
    return f"{sign}€{v/1000:.1f}k" if v >= 1000 else f"{sign}€{v:.0f}"


def summary(tags, capex):
    fig, axes = plt.subplots(1, len(tags), figsize=(4.2 * len(tags), 4.4), sharey=True)
    axes = [axes] if len(tags) == 1 else axes
    for ax, tag in zip(axes, tags):
        df = pd.read_csv(os.path.join(RES, f"wear_value_{tag}.csv"))
        df = df[df.capex_eur_per_kwh == capex]
        xs = range(len(df))
        for x, (_, r) in zip(xs, df.iterrows()):
            col = C[r.case]
            ax.bar(x, r.gross_saving_eur, width=0.56, color=col, alpha=0.22, lw=0)
            ax.bar(x, r.net_value_eur, width=0.56, color=col, lw=0)
            y = max(r.net_value_eur, 0)
            ax.text(x, y + 250, f"net {eur(r.net_value_eur)}", ha="center", va="bottom",
                    fontsize=9.5, color=INK, fontweight="bold")
            ax.text(x, r.gross_saving_eur + 250 if r.gross_saving_eur - y > 1500 else y + 1300,
                    f"gross {eur(r.gross_saving_eur)}", ha="center", va="bottom",
                    fontsize=8.5, color=MUTED)
            ax.text(x, min(r.net_value_eur, 0) - 300, f"{r.efc_per_year:.0f} cycles/yr\n"
                    f"{r.years_to_eol:.1f} yr life", ha="center", va="top", fontsize=8, color=MUTED)
        ax.axhline(0, color=MUTED, lw=1)
        ax.set_xticks(list(xs), [NAME[c] for c in df.case], fontsize=8.5, color=INK)
        ax.set_title(TITLE.get(tag, tag), fontsize=10.5, color=INK, loc="left")
        style(ax)
    lo = min(a.get_ylim()[0] for a in axes)
    for a in axes:
        a.set_ylim(lo - 2500, a.get_ylim()[1] + 1500)
    axes[0].set_ylabel("€ per year vs no battery", color=MUTED, fontsize=9)
    fig.suptitle(f"Battery value before and after wear  (400 kWh / 200 kW, cells valued at "
                 f"€{capex:g}/kWh)", fontsize=12, color=INK, x=0.01, ha="left")
    fig.text(0.01, -0.02, "Light bar = gross saving (energy only). Solid bar = net value after "
             "cycle wear, scored for every case by the same rainflow yardstick "
             "(6,000 cycles at full depth, depth exponent 1.5; illustrative, not a fitted cell).",
             fontsize=8, color=MUTED, ha="left")
    fig.tight_layout()
    out = os.path.join(RES, "wear_value_summary.png")
    fig.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    print("wrote", out)


def sweep(tags):
    fig, axes = plt.subplots(1, len(tags), figsize=(4.2 * len(tags), 3.8), sharey=False)
    axes = [axes] if len(tags) == 1 else axes
    for ax, tag in zip(axes, tags):
        df = pd.read_csv(os.path.join(RES, f"wear_value_{tag}.csv"))
        for case in ("B  wear-blind", "D  cycle-depth"):
            d = df[df.case == case].sort_values("capex_eur_per_kwh")
            ax.plot(d.capex_eur_per_kwh, d.net_value_eur, color=C[case], lw=2, marker="o", ms=5,
                    markeredgecolor="white", markeredgewidth=1.5)
            last = d.iloc[-1]
            ax.annotate(NAME[case].replace("\n", " "), (last.capex_eur_per_kwh, last.net_value_eur),
                        xytext=(6, 0), textcoords="offset points", va="center", fontsize=8.5,
                        color=INK)
        ax.axhline(0, color=MUTED, lw=1)
        ax.set_title(TITLE.get(tag, tag), fontsize=10.5, color=INK, loc="left")
        ax.set_xlabel("cell value, € per kWh", color=MUTED, fontsize=9)
        ax.set_xlim(df.capex_eur_per_kwh.min() - 20, df.capex_eur_per_kwh.max() + 120)
        style(ax)
    axes[0].set_ylabel("net value, € per year", color=MUTED, fontsize=9)
    fig.suptitle("The dearer the cells, the more it pays to dispatch with wear in mind",
                 fontsize=12, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    out = os.path.join(RES, "wear_value_sweep.png")
    fig.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    print("wrote", out)


def week(tag, capex, start_h):
    with open(os.path.join(RES, f"wear_value_{tag}_soc.json")) as f:
        j = json.load(f)
    tr, E = j["traces"], j["meta"]["E_cap"]
    sl = slice(start_h, start_h + 168)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 4.6), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 1.2]})
    hours = list(range(168))
    for case in ("B  wear-blind", f"D  cycle-depth @{capex:g}"):
        key = case.split(" @")[0]
        a1.plot(hours, [100 * v / E for v in tr[case][sl]], color=C[key], lw=2,
                label=NAME[key].replace("\n", " "))
    a1.set_ylabel("battery charge, %", color=MUTED, fontsize=9)
    a1.set_ylim(-3, 103)
    a1.legend(frameon=False, fontsize=9, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2)
    style(a1)
    a2.plot(hours, [1000 * p for p in tr["price_exp"][sl]], color=MUTED, lw=1.5)
    a2.set_ylabel("€/MWh", color=MUTED, fontsize=9)
    a2.set_xticks(range(0, 169, 24), [f"day {d + 1}" for d in range(8)])
    style(a2)
    fig.suptitle("One summer week (2024): with wear priced, the battery cycles less often "
                 "and less deep when the spread is thin", fontsize=11, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    out = os.path.join(RES, "wear_value_week.png")
    fig.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    print("wrote", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", default="DE_2019,DE_2024,DE_2024_retail")
    ap.add_argument("--capex", type=float, default=200.0)
    ap.add_argument("--week-tag", default="DE_2024")
    ap.add_argument("--week-start", type=int, default=24 * 180)
    args = ap.parse_args()
    tags = [t for t in args.tags.split(",") if os.path.exists(os.path.join(RES, f"wear_value_{t}.csv"))]
    summary(tags, args.capex)
    sweep(tags)
    week(args.week_tag, args.capex, args.week_start)


if __name__ == "__main__":
    main()
