"""
plot_comment_summary.py
=======================
One portrait image (1200 x 1500 px, LinkedIn's 4:5 feed format) summarising
the ideas from the comment thread that were tested in HEXOS:

  top     how far ahead the controller must see, planning once a day:
          24 h, 24 h with a terminal value, and 48 h, per season
  left    what the battery is worth on a spot-linked vs a retail tariff,
          against a battery left in self-consumption mode
  right   what it costs to stop the CHP cycling daily

Every number is read from files the other scripts write, so the figure is
reproducible. Produce the inputs first:

    python scenarios/run_horizon_sweep.py --data 2024 --commit 24
    python scenarios/run_horizon_sweep.py --data 2024 --commit 24 --terminal-value auto
    python scenarios/run_baselines.py --data 2024
    python scenarios/run_baselines.py --data 2024_retail
    python scenarios/run_baselines.py --data 2024 --chp-start-cost 15 --max-starts 1

then:
    python scenarios/plot_comment_summary.py
"""
import _paths  # noqa

import argparse
import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RES = os.path.join(ROOT, "results")

# Same palette as the other HEXOS figures.
AMBER, SLATE, INDIGO, LAVENDER = "#E9C46A", "#7D8597", "#3D348B", "#A288E3"
NAVY, GREY = "#1B1B3A", "#6B6B7B"
SEASONS = ["winter", "spring", "summer", "autumn"]


def read_rows(path):
    if not os.path.isfile(path):
        sys.exit(f"Missing {path}\n  See the docstring for the runs that produce it.")
    with open(path) as f:
        return list(csv.DictReader(f))


def horizon_gaps(path, case):
    rows = read_rows(path)
    out = {r["season"]: float(r["gap_pct"]) for r in rows if r["case"] == case}
    return [max(0.0, out.get(s, 0.0)) for s in SEASONS]


def baselines(path):
    rows = {r["case"][0]: r for r in read_rows(path) if r["case"][:1] in "ABC"}
    return rows


def style(ax):
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="y", length=0, labelsize=9, colors=GREY)
    ax.tick_params(axis="x", length=0, labelsize=10)
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="DE_2024")
    ap.add_argument("--out", default=os.path.join(RES, "comments_tested_summary.png"))
    args = ap.parse_args()
    t = args.tag

    hz = os.path.join(RES, "horizon_sweep", f"{t}_c24", "summary.csv")
    hz_tv = os.path.join(RES, "horizon_sweep", f"{t}_c24_tvauto", "summary.csv")
    h24, h48 = horizon_gaps(hz, "h24"), horizon_gaps(hz, "h48")
    h24_tv = horizon_gaps(hz_tv, "h24")

    spot = baselines(os.path.join(RES, f"baselines_{t}.csv"))
    retail = baselines(os.path.join(RES, f"baselines_{t}_retail.csv"))
    chp = baselines(os.path.join(RES, f"baselines_{t}_sc15_ms1.csv"))

    fig = plt.figure(figsize=(8, 10), dpi=150, facecolor="white")
    gs = fig.add_gridspec(2, 2, height_ratios=[1.05, 1], hspace=0.5, wspace=0.38,
                          left=0.08, right=0.97, top=0.855, bottom=0.085)

    fig.text(0.04, 0.965, "Ideas from the comments, tested",
             fontsize=20, fontweight="bold", color=NAVY)
    fig.text(0.04, 0.935, "HEXOS  ·  one German industrial site  ·  "
             "day-ahead prices 2024", fontsize=11, color=GREY)

    # ---- top: horizon ----------------------------------------------------
    ax = fig.add_subplot(gs[0, :])
    w = 0.26
    xs = range(len(SEASONS))
    series = [(h24, "24 h", SLATE), (h24_tv, "24 h + terminal value", LAVENDER),
              (h48, "48 h", INDIGO)]
    for k, (vals, label, col) in enumerate(series):
        pos = [x + (k - 1) * w for x in xs]
        ax.bar(pos, vals, w * 0.92, color=col, label=label)
        for p, v in zip(pos, vals):
            txt = "≈0" if v < 0.005 else f"{v:.2f}%"
            ax.text(p, v + 0.03, txt, ha="center", va="bottom", fontsize=8.5,
                    color=NAVY, fontweight="bold" if label == "48 h" else None)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([s.capitalize() for s in SEASONS])
    ax.set_ylim(0, max(h24 + h24_tv) * 1.3)
    ax.set_ylabel("cost above the\nperfect-foresight optimum", fontsize=9, color=GREY)
    style(ax)
    ax.legend(frameon=False, fontsize=9, loc="upper left", ncol=3,
              bbox_to_anchor=(0.0, 1.0))
    ax.set_title("How far ahead does the controller need to see?",
                 loc="left", fontsize=13, fontweight="bold", color=NAVY, pad=26)
    ax.text(0, 1.035, "Planning once a day, one week per season. "
            "48 h closes the gap; a flat terminal value made 24 h worse.",
            transform=ax.transAxes, fontsize=9, color=GREY)

    # ---- bottom left: tariff x baseline ---------------------------------
    ax = fig.add_subplot(gs[1, 0])
    groups = [("Spot-linked", spot), ("Retail", retail)]
    for g, (name, d) in enumerate(groups):
        rule = float(d["B"]["saving_vs_A_eur"])
        opt = float(d["C"]["saving_vs_A_eur"])
        pct = float(d["C"]["saving_vs_A_pct"])
        ax.bar(g - 0.2, rule, 0.36, color=AMBER,
               label="self-consumption mode" if g == 0 else None)
        ax.bar(g + 0.2, opt, 0.36, color=INDIGO,
               label="optimised" if g == 0 else None)
        ax.text(g - 0.2, rule + 300, "€0", ha="center", va="bottom",
                fontsize=9, color=NAVY)
        ax.text(g + 0.2, opt + 300, f"€{opt / 1000:.1f}k\n{pct:.1f}% of bill",
                ha="center", va="bottom", fontsize=9, color=NAVY, fontweight="bold")
    ax.set_xticks([0, 1])
    ax.set_xticklabels([n for n, _ in groups])
    top = max(float(d["C"]["saving_vs_A_eur"]) for _, d in groups)
    ax.set_ylim(0, top * 1.45)
    ax.yaxis.set_major_formatter(lambda v, _: f"€{v / 1000:.0f}k" if v else "€0")
    ax.set_ylabel("battery saving per year", fontsize=9, color=GREY)
    style(ax)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    ax.set_title("What is the battery worth?", loc="left", fontsize=13,
                 fontweight="bold", color=NAVY, pad=34)
    ax.text(0, 1.035, "Solar never exceeds the load,\nso self-consumption mode never charges.",
            transform=ax.transAxes, fontsize=8.5, color=GREY, va="bottom")

    # ---- bottom right: CHP starts ---------------------------------------
    ax = fig.add_subplot(gs[1, 1])
    free_starts = int(spot["A"]["chp_starts"])
    capped_starts = int(chp["A"]["chp_starts"])
    extra = 100 * (float(chp["A"]["cost_eur"]) / float(spot["A"]["cost_eur"]) - 1)
    ax.bar([0, 1], [free_starts, capped_starts], 0.55, color=[SLATE, INDIGO])
    ax.text(0, free_starts * 1.02, f"{free_starts}", ha="center", va="bottom",
            fontsize=10, color=NAVY, fontweight="bold")
    ax.text(1, capped_starts * 1.02 + free_starts * 0.02,
            f"{capped_starts}\n+{extra:.2f}% cost", ha="center", va="bottom",
            fontsize=10, color=NAVY, fontweight="bold")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["starts free", "€15 per start,\nmax 1 per day"], fontsize=9.5)
    ax.set_ylim(0, free_starts * 1.3)
    ax.set_ylabel("CHP starts per year", fontsize=9, color=GREY)
    style(ax)
    ax.set_title("Does the CHP need to cycle?", loc="left", fontsize=13,
                 fontweight="bold", color=NAVY, pad=34)
    ax.text(0, 1.035, "No. Capping starts barely moves\nthe bill, and the battery value holds.",
            transform=ax.transAxes, fontsize=8.5, color=GREY, va="bottom")

    fig.text(0.04, 0.025,
             "Pyomo + HiGHS MILP, 48 h rolling horizon. Prices: Fraunhofer ISE Energy-Charts "
             "(CC BY 4.0). Weather: EnergyPlus Munich TMY.\nHorizon study: perfect "
             "foresight, four seasonal weeks. Tariff and CHP results: full year. "
             "Battery wear not yet included.",
             fontsize=7.3, color=GREY)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=150, facecolor="white")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
