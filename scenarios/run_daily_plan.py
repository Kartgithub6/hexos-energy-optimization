"""
run_daily_plan.py
=================
Make tomorrow's plan for the demo site from the live data feed, with battery
wear priced in. Runs every day on GitHub Actions right after the data feed
(.github/workflows/data_feed.yml); you can also run it yourself.

Reads
    data/feed/de_lu_day_ahead.csv      prices (python -m engine.data.feed)
    data/feed/munich_weather.csv       Open-Meteo temperature + radiation
    data/site/site_profiles.csv        demand profiles (export_site_profiles.py)
Writes
    data/plans/plan_<date>.csv         hour-by-hour plan for that day
    data/plans/summary.csv             one row per day, appended
    data/plans/latest.md               the newest plan, readable on GitHub

Run:
    python -m engine.data.feed                   # fetch the newest prices first
    python scenarios/run_daily_plan.py           # tomorrow (Berlin time)
    python scenarios/run_daily_plan.py --date 2026-10-27
    python scenarios/run_daily_plan.py --date 2026-10-27 --capex 300 --no-weather
"""
import _paths  # noqa

import argparse
import os
import sys
from datetime import date, timedelta

import pandas as pd

from engine.control.daily_plan import (DEFAULT_WEAR, TZ, previous_state, read_hourly,
                                       run_plan, write_outputs)
import demo_plant

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FEED = os.path.join(ROOT, "data", "feed")
SITE = os.path.join(ROOT, "data", "site", "site_profiles.csv")
PLANS = os.path.join(ROOT, "data", "plans")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=date.fromisoformat, default=None,
                    help="delivery day (default: tomorrow, Berlin time)")
    ap.add_argument("--capex", type=float, default=DEFAULT_WEAR["capex_eur_per_kwh"])
    ap.add_argument("--no-weather", action="store_true", help="use the site profile for PV and COP")
    ap.add_argument("--fresh", action="store_true", help="ignore yesterday's end-of-day storage levels")
    ap.add_argument("--feed", default=FEED)
    ap.add_argument("--site", default=SITE)
    ap.add_argument("--out", default=PLANS)
    a = ap.parse_args()

    day = a.date or (pd.Timestamp.now(tz=TZ).date() + timedelta(days=1))
    price_path = os.path.join(a.feed, "de_lu_day_ahead.csv")
    if not os.path.exists(price_path):
        sys.exit(f"No prices at {price_path}. Run: python -m engine.data.feed")
    prices = read_hourly(price_path)
    wpath = os.path.join(a.feed, "munich_weather.csv")
    weather = None if a.no_weather or not os.path.exists(wpath) else read_hourly(wpath)
    site = pd.read_csv(a.site, comment="#")

    wear = dict(DEFAULT_WEAR, capex_eur_per_kwh=a.capex)
    state = None if a.fresh else previous_state(a.out, day)
    try:
        plan, s = run_plan(day, prices, site, demo_plant.demo_plant_cfg(), weather, wear, state)
    except ValueError as e:
        sys.exit(str(e))
    write_outputs(a.out, plan, s)

    print(f"Plan for {s['date']} ({s['hours']} h), prices {s['price_min_eur_mwh']:.1f} to "
          f"{s['price_max_eur_mwh']:.1f} EUR/MWh")
    print(f"  wear-blind : saving {s['saving_blind_eur']:8.2f}  wear {s['wear_blind_eur']:6.2f}  "
          f"net {s['net_blind_eur']:8.2f}  cycles {s['efc_blind']:.2f}")
    print(f"  wear-aware : saving {s['saving_aware_eur']:8.2f}  wear {s['wear_aware_eur']:6.2f}  "
          f"net {s['net_aware_eur']:8.2f}  cycles {s['efc_aware']:.2f}")
    print(f"  wrote {os.path.join(a.out, 'plan_' + s['date'] + '.csv')}, summary.csv, latest.md")


if __name__ == "__main__":
    main()
