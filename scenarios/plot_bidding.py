"""
plot_bidding.py
===============
Turn the run_bidding.py outputs into one presentable figure.

The default plot inside run_bidding.py is a diagnostic -- fine for checking the
curve slopes the right way, too plain to show anyone. This script makes the
version you would put in a deck or a post: two panels, annotated, with the
accepted quantity called out explicitly.

Panel A -- the bid curve for one hour, with the clearing price and the volume
           the auction actually accepted marked on it.
Panel B -- cost per strategy against the perfect-foresight bound, so the
           comparison is visible rather than asserted.

Run after run_bidding.py:
    python scenarios/plot_bidding.py
    python scenarios/plot_bidding.py --hour 17 --out results/for_post.png
"""
import _paths  # noqa

import argparse
import csv
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.join(os.path.dirname(__file__), "..")
CURVES = os.path.join(ROOT, "results", "bid_curves.csv")
SUMMARY = os.path.join(ROOT, "results", "bidding_summary.csv")
OUT = os.path.join(ROOT, "results", "bidding_figure.png")

INK = "#1a1a1a"
ACCENT = "#0b6e99"
WARN = "#c0392b"
MUTED = "#8a8a8a"


def load_curves(path):
    d = defaultdict(list)
    with open(path) as f:
        for r in csv.DictReader(f):
            d[int(r["hour"])].append((float(r["bid_price_eur_per_kwh"]) * 1000.0,
                                      float(r["bid_quantity_kw"])))
    return {h: sorted(v) for h, v in d.items()}


def load_summary(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def most_elastic_hour(curves):
    """The hour whose curve actually moves -- the one worth showing."""
    return max(curves, key=lambda h: max(q for _, q in curves[h])
               - min(q for _, q in curves[h]))


def clear(points, price):
    q = points[0][1]
    for p, qq in points:
        if price >= p:
            q = qq
        else:
            break
    return q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hour", type=int, default=None,
                    help="hour to plot (default: the most price-elastic one)")
    ap.add_argument("--clearing", type=float, default=None,
                    help="clearing price [EUR/MWh] to mark; default is the "
                         "midpoint of the bid range")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    if not os.path.exists(CURVES):
        raise SystemExit(f"Missing {CURVES} -- run run_bidding.py first.")

    curves = load_curves(CURVES)
    hour = args.hour if args.hour is not None else most_elastic_hour(curves)
    pts = curves[hour]
    px = [p for p, _ in pts]
    qy = [q for _, q in pts]
    clearing = args.clearing if args.clearing is not None else (min(px) + max(px)) / 2
    accepted = clear(pts, clearing)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2),
                                   gridspec_kw={"width_ratios": [1.55, 1]})

    # ---------------- Panel A: the bid curve --------------------------------
    ax1.step(px, qy, where="post", lw=2.6, color=ACCENT, zorder=3,
             label="submitted bid curve")
    ax1.fill_between(px, qy, step="post", alpha=0.10, color=ACCENT, zorder=1)
    ax1.axhline(0, lw=0.9, color=MUTED, zorder=2)
    ax1.axvline(clearing, ls="--", lw=1.8, color=WARN, zorder=4,
                label=f"clearing price {clearing:.0f} €/MWh")
    ax1.plot([clearing], [accepted], "o", ms=11, color=WARN,
             markeredgecolor="white", markeredgewidth=1.8, zorder=5)
    ax1.annotate(f"accepted\n{accepted:.0f} kW",
                 xy=(clearing, accepted),
                 xytext=(12, 26), textcoords="offset points",
                 fontsize=11, fontweight="bold", color=WARN,
                 ha="left", va="bottom")

    ax1.set_xlabel("Day-ahead price  [€/MWh]", fontsize=11)
    ax1.set_ylabel("Net position  [kW]      + import  /  − export", fontsize=11)
    ax1.set_title(f"What the site is willing to buy, at every price   ·   hour {hour}",
                  fontsize=12.5, fontweight="bold", color=INK, pad=12)
    ax1.legend(frameon=False, fontsize=10, loc="upper right")
    ax1.grid(alpha=0.22)
    for side in ("top", "right"):
        ax1.spines[side].set_visible(False)

    # ---------------- Panel B: cost against the bound -----------------------
    if os.path.exists(SUMMARY):
        rows = load_summary(SUMMARY)

        def tot(k):
            return sum(float(r[k]) for r in rows if r.get(k))

        bound = tot("cost_perfect")
        strategies = [("Bid curve\n(scenario)", "cost_scenario", ACCENT),
                      ("Fixed volume\n(baseline)", "cost_self", MUTED),
                      ("Bid curve\n(per-hour)", "cost_independent", "#b0b0b0")]
        labels, gaps, colors = [], [], []
        for lab, key, col in strategies:
            if key in rows[0]:
                labels.append(lab)
                gaps.append(100.0 * (tot(key) - bound) / bound if bound else 0.0)
                colors.append(col)

        bars = ax2.bar(labels, gaps, color=colors, width=0.6, zorder=3)
        for b, g in zip(bars, gaps):
            ax2.annotate(f"+{g:.2f}%", xy=(b.get_x() + b.get_width() / 2, g),
                         xytext=(0, 5), textcoords="offset points",
                         ha="center", fontsize=10.5, fontweight="bold")
        ax2.axhline(0, lw=1.4, color=INK, zorder=4)
        ax2.set_ylabel("Cost above perfect foresight  [%]", fontsize=11)
        ax2.set_title(f"Cost of not knowing the price   ·   {len(rows)} days",
                      fontsize=12.5, fontweight="bold", color=INK, pad=12)
        ax2.grid(axis="y", alpha=0.22, zorder=0)
        ax2.set_ylim(0, max(gaps) * 1.28 if gaps else 1)
        for side in ("top", "right"):
            ax2.spines[side].set_visible(False)
        ax2.tick_params(axis="x", labelsize=10)
    else:
        ax2.axis("off")
        ax2.text(0.5, 0.5, "run_bidding.py summary not found",
                 ha="center", va="center", color=MUTED)

    fig.suptitle("HEXOS — day-ahead demand-side bidding for a flexible multi-energy site",
                 fontsize=14, fontweight="bold", color=INK, y=0.99)
    fig.text(0.5, 0.015,
             "Cost-minimising MILP dispatch (Pyomo/HiGHS) · bid curves derived by "
             "parametric solve · German day-ahead prices · price taker, no imbalance exposure",
             ha="center", fontsize=8.8, color=MUTED)
    fig.tight_layout(rect=[0, 0.035, 1, 0.955])
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=200, facecolor="white")
    print(f"Wrote {args.out}  (hour {hour}, clearing {clearing:.0f} EUR/MWh, "
          f"accepted {accepted:.0f} kW)")


if __name__ == "__main__":
    main()
