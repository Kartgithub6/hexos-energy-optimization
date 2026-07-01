"""engine.solve.single — solve a built model and extract results."""
import pyomo.environ as pyo


def solve(m, tee=False):
    solver = pyo.SolverFactory("appsi_highs")
    return solver.solve(m, tee=tee)
