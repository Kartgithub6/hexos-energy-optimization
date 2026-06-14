"""compare_cop.py — three-way COP fidelity comparison on the real year."""
import _paths  # noqa
import sys, os, csv
from engine import load_timeseries, solve_rolling
from engine.postprocess.cop_variants import make_cop_variants

YEAR = os.path.join(os.path.dirname(__file__), "..", "data", "year_DE_2019.csv")
OUT = os.path.join(os.path.dirname(__file__), "..", "results", "cop_comparison.csv")


def site_cfg():
    return {
        "price_gas": 0.07, "grid": {"import_max": 1200.0, "export_max": 1200.0},
        "battery": {"E_cap": 400.0, "p_ch_max": 200.0, "p_dis_max": 200.0,
                    "eta_ch": 0.96, "eta_dis": 0.96, "self_disch": 0.0005, "soc_init": 0.0},
        "chp": {"p_el_max": 200.0, "eta_el": 0.4, "htp_ratio": 1.5, "min_load": 0.4},
        "heatpump": {"q_max": 400.0}, "rod": {"q_max": 300.0, "eta": 0.99},
        "heat_storage": {"E_cap": 1500.0, "p_ch_max": 400.0, "p_dis_max": 400.0,
                         "eta_ch": 0.98, "eta_dis": 0.98, "self_disch": 0.002, "soc_init": 0.0},
    }


def main():
    if not os.path.exists(YEAR):
        sys.exit("Run prepare_year.py first.")
    base = load_timeseries(YEAR)
    v = make_cop_variants(base, nameplate_cop=3.0)
    cfg = site_cfg()
    print(f"COP: temp_dependent | mean_constant {v['_mean_cop']:.3f} | nameplate {v['_nameplate_cop']:.3f}\n")
    rows = []
    for case in ("temp_dependent", "mean_constant", "nameplate"):
        r = solve_rolling(v[case], cfg, window_h=48, commit_h=24, verbose=False)
        rows.append({"case": case, "cost": r["cost"], "hp_heat": sum(r["hp_heat"]),
                     "chp_heat": sum(r["chp_heat"])})
        print(f"  {case:<16} cost={r['cost']:.0f}")
    ref = rows[0]["cost"]
    print("\ncase              cost        d_cost   d%")
    for x in rows:
        d = x["cost"] - ref
        print(f"{x['case']:<16}{x['cost']:>10.0f}{d:>12.0f}{100*d/ref:>7.2f}%")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader()
        for x in rows:
            w.writerow(x)
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
