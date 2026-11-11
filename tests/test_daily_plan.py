"""Daily plan from the live feed: input window, clock changes, outputs, state carry.
Offline: prices, weather and site profiles are synthetic."""
import os
from datetime import date

import numpy as np
import pandas as pd
import pytest

from engine.control.daily_plan import (build_inputs, delivery_hours, hours_of_day,
                                       previous_state, run_plan, write_outputs)

CFG = {
    "price_gas": 0.07,
    "grid": {"import_max": 1200.0, "export_max": 1200.0},
    "battery": {"E_cap": 400.0, "p_ch_max": 200.0, "p_dis_max": 200.0, "eta_ch": 0.96,
                "eta_dis": 0.96, "self_disch": 0.0005, "soc_init": 0.0},
    "heatpump": {"q_max": 400.0},
    "rod": {"q_max": 300.0, "eta": 0.99},
    "heat_storage": {"E_cap": 1500.0, "p_ch_max": 400.0, "p_dis_max": 400.0, "eta_ch": 0.98,
                     "eta_dis": 0.98, "self_disch": 0.002, "soc_init": 0.0},
}


def site_profile():
    hours = pd.date_range("2023-01-01", periods=8760, freq="1h")
    h = hours.hour.to_numpy()
    return pd.DataFrame({"month": hours.month, "day": hours.day, "hour_utc": h,
                         "pv_avail": np.clip(400 * np.sin((h - 6) / 12 * np.pi), 0, None),
                         "dem_el": 300 + 100 * ((h >= 6) & (h <= 18)),
                         "dem_heat": np.full(8760, 80.0), "cop": np.full(8760, 3.5)})


def prices(first, last):
    idx = pd.date_range(first, last, freq="1h", tz="UTC")
    h = idx.hour.to_numpy()
    p = 60 + 50 * np.sin((h - 12) / 24 * 2 * np.pi) + 30 * (h == 17)   # a daily spread
    return pd.DataFrame({"price_eur_mwh": p}, index=idx)


def test_window_lengths_follow_berlin_clock():
    assert hours_of_day(date(2026, 10, 27)) == 24
    assert hours_of_day(date(2026, 10, 25)) == 25          # clocks go back
    assert hours_of_day(date(2026, 3, 29)) == 23           # clocks go forward
    idx = delivery_hours(date(2026, 10, 27))
    assert len(idx) == 48 and str(idx[0]) == "2026-10-26 23:00:00+00:00"


def test_missing_day_prices_raise():
    px = prices("2026-10-20", "2026-10-26 22:00")
    with pytest.raises(ValueError, match="no day-ahead price yet"):
        build_inputs(date(2026, 10, 28), px, site_profile())


def test_next_day_is_a_labelled_naive_forecast():
    px = prices("2026-10-20", "2026-10-27 22:00")            # day D = 27 Oct only
    data, info, n = build_inputs(date(2026, 10, 27), px, site_profile())
    assert n == 24 and len(data["T"]) == 48
    assert (info["price_source"].iloc[:24] == "day-ahead").all()
    assert (info["price_source"].iloc[24:] != "day-ahead").all()
    assert np.allclose(info["price_eur_mwh"].iloc[24:].to_numpy(), info["price_eur_mwh"].iloc[:24].to_numpy())


def test_weather_overrides_pv_where_present():
    px = prices("2026-10-20", "2026-10-28 22:00")
    idx = delivery_hours(date(2026, 10, 27))[:24]
    wx = pd.DataFrame({"temperature_2m": 5.0, "shortwave_radiation": 500.0}, index=idx)
    data, info, _ = build_inputs(date(2026, 10, 27), px, site_profile(), wx)
    assert (info["pv_source"].iloc[:24] == "Open-Meteo").all()
    assert (info["pv_source"].iloc[24:] == "site profile").all()
    assert data["pv_avail"][0] == pytest.approx(250.0)


def test_plan_outputs_and_wear_awareness(tmp_path):
    px = prices("2026-10-20", "2026-10-28 22:00")
    plan, s = run_plan(date(2026, 10, 27), px, site_profile(), CFG)
    assert len(plan) == 24 and s["hours"] == 24
    assert s["efc_aware"] <= s["efc_blind"] + 1e-6           # pricing wear never adds cycling
    assert s["wear_aware_eur"] <= s["wear_blind_eur"] + 1e-6
    assert (plan["batt_soc_kwh"] <= 400.0 + 1e-6).all()
    write_outputs(str(tmp_path), plan, s)
    write_outputs(str(tmp_path), plan, s)                     # rerun replaces, not duplicates
    summ = pd.read_csv(tmp_path / "summary.csv")
    assert len(summ) == 1 and summ["date"].iloc[0] == "2026-10-27"
    assert (tmp_path / "latest.md").read_text(encoding="utf-8").startswith("# HEXOS plan for 2026-10-27")


def test_yesterday_end_state_is_carried(tmp_path):
    px = prices("2026-10-20", "2026-10-28 22:00")
    plan, s = run_plan(date(2026, 10, 26), px, site_profile(), CFG)
    write_outputs(str(tmp_path), plan, s)
    st = previous_state(str(tmp_path), date(2026, 10, 27))
    assert st["batt_soc_kwh"] == pytest.approx(plan["batt_soc_kwh"].iloc[-1], abs=1e-3)
    _, s2 = run_plan(date(2026, 10, 27), px, site_profile(), CFG, start_state=st)
    assert s2["soc_start_kwh"] == pytest.approx(round(st["batt_soc_kwh"], 1))
    assert previous_state(str(tmp_path), date(2026, 10, 30)) is None
