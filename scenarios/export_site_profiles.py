"""
export_site_profiles.py
=======================
Write the demo site's hourly profiles (PV, electricity demand, heat demand,
heat-pump COP) to data/site/site_profiles.csv, keyed by month, day and UTC hour.

The year files (data/year_*.csv) are not in git, so the daily plan running on
GitHub Actions cannot read them. This small file is what it uses instead. It is
committed to the repo; rerun this script only when the site changes.

The 2024 year file has 8,759 rows: one hour went missing at the late-October
clock change (hour 7249), which moved every later hour of the profiles one
hour early. This export puts that hour back (a copy of the hour before), so the
profiles line up with the clock again for the whole year.

    python scenarios/export_site_profiles.py
    python scenarios/export_site_profiles.py --site data/year_DE_2024.csv --missing-hour 7249
"""
import _paths  # noqa

import argparse
import os

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_SITE = os.path.join(ROOT, "data", "year_DE_2024.csv")
OUT = os.path.join(ROOT, "data", "site", "site_profiles.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=DEFAULT_SITE)
    ap.add_argument("--missing-hour", type=int, default=7249,
                    help="row index where one hour is missing (-1 = none)")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    df = pd.read_csv(a.site, comment="#")[["pv_avail", "dem_el", "dem_heat", "cop"]]
    if a.missing_hour >= 0 and len(df) == 8759:
        df = pd.concat([df.iloc[:a.missing_hour], df.iloc[[a.missing_hour - 1]],
                        df.iloc[a.missing_hour:]], ignore_index=True)
    if len(df) != 8760:
        raise SystemExit(f"Expected 8,760 hours after the repair, got {len(df)}")

    hours = pd.date_range("2023-01-01", periods=8760, freq="1h")   # a non-leap calendar
    out = pd.DataFrame({"month": hours.month, "day": hours.day, "hour_utc": hours.hour})
    out = pd.concat([out, df.round(4)], axis=1)

    with open(a.site) as f:
        notes = [ln for ln in f if ln.startswith(("# heat", "# dem_el", "# pv"))]
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", newline="") as f:
        f.write("# HEXOS demo site, hourly profiles keyed by month/day/UTC hour (non-leap year)\n")
        f.write(f"# from   : {os.path.basename(a.site)}"
                + (f", missing hour {a.missing_hour} restored\n" if a.missing_hour >= 0 else "\n"))
        f.writelines(notes)
        out.to_csv(f, index=False)
    print(f"wrote {a.out} ({len(out)} h)")


if __name__ == "__main__":
    main()
