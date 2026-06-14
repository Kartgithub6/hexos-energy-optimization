"""run_ref_plant.py — full-year rolling-horizon run of the fictional reference plant."""
import _paths  # noqa
import sys, os, time
from engine import load_timeseries, solve_rolling
import ref_plant

YEAR = os.path.join(os.path.dirname(__file__), "..", "data", "year_DE_2019.csv")


def main():
    if not os.path.exists(YEAR):
        sys.exit("Run prepare_year.py first.")
    data = load_timeseries(YEAR)
    cfg = ref_plant.ref_plant_cfg()
    print(f"Reference plant: {len(cfg['chps'])} CHPs, woodchip+gas boilers, storages. {len(data['T'])}h")
    t0 = time.time()
    r = solve_rolling(data, cfg, window_h=48, commit_h=24, verbose=True)
    print(f"\nSolved {r['n_windows']} windows in {time.time()-t0:.0f}s")
    print(f"Annual operating cost: {r['cost']:.0f}\n")
    s = lambda k: sum(r[k])
    print("Heat (kWh):  CHP %.0f  woodchip %.0f  gas %.0f  rod %.0f  dumped %.0f" % (
        s('chp_heat'), s('wood_heat'), s('gas_heat'), s('rod_heat'), s('h_curtail')))
    print("Elec (kWh):  import %.0f  export %.0f  PV %.0f  CHP %.0f" % (
        s('import'), s('export'), s('pv_used'), s('chp_el')))
    print("CHP unit-hours on: %d" % int(round(s('chp_on'))))


if __name__ == "__main__":
    main()
