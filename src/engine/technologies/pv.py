"""hexos.technologies.pv — non-dispatchable solar, curtailable."""
import pyomo.environ as pyo


def add_pv(m):
    m.pv_limit = pyo.Constraint(m.T, rule=lambda m, t: m.pv_used[t] <= m.pv_avail[t])
