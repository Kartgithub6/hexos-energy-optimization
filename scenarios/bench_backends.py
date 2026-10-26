"""
bench_backends.py
=================
Pyomo vs Linopy vs PyPSA on the same HEXOS problem.

For growing single-shot horizons of the demo plant on real prices, each
backend builds and solves the same MILP in a FRESH process (so peak memory is
not polluted by earlier runs) and reports:

  build_s   Python time to construct the model
  solve_s   time inside the solve call (for Linopy this includes handing the
            arrays to HiGHS; the HiGHS search itself is the same solver)
  peak_mb   peak resident memory of the process
  objective the optimum (must agree across backends to the MIP gap)

Then the full-year rolling solve (48 h window, 24 h commit, ~365 windows) is
timed for Pyomo and Linopy.

Run:
    python scenarios/bench_backends.py --data 2024
    python scenarios/bench_backends.py --data 2024 --horizons 48,168,720 --no-year
"""
import _paths  # noqa

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import warnings

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def peak_mb():
    """Peak memory of this process in MB (Linux/macOS: ru_maxrss; Windows: psutil)."""
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except ImportError:
        try:
            import psutil
            mi = psutil.Process().memory_info()
            return getattr(mi, "peak_wset", mi.rss) / 1e6
        except ImportError:
            return float("nan")


def one(backend, data_path, start, hours):
    warnings.filterwarnings("ignore")
    import logging
    logging.disable(logging.CRITICAL)
    from engine import load_timeseries
    import demo_plant
    d = load_timeseries(data_path)
    w = {k: (v[start:start + hours] if isinstance(v, list) else v) for k, v in d.items()}
    w["T"] = list(range(len(w["price_el"])))
    cfg = demo_plant.demo_plant_cfg()
    # import every backend BEFORE the clock starts: library import time is a
    # one-off per process and would otherwise be billed to the first build
    from engine import build_model, solve
    import pyomo.environ as pyo
    from hexos_linopy import build_linopy, solve_linopy
    from hexos_linopy.pypsa_site import build_network, solve_network
    t0 = time.perf_counter()
    if backend == "pyomo":
        m = build_model(w, cfg, cyclic=False)
        t1 = time.perf_counter()
        solve(m)
        obj = pyo.value(m.cost)
    elif backend == "linopy":
        m = build_linopy(w, cfg, cyclic=False)
        t1 = time.perf_counter()
        solve_linopy(m)
        obj = float(m.objective.value)
    elif backend == "pypsa":
        n = build_network(w, cfg)
        t1 = time.perf_counter()
        solve_network(n, cfg)
        obj = float(n.objective)
    t2 = time.perf_counter()
    return {"backend": backend, "hours": hours, "build_s": t1 - t0, "solve_s": t2 - t1,
            "total_s": t2 - t0, "peak_mb": peak_mb(), "objective": obj}


def year(backend, data_path):
    warnings.filterwarnings("ignore")
    import logging
    logging.disable(logging.CRITICAL)
    from engine import load_timeseries, solve_rolling
    import demo_plant
    d = load_timeseries(data_path)
    import hexos_linopy  # noqa: F401  (import cost outside the clock)
    t0 = time.perf_counter()
    r = solve_rolling(d, demo_plant.demo_plant_cfg(), verbose=False, backend=backend)
    return {"backend": backend, "hours": len(d["T"]), "mode": "rolling 48/24",
            "total_s": time.perf_counter() - t0, "cost": r["cost"], "windows": r["n_windows"],
            "peak_mb": peak_mb()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="2024")
    ap.add_argument("--start", type=int, default=0, help="first hour of the horizon")
    ap.add_argument("--horizons", default="48,168,720,2184")
    ap.add_argument("--backends", default="pyomo,linopy,pypsa")
    ap.add_argument("--no-year", action="store_true")
    ap.add_argument("--_child", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    path = os.path.join(ROOT, "data", f"year_DE_{args.data}.csv")
    if not os.path.exists(path):
        path = os.path.join(ROOT, "data", f"year_{args.data}.csv")

    if args._child:
        spec = json.loads(args._child)
        res = year(spec["backend"], path) if spec.get("year") else \
            one(spec["backend"], path, args.start, spec["hours"])
        print("RESULT " + json.dumps(res))
        return

    def child(spec):
        out = subprocess.run([sys.executable, __file__, "--data", args.data, "--start",
                              str(args.start), "--_child", json.dumps(spec)],
                             capture_output=True, text=True)
        line = [l for l in out.stdout.splitlines() if l.startswith("RESULT ")]
        if not line:
            print(out.stdout[-2000:], out.stderr[-2000:])
            raise SystemExit(f"child failed: {spec}")
        return json.loads(line[0][7:])

    rows = []
    print(f"{'backend':8s} {'hours':>6s} {'build s':>8s} {'solve s':>8s} {'total s':>8s} "
          f"{'peak MB':>8s} {'objective':>14s}")
    for h in [int(x) for x in args.horizons.split(",")]:
        for b in args.backends.split(","):
            r = child({"backend": b, "hours": h})
            rows.append(r)
            print(f"{b:8s} {h:>6d} {r['build_s']:>8.2f} {r['solve_s']:>8.2f} {r['total_s']:>8.2f} "
                  f"{r['peak_mb']:>8.0f} {r['objective']:>14.4f}")
    years = []
    if not args.no_year:
        print("\nFull year, rolling 48 h window / 24 h commit:")
        for b in ("pyomo", "linopy"):
            r = child({"backend": b, "year": True})
            years.append(r)
            print(f"  {b:8s} {r['total_s']:>7.1f} s   cost {r['cost']:>12,.2f}   "
                  f"{r['windows']} windows   peak {r['peak_mb']:.0f} MB")

    out = os.path.join(ROOT, "results", f"bench_backends_{args.data}.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["backend", "mode", "hours", "build_s", "solve_s", "total_s", "peak_mb",
                    "objective"])
        for r in rows:
            w.writerow([r["backend"], "single", r["hours"], f"{r['build_s']:.3f}",
                        f"{r['solve_s']:.3f}", f"{r['total_s']:.3f}", f"{r['peak_mb']:.1f}",
                        f"{r['objective']:.6f}"])
        for r in years:
            w.writerow([r["backend"], r["mode"], r["hours"], "", "", f"{r['total_s']:.3f}",
                        f"{r['peak_mb']:.1f}", f"{r['cost']:.6f}"])
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
