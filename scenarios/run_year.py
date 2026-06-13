"""
run_year.py
===========
Solve the full prepared year by rolling horizon and save the dispatch.

Run from the project root (after data/year_DE_2019.csv exists):
    python scenarios/run_year.py
"""

import sys
import os
import time
import csv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import data_io
import rolling_horizon as R

YEAR_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "year_DE_2019.csv")
OUT_CSV = os.path.join(os.path.dirname(__file__), "..", "results", "year_DE_2019_dispatch.csv")


def main():
    if not os.path.exists(YEAR_CSV):
        sys.exit(f"\nMissing {YEAR_CSV}. Run scenarios/prepare_year.py first.\n")

    data = data_io.load_timeseries(YEAR_CSV)
    n = len(data["T"])
    print(f"Loaded {n} hours from year_DE_2019.csv")

    cfg = {
        "price_gas": 0.07,
        "grid": {"import_max": 1200.0, "export_max": 1200.0},
        "battery": {"E_cap": 400.0, "p_ch_max": 200.0, "p_dis_max": 200.0,
                    "eta_ch": 0.96, "eta_dis": 0.96, "self_disch": 0.0005, "soc_init": 0.0},
        "chp": {"p_el_max": 200.0, "eta_el": 0.4, "htp_ratio": 1.5, "min_load": 0.4},
        "heatpump": {"q_max": 400.0},
        "rod": {"q_max": 300.0, "eta": 0.99},
        "heat_storage": {"E_cap": 1500.0, "p_ch_max": 400.0, "p_dis_max": 400.0,
                         "eta_ch": 0.98, "eta_dis": 0.98, "self_disch": 0.002, "soc_init": 0.0},
    }

    t0 = time.time()
    r = R.solve_rolling(data, cfg, window_h=48, commit_h=24, verbose=True)
    elapsed = time.time() - t0

    print(f"\nSolved {r['n_windows']} windows in {elapsed:.1f}s")
    print(f"Total annual operating cost: {r['cost']:.2f}")

    # Quick annual summary of where energy came from.
    def s(key):
        return sum(r[key])
    print(f"\nAnnual totals (kWh-equivalent):")
    print(f"  grid import   : {s('import'):>12.0f}")
    print(f"  grid export   : {s('export'):>12.0f}")
    print(f"  PV used       : {s('pv_used'):>12.0f}")
    print(f"  CHP heat      : {s('chp_heat'):>12.0f}")
    print(f"  heat pump heat: {s('hp_heat'):>12.0f}")
    print(f"  rod heat      : {s('rod_heat'):>12.0f}")
    print(f"  CHP hours on  : {int(round(s('chp_on'))):>12d}")

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    keys = ["t", "import", "export", "pv_used", "charge", "discharge", "soc",
            "chp_gas", "chp_el", "chp_heat", "chp_on", "hp_el", "hp_heat",
            "rod_el", "rod_heat", "h_charge", "h_discharge", "h_soc"]
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(keys)
        for i in range(len(r["t"])):
            w.writerow([r[k][i] for k in keys])
    print(f"\nWrote full dispatch to {OUT_CSV}")


if __name__ == "__main__":
    main()
