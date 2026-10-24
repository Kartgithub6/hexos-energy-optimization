"""engine.technologies.chp — multiple CHP units: conversion, capacity, min-load,
min-runtime, ramp limits, and start-up flags (for min-runtime and start-up cost).

Optional per-unit keys (all off by default, so existing configs behave exactly
as before):
  on_init            1 if the unit was running in the hour before this window.
                     Without it every window assumes the unit starts cold, which
                     counts a start-up at every seam of a rolling solve.
  max_starts_per_day cap on start-ups in any rolling 24 h. Limits the daily
                     on/off cycling that wears real engines.
  su_hist            start-ups (0/1) in the hours just before this window, most
                     recent last, so the 24 h cap holds across window seams.
"""
import pyomo.environ as pyo


def add_chp(m):
    par = m.chp_par

    m.chp_el_eff = pyo.Constraint(
        m.CHP, m.T, rule=lambda m, c, t: m.chp_el[c, t] == par[c]["eta_el"] * m.chp_gas[c, t])
    m.chp_coupling = pyo.Constraint(
        m.CHP, m.T, rule=lambda m, c, t: m.chp_heat[c, t] == par[c]["htp_ratio"] * m.chp_el[c, t])
    m.chp_max = pyo.Constraint(
        m.CHP, m.T, rule=lambda m, c, t: m.chp_el[c, t] <= par[c]["p_el_max"] * m.chp_on[c, t])
    m.chp_min = pyo.Constraint(
        m.CHP, m.T,
        rule=lambda m, c, t: m.chp_el[c, t] >= par[c]["min_load"] * par[c]["p_el_max"] * m.chp_on[c, t])

    def su_rule(m, c, t):
        prev_on = par[c].get("on_init", 0) if t == m.T.first() else m.chp_on[c, t - 1]
        return m.chp_su[c, t] >= m.chp_on[c, t] - prev_on
    m.chp_startup = pyo.Constraint(m.CHP, m.T, rule=su_rule)

    def max_starts_rule(m, c, t):
        cap = par[c].get("max_starts_per_day", None)
        if cap is None:
            return pyo.Constraint.Skip
        ts = list(m.T)
        i = ts.index(t)
        in_window = sum(m.chp_su[c, k] for k in ts[max(0, i - 23): i + 1])
        lookback = 23 - i                       # hours of the 24 h before the window
        hist = list(par[c].get("su_hist", []))
        before = sum(hist[-lookback:]) if lookback > 0 and hist else 0
        return in_window + before <= cap
    m.chp_max_starts = pyo.Constraint(m.CHP, m.T, rule=max_starts_rule)

    def minrun_rule(m, c, t):
        L = int(par[c].get("min_runtime_h", 1))
        if L <= 1:
            return pyo.Constraint.Skip
        ts = list(m.T)
        i = ts.index(t)
        window = ts[max(0, i - L + 1): i + 1]
        return sum(m.chp_su[c, k] for k in window) <= m.chp_on[c, t]
    m.chp_minrun = pyo.Constraint(m.CHP, m.T, rule=minrun_rule)

    def ramp_up(m, c, t):
        g = par[c].get("max_grad", None)
        if g is None or t == m.T.first():
            return pyo.Constraint.Skip
        return m.chp_el[c, t] - m.chp_el[c, t - 1] <= g
    def ramp_dn(m, c, t):
        g = par[c].get("max_grad", None)
        if g is None or t == m.T.first():
            return pyo.Constraint.Skip
        return m.chp_el[c, t - 1] - m.chp_el[c, t] <= g
    m.chp_ramp_up = pyo.Constraint(m.CHP, m.T, rule=ramp_up)
    m.chp_ramp_dn = pyo.Constraint(m.CHP, m.T, rule=ramp_dn)
