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
"""
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
        return terms
    m.cost = pyo.Objective(rule=total_cost, sense=pyo.minimize)
