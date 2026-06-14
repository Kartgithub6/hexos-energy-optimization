"""prepare_year.py — see data/raw/README_DOWNLOAD.md. Builds data/year_DE_2019.csv."""
import _paths  # noqa
import sys, os, numpy as np, pandas as pd

HERE = os.path.dirname(__file__)
RAW = os.path.join(HERE, "..", "data", "raw")
OUT_DIR = os.path.join(HERE, "..", "data")
COUNTRY, YEAR, HP_SOURCE = "DE", 2019, "ASHP_floor"
SITE_ANNUAL_HEAT_MWH, SITE_PEAK_EL_KW, SITE_PV_PEAK_KW = 2000.0, 600.0, 500.0
IMPORT_MARKUP_EUR_KWH = 0.12
TIME_COL = "cet_cest_timestamp"
HEAT_PROFILE_COLS = [f"{COUNTRY}_heat_profile_space_SFH", f"{COUNTRY}_heat_profile_water_SFH"]
COP_COL = f"{COUNTRY}_COP_{HP_SOURCE}"
PRICE_COL, LOAD_COL = "DE_LU_price_day_ahead", "DE_load_actual_entsoe_transparency"


def read_year(path, usecols, year, sep=",", decimal="."):
    df = pd.read_csv(path, sep=sep, decimal=decimal, usecols=[TIME_COL] + usecols)
    idx = pd.to_datetime(df[TIME_COL], utc=True, errors="coerce").dt.tz_localize(None)
    df = df.drop(columns=[TIME_COL]); df.index = idx
    df = df[~df.index.isna()]; df = df[df.index.year == year]
    return df[~df.index.duplicated(keep="first")]


def main():
    w = os.path.join(RAW, "when2heat.csv"); o = os.path.join(RAW, "time_series_60min_singleindex.csv")
    for p in (w, o):
        if not os.path.exists(p):
            sys.exit(f"Missing {p}. See data/raw/README_DOWNLOAD.md")
    w2h = read_year(w, HEAT_PROFILE_COLS + [COP_COL], YEAR, sep=";", decimal=",")
    opsd = read_year(o, [PRICE_COL, LOAD_COL], YEAR, sep=",", decimal=".")
    print(f"When2Heat {len(w2h)}h, OPSD {len(opsd)}h")
    df = w2h.join(opsd, how="inner").dropna(subset=HEAT_PROFILE_COLS + [COP_COL, PRICE_COL, LOAD_COL])
    n = len(df); print(f"Aligned {n}h")
    if n == 0:
        sys.exit("No overlap after join.")
    heat_shape = df[HEAT_PROFILE_COLS].sum(axis=1).to_numpy(float)
    heat_kw = heat_shape * (SITE_ANNUAL_HEAT_MWH * 1000.0 / heat_shape.sum())
    load = df[LOAD_COL].to_numpy(float); dem_el = load * (SITE_PEAK_EL_KW / load.max())
    hod = df.index.hour.to_numpy()
    pv = np.clip(np.sin((hod - 6) / 12.0 * np.pi), 0, None) * SITE_PV_PEAK_KW
    wholesale = df[PRICE_COL].to_numpy(float) / 1000.0
    out = pd.DataFrame({"t": range(n), "price_el": wholesale + IMPORT_MARKUP_EUR_KWH,
                        "price_exp": wholesale, "pv_avail": pv, "dem_el": dem_el,
                        "dem_heat": heat_kw, "cop": df[COP_COL].to_numpy(float)})
    op = os.path.join(OUT_DIR, f"year_{COUNTRY}_{YEAR}.csv")
    with open(op, "w") as f:
        f.write(f"# HEXOS year {COUNTRY} {YEAR}: heat=When2Heat profiles scaled to "
                f"{SITE_ANNUAL_HEAT_MWH}MWh/yr; price=OPSD wholesale+{IMPORT_MARKUP_EUR_KWH} import markup; PV synthetic\n")
    out.to_csv(op, mode="a", index=False)
    print(f"Wrote {op} ({n}h)"); print(out.describe().round(3).to_string())


if __name__ == "__main__":
    main()
