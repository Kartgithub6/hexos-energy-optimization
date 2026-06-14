"""hexos.technologies.rod — resistive electricity -> heat."""
import pyomo.environ as pyo


def add_rod(m, r):
    m.rod_conv = pyo.Constraint(m.T, rule=lambda m, t: m.rod_heat[t] == r["eta"] * m.rod_el[t])
    m.rod_max = pyo.Constraint(m.T, rule=lambda m, t: m.rod_heat[t] <= r["q_max"])
