# HEXOS — Heat-Electricity eXchange Optimization System

HEXOS is an open, from-scratch optimization model for the live operation of a corporate
multi-energy system (electricity + heat sector coupling), built with
[Pyomo](https://pyomo.org) and solved with the free
[HiGHS](https://highs.dev) solver.

The model decides the cheapest hour-by-hour operation of on-site producers,
consumers, and storages — PV, CHP, heat pump, heating rod, battery, and thermal
storage — against time-varying electricity prices and demand.

## Provenance

This is an independent clean-room implementation. The formulation follows
standard, publicly documented energy-hub modeling as found in open-source
frameworks such as [URBS](https://github.com/tum-ens/urbs) (TU Munich),
[oemof](https://oemof.org), and [PyPSA](https://pypsa.org), combined with
published district-heating literature. It does not contain or derive from any
proprietary or confidential code.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Run the validation suite:

```bash
pytest -v
```

Run the dispatch demo:

```bash
python scenarios/run_dispatch.py
```

Prepare the realistic 2019 German dataset (after downloading the raw files per `data/raw/README_DOWNLOAD.md`):

```bash
python scenarios/prepare_year.py    # writes data/year_DE_2019.csv
```

## Project layout

```
src/         model modules (data_io, model_step1, …)
tests/       hand-checkable validation tests
data/        input time series (toy + realistic samples)
scenarios/   runnable end-to-end scripts
results/     outputs (gitignored)
```

## Build roadmap

Each step ships a runnable model **and** passing tests before the next begins.

1. **Electricity core** — grid + PV + battery + demand (LP).  ✅ done
2. **Heat bus + sector coupling** — CHP (fixed heat-to-power ratio, min-load
   on/off binaries → MILP), heat pump (constant *or* temperature-dependent COP,
   switchable for the fidelity comparison), heating rod, thermal storage.  ✅ done
3. **Realistic year (DE, 2019)** — national When2Heat + OPSD profiles scaled to
   a company-sized site via `scenarios/prepare_year.py`.  ◐ pipeline built;
   needs the raw downloads (see `data/raw/README_DOWNLOAD.md`).
4. **Heat-model fidelity comparison** — quantify how constant vs.
   temperature-dependent COP changes optimal dispatch and cost (the project's
   differentiator).
5. **Post-processing & Dymola hand-off** — export optimized setpoints as CSV to
   drive a Modelica building-simulation model for physical validation.
6. *(optional)* **Reserve markets** — FCR first (symmetric, capacity-only),
   then aFRR / mFRR.

## Module layout (src/)

```
data_io.py      load + validate input CSV (electricity, heat, COP)
model_core.py   sets, parameters, variables
constraints.py  bus balances + each technology's relations and limits
objective.py    total operating cost
build_model.py  assemble / solve / extract (enables a tech when capacity > 0)
```

A technology is switched off by setting its capacity to 0 in the config; its
variables are then locked to zero so the solver cannot use a phantom unit.

## Data sources

All datasets below are open-licensed and relevant to a German company site.
The toy datasets in `data/` are synthetic and hand-checkable; the realistic
week is assembled from these sources.

**Heat demand & heat-pump COP**
- **When2Heat** (Open Power System Data) — hourly heat-demand and heat-pump COP
  time series, computed with the German gas standard-load-profile methodology.
  License: CC-BY 4.0. https://data.open-power-system-data.org/when2heat/
  Cite: Ruhnau, O., Hirth, L., Praktiknjo, A. (2019). *Time series of heat
  demand and heat pump efficiency for energy system modeling.* Scientific Data
  6, 189. https://doi.org/10.1038/s41597-019-0199-y

**Electricity load, prices, PV/wind generation**
- **Open Power System Data — Time Series** — hourly load, wind/solar
  generation, and day-ahead prices for European countries.
  https://data.open-power-system-data.org/time_series/
- **SMARD.de** (German Federal Network Agency / Bundesnetzagentur) — German
  day-ahead prices, load, generation, and balancing/reserve data (the source
  for FCR/aFRR/mFRR if step 6 is built). https://www.smard.de/en
- **ENTSO-E Transparency Platform** — pan-European load, generation, and
  day-ahead prices (free account required). https://transparency.entsoe.eu

**PV generation profiles**
- **renewables.ninja** — hourly PV/wind output for any location from reanalysis
  weather data. https://www.renewables.ninja
- **PVGIS** (European Commission JRC) — hourly PV potential, official EU tool.
  https://re.jrc.ec.europa.eu/pvg_tools/en/

## License

Add your chosen license here (MIT is a common choice for portfolio code).
