"""
prepare_year_feed.py
====================
Build a HEXOS year file from the self-updating data feed (data/feed/), with no
When2Heat download and no API call.

Prices come from the feed (Energy-Charts, falling back to SMARD hour by hour).
Everything that describes the SITE -- heat demand, COP, electrical demand, PV
availability -- is copied hour-of-year from an existing year file, so a new
price year changes exactly one thing: the prices. That makes year-to-year
comparisons clean, and it is the same substitution prepare_year_ec.py already
documents for heat and COP.

Tariff rules are identical to prepare_year_ec.py:
  spot   : import = wholesale + fee, export = wholesale - fee   (default fee 0.015)
  retail : import = wholesale + 0.12, export = wholesale

Run:
    python -m engine.data.feed --since 2025-01-01      # (or let the Action do it)
    python scenarios/prepare_year_feed.py --year 2025
    python scenarios/prepare_year_feed.py --year 2025 --mode retail
    python scenarios/prepare_year_feed.py --year 2025 --prices some_prices.csv --price-col smard
"""
import _paths  # noqa

import argparse
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "data")
FEED = os.path.join(DATA_DIR, "feed", "de_lu_day_ahead.csv")
IMPORT_MARKUP_EUR_KWH = 0.12     # must match prepare_year_ec.py


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--prices", default=FEED, help="hourly price CSV, UTC index, EUR/MWh")
    ap.add_argument("--price-col", default="price_eur_mwh")
    ap.add_argument("--site", default=os.path.join(DATA_DIR, "year_DE_2024.csv"),
                    help="year file whose site profiles (heat, COP, load, PV) are reused")
    ap.add_argument("--mode", choices=("spot", "retail"), default="spot")
    ap.add_argument("--spot-fee", type=float, default=0.015)
    ap.add_argument("--source-note", default=None,
                    help="text for the header's price line (default: describes the feed)")
    args = ap.parse_args()

    if not os.path.exists(args.prices):
        sys.exit(f"No price file at {args.prices}. Run: python -m engine.data.feed --since "
                 f"{args.year}-01-01")
    px = pd.read_csv(args.prices, index_col=0, parse_dates=True)[args.price_col].dropna()
    if px.index.tz is None:
        px.index = px.index.tz_localize("UTC")
    px = px[px.index.year == args.year]
    if px.empty:
        sys.exit(f"No {args.year} prices in {args.prices}")
    hoy = ((px.index - pd.Timestamp(year=args.year, month=1, day=1, tz="UTC"))
           .total_seconds() // 3600).astype(int)
    px = pd.Series(px.values, index=hoy).groupby(level=0).mean()

    site = pd.read_csv(args.site, comment="#")
    n = min(len(site), int(px.index.max()) + 1)
    full = px.reindex(range(n))
    missing = int(full.isna().sum())
    if missing:
        print(f"  ! {missing} hours without a price; filled from the same hour one week "
              f"earlier/later. Check the feed's gap report before quoting annual numbers.")
        full = full.fillna(full.shift(168)).fillna(full.shift(-168))
        if full.isna().any():
            sys.exit("Gaps too long to fill honestly. Backfill the feed first.")
    wholesale = full.to_numpy(float) / 1000.0

    out = site.iloc[:n][["t", "pv_avail", "dem_el", "dem_heat", "cop"]].copy()
    if args.mode == "spot":
        out["price_el"] = np.round(wholesale + args.spot_fee, 6)
        out["price_exp"] = np.round(wholesale - args.spot_fee, 6)
        tariff = (f"# tariff : spot-linked, +/-{args.spot_fee} EUR/kWh one-way fee "
                  f"(export can be optimal)\n")
        name = f"year_DE_{args.year}.csv"
    else:
        out["price_el"] = np.round(wholesale + IMPORT_MARKUP_EUR_KWH, 6)
        out["price_exp"] = np.round(wholesale, 6)
        tariff = f"# tariff : retail: +{IMPORT_MARKUP_EUR_KWH} EUR/kWh import markup, export at wholesale\n"
        name = f"year_DE_{args.year}_retail.csv"
    out = out[["t", "price_el", "price_exp", "pv_avail", "dem_el", "dem_heat", "cop"]]

    with open(args.site) as f:
        site_hdr = [ln for ln in f if ln.startswith("#")]
    keep = [ln for ln in site_hdr if ln.startswith(("# heat", "# dem_el", "# pv"))]
    src = args.source_note or ("HEXOS data feed (Energy-Charts day-ahead, SMARD as fallback; "
                               "CC BY 4.0), hourly means")
    path = os.path.join(DATA_DIR, name)
    with open(path, "w", newline="") as f:
        f.write(f"# HEXOS year DE {args.year} (DE-LU)\n")
        f.write(f"# prices : {src}, {args.year}\n")
        f.write(tariff)
        f.write(f"# site   : profiles copied hour-of-year from {os.path.basename(args.site)}:\n")
        f.writelines(keep)
        f.write(f"# rows   : {n}\n")
        out.to_csv(f, index=False)
    print(f"Wrote {path} ({n} h, mean wholesale {wholesale.mean()*1000:.1f} EUR/MWh, "
          f"{(wholesale < 0).sum()} negative hours)")


if __name__ == "__main__":
    main()
