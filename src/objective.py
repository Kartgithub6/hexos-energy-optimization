"""
objective.py
============
The objective: minimise total operating cost over the horizon.

  cost = sum over t of:
        electricity import cost
      - electricity export revenue
      + gas cost for the CHP
    all scaled by the time-step length dt (so partial-hour steps work too).

Start-up costs and demand charges are deliberately left out for now; they are a
clean future extension (and another fidelity level for the comparison study).
"""

from __future__ import annotations
import pyomo.environ as pyo


def add_objective(m):
    def total_cost(m):
        return sum(
            (m.price_el[t] * m.p_import[t]
             - m.price_exp[t] * m.p_export[t]
             + m.price_gas * m.chp_gas[t]) * m.dt
            for t in m.T
        )
    m.cost = pyo.Objective(rule=total_cost, sense=pyo.minimize)
