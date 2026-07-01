"""engine.technologies.heatpump — electricity -> heat via COP (per-step)."""
import pyomo.environ as pyo


def add_heatpump(m, h):
    m.hp_conv = pyo.Constraint(m.T, rule=lambda m, t: m.hp_heat[t] == m.cop[t] * m.hp_el[t])
    m.hp_max = pyo.Constraint(m.T, rule=lambda m, t: m.hp_heat[t] <= h["q_max"])
