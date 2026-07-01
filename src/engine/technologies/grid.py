"""engine.technologies.grid — grid connection capacity."""
import pyomo.environ as pyo


def add_grid(m, g):
    m.import_limit = pyo.Constraint(m.T, rule=lambda m, t: m.p_import[t] <= g["import_max"])
    m.export_limit = pyo.Constraint(m.T, rule=lambda m, t: m.p_export[t] <= g["export_max"])
