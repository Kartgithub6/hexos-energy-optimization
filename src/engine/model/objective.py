"""
engine.model.objective
======================
Total operating cost over the horizon:

  energy:  import*price_el - export*price_exp
  fuels:   price_gas * sum(CHP gas) + woodchip_fuel_price * woodchip fuel
           + gas_boiler_fuel_price * gas-boiler fuel
  startup: sum over CHP units of startup_cost * start-up flag
  demand:  demand_charge [currency per kW of peak] * peak_import  (once)

The demand charge models the German "Lastspitze" industrial tariff: a charge on
the highest power drawn, not just energy. It is applied once over the horizon.

Terminal value (optional, off by default): battery energy left at the end of
the window is credited at `battery.terminal_value` EUR/kWh, so a finite-window
optimiser stops draining the battery just before the window ends. Set it to a
number, or to "auto" for the median import price of the window times the
discharge efficiency (what a stored kWh is roughly worth when used later). It
only shapes decisions; reported costs never include it.

Battery wear (optional, off by default): when cfg['battery']['wear'] is set,
engine.technologies.wear adds a degradation cost for every kWh cycled, so the
battery only cycles when the spread also pays for the capacity it uses up.
Unlike the terminal value this is a real cost, but solve_rolling still reports
energy cost only; score wear after the fact with engine.postprocess.wear so
wear-aware and wear-blind runs are judged by the same yardstick.
"""
import statistics
import pyomo.environ as pyo


def add_objective(m):
    cfg = m.cfg
    wood_price = cfg.get("woodchip", {}).get("fuel_price", 0.0)
    gasb_price = cfg.get("gas_boiler", {}).get("fuel_price", 0.0)
    demand_charge = cfg.get("demand_charge", 0.0)   # currency per kW of peak
    par = m.chp_par

    def total_cost(m):
        terms = 0
        for t in m.T:
            chp_gas = sum(m.chp_gas[c, t] for c in m.CHP)
            chp_su = sum(par[c].get("startup_cost", 0.0) * m.chp_su[c, t] for c in m.CHP)
            terms += (m.price_el[t] * m.p_import[t]
                      - m.price_exp[t] * m.p_export[t]
                      + m.price_gas * chp_gas
                      + wood_price * m.wood_fuel[t]
                      + gasb_price * m.gas_fuel[t]
                      + chp_su) * m.dt
        terms += demand_charge * m.peak_import
        terms -= _terminal_value(m) * m.soc[m.T.last()]
        terms += _wear_cost(m)
        return terms
    m.cost = pyo.Objective(rule=total_cost, sense=pyo.minimize)


def _wear_cost(m):
    f = getattr(m, "wear_cost_terms", None)
    return f(m) if f is not None else 0.0


def _terminal_value(m):
    b = m.cfg.get("battery", {})
    tv = b.get("terminal_value", None)
    if tv is None or b.get("E_cap", 0) <= 0:
        return 0.0
    if tv == "auto":
        prices = [m.price_el[t] for t in m.T]
        return b.get("eta_dis", 1.0) * statistics.median(prices)
    return float(tv)
