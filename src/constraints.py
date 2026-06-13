"""
constraints.py
==============
All constraints for HEXOS, grouped by concern. Each `add_*` function attaches
one logical block of constraints to the model. build_model.py decides which
blocks to include based on the config (e.g. skip CHP if its capacity is 0).

Every technology follows the same shape:
  - a conversion/coupling relation (how inputs map to outputs)
  - capacity / operating limits

The two bus balances (electricity, heat) tie everything together.
"""

from __future__ import annotations
import pyomo.environ as pyo


# ----------------------------------------------------------------------------
# Bus balances
# ----------------------------------------------------------------------------
def add_electricity_balance(m):
    """Sources == sinks on the electricity bus, every hour."""
    def rule(m, t):
        sources = m.p_import[t] + m.pv_used[t] + m.p_dis[t] + m.chp_el[t]
        sinks = (m.dem_el[t] + m.p_export[t] + m.p_ch[t]
                 + m.hp_el[t] + m.rod_el[t])
        return sources == sinks
    m.elec_balance = pyo.Constraint(m.T, rule=rule)


def add_heat_balance(m):
    """Sources == sinks on the heat bus, every hour."""
    def rule(m, t):
        sources = m.chp_heat[t] + m.hp_heat[t] + m.rod_heat[t] + m.h_dis[t]
        sinks = m.dem_heat[t] + m.h_ch[t]
        return sources == sinks
    m.heat_balance = pyo.Constraint(m.T, rule=rule)


# ----------------------------------------------------------------------------
# Grid connection capacity. A real site has a contracted connection limit; it
# also makes the model well-posed when the export price can exceed the import
# price (e.g. negative-price hours), which would otherwise allow unbounded
# buy-low/sell-high arbitrage through an unlimited grid.
# ----------------------------------------------------------------------------
def add_grid(m, g):
    """g keys: import_max, export_max [kW]."""
    m.import_limit = pyo.Constraint(
        m.T, rule=lambda m, t: m.p_import[t] <= g["import_max"])
    m.export_limit = pyo.Constraint(
        m.T, rule=lambda m, t: m.p_export[t] <= g["export_max"])


# ----------------------------------------------------------------------------
# PV
# ----------------------------------------------------------------------------
def add_pv(m):
    def rule(m, t):
        return m.pv_used[t] <= m.pv_avail[t]
    m.pv_limit = pyo.Constraint(m.T, rule=rule)


# ----------------------------------------------------------------------------
# Battery (electrical storage)
# ----------------------------------------------------------------------------
def add_battery(m, b, cyclic=True):
    def soc_dyn(m, t):
        prev = b["soc_init"] if t == m.T.first() else m.soc[t - 1]
        return (m.soc[t] == (1 - b["self_disch"]) * prev
                + b["eta_ch"] * m.p_ch[t] * m.dt
                - (m.p_dis[t] / b["eta_dis"]) * m.dt)
    m.soc_dynamics = pyo.Constraint(m.T, rule=soc_dyn)

    m.soc_cap = pyo.Constraint(m.T, rule=lambda m, t: m.soc[t] <= b["E_cap"])
    m.ch_limit = pyo.Constraint(m.T, rule=lambda m, t: m.p_ch[t] <= b["p_ch_max"])
    m.dis_limit = pyo.Constraint(m.T, rule=lambda m, t: m.p_dis[t] <= b["p_dis_max"])
    # Cyclic boundary only for standalone runs; rolling-horizon windows carry
    # state forward instead, so they pass cyclic=False.
    if cyclic:
        m.soc_cyclic = pyo.Constraint(rule=lambda m: m.soc[m.T.last()] == b["soc_init"])


# ----------------------------------------------------------------------------
# CHP: gas -> electricity + heat, fixed heat-to-power ratio, min-load on/off.
# ----------------------------------------------------------------------------
def add_chp(m, c):
    """
    c keys:
      p_el_max   : max electrical output            [kW]
      eta_el     : electrical efficiency (el/gas)    (0..1)
      htp_ratio  : heat-to-power ratio (heat/el)     [-]   <- the coupling
      min_load   : minimum load fraction when on     [0..1]
    """
    # Electrical efficiency: gas in -> electricity out.
    m.chp_el_eff = pyo.Constraint(
        m.T, rule=lambda m, t: m.chp_el[t] == c["eta_el"] * m.chp_gas[t])

    # Fixed heat-to-power coupling (backpressure): heat = ratio * electricity.
    m.chp_coupling = pyo.Constraint(
        m.T, rule=lambda m, t: m.chp_heat[t] == c["htp_ratio"] * m.chp_el[t])

    # Capacity tied to the on/off binary: when off (chp_on=0) output is forced
    # to 0; when on, output may go up to p_el_max.
    m.chp_max = pyo.Constraint(
        m.T, rule=lambda m, t: m.chp_el[t] <= c["p_el_max"] * m.chp_on[t])

    # Minimum load: when on, the unit must produce at least min_load of capacity.
    # When off, the binary makes the right-hand side 0, so the bound is inactive.
    m.chp_min = pyo.Constraint(
        m.T,
        rule=lambda m, t: m.chp_el[t] >= c["min_load"] * c["p_el_max"] * m.chp_on[t])


# ----------------------------------------------------------------------------
# Heat pump: electricity -> heat via COP (per-step, so it handles both the
# constant and temperature-dependent cases transparently).
# ----------------------------------------------------------------------------
def add_heatpump(m, h):
    """h keys:  q_max : max heat output [kW]"""
    m.hp_conv = pyo.Constraint(
        m.T, rule=lambda m, t: m.hp_heat[t] == m.cop[t] * m.hp_el[t])
    m.hp_max = pyo.Constraint(
        m.T, rule=lambda m, t: m.hp_heat[t] <= h["q_max"])


# ----------------------------------------------------------------------------
# Heating rod: electricity -> heat at fixed efficiency (near 1.0).
# ----------------------------------------------------------------------------
def add_rod(m, r):
    """r keys:  eta : conversion efficiency;  q_max : max heat output [kW]"""
    m.rod_conv = pyo.Constraint(
        m.T, rule=lambda m, t: m.rod_heat[t] == r["eta"] * m.rod_el[t])
    m.rod_max = pyo.Constraint(
        m.T, rule=lambda m, t: m.rod_heat[t] <= r["q_max"])


# ----------------------------------------------------------------------------
# Heat storage: same dynamics as the battery, on the heat bus.
# ----------------------------------------------------------------------------
def add_heat_storage(m, s, cyclic=True):
    def soc_dyn(m, t):
        prev = s["soc_init"] if t == m.T.first() else m.h_soc[t - 1]
        return (m.h_soc[t] == (1 - s["self_disch"]) * prev
                + s["eta_ch"] * m.h_ch[t] * m.dt
                - (m.h_dis[t] / s["eta_dis"]) * m.dt)
    m.h_soc_dynamics = pyo.Constraint(m.T, rule=soc_dyn)

    m.h_soc_cap = pyo.Constraint(m.T, rule=lambda m, t: m.h_soc[t] <= s["E_cap"])
    m.h_ch_limit = pyo.Constraint(m.T, rule=lambda m, t: m.h_ch[t] <= s["p_ch_max"])
    m.h_dis_limit = pyo.Constraint(m.T, rule=lambda m, t: m.h_dis[t] <= s["p_dis_max"])
    if cyclic:
        m.h_soc_cyclic = pyo.Constraint(rule=lambda m: m.h_soc[m.T.last()] == s["soc_init"])


# ----------------------------------------------------------------------------
# "Off switches": when a technology has zero capacity, pin its variables to 0
# so the solver can't use a phantom unit. Cheap insurance for the test cases
# that disable technologies.
# ----------------------------------------------------------------------------
def add_disabled_locks(m, disabled: set):
    if "chp" in disabled:
        # Lock every CHP variable: input, both outputs, and the binary.
        m.lock_chp = pyo.Constraint(
            m.T, rule=lambda m, t: m.chp_gas[t] + m.chp_el[t] + m.chp_heat[t] == 0)
        m.lock_chp_on = pyo.Constraint(m.T, rule=lambda m, t: m.chp_on[t] == 0)
    if "heatpump" in disabled:
        m.lock_hp = pyo.Constraint(m.T, rule=lambda m, t: m.hp_el[t] + m.hp_heat[t] == 0)
    if "rod" in disabled:
        m.lock_rod = pyo.Constraint(m.T, rule=lambda m, t: m.rod_el[t] + m.rod_heat[t] == 0)
    if "battery" in disabled:
        m.lock_batt = pyo.Constraint(m.T, rule=lambda m, t: m.p_ch[t] + m.p_dis[t] == 0)
        # SOC has no dynamics constraint when disabled -> pin it so it is defined.
        m.lock_batt_soc = pyo.Constraint(m.T, rule=lambda m, t: m.soc[t] == 0)
    if "heat_storage" in disabled:
        m.lock_hstor = pyo.Constraint(m.T, rule=lambda m, t: m.h_ch[t] + m.h_dis[t] == 0)
        m.lock_hstor_soc = pyo.Constraint(m.T, rule=lambda m, t: m.h_soc[t] == 0)
