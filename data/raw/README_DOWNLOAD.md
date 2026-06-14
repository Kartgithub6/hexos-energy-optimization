# Downloading the raw data (Germany, 2019)

`prepare_year.py` needs two source files placed in this folder. Both are open
data. Download them exactly as below, drop them here, then run
`python scenarios/prepare_year.py` from the project root.

The script slices each file to Germany + 2019 on load, so the full national
files are fine even though they are large.

---

## 1. When2Heat — heat demand + heat-pump COP

- Page: https://data.open-power-system-data.org/when2heat/
- Version: **2023-07-27** (latest)
- File to download: **`when2heat.csv`** (singleindex CSV, ~313 MB)
  Direct link:
  https://data.open-power-system-data.org/when2heat/2023-07-27/when2heat.csv
- Save it here as: `data/raw/when2heat.csv`

Columns the script reads (Germany, air-source heat pump, floor heating):
- `DE_heat_profile_space_SFH` + `DE_heat_profile_water_SFH` — normalized space
  and water heating shapes [MW/TWh]. **Note:** the absolute `DE_heat_demand_*`
  columns are not populated for recent years, so heat demand is built from these
  normalized profiles instead (and scaled to the site target anyway).
- `DE_COP_ASHP_floor`     — air-source heat-pump COP [-]

**File format:** When2Heat is **semicolon-delimited with comma decimals**
(German format) — the script handles this with `sep=";", decimal=","`.

License: CC-BY 4.0. Cite: Ruhnau, O., Hirth, L., Praktiknjo, A. (2019),
*Time series of heat demand and heat pump efficiency for energy system
modeling*, Scientific Data 6, 189. https://doi.org/10.1038/s41597-019-0199-y

---

## 2. OPSD Time Series — electricity price + load

- Page: https://data.open-power-system-data.org/time_series/
- Version: **2020-10-06** (latest)
- File to download: **`time_series_60min_singleindex.csv`** (hourly, singleindex)
  From the page, choose the 60-minute singleindex CSV.
- Save it here as: `data/raw/time_series_60min_singleindex.csv`

Columns the script reads:
- `DE_LU_price_day_ahead`                 — German day-ahead price [EUR/MWh]
- `DE_load_actual_entsoe_transparency`    — German load [MW]

(2019 is fully inside the DE-LU bidding zone, so `DE_LU_price_day_ahead` has
complete coverage for that year.)

License: see the OPSD time_series datapackage (primary data ENTSO-E, etc.).

---

## After downloading

```
python scenarios/prepare_year.py
```

This writes `data/year_DE_2019.csv` (~8760 rows) with the columns HEXOS expects:
`t, price_el, price_exp, pv_avail, dem_el, dem_heat, cop`, plus a header
recording the scaling assumptions. If a column name has changed in a newer
dataset version, the script will fail with a clear message naming the missing
column so you can adjust it in `prepare_year.py`.

## Note on scaling (read this before quoting any cost number)

When2Heat and OPSD report *national* quantities. `prepare_year.py` keeps the
*shape* of those profiles but rescales their *magnitude* to a single
company-sized site (heat scaled to an annual total, electrical load scaled to a
peak). Prices are not scaled, only unit-converted. These assumptions are set at
the top of `prepare_year.py` and recorded in the output file's header. They are
a deliberate, documented modelling choice — adjust them to match a real site if
you have its figures.
