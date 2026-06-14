"""
engine.data.weather
===================
Parse an EnergyPlus `.mos` weather file (Modelica format) and derive
physically-consistent energy profiles from it:

  - PV availability       from global horizontal solar radiation
  - heat-pump COP         from ambient (dry-bulb) temperature
  - heat-demand shape     from ambient temperature (heating-degree style)

The `.mos` format: a few '#'-prefixed header lines, then 8760 tab-separated
rows of 30 columns. Column meanings (1-indexed in the file header):
  C1  time [s]              -> index 0
  C2  dry-bulb temp [C]     -> index 1
  C9  global horiz rad Wh/m2-> index 8

NOTE (documented assumption): EnergyPlus weather is a TYPICAL year (TMY), not a
specific calendar year. When combined with calendar-2019 market prices, the two
do not time-align day-for-day. This is a standard, acceptable modelling
combination (typical weather + market prices); it is stated explicitly so the
mismatch is transparent rather than hidden.
"""

from __future__ import annotations

TEMP_COL = 1
GHI_COL = 8     # global horizontal radiation [Wh/m2]


def read_mos(path: str) -> dict:
    """Return {'temp_C': [...], 'ghi': [...]} with 8760 hourly values."""
    temp, ghi = [], []
    with open(path) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("double"):
                continue
            parts = s.split("\t")
            if len(parts) < 30:
                continue
            temp.append(float(parts[TEMP_COL]))
            ghi.append(float(parts[GHI_COL]))
    if len(temp) != 8760:
        raise ValueError(f"Expected 8760 weather rows, got {len(temp)}")
    return {"temp_C": temp, "ghi": ghi}


def pv_availability(ghi, peak_kw: float):
    """PV available power [kW] from global horizontal radiation.

    Normalised by the file's own maximum radiation and scaled to the installed
    peak. This is a simple, transparent irradiance-proportional model (no panel
    tilt/temperature derating); good enough for dispatch and clearly documented.
    """
    gmax = max(ghi) or 1.0
    return [peak_kw * (g / gmax) for g in ghi]


def heatpump_cop(temp_C, cop_ref=3.5, t_ref=7.0, slope=0.10, cop_min=1.5, cop_max=5.0):
    """Air-source heat-pump COP as a function of ambient temperature.

    Linear approximation around a reference point: COP rises ~`slope` per degree
    above `t_ref` and falls below it. Clipped to a physical range. (A standard
    first-order model; the real When2Heat COP series can be used instead.)
    """
    out = []
    for t in temp_C:
        cop = cop_ref + slope * (t - t_ref)
        out.append(max(cop_min, min(cop_max, cop)))
    return out


def heat_demand_shape(temp_C, base_kw=50.0, hdd_coeff=8.0, t_base=15.0):
    """Heat demand [kW] from a heating-degree model: demand rises as temperature
    drops below `t_base`. base_kw is a constant (e.g. hot water); hdd_coeff is kW
    per degree below the base temperature.
    """
    out = []
    for t in temp_C:
        hdd = max(0.0, t_base - t)
        out.append(base_kw + hdd_coeff * hdd)
    return out
