"""hexos.technologies.heat_storage — thermal storage on the heat bus."""
import pyomo.environ as pyo


def add_heat_storage(m, s, cyclic=True):
    def soc_dyn(m, t):
        prev = s["soc_init"] if t == m.T.first() else m.h_soc[t - 1]
        return (m.h_soc[t] == (1 - s["self_disch"]) * prev
                + s["eta_ch"] * m.h_ch[t] * m.dt - (m.h_dis[t] / s["eta_dis"]) * m.dt)
    m.h_soc_dynamics = pyo.Constraint(m.T, rule=soc_dyn)
    m.h_soc_cap = pyo.Constraint(m.T, rule=lambda m, t: m.h_soc[t] <= s["E_cap"])
    m.h_ch_limit = pyo.Constraint(m.T, rule=lambda m, t: m.h_ch[t] <= s["p_ch_max"])
    m.h_dis_limit = pyo.Constraint(m.T, rule=lambda m, t: m.h_dis[t] <= s["p_dis_max"])
    if cyclic:
        m.h_soc_cyclic = pyo.Constraint(rule=lambda m: m.h_soc[m.T.last()] == s["soc_init"])
