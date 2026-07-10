"""
prepare_weather_year.py
=======================
Build a year dataset driven by REAL Munich weather (.mos) for PV, COP, and heat
demand, combined with 2019 wholesale electricity prices from OPSD (if present)
or a simple synthetic price otherwise.

Documented assumption: the Munich weather is a TYPICAL year (TMY), so it does
not calendar-align with 2019 prices. Combining typical weather with market
prices is standard practice; the mismatch is stated, not hidden.

Output: data/year_weather.csv
"""
import _paths  # noqa
import os
import numpy as np
import pandas as pd
from engine.data import weather

HERE = os.path.dirname(__file__)
MOS = os.path.join(HERE, "..", "data", "weather", "DEU_Munich_108660_IWEC.mos")
OPSD = os.path.join(HERE, "..", "data", "raw", "time_series_60min_singleindex.csv")
OUT = os.path.join(HERE, "..", "data", "year_weather.csv")

PV_PEAK_KW = 500.0
IMPORT_MARKUP = 0.12


def opsd_prices():
    """Try to read 2019 wholesale prices from OPSD; else return None."""
    if not os.path.exists(OPSD):
        return None
    df = pd.read_csv(OPSD, usecols=["cet_cest_timestamp", "DE_LU_price_day_ahead"])
    ts = pd.to_datetime(df["cet_cest_timestamp"], utc=True, errors="coerce").dt.tz_localize(None)
    df.index = ts
    s = df[df.index.year == 2019]["DE_LU_price_day_ahead"].dropna()
    if len(s) < 8000:          # sanity floor: clearly not a real year of data
        return None
    arr = s.to_numpy(float) / 1000.0        # EUR/MWh -> EUR/kWh
    if len(arr) >= 8760:
        return arr[:8760]
    # pad the last couple of DST/gap hours by repeating the final value
    import numpy as np
    return np.concatenate([arr, np.full(8760 - len(arr), arr[-1])])

def main():
    w = weather.read_mos(MOS)
    n = 8760
    pv = weather.pv_availability(w["ghi"], PV_PEAK_KW)
    cop = weather.heatpump_cop(w["temp_C"])
    heat = weather.heat_demand_shape(w["temp_C"], base_kw=80.0, hdd_coeff=12.0)

    wholesale = opsd_prices()
    if wholesale is None:
        print("OPSD prices not found; using a synthetic daily price shape.")
        hod = np.arange(n) % 24
        wholesale = 0.035 + 0.025 * np.sin(hod / 24 * 2 * np.pi - 1)
    else:
        print("Using real OPSD 2019 wholesale prices.")

    # Electrical demand: a simple weekday/working-hours shape.
    hod = np.arange(n) % 24
    dem_el = 250 + 200 * ((hod >= 7) & (hod <= 19))

    out = pd.DataFrame({
        "t": range(n),
        "price_el": np.asarray(wholesale) + IMPORT_MARKUP,
        "price_exp": np.asarray(wholesale),
        "pv_avail": pv,
        "dem_el": dem_el,
        "dem_heat": heat,
        "cop": cop,
    })
    with open(OUT, "w") as f:
        f.write("# HEXOS weather-driven year: PV/COP/heat from Munich TMY (.mos); "
                "prices = 2019 wholesale + markup. TMY weather does not calendar-align with 2019 prices.\n")
    out.to_csv(OUT, mode="a", index=False)
    print(f"Wrote {OUT} ({n}h)")
    print(out.describe().round(3).to_string())


if __name__ == "__main__":
    main()
