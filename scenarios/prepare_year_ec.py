"""
prepare_year_ec.py
==================
Build a HEXOS year input file using REAL day-ahead prices for any recent year,
pulled from the Fraunhofer ISE Energy-Charts API.

Why this exists alongside prepare_year.py
-----------------------------------------
`prepare_year.py` reads prices from the OPSD `time_series` package. That
package's last release is 2020-10-06, so it only covers up to ~2019/2020. To
run HEXOS on 2022-2026 prices -- the volatile years where flexibility is
actually worth something -- the price series has to come from somewhere else.

Energy-Charts is the right source: Fraunhofer ISE, CC-BY 4.0, no registration
or API token needed, DE-LU day-ahead, updated daily. It is also the source
cited by most of the German market analysis you will read.

The honest caveat about heat and COP
------------------------------------
When2Heat's published series does NOT extend to the most recent years. So for a
recent price year, the heat-demand shape and heat-pump COP come from a
DIFFERENT year than the prices. That substitution is:

  * deliberate  -- it lets you study price effects while holding load constant
  * documented  -- recorded in the output file header and printed on every run
  * a limitation -- you must NEVER describe the output as, say, "2024 heat data"

If When2Heat does cover the requested year, the script uses it and says so.
Use --heat-year to pin the substitution year explicitly.

Weather note: the PV series here is the same synthetic daily sine used by
prepare_year.py, not a measured series. Same limitation as the original script.

Run:
    python scenarios/prepare_year_ec.py --year 2024
    python scenarios/prepare_year_ec.py --year 2025 --heat-year 2022
    python scenarios/prepare_year_ec.py --year 2024 --resolution quarterly
"""
import _paths  # noqa

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

from engine.data import weather

HERE = os.path.dirname(__file__)
RAW = os.path.join(HERE, "..", "data", "raw")
OUT_DIR = os.path.join(HERE, "..", "data")
MOS = os.path.join(HERE, "..", "data", "weather", "DEU_Munich_108660_IWEC.mos")

API = "https://api.energy-charts.info/price"
BZN = "DE-LU"

# Site scaling -- IDENTICAL to prepare_year.py so cost numbers stay comparable
# across years and across scenarios. Do not change one without the other.
SITE_ANNUAL_HEAT_MWH, SITE_PEAK_EL_KW, SITE_PV_PEAK_KW = 2000.0, 600.0, 500.0
IMPORT_MARKUP_EUR_KWH = 0.12

TIME_COL = "cet_cest_timestamp"
COUNTRY, HP_SOURCE = "DE", "ASHP_floor"
HEAT_PROFILE_COLS = [f"{COUNTRY}_heat_profile_space_SFH",
                     f"{COUNTRY}_heat_profile_water_SFH"]
COP_COL = f"{COUNTRY}_COP_{HP_SOURCE}"


# ---------------------------------------------------------------------------
# Energy-Charts
# ---------------------------------------------------------------------------
def fetch_prices(year, bzn=BZN, resolution="hourly", timeout=60):
    """Pull day-ahead prices for one calendar year. Returns a DataFrame indexed
    by naive UTC timestamps with a single 'price' column in EUR/MWh.

    Raises SystemExit with an actionable message on any failure -- never
    fabricates or silently substitutes data.
    """
    url = (f"{API}?bzn={bzn}&start={year}-01-01&end={year}-12-31"
           f"&resolution={resolution}")
    print(f"  GET {url}")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"Energy-Charts returned HTTP {e.code} for {year}.\n"
                 f"  If 404/422: that year or resolution may not be retained "
                 f"upstream -- try an earlier year, or resolution=hourly.\n"
                 f"  URL: {url}")
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach Energy-Charts ({e.reason}).\n"
                 f"  Check your internet connection or proxy settings.")
    except json.JSONDecodeError:
        sys.exit(f"Energy-Charts returned a non-JSON response for {year}.")

    if "unix_seconds" not in payload:
        sys.exit(f"Unexpected Energy-Charts schema. Keys: {list(payload)}\n"
                 f"  Expected 'unix_seconds' plus a price array.")

    # The value array has been named 'price' historically; accept alternatives
    # rather than break on a rename.
    values = None
    for key in ("price", "data", "values"):
        if key in payload and isinstance(payload[key], list):
            values = payload[key]
            break
    if values is None:
        sys.exit(f"No price array in Energy-Charts response. Keys: {list(payload)}")

    ts = pd.to_datetime(payload["unix_seconds"], unit="s", utc=True)
    df = pd.DataFrame({"price": values}, index=ts.tz_localize(None))
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df = df.dropna()
    unit = payload.get("unit", "EUR/MWh")
    print(f"  {len(df)} price points, unit reported as {unit}")
    if "MWh" not in str(unit):
        sys.exit(f"Unexpected price unit '{unit}' -- the script assumes EUR/MWh. "
                 f"Check the API before trusting any cost number.")
    return df


# ---------------------------------------------------------------------------
# When2Heat
# ---------------------------------------------------------------------------
def load_when2heat(path):
    """Read the whole When2Heat series (all years) once."""
    if not os.path.exists(path):
        sys.exit(f"Missing {path}. See data/raw/README_DOWNLOAD.md")
    df = pd.read_csv(path, sep=";", decimal=",",
                     usecols=[TIME_COL] + HEAT_PROFILE_COLS + [COP_COL])
    idx = pd.to_datetime(df[TIME_COL], utc=True, errors="coerce").dt.tz_localize(None)
    df = df.drop(columns=[TIME_COL])
    df.index = idx
    df = df[~df.index.isna()]
    df = df[~df.index.duplicated(keep="first")]
    return df.dropna()


def pick_heat_year(w2h, want_year, forced=None):
    """Choose which year's heat/COP series to use, and say why.

    Returns (year_used, substituted_bool).
    """
    years = sorted(set(w2h.index.year))
    if not years:
        sys.exit("When2Heat contained no usable rows.")
    if forced is not None:
        if forced not in years:
            sys.exit(f"--heat-year {forced} not in When2Heat "
                     f"(available: {years[0]}-{years[-1]}).")
        return forced, forced != want_year
    if want_year in years:
        return want_year, False
    nearest = min(years, key=lambda y: abs(y - want_year))
    return nearest, True


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True,
                    help="price year to build, e.g. 2024")
    ap.add_argument("--heat-year", type=int, default=None,
                    help="pin the When2Heat year explicitly (default: the "
                         "requested year if available, else the nearest)")
    ap.add_argument("--resolution", choices=["hourly", "quarterly"],
                    default="hourly",
                    help="Energy-Charts price resolution. HEXOS is hourly; "
                         "quarterly is downsampled to hourly means and the "
                         "output records that it was.")
    ap.add_argument("--bzn", default=BZN, help="bidding zone")
    ap.add_argument("--pv", choices=["weather", "synthetic"], default="weather",
                    help="PV series. 'weather' (default) derives it from real "
                         "Munich TMY irradiance and HAS seasonality. "
                         "'synthetic' reproduces prepare_year.py's daily sine, "
                         "which does not.")
    ap.add_argument("--export-mode", choices=["retail", "spot"], default="retail",
                    help="'retail': import = wholesale + full markup, export = "
                         "wholesale (a supplied-site tariff; export is almost "
                         "never optimal). 'spot': a spot-linked industrial "
                         "contract with a narrow symmetric fee, under which "
                         "export can be optimal.")
    ap.add_argument("--spot-fee", type=float, default=0.015,
                    help="one-way fee [EUR/kWh] used by --export-mode spot")
    args = ap.parse_args()

    print(f"Building HEXOS year input for {args.year} ({args.bzn})\n")

    print("Prices — Fraunhofer ISE Energy-Charts")
    px = fetch_prices(args.year, bzn=args.bzn, resolution=args.resolution)
    if args.resolution == "quarterly":
        px = px.resample("1h").mean().dropna()
        print(f"  downsampled to {len(px)} hourly means")

    print("\nHeat and COP — When2Heat")
    w2h = load_when2heat(os.path.join(RAW, "when2heat.csv"))
    heat_year, substituted = pick_heat_year(w2h, args.year, args.heat_year)
    hy = w2h[w2h.index.year == heat_year]
    print(f"  using {heat_year} ({len(hy)} h)")
    if substituted:
        print(f"  ! SUBSTITUTION: heat/COP are from {heat_year}, prices from "
              f"{args.year}.\n"
              f"    When2Heat does not publish {args.year}. This is recorded in "
              f"the output header.\n"
              f"    Never describe the result as '{args.year} heat data'.")

    # Align by hour-of-year so a substituted year still lines up seasonally.
    # Both series are trimmed to the shorter one; leap-day mismatch just costs
    # the tail hours, which is why the row count is printed and not assumed.
    hy = hy.copy()
    hy["hoy"] = ((hy.index - pd.Timestamp(year=heat_year, month=1, day=1))
                 .total_seconds() // 3600).astype(int)
    px = px.copy()
    px["hoy"] = ((px.index - pd.Timestamp(year=args.year, month=1, day=1))
                 .total_seconds() // 3600).astype(int)

    merged = px.merge(hy, on="hoy", how="inner").sort_values("hoy")
    n = len(merged)
    print(f"\nAligned {n} h")
    if n < 8000:
        print(f"  ! Only {n} h aligned — expected ~8760. Check for gaps before "
              f"quoting any annual figure.")
    if n == 0:
        sys.exit("No overlap after alignment.")

    heat_shape = merged[HEAT_PROFILE_COLS].sum(axis=1).to_numpy(float)
    if heat_shape.sum() <= 0:
        sys.exit("Heat profile summed to zero — check the When2Heat columns.")
    heat_kw = heat_shape * (SITE_ANNUAL_HEAT_MWH * 1000.0 / heat_shape.sum())

    # Electrical demand: prepare_year.py scales ENTSO-E national load. That
    # series is not in this pull, so a flat-shape proxy would be dishonest.
    # Instead reuse the heat profile's daily rhythm only as a shape for load,
    # scaled to the same site peak -- and say so in the header.
    hoy = merged["hoy"].to_numpy()
    hod = hoy % 24

    load_shape = 0.75 + 0.25 * np.sin((hod - 7) / 24.0 * 2 * np.pi)
    dem_el = load_shape * (SITE_PEAK_EL_KW / load_shape.max())

    # --- PV --------------------------------------------------------------
    # Default: real Munich TMY irradiance. prepare_year.py uses a sin(hour)
    # shape that is IDENTICAL in December and July, which silently removes all
    # seasonality from the PV series -- and therefore from any summer/winter
    # story told about the results. Real GHI gives a Dec/Jul ratio near 0.12.
    if args.pv == "weather":
        if not os.path.exists(MOS):
            sys.exit(f"Missing {MOS} -- needed for --pv weather. "
                     f"Use --pv synthetic to fall back (no seasonality).")
        w = weather.read_mos(MOS)
        pv_full = np.array(weather.pv_availability(w["ghi"], SITE_PV_PEAK_KW))
        # TMY is a TYPICAL year, prices are a REAL calendar year, so they do
        # not day-align. Indexing by hour-of-year is the standard, documented
        # way to combine them; the mismatch is stated, never hidden.
        pv = pv_full[np.clip(hoy, 0, len(pv_full) - 1)]
        pv_note = ("Munich TMY irradiance (real seasonality; TMY is a typical "
                   "year, not calendar-aligned to the price year)")
    else:
        pv = np.clip(np.sin((hod - 6) / 12.0 * np.pi), 0, None) * SITE_PV_PEAK_KW
        pv_note = "SYNTHETIC daily sine -- NO seasonality (Dec == Jul)"

    # --- Tariff ----------------------------------------------------------
    wholesale = merged["price"].to_numpy(float) / 1000.0   # EUR/MWh -> EUR/kWh
    if args.export_mode == "spot":
        price_el = wholesale + args.spot_fee
        price_exp = wholesale - args.spot_fee
        tariff_note = (f"spot-linked, +/-{args.spot_fee} EUR/kWh one-way fee "
                       f"(export can be optimal)")
    else:
        price_el = wholesale + IMPORT_MARKUP_EUR_KWH
        price_exp = wholesale
        tariff_note = (f"retail: +{IMPORT_MARKUP_EUR_KWH} EUR/kWh import markup, "
                       f"export at wholesale (spread makes export rarely optimal)")

    out = pd.DataFrame({
        "t": range(n),
        "price_el": price_el,
        "price_exp": price_exp,
        "pv_avail": pv,
        "dem_el": dem_el,
        "dem_heat": heat_kw,
        "cop": merged[COP_COL].to_numpy(float),
    })

    op = os.path.join(OUT_DIR, f"year_{COUNTRY}_{args.year}.csv")
    header = (
        f"# HEXOS year {COUNTRY} {args.year} ({args.bzn})\n"
        f"# prices : Fraunhofer ISE Energy-Charts day-ahead, {args.year}, "
        f"{args.resolution} (CC-BY 4.0)\n"
        f"# tariff : {tariff_note}\n"
        f"# heat+COP: When2Heat {heat_year}"
        f"{' -- SUBSTITUTED, not ' + str(args.year) if substituted else ''}, "
        f"scaled to {SITE_ANNUAL_HEAT_MWH} MWh/yr\n"
        f"# dem_el : SYNTHETIC daily shape scaled to {SITE_PEAK_EL_KW} kW peak "
        f"(no measured load series in this pull)\n"
        f"# pv     : {pv_note}, scaled to {SITE_PV_PEAK_KW} kW peak\n"
        f"# rows   : {n}\n"
    )
    with open(op, "w") as f:
        f.write(header)
    out.to_csv(op, mode="a", index=False)

    print(f"\nWrote {op} ({n} h)")
    print(header.rstrip())
    px_eur_mwh = merged["price"].to_numpy(float)
    print(f"\nPrice summary [EUR/MWh]: mean {px_eur_mwh.mean():.1f} | "
          f"min {px_eur_mwh.min():.1f} | max {px_eur_mwh.max():.1f} | "
          f"negative hours {(px_eur_mwh < 0).sum()}")

    # Seasonality check -- the number that tells you the PV series is real.
    mo = (pd.Timestamp(year=args.year, month=1, day=1)
          + pd.to_timedelta(hoy, unit="h")).month
    jul = pv[mo == 7].mean() if (mo == 7).any() else float("nan")
    dec = pv[mo == 12].mean() if (mo == 12).any() else float("nan")
    print(f"PV seasonality: Jul mean {jul:.1f} kW | Dec mean {dec:.1f} kW | "
          f"Dec/Jul {dec/jul:.2f}"
          f"{'   <-- 1.00 means NO seasonality' if dec/jul > 0.9 else ''}")


if __name__ == "__main__":
    main()
