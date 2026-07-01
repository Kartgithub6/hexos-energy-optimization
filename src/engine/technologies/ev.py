"""engine.technologies.ev — EV charging as a controllable load.

Each EV session has a fixed energy need that must be delivered within a time
window, and a max charging power. The model chooses WHEN to charge within the
window (e.g. cheap or high-PV hours). This is the "variable load" flexibility:
total energy fixed, timing free.

EV config (cfg["evs"] = list of):
  name        : identifier
  p_max       : maximum charging power [kW]
  energy_need : total energy to deliver over the window [kWh]
  start_t     : first hour of the window (inclusive)
  end_t       : last hour of the window (inclusive)
Outside its window an EV's charging power is forced to zero.
"""
import pyomo.environ as pyo


def add_ev(m):
    par = m.ev_par

    # Power limit, and zero outside the charging window.
    def p_limit(m, e, t):
        p = par[e]
        if t < p["start_t"] or t > p["end_t"]:
            return m.ev_p[e, t] == 0
        return m.ev_p[e, t] <= p["p_max"]
    m.ev_p_limit = pyo.Constraint(m.EV, m.T, rule=p_limit)

    # Energy delivered over the window must meet the requirement exactly.
    def energy_need(m, e):
        p = par[e]
        ts = [t for t in m.T if p["start_t"] <= t <= p["end_t"]]
        return sum(m.ev_p[e, t] * m.dt for t in ts) == p["energy_need"]
    m.ev_energy = pyo.Constraint(m.EV, rule=energy_need)
