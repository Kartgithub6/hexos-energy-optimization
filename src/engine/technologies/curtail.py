"""engine.technologies.curtail — heat curtailment (emergency cooler) lock.

Heat dump is OFF unless cfg['allow_heat_dump'] is True, so by default heat must
be exactly balanced.
"""
import pyomo.environ as pyo


def add_curtail_lock(m):
    if not m.cfg.get("allow_heat_dump", False):
        m.lock_curtail = pyo.Constraint(m.T, rule=lambda m, t: m.h_curtail[t] == 0)


def add_disabled_locks(m, disabled):
    if "woodchip" in disabled:
        m.lock_wood = pyo.Constraint(m.T, rule=lambda m, t: m.wood_fuel[t] + m.wood_heat[t] == 0)
    if "gas_boiler" in disabled:
        m.lock_gas = pyo.Constraint(m.T, rule=lambda m, t: m.gas_fuel[t] + m.gas_heat[t] == 0)
    if "heatpump" in disabled:
        m.lock_hp = pyo.Constraint(m.T, rule=lambda m, t: m.hp_el[t] + m.hp_heat[t] == 0)
    if "rod" in disabled:
        m.lock_rod = pyo.Constraint(m.T, rule=lambda m, t: m.rod_el[t] + m.rod_heat[t] == 0)
    if "battery" in disabled:
        m.lock_batt = pyo.Constraint(m.T, rule=lambda m, t: m.p_ch[t] + m.p_dis[t] == 0)
        m.lock_batt_soc = pyo.Constraint(m.T, rule=lambda m, t: m.soc[t] == 0)
    if "heat_storage" in disabled:
        m.lock_hstor = pyo.Constraint(m.T, rule=lambda m, t: m.h_ch[t] + m.h_dis[t] == 0)
        m.lock_hstor_soc = pyo.Constraint(m.T, rule=lambda m, t: m.h_soc[t] == 0)
