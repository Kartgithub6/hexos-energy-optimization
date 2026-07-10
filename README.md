# HEXOS — Multi-Energy Dispatch Optimizer

HEXOS works out the cheapest way to run an industrial site's energy system,
hour by hour. A factory or campus with its own solar, combined heat-and-power
(CHP) units, heat pumps, boilers, and batteries has to decide constantly where
its electricity and heat should come from — and doing that well, against
changing prices and weather, can save real money. HEXOS makes that decision
automatically by solving it as an optimization problem instead of following
fixed rules.

Under the hood it's a Mixed-Integer Linear Program, written in Python with
[Pyomo](https://pyomo.org) and solved using [HiGHS](https://highs.dev). Most of
the model is linear, but the CHP on/off choices are yes/no decisions — that's
the "integer" part — along with realistic constraints like minimum runtime,
ramp limits, and start-up costs.

## What it does

- Optimizes a full year (8,760 hours) at once, using a rolling-horizon solver
  that keeps it tractable — the whole year solves in about two minutes.
- Runs on real data: German day-ahead electricity prices (OPSD), Munich weather
  (EnergyPlus), and heat-demand and heat-pump efficiency profiles (When2Heat).
- Includes a closed-loop Model Predictive Control simulation that tests how the
  system performs when it has to rely on imperfect forecasts, and measures the
  cost of that uncertainty against a perfect-foresight benchmark.
- Runs a study on how much the heat pump's efficiency modelling actually affects
  the results — a small but real modelling-fidelity question.
- Comes with an interactive dashboard (Streamlit + Plotly) where you can pick a
  real day, switch technologies on and off, and solve it live. Results are saved
  to a PostgreSQL database so you can compare past runs.
- Backed by a 52-test suite covering hand-checked cases and energy-balance checks.

## Getting started

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q                                           # should show 52 passing
streamlit run app/streamlit_app.py                  # launch the dashboard
```

The full-year scenarios need the raw datasets — `data/raw/README_DOWNLOAD.md`
explains where to get them. The database features are optional; the app runs
fine without one, and `SETUP_DATABASE.md` covers the setup if you want them.

## Scope

HEXOS is an offline optimization and control-strategy engine — it works out and
tests the best schedule, but it isn't wired to live hardware and doesn't run a
plant in real time. It also isn't a trading tool or an equipment-sizing tool;
the goal is simply to minimize a site's operating cost.

## Provenance

This is an independent, clean-room implementation built from published
energy-system optimization methods and open datasets. It contains no
proprietary code, and the example plant uses realistic but fictional values.

## License

Released under the MIT License — see the `LICENSE` file.