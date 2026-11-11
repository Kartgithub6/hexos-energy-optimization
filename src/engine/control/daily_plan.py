"""
engine.control.daily_plan
=========================
Tomorrow's plan for the demo site, built from live open data.

Once the day-ahead auction has cleared (results around 12:45 CET), tomorrow's
24 hourly prices are known. This module turns them into an operating plan:

  1. Prices: tomorrow (delivery day D, Europe/Berlin) from the data feed
     (data/feed/de_lu_day_ahead.csv: Energy-Charts, SMARD as fallback).
     The optimiser looks 48 h ahead so the battery does not empty itself at
     the end of the day; day D+1 is not auctioned yet, so its prices are a
     naive forecast: the same hour of day D. Every row says which it is.
  2. Weather: Munich temperature and radiation for the planned hours from the
     feed's Open-Meteo forecast (data/feed/munich_weather.csv) when present,
     turned into PV output and heat-pump COP. Hours without a forecast fall
     back to the site profile.
  3. Site: heat and electricity demand from the site profile
     (data/site/site_profiles.csv), matched by month, day and UTC hour.
  4. Three solves of the same 48 h window: no battery, wear-blind battery,
     wear-aware battery (cycle-depth model). Day D is committed; the rest of
     the window only shapes the decision.
  5. Every schedule is scored for wear with engine.postprocess.wear, so the
     wear-blind and wear-aware plans are judged by one yardstick.

The battery and heat-store levels at the end of yesterday's plan become
today's starting point, when yesterday's plan exists.

Limits, stated plainly:
  * Demand is a profile, not a measurement or a forecast of a real site.
  * Day D+1 prices are naive. They only influence where the battery ends day D.
  * The CHP starts each day off (its on/off state is not carried between days).
  * Wear parameters are illustrative, the same as scenarios/run_wear_value.py.
  * Hourly resolution: the 15-minute prices in the feed are averaged per hour.
"""
from __future__ import annotations

import copy
import os
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from engine.data.weather import heatpump_cop
from engine.postprocess.wear import evaluate_wear
from engine.solve.rolling import solve_rolling

TZ = "Europe/Berlin"
WINDOW_H = 48
PV_PEAK_KW = 500.0          # must match the site profile's PV scaling
GHI_REF_W_M2 = 1000.0       # radiation at which PV gives its peak (simple model)

DEFAULT_WEAR = {"model": "cycle_depth", "capex_eur_per_kwh": 200.0, "cycle_life_efc": 6000.0,
                "dod_exponent": 1.5, "segments": 5}

PLAN_COLUMNS = ["utc", "local", "price_eur_mwh", "price_source", "pv_source",
                "import_kw", "export_kw", "pv_used_kw", "chp_el_kw", "hp_el_kw", "rod_el_kw",
                "batt_charge_kw", "batt_discharge_kw", "batt_soc_kwh", "heat_soc_kwh",
                "blind_charge_kw", "blind_discharge_kw", "blind_soc_kwh"]


# ----------------------------------------------------------------- inputs
def delivery_hours(day: date) -> pd.DatetimeIndex:
    """UTC hours of the Berlin delivery day `day` and the day after (46-50 h
    on daylight-saving weekends, 48 otherwise)."""
    start = pd.Timestamp(day, tz=TZ)
    end = pd.Timestamp(day + timedelta(days=2), tz=TZ)
    return pd.date_range(start, end, freq="1h", inclusive="left").tz_convert("UTC")


def hours_of_day(day: date) -> int:
    start = pd.Timestamp(day, tz=TZ)
    return int((pd.Timestamp(day + timedelta(days=1), tz=TZ) - start) / pd.Timedelta("1h"))


def read_hourly(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.sort_index()


def site_rows(site: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Site profile values for each UTC hour, matched on month/day/hour.
    29 February uses 28 February."""
    key = site.set_index(["month", "day", "hour_utc"])
    rows = []
    for ts in idx:
        m, d = (2, 28) if (ts.month, ts.day) == (2, 29) else (ts.month, ts.day)
        rows.append(key.loc[(m, d, ts.hour)])
    return pd.DataFrame(rows, index=idx)[["pv_avail", "dem_el", "dem_heat", "cop"]]


def build_inputs(day: date, prices: pd.DataFrame, site: pd.DataFrame,
                 weather: pd.DataFrame | None = None, price_col: str = "price_eur_mwh"):
    """The 48 h input window for delivery day `day`.

    Returns (data dict for the solver, DataFrame describing every hour, n_day).
    Raises ValueError when day D's prices are not (all) in the feed yet."""
    idx = delivery_hours(day)
    n_day = hours_of_day(day)
    px = prices[price_col].reindex(idx)
    day_px = px.iloc[:n_day]
    if day_px.isna().any():
        missing = int(day_px.isna().sum())
        raise ValueError(f"{missing} of {n_day} hours of {day} have no day-ahead price yet. "
                         f"Run the feed after the auction (results ~12:45 CET).")
    src = ["day-ahead"] * n_day
    rest = px.iloc[n_day:].copy()
    for i in range(len(rest)):
        if pd.isna(rest.iloc[i]):
            rest.iloc[i] = day_px.iloc[min(i, n_day - 1)]   # same hour of day D
            src.append("naive: same hour of day D")
        else:
            src.append("day-ahead")
    px = pd.concat([day_px, rest])

    s = site_rows(site, idx)
    pv, cop, pv_src = s["pv_avail"].copy(), s["cop"].copy(), ["site profile"] * len(idx)
    if weather is not None and len(weather):
        w = weather.reindex(idx)
        for i, ts in enumerate(idx):
            g, t = w["shortwave_radiation"].iloc[i], w["temperature_2m"].iloc[i]
            if pd.notna(g):
                pv.iloc[i] = PV_PEAK_KW * min(1.0, max(0.0, g) / GHI_REF_W_M2)
                pv_src[i] = "Open-Meteo"
            if pd.notna(t):
                cop.iloc[i] = heatpump_cop([float(t)])[0]

    wholesale = px.to_numpy(float) / 1000.0
    fee = 0.015                                  # spot-linked tariff, as in the year files
    data = {"T": list(range(len(idx))),
            "price_el": list(wholesale + fee), "price_exp": list(wholesale - fee),
            "pv_avail": [float(v) for v in pv], "dem_el": [float(v) for v in s["dem_el"]],
            "dem_heat": [float(v) for v in s["dem_heat"]], "cop": [float(v) for v in cop]}
    info = pd.DataFrame({"utc": idx, "local": idx.tz_convert(TZ),
                         "price_eur_mwh": px.to_numpy(float), "price_source": src,
                         "pv_source": pv_src}, index=range(len(idx)))
    return data, info, n_day


# ----------------------------------------------------------------- solve
def _day_cost(data, r, cfg, n):
    return sum(data["price_el"][i] * r["import"][i] - data["price_exp"][i] * r["export"][i]
               + cfg["price_gas"] * r["chp_gas"][i] for i in range(n))


def run_plan(day: date, prices: pd.DataFrame, site: pd.DataFrame, cfg: dict,
             weather: pd.DataFrame | None = None, wear: dict | None = None,
             start_state: dict | None = None):
    """Solve the three cases and return (plan DataFrame for day D, summary dict)."""
    wear = dict(wear or DEFAULT_WEAR)
    data, info, n = build_inputs(day, prices, site, weather)
    base = copy.deepcopy(cfg)
    if start_state:
        base["battery"]["soc_init"] = float(start_state.get("batt_soc_kwh", 0.0))
        if "heat_storage" in base:
            base["heat_storage"]["soc_init"] = float(start_state.get("heat_soc_kwh", 0.0))
    E = base["battery"]["E_cap"]

    nb = copy.deepcopy(base); nb["battery"]["E_cap"] = 0.0; nb["battery"]["soc_init"] = 0.0
    aware = copy.deepcopy(base); aware["battery"]["wear"] = wear
    t0 = time.time()
    runs = {k: solve_rolling(data, c, window_h=len(data["T"]), commit_h=len(data["T"]), verbose=False)
            for k, c in (("none", nb), ("blind", base), ("aware", aware))}
    secs = time.time() - t0

    yard = {"capex_eur_per_kwh": wear["capex_eur_per_kwh"], "cycle_life_efc": wear["cycle_life_efc"],
            "dod_exponent": wear.get("dod_exponent", 1.5)}
    soc0 = base["battery"]["soc_init"]
    score = {k: evaluate_wear(runs[k]["soc"][:n], runs[k]["charge"][:n], runs[k]["discharge"][:n],
                              E, yard, soc0=soc0)
             for k in ("blind", "aware")}
    # cycle wear only: calendar ageing is the same for both plans and not a decision
    cost = {k: _day_cost(data, runs[k], cfg, n) for k in runs}

    a, b = runs["aware"], runs["blind"]
    plan = info.iloc[:n].copy()
    plan["import_kw"] = a["import"][:n]
    plan["export_kw"] = a["export"][:n]
    plan["pv_used_kw"] = a["pv_used"][:n]
    plan["chp_el_kw"] = a["chp_el"][:n]
    plan["hp_el_kw"] = a["hp_el"][:n]
    plan["rod_el_kw"] = a["rod_el"][:n]
    plan["batt_charge_kw"] = a["charge"][:n]
    plan["batt_discharge_kw"] = a["discharge"][:n]
    plan["batt_soc_kwh"] = a["soc"][:n]
    plan["heat_soc_kwh"] = a["h_soc"][:n]
    plan["blind_charge_kw"] = b["charge"][:n]
    plan["blind_discharge_kw"] = b["discharge"][:n]
    plan["blind_soc_kwh"] = b["soc"][:n]
    plan = plan[PLAN_COLUMNS]

    dp = plan["price_eur_mwh"]
    summary = {
        "date": day.isoformat(), "hours": n,
        "price_mean_eur_mwh": round(float(dp.mean()), 2),
        "price_min_eur_mwh": round(float(dp.min()), 2), "price_max_eur_mwh": round(float(dp.max()), 2),
        "negative_hours": int((dp < 0).sum()),
        "cost_no_battery_eur": round(cost["none"], 2),
        "saving_blind_eur": round(cost["none"] - cost["blind"], 2),
        "wear_blind_eur": round(score["blind"]["cycle_wear_eur"], 2),
        "net_blind_eur": round(cost["none"] - cost["blind"] - score["blind"]["cycle_wear_eur"], 2),
        "saving_aware_eur": round(cost["none"] - cost["aware"], 2),
        "wear_aware_eur": round(score["aware"]["cycle_wear_eur"], 2),
        "net_aware_eur": round(cost["none"] - cost["aware"] - score["aware"]["cycle_wear_eur"], 2),
        "efc_blind": round(score["blind"]["efc"], 3), "efc_aware": round(score["aware"]["efc"], 3),
        "soc_start_kwh": round(soc0, 1), "soc_end_kwh": round(float(plan["batt_soc_kwh"].iloc[-1]), 1),
        "naive_price_hours": int((info["price_source"] != "day-ahead").sum()),
        "pv_forecast_hours": int((plan["pv_source"] == "Open-Meteo").sum()),
        "capex_eur_per_kwh": wear["capex_eur_per_kwh"], "solve_s": round(secs, 2),
        "made_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    }
    return plan, summary


# ----------------------------------------------------------------- outputs
def previous_state(plans_dir: str, day: date) -> dict | None:
    """End-of-day storage levels from yesterday's plan, if it exists."""
    p = os.path.join(plans_dir, f"plan_{(day - timedelta(days=1)).isoformat()}.csv")
    if not os.path.exists(p):
        return None
    last = pd.read_csv(p).iloc[-1]
    return {"batt_soc_kwh": float(last["batt_soc_kwh"]), "heat_soc_kwh": float(last["heat_soc_kwh"])}


def write_outputs(plans_dir: str, plan: pd.DataFrame, summary: dict):
    os.makedirs(plans_dir, exist_ok=True)
    d = summary["date"]
    plan.to_csv(os.path.join(plans_dir, f"plan_{d}.csv"), index=False, float_format="%.3f")

    spath = os.path.join(plans_dir, "summary.csv")
    rows = pd.read_csv(spath) if os.path.exists(spath) else pd.DataFrame()
    if len(rows):
        rows = rows[rows["date"] != d]
    rows = pd.concat([rows, pd.DataFrame([summary])], ignore_index=True).sort_values("date")
    rows.to_csv(spath, index=False)

    with open(os.path.join(plans_dir, "latest.md"), "w", encoding="utf-8") as f:
        f.write(latest_markdown(plan, summary))


def latest_markdown(plan: pd.DataFrame, s: dict) -> str:
    def eur(v):
        return f"{'−' if round(v, 2) < 0 else ''}€{abs(v):,.2f}"

    def num(v, nd=0):
        return f"{round(float(v), nd) + 0.0:.{nd}f}"     # no "-0"
    lines = [
        f"# HEXOS plan for {s['date']}", "",
        f"Made {s['made_utc']} from the day-ahead auction for {s['date']} (DE-LU). "
        f"Demo site, 400 kWh / 200 kW battery, cells valued at €{s['capex_eur_per_kwh']:.0f}/kWh.", "",
        f"Prices: mean {num(s['price_mean_eur_mwh'], 1)} €/MWh, from {num(s['price_min_eur_mwh'], 1)} "
        f"to {num(s['price_max_eur_mwh'], 1)}, {s['negative_hours']} negative hours.", "",
        "| | saving vs no battery | wear | net | full cycles |",
        "|---|---:|---:|---:|---:|",
        f"| wear-blind | {eur(s['saving_blind_eur'])} | {eur(s['wear_blind_eur'])} | "
        f"{eur(s['net_blind_eur'])} | {s['efc_blind']:.2f} |",
        f"| wear-aware (plan) | {eur(s['saving_aware_eur'])} | {eur(s['wear_aware_eur'])} | "
        f"{eur(s['net_aware_eur'])} | {s['efc_aware']:.2f} |", "",
        "## Battery, hour by hour (local time)", "",
        "| hour | price €/MWh | charge kW | discharge kW | stored kWh |",
        "|---|---:|---:|---:|---:|",
    ]
    for _, r in plan.iterrows():
        lines.append(f"| {pd.Timestamp(r['local']).strftime('%H:%M')} | {num(r['price_eur_mwh'], 1)} | "
                     f"{num(r['batt_charge_kw'])} | {num(r['batt_discharge_kw'])} | {num(r['batt_soc_kwh'])} |")
    lines += ["", f"Starting level {s['soc_start_kwh']:.0f} kWh, ending {s['soc_end_kwh']:.0f} kWh. "
              f"{s['naive_price_hours']} look-ahead hours used naive prices; "
              f"{s['pv_forecast_hours']} of {s['hours']} hours used the Open-Meteo PV forecast.",
              "Savings count day D only; energy left in the battery at midnight carries into "
              "the next day's plan.",
              "", "Wear parameters are illustrative, not fitted to a cell. "
              "Demand is a site profile, not a measured load.", ""]
    return "\n".join(lines)
