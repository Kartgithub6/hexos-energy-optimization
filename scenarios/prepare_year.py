"""
prepare_year.py
===============
Turn the raw national datasets into one clean, validated, site-scaled yearly
input file for HEXOS.

It reads two downloaded source files (see data/raw/README_DOWNLOAD.md), slices
them to Germany + the chosen year, scales the national-aggregate profiles down
to a single company-sized site, aligns them on one hourly index, and writes
data/year_DE_<year>.csv.

WHY SCALING IS NEEDED (and why it is legitimate)
------------------------------------------------
When2Heat and OPSD report *national* quantities. A single company is not a
scaled-down Germany in absolute terms, but the *shape* of the profiles
transfers: when heat is needed, how prices move hour to hour, how COP follows
the weather. We keep the profiles' shape and rescale magnitude to a realistic
site size. Assumptions are explicit below and recorded in the output header.

Prices are NOT scaled (EUR/MWh is per-unit), only converted to EUR/kWh.

File-format facts discovered from the real files:
  - When2Heat: SEMICOLON-delimited, COMMA decimal separator (German format).
  - OPSD:      COMMA-delimited, point decimal.
  - Both use ISO timestamps with a UTC offset in 'cet_cest_timestamp'; we parse
    with utc=True then drop the tz so both share one naive hourly index.
  - When2Heat's absolute 'heat_demand_*' columns are NOT populated for recent
    years, but the normalized 'heat_profile_*' columns ARE. Since we rescale to
    a site target anyway, we build heat demand from the populated profiles:
    space + water heating (single-family-house shape).

Run:  python scenarios/prepare_year.py
"""

import sys
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(__file__)
RAW = os.path.join(HERE, "..", "data", "raw")
OUT_DIR = os.path.join(HERE, "..", "data")

# --- Choices fixed in earlier discussion --------------------------------
COUNTRY = "DE"
YEAR = 2019
HP_SOURCE = "ASHP_floor"   # air-source heat pump, floor heating

# --- Site-scaling assumptions (documented; change here if needed) -------
SITE_ANNUAL_HEAT_MWH = 2000.0     # ~2 GWh/yr heat  (mid-size company)
SITE_PEAK_EL_KW = 600.0           # electrical demand peak [kW]
SITE_PV_PEAK_KW = 500.0           # PV peak [kW] (synthetic profile for now)

# Electricity pricing. The OPSD day-ahead price is the WHOLESALE spot price.
# A company pays wholesale PLUS grid fees, levies and taxes to import, and
# receives roughly the wholesale price to export. We add a fixed import markup
# so import price > export price -- this reflects reality and prevents
# unphysical buy-low/sell-high grid arbitrage.
IMPORT_MARKUP_EUR_KWH = 0.12      # grid fees + levies + taxes (German industrial)

WHEN2HEAT_FILE = "when2heat.csv"
OPSD_FILE = "time_series_60min_singleindex.csv"
TIME_COL = "cet_cest_timestamp"

# Heat demand is built from these populated normalized-profile columns.
HEAT_PROFILE_COLS = [
    f"{COUNTRY}_heat_profile_space_SFH",
    f"{COUNTRY}_heat_profile_water_SFH",
]
COP_COL = f"{COUNTRY}_COP_{HP_SOURCE}"
PRICE_COL = "DE_LU_price_day_ahead"
LOAD_COL = "DE_load_actual_entsoe_transparency"


def read_year(path, usecols, year, sep=",", decimal="."):
    """Read a big CSV, parse timestamps robustly, return a naive-indexed year
    slice. `decimal` handles When2Heat's German comma decimals.
    """
    df = pd.read_csv(path, sep=sep, decimal=decimal, usecols=[TIME_COL] + usecols)
    idx = pd.to_datetime(df[TIME_COL], utc=True, errors="coerce").dt.tz_localize(None)
    df = df.drop(columns=[TIME_COL])
    df.index = idx
    df = df[~df.index.isna()]
    df = df[df.index.year == year]
    df = df[~df.index.duplicated(keep="first")]
    return df


def main():
    when2heat_path = os.path.join(RAW, WHEN2HEAT_FILE)
    opsd_path = os.path.join(RAW, OPSD_FILE)
    for p in (when2heat_path, opsd_path):
        if not os.path.exists(p):
            sys.exit(f"\nMissing raw file: {p}\nSee data/raw/README_DOWNLOAD.md\n")

    # When2Heat: semicolon-delimited, comma decimals; build heat from profiles.
    w2h = read_year(when2heat_path, HEAT_PROFILE_COLS + [COP_COL], YEAR,
                    sep=";", decimal=",")
    # OPSD: comma-delimited, point decimals.
    opsd = read_year(opsd_path, [PRICE_COL, LOAD_COL], YEAR, sep=",", decimal=".")

    print(f"When2Heat hours in {YEAR}: {len(w2h)}")
    print(f"OPSD hours in {YEAR}:      {len(opsd)}")

    df = w2h.join(opsd, how="inner")
    needed = HEAT_PROFILE_COLS + [COP_COL, PRICE_COL, LOAD_COL]
    df = df.dropna(subset=needed)
    n = len(df)
    print(f"Aligned hours:             {n}")
    if n == 0:
        sys.exit("No overlapping populated hours after join.")
    if n < 8000:
        print(f"WARNING: only {n} aligned hours (expected ~8760).")

    # --- Heat demand: sum space + water profiles, scale to site annual MWh ---
    heat_shape = df[HEAT_PROFILE_COLS].sum(axis=1).to_numpy(dtype=float)
    heat_kw = heat_shape * (SITE_ANNUAL_HEAT_MWH * 1000.0 / heat_shape.sum())

    # --- Electrical demand: shape from national load, scale to site peak ---
    load_shape = df[LOAD_COL].to_numpy(dtype=float)
    dem_el_kw = load_shape * (SITE_PEAK_EL_KW / load_shape.max())

    # --- PV: synthetic daytime profile (real renewables.ninja data later) ---
    hours = df.index.hour.to_numpy()
    pv_norm = np.clip(np.sin((hours - 6) / 12.0 * np.pi), 0, None)
    pv_kw = pv_norm * SITE_PV_PEAK_KW

    # --- Price: EUR/MWh -> EUR/kWh. Import = wholesale + markup; export =
    #     wholesale spot. Import > export by the markup, so no arbitrage. ---
    wholesale = df[PRICE_COL].to_numpy(dtype=float) / 1000.0
    price_el = wholesale + IMPORT_MARKUP_EUR_KWH
    price_exp = wholesale

    out = pd.DataFrame({
        "t": range(n),
        "price_el": price_el,
        "price_exp": price_exp,
        "pv_avail": pv_kw,
        "dem_el": dem_el_kw,
        "dem_heat": heat_kw,
        "cop": df[COP_COL].to_numpy(dtype=float),
    })

    out_path = os.path.join(OUT_DIR, f"year_{COUNTRY}_{YEAR}.csv")
    header = (
        f"# HEXOS yearly input -- {COUNTRY} {YEAR}\n"
        f"# Heat: When2Heat space+water SFH profiles, scaled to "
        f"{SITE_ANNUAL_HEAT_MWH} MWh/yr.\n"
        f"# COP: When2Heat {HP_SOURCE}. Price+load: OPSD; load scaled to "
        f"{SITE_PEAK_EL_KW} kW peak.\n"
        f"# Import=wholesale+{IMPORT_MARKUP_EUR_KWH} EUR/kWh markup; export=wholesale. PV synthetic "
        f"{SITE_PV_PEAK_KW} kW peak.\n"
    )
    with open(out_path, "w") as f:
        f.write(header)
    out.to_csv(out_path, mode="a", index=False)

    print(f"\nWrote {out_path}  ({n} hours)")
    print(out.describe().round(3).to_string())


if __name__ == "__main__":
    main()
