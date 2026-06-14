"""run_year.py — full-year rolling-horizon run with a generic config."""
import _paths  # noqa
import sys, os, time, csv
from engine import load_timeseries, solve_rolling

YEAR = os.path.join(os.path.dirname(__file__), "..", "data", "year_DE_2019.csv")
OUT = os.path.join(os.path.dirname(__file__), "..", "results", "year_dispatch.csv")


def main():
    if not os.path.exists(YEAR):
        sys.exit("Run prepare_year.py first.")
    data = load_timeseries(YEAR)
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
    r = solve_rolling(data, cfg, window_h=48, commit_h=24, verbose=True)
    print(f"\nSolved {r['n_windows']} windows in {time.time()-t0:.0f}s")
    print(f"Annual cost: {r['cost']:.0f}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    keys = ["t", "import", "export", "pv_used", "charge", "discharge", "soc",
            "chp_el", "chp_heat", "chp_on", "hp_heat", "rod_heat", "h_soc"]
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f); w.writerow(keys)
        for i in range(len(r["t"])):
            w.writerow([r[k][i] for k in keys])
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
