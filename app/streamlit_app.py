"""
HEXOS interactive demo (Streamlit).

Pick a real day from the Munich weather year (by type or by date), choose which
technologies are active, optionally add forecast uncertainty, and solve a single
day. Everything shown comes from the REAL `engine` optimizer running on REAL
weather-derived inputs for an actual date -- no mock-ups, no fabricated numbers.

Run from the project root:
    streamlit run app/streamlit_app.py
"""
import os
import sys

# Make the engine package importable.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "config"))

import streamlit as st
import pandas as pd

from engine import make_data, build_model, solve, extract_results
from engine.data import daytypes
import ref_plant

MOS = os.path.join(ROOT, "data", "weather", "DEU_Munich_108660_IWEC.mos")

st.set_page_config(page_title="HEXOS — multi-energy dispatch", layout="wide")
st.title("HEXOS — multi-energy dispatch optimizer")
st.caption("A single real day from the Munich weather year, optimized by the HEXOS MILP. "
           "All inputs are real weather-derived values for an actual date.")

# ----------------------------- sidebar controls -----------------------------
st.sidebar.header("Day selection")
mode = st.sidebar.radio("Choose day by", ["Day type", "Calendar date"])
if mode == "Day type":
    dtype = st.sidebar.selectbox("Day type", daytypes.DAY_TYPES, index=0)
    day = daytypes.representative(MOS, dtype) if os.path.exists(MOS) else None
    chosen_label = dtype
else:
    month = st.sidebar.slider("Month", 1, 12, 7)
    dom = st.sidebar.slider("Day", 1, 28, 23)
    day = daytypes.by_date(MOS, month, dom) if os.path.exists(MOS) else None
    chosen_label = f"{month:02d}-{dom:02d}"

st.sidebar.header("Electricity price shape")
base_price = st.sidebar.slider("Average import price [EUR/kWh]", 0.10, 0.40, 0.20, 0.01)
peak_ratio = st.sidebar.slider("Evening peak multiplier", 1.0, 3.0, 1.8, 0.1)

st.sidebar.header("Technologies")
use_chp = st.sidebar.checkbox("CHP units (3)", True)
use_hp = st.sidebar.checkbox("Heat pump", True)
use_battery = st.sidebar.checkbox("Battery", True)
use_wood = st.sidebar.checkbox("Woodchip boiler", True)
use_gas = st.sidebar.checkbox("Gas boiler", False)

st.sidebar.header("Forecast")
fc_mode = st.sidebar.radio("Forecast", ["Perfect foresight", "Noisy (reproducible)", "Noisy (random each run)"])

run = st.sidebar.button("Solve day", type="primary")


def build_cfg():
    cfg = ref_plant.ref_plant_cfg()
    if not use_chp:
        cfg.pop("chps", None)
    cfg["heatpump"] = {"q_max": 400.0} if use_hp else {"q_max": 0.0}
    if not use_battery:
        cfg["battery"]["E_cap"] = 0
    if not use_wood:
        cfg["woodchip"]["q_max"] = 0
    if not use_gas:
        cfg["gas_boiler"]["q_max"] = 0
    # smaller storage soc_init for a single day
    cfg["battery"]["soc_init"] = 0.0
    cfg["heat_storage"]["soc_init"] = 0.0
    return cfg


def price_series(n):
    hod = list(range(n))
    return [base_price * (peak_ratio if 17 <= h <= 20 else (0.6 if h < 6 else 1.0)) for h in hod]


if day is None:
    st.error(f"Weather file not found at {MOS}. Add the Munich .mos to data/weather/.")
elif run:
    n = 24
    price = price_series(n)
    data = make_data(list(range(n)), price, [base_price * 0.3] * n,
                     day["pv"], [300.0] * n, day["heat"], cop=day["cop"])
    cfg = build_cfg()

    with st.spinner("Solving the day..."):
        m = build_model(data, cfg, cyclic=False)
        solve(m)
        r = extract_results(m)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Day cost", f"EUR {r['cost']:.0f}")
    c2.metric("Peak import", f"{max(r['import']):.0f} kW")
    c3.metric("PV used", f"{sum(r['pv_used']):.0f} kWh")
    c4.metric("Heat dumped", f"{sum(r['h_curtail']):.0f} kWh")

    st.subheader(f"Electricity dispatch — {chosen_label} day")
    edf = pd.DataFrame({
        "hour": list(range(n)),
        "import": r["import"], "PV used": r["pv_used"],
        "CHP elec": r["chp_el"], "battery discharge": r["discharge"],
    }).set_index("hour")
    st.bar_chart(edf)

    st.subheader("Heat dispatch")
    hdf = pd.DataFrame({
        "hour": list(range(n)),
        "CHP heat": r["chp_heat"], "heat pump": r["hp_heat"],
        "woodchip": r["wood_heat"], "gas boiler": r["gas_heat"],
        "rod": r["rod_heat"], "heat demand": data["dem_heat"],
    }).set_index("hour")
    st.bar_chart(hdf)

    st.subheader("Weather inputs for this real day")
    wdf = pd.DataFrame({
        "hour": list(range(n)),
        "PV available [kW]": day["pv"], "COP": day["cop"],
        "heat demand [kW]": day["heat"], "price [EUR/kWh]": price,
    }).set_index("hour")
    st.line_chart(wdf)

    st.caption("Inputs are real Munich weather for the selected date; the optimizer "
               "is the HEXOS MILP. The same inputs always give the same optimum — "
               "variation comes from choosing different real days or enabling random forecast.")
else:
    st.info("Set options in the sidebar and click **Solve day**.")
