"""hexos.technologies.chp — multiple CHP units: conversion, capacity, min-load,
min-runtime, ramp limits, and start-up flags (for min-runtime and start-up cost).
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
        prev_on = 0 if t == m.T.first() else m.chp_on[c, t - 1]
        return m.chp_su[c, t] >= m.chp_on[c, t] - prev_on
    m.chp_startup = pyo.Constraint(m.CHP, m.T, rule=su_rule)

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
