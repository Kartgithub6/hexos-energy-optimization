"""
run_flex_value.py
=================
Flexibility-value experiment: how much operating cost does the battery's
in-time energy shifting actually avoid over the full year?

Method (a controlled comparison):
  * Solve the SAME year, on the SAME data, with the SAME rolling-horizon
    settings, changing exactly ONE thing: the battery capacity.
      - ENABLED  : battery E_cap as in the reference year config
      - DISABLED : battery E_cap = 0 (the build layer locks the battery out)
  * Everything else -- CHP, heat pump, rod, heat storage, grid, prices,
    demand -- is held identical, so the cost difference is attributable purely
    to battery flexibility.

The reported figure is the flexibility value FOR THIS MODELLED SITE under 2019
German day-ahead prices -- not a universal constant. It depends on the plant's
sizing and the price series, which is the honest framing to use.

Note: the year config carries no EV sessions, so this experiment isolates the
BATTERY only. An EV-flexibility figure would require an EV-bearing year config
and is deliberately not claimed here.

Run (after prepare_year.py has written data/year_DE_2019.csv):
    python scenarios/run_flex_value.py
"""
import _paths  # noqa
import sys
import os
import time
import csv

from engine import load_timeseries, solve_rolling

YEAR = os.path.join(os.path.dirname(__file__), "..", "data", "year_DE_2019.csv")
OUT = os.path.join(os.path.dirname(__file__), "..", "results", "flex_value.csv")

# The reference battery block, identical to run_year.py.
BATTERY = {"E_cap": 400.0, "p_ch_max": 200.0, "p_dis_max": 200.0,
           "eta_ch": 0.96, "eta_dis": 0.96, "self_disch": 0.0005, "soc_init": 0.0}


def base_cfg():
    """Exactly the run_year.py config, so the ENABLED case reproduces the
    known annual cost. The DISABLED case will overwrite the battery only."""
    return {
        "price_gas": 0.07,
        "grid": {"import_max": 1200.0, "export_max": 1200.0},
        "battery": dict(BATTERY),
        "chp": {"p_el_max": 200.0, "eta_el": 0.4, "htp_ratio": 1.5, "min_load": 0.4},
        "heatpump": {"q_max": 400.0},
        "rod": {"q_max": 300.0, "eta": 0.99},
        "heat_storage": {"E_cap": 1500.0, "p_ch_max": 400.0, "p_dis_max": 400.0,
                         "eta_ch": 0.98, "eta_dis": 0.98, "self_disch": 0.002, "soc_init": 0.0},
    }


def _solve(data, battery_cap, label):
    cfg = base_cfg()
    cfg["battery"] = dict(BATTERY, E_cap=battery_cap)
    t0 = time.time()
    r = solve_rolling(data, cfg, window_h=48, commit_h=24, verbose=False)
    print(f"  {label:16s} cost = {r['cost']:>10.0f}   [{time.time()-t0:.0f}s]")
    return r["cost"]


def main():
    if not os.path.exists(YEAR):
        sys.exit("Run prepare_year.py first (need data/year_DE_2019.csv).")
    data = load_timeseries(YEAR)

    print("Flexibility-value experiment (battery enabled vs disabled)\n")
    cost_on = _solve(data, BATTERY["E_cap"], "battery ENABLED")
    cost_off = _solve(data, 0.0, "battery DISABLED")

    avoided = cost_off - cost_on
    pct = 100.0 * avoided / cost_off if cost_off else 0.0

    print("\n=== Flexibility value (battery) ===")
    print(f"  Annual cost avoided by battery flexibility : {avoided:.0f} EUR/yr")
    print(f"  As a share of the no-battery cost          : {pct:.2f}%")
    if avoided < -1e-6:
        print("  WARNING: negative saving -- check config; disabling flexibility "
              "should never reduce cost.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case", "battery_E_cap_kWh", "annual_cost_eur"])
        w.writerow(["battery_enabled", BATTERY["E_cap"], f"{cost_on:.2f}"])
        w.writerow(["battery_disabled", 0.0, f"{cost_off:.2f}"])
        w.writerow(["avoided_eur", "", f"{avoided:.2f}"])
        w.writerow(["avoided_pct", "", f"{pct:.4f}"])
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
