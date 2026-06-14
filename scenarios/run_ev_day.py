"""run_ev_day.py — single-day demo of EV smart charging on the reference plant.

Shows the EV-scheduling capability (single-horizon solve, since EV windows are
absolute and not suited to the rolling solver).
"""
import _paths  # noqa
from engine import make_data, build_model, solve, extract_results
import ref_plant


def main():
    # A 24-hour day: cheap overnight power, pricey daytime, PV midday.
    T = list(range(24))
    price = [0.10 if (h < 6 or h >= 22) else (0.28 if 8 <= h <= 19 else 0.18) for h in T]
    pv = [max(0.0, 400.0 * __import__("math").sin((h - 6) / 12 * 3.14159)) if 6 <= h <= 18 else 0.0 for h in T]
    dem_el = [200 + 150 * (8 <= h <= 18) for h in T]
    dem_heat = [120 + 80 * (h < 8) for h in T]
    data = make_data(T, price, [0.05] * 24, pv, dem_el, dem_heat, cop=3.2)

    cfg = ref_plant.ref_plant_cfg()
    cfg["evs"] = ref_plant.ev_fleet_day()
    # Single-horizon solve (not rolling) so EV windows are handled directly.
    m = build_model(data, cfg); solve(m); r = extract_results(m)

    print(f"Day cost: {r['cost']:.2f}\n")
    print(f"{'h':>3} {'price':>6} {'pv':>5} {'EV_tot':>7} " +
          " ".join(f"{e:>5}" for e in r["ev_units"]))
    for h in T:
        evs = " ".join(f"{r['ev_units'][e][h]:>5.1f}" for e in r["ev_units"])
        print(f"{h:>3} {price[h]:>6.2f} {pv[h]:>5.0f} {r['ev_p'][h]:>7.1f} {evs}")
    print("\nEach EV's total delivered energy (kWh):")
    for e in r["ev_units"]:
        print(f"  {e}: {sum(r['ev_units'][e]):.1f}")


if __name__ == "__main__":
    main()
