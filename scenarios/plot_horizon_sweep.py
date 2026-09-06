"""
plot_horizon_sweep.py
=====================
Three figres from run_horizon_sweep.py.

Figure 1 — season x horizon grid. Rows are seasons, columns are horizons, each
           panel showing the full electricity balance as a stacked area with
           battery energy content on a secondary axis. Reading DOWN a column
           shows how the same horizon copes with different times of year;
           reading ACROSS a row shows what the extra day of foresight bought in
           that season.

Figure 2 — battery trajectory for one season: single-shot against the chosen
           horizon, with their difference. The difference line is the honest
           part -- where it leaves zero is where finite foresight actually cost
           something.

Figure 3 — the one-slide result. Cost gap per horizon shown as a RANGE across
           the four seasonal weeks rather than a single bar, because one week
           cannot tell you whether a horizon is sufficient in general.
"""
import _paths  # noqa

import argparse
import csv
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SWEEP_ROOT = os.path.join(ROOT, "results", "horizon_sweep")
# Set per-run in main() once the dataset tag is known, so figures from
# different years do not overwrite each other.
SWEEP = SWEEP_ROOT
FIG1 = FIG2 = FIG3 = None

# --- Palette -------------------------------------------------------------
# Indigo / slate / plum base with amber as the single warm accent. Chosen to
# read as its own thing rather than as a recolour of either the reference
# thesis figures (orange/brown dominant) or the earlier internal test run
# (blue/teal dominant). Amber is reserved for PV, where warmth is meaningful.
C_PV = "#E9C46A"        # PV used              - the one warm accent
C_IMP = "#7D8597"       # grid import          - slate
C_DIS = "#3D348B"       # battery discharge    - deep indigo
C_CHP = "#A288E3"       # CHP                  - lavender
C_CHG = "#5C6784"       # battery charge       - dark slate-blue
C_EXP = "#B8B3D9"       # grid export          - pale periwinkle
C_HP = "#6D597A"        # heat pump            - plum
C_ROD = "#C3B5CE"       # heating rod          - pale plum
C_SOC = "#1B1B3A"       # battery energy       - near-black indigo
C_PRICE = "#4A4E69"     # day-ahead price      - slate-purple
C_ACCENT = "#E9C46A"    # highlight in summary figure

ROD_ETA = 0.99          # matches base_cfg in run_horizon_sweep.py
SEASON_ORDER = ["winter", "spring", "summer", "autumn"]


def load_run(season, case):
    p = os.path.join(SWEEP, season, case, "dispatch.csv")
    if not os.path.exists(p):
        return None
    cols = {}
    with open(p) as f:
        rd = csv.DictReader(f)
        for k in rd.fieldnames:
            cols[k] = []
        for r in rd:
            for k in rd.fieldnames:
                cols[k].append(float(r[k]))
    return {k: np.array(v) for k, v in cols.items()}


def load_meta():
    p = os.path.join(SWEEP, "meta.json")
    if not os.path.exists(p):
        sys.exit(f"Missing {p} -- run run_horizon_sweep.py first.")
    return json.load(open(p))


def panel(ax, d, label):
    """One panel's ELECTRICITY BALANCE. Sources stack up, sinks stack down.

    All four electrical sources and all four electrical sinks are drawn, so the
    stack closes: PV + import + discharge + CHP equals demand + charge + export
    + heat-pump load + rod load. Power-to-heat appears as ELECTRICAL load,
    derived from heat output (hp_el = hp_heat / COP, rod_el = rod_heat / eta),
    which is why the import area sits above the demand line.
    """
    t = d["t"]
    cop = np.where(d["cop"] > 0.01, d["cop"], 1.0)
    hp_el = d["hp_heat"] / cop
    rod_el = d["rod_heat"] / ROD_ETA

    ax.stackplot(t, d["pv_used"], d["import"], d["discharge"], d["chp_el"],
                 colors=[C_PV, C_IMP, C_DIS, C_CHP], alpha=0.93,
                 labels=["PV used", "grid import", "battery discharge", "CHP"])
    ax.stackplot(t, -d["charge"], -d["export"], -hp_el, -rod_el,
                 colors=[C_CHG, C_EXP, C_HP, C_ROD], alpha=0.93,
                 labels=["battery charge", "grid export", "heat pump",
                         "heating rod"])
    ax.plot(t, d["dem_el"], lw=1.1, color="#222", ls=":",
            label="electricity demand")
    ax.axhline(0, lw=0.8, color="#444")
    ax.tick_params(labelsize=8)
    ax.margins(x=0)
    ax.text(0.01, 0.94, label, transform=ax.transAxes, fontsize=9.5,
            fontweight="bold", va="top",
            bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#ccc", alpha=0.9))

    ax2 = ax.twinx()
    ax2.plot(t, d["batt_soc"], lw=1.5, color=C_SOC)
    ax2.tick_params(labelsize=7.5, colors=C_SOC)
    ax2.margins(x=0)
    return ax2


def figure_grid(seasons, horizons):
    """Rows = seasons, columns = horizons."""
    nr, nc = len(seasons), len(horizons)
    fig, axes = plt.subplots(nr, nc, figsize=(6.6 * nc, 2.7 * nr),
                             squeeze=False)
    legend_ax = None
    for i, season in enumerate(seasons):
        for j, h in enumerate(horizons):
            ax = axes[i][j]
            d = load_run(season, f"h{h:02d}")
            if d is None:
                ax.axis("off")
                continue
            panel(ax, d, f"{season} · {h} h")
            if legend_ax is None:
                legend_ax = ax
            if j == 0:
                ax.set_ylabel("kW", fontsize=9)
            if i == nr - 1:
                ax.set_xlabel("hour of week", fontsize=9.5)

    if legend_ax is not None:
        hd, hl = legend_ax.get_legend_handles_labels()
        fig.legend(hd, hl, loc="upper center", ncol=5, frameon=False,
                   fontsize=9.5, bbox_to_anchor=(0.5, 0.975))
    fig.suptitle("HEXOS — MPC horizon across the seasons  ·  perfect foresight, "
                 "horizon is the only variable within a week",
                 fontsize=13.5, fontweight="bold", y=0.997)
    fig.text(0.5, 0.006,
             "Dark line on each right axis is battery energy content [kWh]. "
             "Read down a column for seasonal robustness, across a row for what "
             "the extra day of foresight bought.",
             ha="center", fontsize=8.6, color="#777")
    fig.tight_layout(rect=[0, 0.016, 1, 0.955])
    fig.savefig(FIG1, dpi=170, facecolor="white")
    print(f"Wrote {FIG1}")


def figure_soc(season, horizon):
    ss = load_run(season, "single_shot")
    cmp_d = load_run(season, f"h{horizon:02d}")
    if ss is None or cmp_d is None:
        print(f"  (skipping SOC figure: need {season}/single_shot and "
              f"{season}/h{horizon:02d})")
        return
    t, err = ss["t"], cmp_d["batt_soc"] - ss["batt_soc"]
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(t, ss["batt_soc"], lw=2.0, color=C_SOC,
            label="single-shot (whole week visible)")
    ax.plot(t, cmp_d["batt_soc"], lw=1.8, color=C_HP,
            label=f"{horizon} h MPC")
    ax.plot(t, err, lw=1.3, color=C_ACCENT, ls="--",
            label="difference (MPC − single-shot)")
    ax.fill_between(t, err, alpha=0.22, color=C_ACCENT)
    ax.axhline(0, lw=0.8, color="#999")
    ax.set_xlabel("hour of week", fontsize=11)
    ax.set_ylabel("battery energy content [kWh]", fontsize=11)
    ax.set_title(f"Battery trajectory · {season} · {horizon} h MPC vs single-shot",
                 fontsize=13, fontweight="bold", pad=12)
    ax.legend(frameon=False, fontsize=10)
    ax.grid(alpha=0.2)
    ax.margins(x=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    rms = float(np.sqrt(np.mean(err ** 2)))
    ax.text(0.985, 0.04, f"RMS divergence {rms:.1f} kWh  ·  "
                         f"max {np.abs(err).max():.1f} kWh",
            transform=ax.transAxes, ha="right", fontsize=9.5, color="#555")
    fig.tight_layout()
    fig.savefig(FIG2, dpi=170, facecolor="white")
    print(f"Wrote {FIG2}   (RMS divergence {rms:.1f} kWh)")


def figure_summary(seasons, horizons):
    """Cost gap per horizon as a RANGE across seasons, not a single bar.

    With four seasonal weeks the honest object is a spread, not a point. Each
    season is drawn as its own marker so an outlier season stays visible
    instead of being averaged away.
    """
    sp = os.path.join(SWEEP, "summary.csv")
    if not os.path.exists(sp):
        return
    rows = list(csv.DictReader(open(sp)))
    by_h = {h: [(r["season"], float(r["gap_pct"]),
                 float(r["batt_cycles"]) if r["batt_cycles"] else np.nan)
                for r in rows if r["case"] == f"h{h:02d}"] for h in horizons}
    by_h = {h: v for h, v in by_h.items() if v}
    if not by_h:
        return

    hs = sorted(by_h)
    x = np.arange(len(hs))
    fig, ax = plt.subplots(figsize=(9, 5.4))

    season_marks = {"winter": "o", "spring": "^", "summer": "s", "autumn": "D"}
    for i, h in enumerate(hs):
        gaps = [g for _, g, _ in by_h[h]]
        ax.vlines(x[i], min(gaps), max(gaps), color=C_IMP, lw=7, alpha=0.35,
                  zorder=2)
        ax.hlines(np.mean(gaps), x[i] - 0.14, x[i] + 0.14, color=C_DIS, lw=2.6,
                  zorder=4)
        for season, g, _ in by_h[h]:
            ax.plot(x[i], g, season_marks.get(season, "o"), ms=9,
                    color=C_ACCENT, markeredgecolor=C_SOC, markeredgewidth=1.1,
                    zorder=5, label=season if i == 0 else None)
        ax.annotate(f"{min(gaps):+.3f} … {max(gaps):+.3f}%",
                    xy=(x[i], max(gaps)), xytext=(0, 12),
                    textcoords="offset points", ha="center", fontsize=9.5,
                    fontweight="bold", color=C_SOC)

    ax.axhline(0, lw=1.4, color=C_SOC, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h} h" for h in hs], fontsize=11)
    ax.set_xlabel("MPC prediction horizon", fontsize=11)
    ax.set_ylabel("cost above single-shot optimum [%]", fontsize=11)
    ax.set_xlim(-0.5, len(hs) - 0.5)
    ax.grid(axis="y", alpha=0.2, zorder=0)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=9.5, title="season", title_fontsize=9.5,
              loc="best")

    cyc_ok = all(not np.isnan(c) for h in hs for _, _, c in by_h[h])
    if cyc_ok:
        ax2 = ax.twinx()
        means = [np.mean([c for _, _, c in by_h[h]]) for h in hs]
        ax2.plot(x, means, "--", lw=1.8, color=C_HP, zorder=1)
        ax2.set_ylabel("battery full-equivalent cycles (season mean)",
                       fontsize=10.5, color=C_HP)
        ax2.tick_params(axis="y", colors=C_HP, labelsize=9)
        ax2.spines["top"].set_visible(False)
        # Suppress matplotlib's offset notation (e.g. "+1.594e1"), which is
        # unreadable on a slide and hides the actual cycle count.
        ax2.ticklabel_format(axis="y", style="plain", useOffset=False)

    ax.set_title("Is one day of foresight enough, in every season?",
                 fontsize=13.5, fontweight="bold", pad=14)
    fig.text(0.5, 0.015,
             "Bar = range across the four seasonal weeks · horizontal rule = mean · "
             "markers = individual seasons. Lower is closer to the perfect-foresight bound.",
             ha="center", fontsize=8.7, color="#777")
    fig.tight_layout(rect=[0, 0.035, 1, 1])
    fig.savefig(FIG3, dpi=170, facecolor="white")
    print(f"Wrote {FIG3}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=None,
                    help="which dataset run to plot (e.g. DE_2024). Default: "
                         "the only one present, or the newest.")
    ap.add_argument("--season", default="winter", help="season for figure 2")
    ap.add_argument("--compare", type=int, default=None,
                    help="horizon for figure 2 (default: the shortest run)")
    args = ap.parse_args()

    global SWEEP, FIG1, FIG2, FIG3
    tags = ([args.tag] if args.tag else
            sorted((d for d in os.listdir(SWEEP_ROOT)
                    if os.path.isfile(os.path.join(SWEEP_ROOT, d, "meta.json"))),
                   key=lambda d: os.path.getmtime(
                       os.path.join(SWEEP_ROOT, d, "meta.json")))
            if os.path.isdir(SWEEP_ROOT) else [])
    if not tags:
        sys.exit("No sweep results found. Run run_horizon_sweep.py first.")
    tag = tags[-1]
    SWEEP = os.path.join(SWEEP_ROOT, tag)
    FIG1 = os.path.join(ROOT, "results", f"horizon_{tag}_dispatch.png")
    FIG2 = os.path.join(ROOT, "results", f"horizon_{tag}_soc.png")
    FIG3 = os.path.join(ROOT, "results", f"horizon_{tag}_summary.png")
    print(f"Plotting dataset: {tag}")

    meta = load_meta()
    seasons = [s for s in SEASON_ORDER if s in meta["seasons"]]
    seasons += [s for s in meta["seasons"] if s not in seasons]
    horizons = meta["horizons"]
    compare = args.compare if args.compare is not None else min(horizons)

    figure_grid(seasons, horizons)
    figure_summary(seasons, horizons)
    season = args.season if args.season in seasons else seasons[0]
    figure_soc(season, compare)


if __name__ == "__main__":
    main()
