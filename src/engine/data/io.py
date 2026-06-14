"""
hexos.data.io
=============
Load and validate input time series. Fail loudly and early.

Input CSV columns (hourly): t, price_el, price_exp, pv_avail, dem_el, dem_heat,
and optionally cop (heat-pump COP per step).
"""

from __future__ import annotations
import pandas as pd

REQUIRED_COLUMNS = ["t", "price_el", "price_exp", "pv_avail", "dem_el", "dem_heat"]
NONNEGATIVE_COLUMNS = ["pv_avail", "dem_el", "dem_heat"]


def load_timeseries(csv_path: str, const_cop: float | None = None) -> dict:
    df = pd.read_csv(csv_path, comment="#")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Input {csv_path} is missing columns: {missing}")

    t = df["t"].tolist()
    if t != list(range(len(df))):
        raise ValueError(f"Column 't' must be 0..{len(df)-1} with no gaps; got {t[:5]}...")

    for col in NONNEGATIVE_COLUMNS:
        bad = df.index[df[col] < 0].tolist()
        if bad:
            raise ValueError(f"Column '{col}' has negative values at rows {bad}")

    if df[REQUIRED_COLUMNS].isnull().any().any():
        raise ValueError(f"Input {csv_path} contains empty/NaN cells")

    if "cop" in df.columns:
        cop = df["cop"].tolist()
        if any(v <= 0 for v in cop):
            raise ValueError("COP values must be strictly positive")
    else:
        if const_cop is None:
            raise ValueError("No 'cop' column and no const_cop provided")
        cop = [const_cop] * len(df)

    return {
        "T": t,
        "price_el": df["price_el"].tolist(),
        "price_exp": df["price_exp"].tolist(),
        "pv_avail": df["pv_avail"].tolist(),
        "dem_el": df["dem_el"].tolist(),
        "dem_heat": df["dem_heat"].tolist(),
        "cop": cop,
    }


def make_data(T, price_el, price_exp, pv_avail, dem_el, dem_heat, cop):
    n = len(T)
    cop_series = cop if isinstance(cop, list) else [cop] * n
    return {
        "T": list(T),
        "price_el": list(price_el), "price_exp": list(price_exp),
        "pv_avail": list(pv_avail), "dem_el": list(dem_el),
        "dem_heat": list(dem_heat), "cop": cop_series,
    }
