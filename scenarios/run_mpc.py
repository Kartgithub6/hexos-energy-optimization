"""
run_mpc.py
==========
Demonstrates BOTH re-planning cadences of the generalised MPC framework on a
sample horizon:
  - Hourly MPC        (commit_h=1)  -- re-plans every hour, classic MPC
  - Rolling-horizon MPC (commit_h=24, horizon_h=48) -- re-plans once a day on a
    48h forecast, exactly mirroring the annual rolling-horizon solver's
    cadence, but driven by imperfect forecasts instead of perfect foresight

Both are benchmarked against the perfect-foresight optimum, and against a
noisy forecaster, to show how re-planning cadence affects the realistic cost
of forecast uncertainty.

This is an OFFLINE simulation of a real-time control strategy -- not a
deployed controller and not connected to hardware.

Run (after prepare_weather_year.py):  python scenarios/run_mpc.py
"""
import _paths  # noqa
import sys, os, time
from engine import load_timeseries, build_model, solve, extract_results
from engine.control.mpc import run_mpc, perfect_forecaster
from engine.control.forecasters import noisy_factory

YEAR = os.path.join(os.path.dirname(__file__), "..", "data", "year_weather.csv")
SAMPLE_HOURS = 24 * 14


def site_cfg():
    return {
        "price_gas": 0.07,
        "grid": {"import_max": 1500.0, "export_max": 1500.0},
        "battery": {"E_cap": 600.0, "p_ch_max": 250.0, "p_dis_max": 250.0,
                    "eta_ch": 0.96, "eta_dis": 0.96, "self_disch": 0.0005, "soc_init": 100.0},
        "chp": {"p_el_max": 250.0, "eta_el": 0.4, "htp_ratio": 1.2, "min_load": 0.3},
        "heatpump": {"q_max": 400.0}, "rod": {"q_max": 300.0, "eta": 0.99},
        "heat_storage": {"E_cap": 1500.0, "p_ch_max": 500.0, "p_dis_max": 500.0,
                         "eta_ch": 0.98, "eta_dis": 0.98, "self_disch": 0.002, "soc_init": 300.0},
    }


def main():
    if not os.path.exists(YEAR):
        sys.exit("Run scenarios/prepare_weather_year.py first.")
    full = load_timeseries(YEAR)
    data = {k: (v[:SAMPLE_HOURS] if isinstance(v, list) else v) for k, v in full.items()}
    data["T"] = list(range(SAMPLE_HOURS))
    cfg = site_cfg()

    print(f"Sample horizon: {SAMPLE_HOURS} h\n")

    m = build_model(data, cfg, cyclic=False); solve(m); ref = extract_results(m)
    print(f"Perfect-foresight optimum          : {ref['cost']:.2f}\n")

    print("--- Hourly MPC (commit_h=1, horizon_h=24): re-plans every hour ---")
    t0 = time.time()
    hourly_perfect = run_mpc(data, cfg, forecaster=perfect_forecaster, horizon_h=24, commit_h=1)
    print(f"  perfect forecast : {hourly_perfect['cost']:.2f}   [{time.time()-t0:.0f}s]")
    t0 = time.time()
    hourly_noisy = run_mpc(data, cfg, forecaster=noisy_factory(seed=1), horizon_h=24, commit_h=1)
    print(f"  noisy forecast   : {hourly_noisy['cost']:.2f}   [{time.time()-t0:.0f}s]")

    print("\n--- Rolling-horizon MPC (commit_h=24, horizon_h=48): re-plans once a day ---")
    t0 = time.time()
    rh_perfect = run_mpc(data, cfg, forecaster=perfect_forecaster, horizon_h=48, commit_h=24)
    print(f"  perfect forecast : {rh_perfect['cost']:.2f}   [{time.time()-t0:.0f}s]")
    t0 = time.time()
    rh_noisy = run_mpc(data, cfg, forecaster=noisy_factory(seed=1), horizon_h=48, commit_h=24)
    print(f"  noisy forecast   : {rh_noisy['cost']:.2f}   [{time.time()-t0:.0f}s]")

    print("\n=== Cost of forecast uncertainty (vs perfect foresight) ===")
    for label, cost in [("Hourly MPC", hourly_noisy["cost"]), ("Rolling-horizon MPC", rh_noisy["cost"])]:
        gap = cost - ref["cost"]
        print(f"  {label:<22}: +{gap:.2f}  ({100*gap/ref['cost']:+.2f}%)")


if __name__ == "__main__":
    main()
