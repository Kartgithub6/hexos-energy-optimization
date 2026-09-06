"""
run_horizon_sweep.py
====================
Does the MPC prediction horizon need to exceed one day, and does the answer
hold across the year?

Design
------
Two horizons (24 h, 48 h) run over FOUR representative weeks -- one per season.
Every run uses perfect foresight, so forecast error is removed and horizon
length is the only variable within a season. A single-shot solve over each week
is the reference: it sees the whole week at once, so nothing with a finite
horizon can beat it.
"""
import _paths  # noqa

import argparse
import csv
import json
import os
import sys
import time

from engine import load_timeseries, build_model, solve
from engine.data.io import make_data
from engine.postprocess.extract import extract_results
from engine.control.mpc import run_mpc, perfect_forecaster

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "data")
SWEEP_ROOT = os.path.join(ROOT, "results", "horizon_sweep")


def resolve_dataset(arg):
    """Accept a year ('2024'), a bare name ('year_DE_2024'), or a full path.

    Returns (path, tag). The tag names the results folder, so runs on different
    years sit side by side instead of overwriting each other -- which is the
    whole point of being able to compare 2019 against 2024.
    """
    cands = [arg,
             os.path.join(DATA_DIR, arg),
             os.path.join(DATA_DIR, f"{arg}.csv"),
             os.path.join(DATA_DIR, f"year_DE_{arg}.csv"),
             os.path.join(DATA_DIR, f"year_{arg}.csv")]
    for c in cands:
        if os.path.isfile(c):
            tag = os.path.splitext(os.path.basename(c))[0].replace("year_", "")
            return c, tag
    have = sorted(f for f in os.listdir(DATA_DIR) if f.startswith("year_"))
    sys.exit(f"No dataset matching '{arg}'. Available in data/: {have}\n"
             f"  Build one with: python scenarios/prepare_year_ec.py --year 2024")

HORIZONS = [24, 48]

# Four weeks, 13 weeks apart, each mid-season. Chosen so every week sits well
# inside the 8757 h series and none overlaps another.
SEASONS = {
    "winter": 336,     # ~15 Jan
    "spring": 2520,    # ~16 Apr
    "summer": 4704,    # ~16 Jul
    "autumn": 6888,    # ~15 Oct
}


def base_cfg():
    """Same plant as run_year.py / run_bidding.py. Keep them in step or the
    cost numbers stop being comparable across experiments."""
    return {
        "price_gas": 0.07,
        "grid": {"import_max": 1200.0, "export_max": 1200.0},
        "battery": {"E_cap": 400.0, "p_ch_max": 200.0, "p_dis_max": 200.0,
                    "eta_ch": 0.96, "eta_dis": 0.96, "self_disch": 0.0005,
                    "soc_init": 0.0},
        "chp": {"p_el_max": 200.0, "eta_el": 0.4, "htp_ratio": 1.5,
                "min_load": 0.4},
        "heatpump": {"q_max": 400.0},
        "rod": {"q_max": 300.0, "eta": 0.99},
        "heat_storage": {"E_cap": 1500.0, "p_ch_max": 400.0, "p_dis_max": 400.0,
                         "eta_ch": 0.98, "eta_dis": 0.98, "self_disch": 0.002,
                         "soc_init": 0.0},
    }


def week_slice(data, start, hours):
    idx = list(range(start, start + hours))
    return make_data(list(range(hours)),
                     [data["price_el"][i] for i in idx],
                     [data["price_exp"][i] for i in idx],
                     [data["pv_avail"][i] for i in idx],
                     [data["dem_el"][i] for i in idx],
                     [data["dem_heat"][i] for i in idx],
                     [data["cop"][i] for i in idx])


COLS = ["t", "price_el", "pv_avail", "dem_el", "cop", "import", "export",
        "pv_used", "charge", "discharge", "batt_soc", "chp_el", "hp_heat",
        "rod_heat", "hstor_soc"]


def write_run(path, week, res):
    """One CSV per (season, case), wide enough that the plotting script needs
    nothing else -- including COP, so power-to-heat electrical load can be
    derived without reloading the year file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for i in range(len(res["t"])):
            w.writerow([
                i,
                f"{week['price_el'][i]:.6f}", f"{week['pv_avail'][i]:.3f}",
                f"{week['dem_el'][i]:.3f}", f"{week['cop'][i]:.4f}",
                f"{res['import'][i]:.3f}", f"{res['export'][i]:.3f}",
                f"{res['pv_used'][i]:.3f}", f"{res['charge'][i]:.3f}",
                f"{res['discharge'][i]:.3f}", f"{res['batt_soc'][i]:.3f}",
                f"{res['chp_el'][i]:.3f}", f"{res['hp_heat'][i]:.3f}",
                f"{res['rod_heat'][i]:.3f}", f"{res['hstor_soc'][i]:.3f}",
            ])


def single_shot(week, cfg, dt=1.0):
    """Reference case: one optimisation over the whole week, everything visible.

    Returned in run_mpc's output shape so the plotting script needs no special
    case. SOC is reported as the state at the START of each hour, matching
    run_mpc -- otherwise the trajectories would look offset by one step.
    """
    m = build_model(week, cfg, dt, cyclic=False)
    solve(m)
    r = extract_results(m)
    n = len(week["T"])

    soc_b = [cfg.get("battery", {}).get("soc_init", 0.0)]
    soc_h = [cfg.get("heat_storage", {}).get("soc_init", 0.0)]
    for i in range(n - 1):
        soc_b.append(r["soc"][i])
        soc_h.append(r["h_soc"][i])

    out = {k: list(r[k]) for k in
           ("import", "export", "pv_used", "charge", "discharge",
            "chp_el", "hp_heat", "rod_heat")}
    out["batt_soc"], out["hstor_soc"] = soc_b, soc_h
    out["t"] = list(range(n))
    out["cost"] = sum(
        week["price_el"][i] * r["import"][i]
        - week["price_exp"][i] * r["export"][i]
        + cfg["price_gas"] * r["chp_gas"][i]
        for i in range(n)) * dt
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="2019",
                    help="which year file to run: a year ('2024'), a name, or "
                         "a path. Results are written under a folder named "
                         "after it, so years do not overwrite each other.")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--commit", type=int, default=1,
                    help="MPC re-planning cadence [h]. 1 = re-plan hourly, "
                         "which isolates horizon length cleanly.")
    ap.add_argument("--horizons", type=str,
                    default=",".join(str(h) for h in HORIZONS))
    ap.add_argument("--seasons", type=str, default=",".join(SEASONS),
                    help="comma-separated subset of " + ",".join(SEASONS))
    args = ap.parse_args()

    year_path, tag = resolve_dataset(args.data)
    out_root = os.path.join(SWEEP_ROOT, tag)

    horizons = [int(x) for x in args.horizons.split(",")]
    seasons = [s.strip() for s in args.seasons.split(",")]
    unknown = [s for s in seasons if s not in SEASONS]
    if unknown:
        sys.exit(f"Unknown season(s) {unknown}. Choose from {list(SEASONS)}.")

    hours = args.days * 24
    data = load_timeseries(year_path)
    n_year = len(data["T"])
    cfg = base_cfg()

    too_late = [s for s in seasons if SEASONS[s] + hours > n_year]
    if too_late:
        sys.exit(f"Season(s) {too_late} run past the end of the data "
                 f"({n_year} h). Reduce --days or edit SEASONS.")

    print(f"MPC horizon sensitivity across seasons\n"
          f"  dataset {os.path.basename(year_path)}  ->  results/horizon_sweep/{tag}\n"
          f"  {args.days} d per week · commit {args.commit} h · perfect foresight\n"
          f"  horizons {horizons} · seasons {seasons}\n")

    summary = []
    for season in seasons:
        start = SEASONS[season]
        week = week_slice(data, start, hours)
        px = [p * 1000 for p in week["price_el"]]
        pv_mean = sum(week["pv_avail"]) / hours
        print(f"{season.upper():7s}  start h{start:5d}  "
              f"price {min(px):6.1f}-{max(px):6.1f} €/MWh  "
              f"PV mean {pv_mean:5.1f} kW")

        t0 = time.time()
        ss = single_shot(week, cfg)
        write_run(os.path.join(out_root, season, "single_shot", "dispatch.csv"),
                  week, ss)
        print(f"    single-shot        : {ss['cost']:9.2f} EUR  "
              f"[{time.time()-t0:.1f}s]")
        summary.append({"season": season, "start": start, "case": "single_shot",
                        "horizon_h": hours, "cost": round(ss["cost"], 4),
                        "gap_pct": 0.0, "batt_cycles": "",
                        "solve_s": round(time.time() - t0, 1)})

        for h in horizons:
            t0 = time.time()
            res = run_mpc(week, cfg, forecaster=perfect_forecaster,
                          horizon_h=h, commit_h=args.commit)
            write_run(os.path.join(out_root, season, f"h{h:02d}", "dispatch.csv"),
                      week, res)
            cyc = (sum(res["charge"]) / cfg["battery"]["E_cap"]
                   if cfg["battery"]["E_cap"] else 0.0)
            gap = (100.0 * (res["cost"] - ss["cost"]) / ss["cost"]
                   if ss["cost"] else 0.0)
            print(f"    horizon {h:3d} h       : {res['cost']:9.2f} EUR  "
                  f"({gap:+.3f}% vs single-shot, {cyc:.2f} cycles) "
                  f"[{time.time()-t0:.1f}s]")
            summary.append({"season": season, "start": start, "case": f"h{h:02d}",
                            "horizon_h": h, "cost": round(res["cost"], 4),
                            "gap_pct": round(gap, 5),
                            "batt_cycles": round(cyc, 3),
                            "solve_s": round(time.time() - t0, 1)})
        print()

    os.makedirs(out_root, exist_ok=True)
    sp = os.path.join(out_root, "summary.csv")
    with open(sp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)
    with open(os.path.join(out_root, "meta.json"), "w") as f:
        json.dump({"dataset": os.path.basename(year_path), "tag": tag, "seasons": {s: SEASONS[s] for s in seasons},
                   "hours": hours, "commit_h": args.commit,
                   "horizons": horizons, "forecast": "perfect"}, f, indent=2)

    # Cross-season read, which is the point of running four weeks.
    print("=== Range across seasons ===")
    for h in horizons:
        gaps = [r["gap_pct"] for r in summary if r["case"] == f"h{h:02d}"]
        if gaps:
            print(f"  {h:3d} h horizon : gap {min(gaps):+.3f}% to {max(gaps):+.3f}%  "
                  f"(mean {sum(gaps)/len(gaps):+.3f}%)")
    print(f"\n  Wrote {sp}")
    print(f"  Per-run dispatch CSVs under {out_root}\\<season>\\<case>")
    print(f"\n  Next: python scenarios/plot_horizon_sweep.py --tag {tag}")


if __name__ == "__main__":
    main()
