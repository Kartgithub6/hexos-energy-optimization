"""
run_dispatch.py
===============
Run the coupled electricity + heat dispatch on the full sector-coupled system
and print the hour-by-hour result for both energy buses.

Usage (from the project root):   python scenarios/run_dispatch.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import data_io
import build_model as B


def main():
    csv = os.path.join(os.path.dirname(__file__), "..", "data", "toy_system.csv")
    data = data_io.load_timeseries(csv)  # COP comes from the file's column

    cfg = {
        "price_gas": 0.07,
        "battery": {"E_cap": 8.0, "p_ch_max": 4.0, "p_dis_max": 4.0,
                    "eta_ch": 0.96, "eta_dis": 0.96, "self_disch": 0.001, "soc_init": 0.0},
        "chp": {"p_el_max": 5.0, "eta_el": 0.4, "htp_ratio": 1.5, "min_load": 0.4},
        "heatpump": {"q_max": 8.0},
        "rod": {"q_max": 10.0, "eta": 0.99},
        "heat_storage": {"E_cap": 12.0, "p_ch_max": 6.0, "p_dis_max": 6.0,
                         "eta_ch": 0.98, "eta_dis": 0.98, "self_disch": 0.005, "soc_init": 0.0},
    }

    m = B.build_model(data, cfg)
    res = B.solve(m)
    r = B.extract_results(m)

    print(f"\nSolver status: {res.solver.termination_condition}")
    print(f"Total cost over horizon: {r['cost']:.4f}\n")

    print("ELECTRICITY bus")
    h = f"{'t':>3} {'price':>6} {'pv':>5} {'dem':>5} {'imp':>6} {'exp':>5} {'chpE':>5} {'hpE':>5} {'rodE':>5} {'bCh':>5} {'bDis':>5}"
    print(h); print("-" * len(h))
    for i, t in enumerate(r["t"]):
        print(f"{t:>3} {data['price_el'][i]:>6.2f} {data['pv_avail'][i]:>5.1f} "
              f"{data['dem_el'][i]:>5.1f} {r['import'][i]:>6.2f} {r['export'][i]:>5.2f} "
              f"{r['chp_el'][i]:>5.2f} {r['hp_el'][i]:>5.2f} {r['rod_el'][i]:>5.2f} "
              f"{r['charge'][i]:>5.2f} {r['discharge'][i]:>5.2f}")

    print("\nHEAT bus")
    h2 = f"{'t':>3} {'dem':>5} {'chpH':>5} {'hpH':>5} {'rodH':>5} {'hsCh':>5} {'hsDis':>5} {'hSoc':>6} {'on':>3}"
    print(h2); print("-" * len(h2))
    for i, t in enumerate(r["t"]):
        print(f"{t:>3} {data['dem_heat'][i]:>5.1f} {r['chp_heat'][i]:>5.2f} "
              f"{r['hp_heat'][i]:>5.2f} {r['rod_heat'][i]:>5.2f} {r['h_charge'][i]:>5.2f} "
              f"{r['h_discharge'][i]:>5.2f} {r['h_soc'][i]:>6.2f} {int(round(r['chp_on'][i])):>3}")


if __name__ == "__main__":
    main()
