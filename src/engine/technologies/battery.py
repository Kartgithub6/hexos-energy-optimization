"""hexos.technologies.battery — electrical storage."""
import pyomo.environ as pyo


def add_battery(m, b, cyclic=True):
    def soc_dyn(m, t):
        prev = b["soc_init"] if t == m.T.first() else m.soc[t - 1]
        return (m.soc[t] == (1 - b["self_disch"]) * prev
                + b["eta_ch"] * m.p_ch[t] * m.dt - (m.p_dis[t] / b["eta_dis"]) * m.dt)
    m.soc_dynamics = pyo.Constraint(m.T, rule=soc_dyn)
    m.soc_cap = pyo.Constraint(m.T, rule=lambda m, t: m.soc[t] <= b["E_cap"])
    m.ch_limit = pyo.Constraint(m.T, rule=lambda m, t: m.p_ch[t] <= b["p_ch_max"])
    m.dis_limit = pyo.Constraint(m.T, rule=lambda m, t: m.p_dis[t] <= b["p_dis_max"])
    if cyclic:
        m.soc_cyclic = pyo.Constraint(rule=lambda m: m.soc[m.T.last()] == b["soc_init"])
