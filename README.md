# HEXOS — Heat-Electricity eXchange Optimization System

HEXOS is an open, from-scratch optimization model for the live operation of a
corporate multi-energy system (electricity + heat sector coupling), built with
[Pyomo](https://pyomo.org) and solved with the free [HiGHS](https://highs.dev)
solver. It is a **Mixed-Integer Linear Program (MILP)**: continuous energy flows
plus binary CHP on/off decisions, minimum-runtime and start-up logic.

The model decides the cheapest hour-by-hour operation of on-site producers,
consumers, and storages — PV, multiple CHP units, woodchip and gas boilers, heat
pump, heating rods, battery, heat storage, and controllable EV charging — against
time-varying electricity prices, demand, and weather-dependent heat-pump COP.

## Provenance

Independent clean-room implementation. The formulation follows standard,
publicly documented energy-hub modelling as in open-source frameworks such as
[URBS](https://github.com/tum-ens/urbs) (TU Munich), [oemof](https://oemof.org),
and [PyPSA](https://pypsa.org), plus published district-heating literature. It
contains no proprietary or confidential code. The reference plant and the input
template use fictional, realistic values — no real plant data.

## Capabilities

- Two energy buses (electricity, heat) with full sector coupling
- **Multiple independent CHP units**, each with capacity, efficiency,
  heat-to-power ratio, minimum load, **minimum runtime**, **ramp limit**, and
  **start-up cost** (the MILP/integer features)
- Woodchip boiler, gas (condensing) boiler, heat pump (temperature-dependent or
  constant COP), heating rods
- Battery and thermal storage; heat curtailment (emergency cooler)
- **EV charging** as a controllable load (fixed energy by a deadline, timing free)
- **Peak-demand charge** (German "Lastspitze" industrial tariff)
- **Rolling-horizon solver** for full-year (8760 h) runs in ~1–2 min
- **Three-way COP fidelity comparison** (temperature-dependent vs mean vs nameplate)
- **Baseline forecasting** module (persistence, type-day average) — the clean
  "prognosis" starter for running on predictions instead of perfect foresight
- **Real Munich weather** (EnergyPlus `.mos`) driving PV, heat-pump COP, and heat
  demand from one physically-consistent source
- **Closed-loop MPC simulation** — an offline test of a real-time control
  strategy (forecast → optimise → apply one hour → simulate reality → re-forecast),
  measuring the realistic cost of imperfect forecasts vs perfect foresight
- **Interactive Streamlit app** — pick a real day from the Munich year (by type:
  sunny / cloudy / rainy / cold snap / hot, or by date), toggle technologies,
  add forecast uncertainty, and solve it live. Variation comes from choosing
  different REAL days, never from cosmetic randomness on the optimizer.

## Package layout

```
src/engine/
  data/         io (load + validate input)
  model/        core (sets/params/vars), objective, build (orchestration)
  technologies/ one module per prosumer: chp, boiler, heatpump, rod, pv,
                battery, heat_storage, ev, grid, balances, curtail
  solve/        single, rolling (rolling-horizon decomposition)
  control/      mpc (closed-loop simulation), simulator, forecasters
  forecast/     baseline forecasters (persistence, type-day average)
  data/         io, weather (.mos parser + PV/COP/heat derivations)
  postprocess/  extract, cop_variants
config/         ref_plant (fictional reference plant + EV fleet)
scenarios/      run_year, run_ref_plant, run_ev_day, compare_cop, prepare_year
tests/          one test module per concern (mirrors src/)
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -v                                            # run the validation suite
```

Scenarios add `src/` and `config/` to the path automatically, so no install is
needed. (A `pyproject.toml` is included if you prefer `pip install -e .`.)

## Running

```bash
python scenarios/prepare_year.py     # build the real German 2019 dataset (see data/raw/README_DOWNLOAD.md)
python scenarios/run_ref_plant.py    # full-year run of the reference plant
python scenarios/run_ev_day.py       # single-day EV smart-charging demo
python scenarios/compare_cop.py      # COP fidelity comparison
python scenarios/prepare_weather_year.py  # build a year from real Munich weather (.mos)
python scenarios/run_mpc.py          # closed-loop MPC simulation vs perfect foresight
streamlit run app/streamlit_app.py   # interactive demo (pick a real day, solve live)
```

## Methodology notes

- **MILP**: CHP on/off, minimum runtime and start-up are the integer/binary part;
  everything else is linear. Solved with HiGHS (swappable for Gurobi/CPLEX).
- **Rolling horizon** approximates the true full-year optimum (no window sees the
  whole year); min-runtime is enforced within a window, not across seams; EV
  scheduling uses a single-horizon solve.
- **Validation**: a test suite of hand-checkable scenarios and energy-balance
  invariants; see `tests/`.

## Not yet built (productionization, deliberately out of scope)

A closed-loop **MPC simulation** is included (`engine/control/mpc.py`) — an
*offline* test of a real-time control strategy against historical data. What is
NOT included (and would be needed for an actual deployment): live hardware
control (OPC UA), a message-queue microservice, 24/7 operation, and database
integration. HEXOS is the modelling + optimisation + control-strategy core; the
deployment/productionisation layer is future work and is not claimed here.

## Data sources

See `data/raw/README_DOWNLOAD.md`. Heat demand + COP: When2Heat (CC-BY 4.0).
Price + load: OPSD time_series / SMARD / ENTSO-E. PV profiles: renewables.ninja /
PVGIS.

## License

Released under the MIT License (see `LICENSE`).
