"""
run_mpc.py
==========
Closed-loop MPC simulation vs perfect foresight on a sample horizon, quantifying
the realistic cost of deciding on imperfect forecasts.

This is an OFFLINE simulation of a real-time control strategy -- not a deployed
controller and not connected to hardware.

Run (after prepare_weather_year.py):  python scenarios/run_mpc.py
"""
import _paths  # noqa
import sys, os, time
from engine import load_timeseries, build_model, solve, extract_results
from engine.control.mpc import run_mpc, perfect_forecaster
from engine.control.forecasters import noisy_factory

YEAR = os.path.join(os.path.dirname(__file__), "..", "data", "year_weather.csv")
HORIZON = 24
SAMPLE_HOURS = 24 * 14   # two weeks (full year MPC is slow; sample is illustrative)


def site_cfg():
    return {
        "price_gas": 0.07,
        "grid": {"import_max": 1500.0, "export_max": 1500.0},
        "battery": {"E_cap": 600.0, "p_ch_max": 250.0, "p_dis_max": 250.0,
                    "eta_ch": 0.96, "eta_dis": 0.96, "self_disch": 0.0005, "soc_init": 100.0},
        "chp": {"p_el_max": 250.0, "eta_el": 0.4, "htp_ratio": 1.2, "min_load": 0.3},
        "heatpump": {"q_max": 400.0},
        "rod": {"q_max": 300.0, "eta": 0.99},
        "heat_storage": {"E_cap": 1500.0, "p_ch_max": 500.0, "p_dis_max": 500.0,
                         "eta_ch": 0.98, "eta_dis": 0.98, "self_disch": 0.002, "soc_init": 300.0},
    }


def main():
    if not os.path.exists(YEAR):
        sys.exit("Run scenarios/prepare_weather_year.py first.")
    full = load_timeseries(YEAR)
    # Take a representative sample window.
    data = {k: (v[:SAMPLE_HOURS] if isinstance(v, list) else v) for k, v in full.items()}
    data["T"] = list(range(SAMPLE_HOURS))
    cfg = site_cfg()

    print(f"Sample horizon: {SAMPLE_HOURS} h, MPC look-ahead {HORIZON} h\n")

    # Perfect-foresight optimum over the sample (the best achievable).
    m = build_model(data, cfg, cyclic=False); solve(m); ref = extract_results(m)
    print(f"Perfect-foresight cost : {ref['cost']:.2f}")

    # Closed-loop MPC with a perfect forecaster (should match the optimum).
    t0 = time.time()
    mpc_perfect = run_mpc(data, cfg, forecaster=perfect_forecaster, horizon_h=HORIZON)
    print(f"MPC (perfect forecast) : {mpc_perfect['cost']:.2f}   [{time.time()-t0:.0f}s]")

    # Closed-loop MPC with a noisy forecaster (the realistic case).
    t0 = time.time()
    mpc_noisy = run_mpc(data, cfg, forecaster=noisy_factory(pv_sigma=0.2, dem_sigma=0.12, seed=1),
                        horizon_h=HORIZON)
    print(f"MPC (noisy forecast)   : {mpc_noisy['cost']:.2f}   [{time.time()-t0:.0f}s]")

    gap = mpc_noisy["cost"] - ref["cost"]
    pct = 100 * gap / ref["cost"] if ref["cost"] else 0
    print(f"\nCost of imperfect forecasts: {gap:.2f}  ({pct:+.2f}% vs perfect foresight)")
    print("This gap is the realistic penalty for not knowing the future -- the")
    print("quantity a real MPC controller lives with.")


if __name__ == "__main__":
    main()
