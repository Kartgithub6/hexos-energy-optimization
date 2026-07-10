"""
HEXOS interactive demo (Streamlit + Plotly + PostgreSQL).

Pick a real day from the Munich weather year, choose which technologies are
active, optionally save/reload named scenarios, and solve a single day live.
Every solve is logged to PostgreSQL (if configured) for a run-history view.

Run from the project root:  streamlit run app/streamlit_app.py

Database: set DATABASE_URL (env var) or add it to .streamlit/secrets.toml.
Without it, the app still works fully -- saved scenarios and run history are
simply unavailable. NEVER commit secrets.toml with a real connection string.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "config"))
sys.path.insert(0, os.path.join(ROOT, "app"))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from engine import make_data, build_model, solve, extract_results
from engine.data import daytypes
import ref_plant
import db

MOS = os.path.join(ROOT, "data", "weather", "DEU_Munich_108660_IWEC.mos")

COLORS = {
    "import": "#e74c3c", "pv_used": "#f1c40f", "chp_el": "#2980b9", "discharge": "#8e44ad",
    "chp_heat": "#2980b9", "hp_heat": "#16a085", "wood_heat": "#27ae60",
    "gas_heat": "#7f8c8d", "rod_heat": "#e67e22",
    "pv": "#f1c40f", "cop": "#16a085", "heat_demand": "#e74c3c", "price": "#ecf0f1",
}

st.set_page_config(page_title="HEXOS — multi-energy dispatch", layout="wide")
st.title("HEXOS — multi-energy dispatch optimizer")
st.caption("A single real day from the Munich weather year, optimized by the HEXOS MILP.")


@st.cache_resource
def get_db():
    conn = db.get_connection()
    if conn is not None:
        db.init_schema(conn)
    return conn


conn = get_db()

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

st.sidebar.header("Saved scenarios")
if conn is None:
    st.sidebar.caption("No database configured — save/history disabled. "
                       "Set DATABASE_URL to enable.")
else:
    existing = db.list_scenario_names(conn)
    load_choice = st.sidebar.selectbox("Load a saved scenario", ["(none)"] + existing)
    if load_choice != "(none)" and st.sidebar.button("Apply loaded scenario"):
        s = db.load_scenario(conn, load_choice)
        st.session_state["_loaded"] = s
        st.rerun()

    new_name = st.sidebar.text_input("Save current settings as")
    if st.sidebar.button("Save scenario") and new_name:
        db.save_scenario(conn, new_name, "daytype" if mode == "Day type" else "date",
                         dtype if mode == "Day type" else f"{month:02d}-{dom:02d}",
                         base_price, peak_ratio, use_chp, use_hp, use_battery, use_wood, use_gas)
        st.sidebar.success(f"Saved '{new_name}'")

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
    cfg["battery"]["soc_init"] = 0.0
    cfg["heat_storage"]["soc_init"] = 0.0
    return cfg


def price_series(n):
    return [base_price * (peak_ratio if 17 <= h <= 20 else (0.6 if h < 6 else 1.0)) for h in range(n)]


def electricity_chart(hours, r):
    fig = go.Figure()
    fig.add_bar(x=hours, y=r["chp_el"], name="CHP electricity", marker_color=COLORS["chp_el"])
    fig.add_bar(x=hours, y=r["pv_used"], name="PV used", marker_color=COLORS["pv_used"])
    fig.add_bar(x=hours, y=r["discharge"], name="Battery discharge", marker_color=COLORS["discharge"])
    fig.add_bar(x=hours, y=r["import"], name="Grid import", marker_color=COLORS["import"])
    fig.update_layout(barmode="stack", template="plotly_dark", height=380,
                      title="Electricity supply by source", xaxis_title="Hour",
                      yaxis_title="kW", legend=dict(orientation="h", y=1.12), margin=dict(t=60, b=40))
    return fig


def heat_chart(hours, r, dem_heat):
    fig = go.Figure()
    fig.add_bar(x=hours, y=r["chp_heat"], name="CHP heat", marker_color=COLORS["chp_heat"])
    fig.add_bar(x=hours, y=r["hp_heat"], name="Heat pump", marker_color=COLORS["hp_heat"])
    fig.add_bar(x=hours, y=r["wood_heat"], name="Woodchip boiler", marker_color=COLORS["wood_heat"])
    fig.add_bar(x=hours, y=r["gas_heat"], name="Gas boiler", marker_color=COLORS["gas_heat"])
    fig.add_bar(x=hours, y=r["rod_heat"], name="Heating rod", marker_color=COLORS["rod_heat"])
    fig.add_trace(go.Scatter(x=hours, y=dem_heat, name="Heat demand", mode="lines+markers",
                             line=dict(color="white", width=2, dash="dot")))
    fig.update_layout(barmode="stack", template="plotly_dark", height=380,
                      title="Heat supply vs demand", xaxis_title="Hour",
                      yaxis_title="kW", legend=dict(orientation="h", y=1.12), margin=dict(t=60, b=40))
    return fig


tab_dispatch, tab_history = st.tabs(["Dispatch", "Run history"])

with tab_dispatch:
    if day is None:
        st.error(f"Weather file not found at {MOS}.")
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

        techs = ",".join(t for t, on in [("CHP", use_chp), ("HP", use_hp), ("Battery", use_battery),
                                         ("Wood", use_wood), ("Gas", use_gas)] if on)
        if conn is not None:
            db.log_run(conn, None, chosen_label, r["cost"], max(0.0, max(r["import"])),
                      sum(r["pv_used"]), sum(r["h_curtail"]), techs)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Day cost", f"EUR {r['cost']:.0f}")
        c2.metric("Peak import", f"{max(0.0, max(r['import'])):.0f} kW")
        c3.metric("PV used", f"{sum(r['pv_used']):.0f} kWh")
        c4.metric("Heat dumped", f"{sum(r['h_curtail']):.0f} kWh")

        hours = list(range(n))
        st.plotly_chart(electricity_chart(hours, r), use_container_width=True)
        st.plotly_chart(heat_chart(hours, r, data["dem_heat"]), use_container_width=True)
        st.caption(f"Day type: **{chosen_label}**. Logged to run history."
                   if conn is not None else f"Day type: **{chosen_label}**.")
    else:
        st.info("Set options in the sidebar and click **Solve day**.")

with tab_history:
    if conn is None:
        st.info("No database configured — set DATABASE_URL to enable run history.")
    else:
        hist = db.get_run_history(conn)
        if not hist:
            st.info("No runs logged yet — solve a day to populate this.")
        else:
            df = pd.DataFrame(hist)[["created_at", "day_label", "cost", "peak_import",
                                     "pv_used", "heat_dumped", "technologies"]]
            st.dataframe(df, use_container_width=True)

            agg = db.get_cost_by_daytype(conn)
            if agg:
                fig = go.Figure(go.Bar(x=[a["day_label"] for a in agg],
                                       y=[a["avg_cost"] for a in agg],
                                       marker_color=COLORS["chp_el"]))
                fig.update_layout(template="plotly_dark", height=320,
                                  title="Average cost by day type (from run history)",
                                  yaxis_title="EUR")
                st.plotly_chart(fig, use_container_width=True)
