"""engine.technologies.boiler — fuel-fed heat-only boilers: woodchip and gas.

Both convert fuel to heat at a fixed efficiency. Kept in one module since they
are structurally identical; they differ only in fuel and price (set in config
and costed in the objective).
"""
import pyomo.environ as pyo


def add_woodchip(m, w):
    m.wood_conv = pyo.Constraint(m.T, rule=lambda m, t: m.wood_heat[t] == w["eta"] * m.wood_fuel[t])
    m.wood_max = pyo.Constraint(m.T, rule=lambda m, t: m.wood_heat[t] <= w["q_max"])


def add_gas_boiler(m, g):
    m.gas_conv = pyo.Constraint(m.T, rule=lambda m, t: m.gas_heat[t] == g["eta"] * m.gas_fuel[t])
    m.gas_max = pyo.Constraint(m.T, rule=lambda m, t: m.gas_heat[t] <= g["q_max"])
