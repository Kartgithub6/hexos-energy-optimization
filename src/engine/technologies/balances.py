"""engine.technologies.balances — electricity and heat bus balances + peak tracking."""
import pyomo.environ as pyo


def add_electricity_balance(m):
    def rule(m, t):
        chp_el = sum(m.chp_el[c, t] for c in m.CHP)
        ev = sum(m.ev_p[e, t] for e in m.EV)
        sources = m.p_import[t] + m.pv_used[t] + m.p_dis[t] + chp_el
        sinks = m.dem_el[t] + m.p_export[t] + m.p_ch[t] + m.hp_el[t] + m.rod_el[t] + ev
        return sources == sinks
    m.elec_balance = pyo.Constraint(m.T, rule=rule)


def add_heat_balance(m):
    def rule(m, t):
        chp_heat = sum(m.chp_heat[c, t] for c in m.CHP)
        sources = (chp_heat + m.wood_heat[t] + m.gas_heat[t]
                   + m.hp_heat[t] + m.rod_heat[t] + m.h_dis[t])
        sinks = m.dem_heat[t] + m.h_ch[t] + m.h_curtail[t]
        return sources == sinks
    m.heat_balance = pyo.Constraint(m.T, rule=rule)


def add_peak_tracking(m):
    """peak_import >= grid import every hour, so it captures the maximum."""
    m.peak_track = pyo.Constraint(m.T, rule=lambda m, t: m.peak_import >= m.p_import[t])
