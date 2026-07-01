"""
engine.data.daytypes
====================
Select REAL representative days from the Munich weather year, so the UI and demos
can show genuinely different days without fabricating data.

Two ways to pick a day:
  - by_date(month, day)         : the specific calendar day
  - representative(day_type)     : a real day matching a qualitative type, found
                                   by scoring every day in the file:
        "sunny"     -> highest total solar radiation
        "cloudy"    -> low radiation, mild temperature
        "rainy"     -> low radiation, moderate temp (proxy: low sun, not cold)
        "cold_snap" -> lowest mean temperature (winter, high heat demand, low COP)
        "hot"       -> highest mean temperature
A day is 24 consecutive hours starting at midnight.

Everything returned is REAL data from the file for an actual date; nothing is
synthesised. The label is just how we chose which real day to show.
"""

from __future__ import annotations
from engine.data import weather

DAY_TYPES = ["sunny", "cloudy", "rainy", "cold_snap", "hot"]


def _daily(values):
    """Split an 8760 series into 365 lists of 24."""
    return [values[d * 24:(d + 1) * 24] for d in range(365)]


def _day_index_of_date(month, day):
    """0-based day-of-year for a (month, day) in a non-leap TMY."""
    import datetime
    doy = datetime.date(2001, month, day).timetuple().tm_yday  # 2001 is non-leap
    return doy - 1


def load_day(mos_path, day_index, pv_peak_kw=500.0,
             heat_base_kw=80.0, heat_hdd_coeff=12.0):
    """Return a 24-hour data dict (PV, COP, heat) for the given day index,
    derived from the real weather for that day."""
    w = weather.read_mos(mos_path)
    temp = w["temp_C"][day_index * 24:(day_index + 1) * 24]
    ghi = w["ghi"][day_index * 24:(day_index + 1) * 24]
    pv = weather.pv_availability(ghi, pv_peak_kw)
    # Re-normalise PV by the whole-year max so magnitudes are comparable to the
    # full-year dataset (pv_availability normalises by its input's own max).
    ymax = max(w["ghi"]) or 1.0
    pv = [pv_peak_kw * (g / ymax) for g in ghi]
    cop = weather.heatpump_cop(temp)
    heat = weather.heat_demand_shape(temp, base_kw=heat_base_kw, hdd_coeff=heat_hdd_coeff)
    return {"temp_C": temp, "ghi": ghi, "pv": pv, "cop": cop, "heat": heat,
            "day_index": day_index}


def by_date(mos_path, month, day, **kw):
    return load_day(mos_path, _day_index_of_date(month, day), **kw)


def representative_index(mos_path, day_type):
    """Find the day-of-year index best matching a qualitative day type."""
    w = weather.read_mos(mos_path)
    temp_days = _daily(w["temp_C"])
    ghi_days = _daily(w["ghi"])
    mean_t = [sum(d) / 24 for d in temp_days]
    sum_g = [sum(d) for d in ghi_days]

    if day_type == "sunny":
        return max(range(365), key=lambda d: sum_g[d])
    if day_type == "hot":
        return max(range(365), key=lambda d: mean_t[d])
    if day_type == "cold_snap":
        return min(range(365), key=lambda d: mean_t[d])
    if day_type == "cloudy":
        # low sun but not freezing: minimise radiation among mild days
        mild = [d for d in range(365) if mean_t[d] > 5]
        pool = mild or list(range(365))
        return min(pool, key=lambda d: sum_g[d])
    if day_type == "rainy":
        # low-ish sun, moderate temp (a damp grey day)
        pool = [d for d in range(365) if 3 < mean_t[d] < 18]
        pool = pool or list(range(365))
        return sorted(pool, key=lambda d: sum_g[d])[len(pool) // 6]
    raise ValueError(f"unknown day_type {day_type!r}; use one of {DAY_TYPES}")


def representative(mos_path, day_type, **kw):
    return load_day(mos_path, representative_index(mos_path, day_type), **kw)
