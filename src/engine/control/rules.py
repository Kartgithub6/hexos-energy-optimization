"""
engine.control.rules
====================
Rule-based battery behaviour, used as a baseline the optimiser has to beat.

`self_consumption_schedule` mimics the "maximise self-consumption" mode most
commercial batteries ship with: charge only from solar surplus, discharge only
to cover the site's own load, never charge from the grid, never export from the
battery, and look neither at prices nor at tomorrow.

Simplification, stated plainly: "load" here is the site's base electrical
demand. The heat pump and heating rod are dispatched by the optimiser after the
battery schedule is fixed, so the rule cannot see their consumption. A real
inverter would see it, which would make the rule discharge slightly more on
cold evenings.
"""
from __future__ import annotations


def self_consumption_schedule(data, battery):
    """Hour-by-hour greedy schedule over the whole horizon.

    Returns (charge, discharge) lists in kW, using the same storage dynamics as
    the model so the schedule is always feasible when pinned into it.
    """
    cap = battery["E_cap"]
    p_ch, p_dis = battery["p_ch_max"], battery["p_dis_max"]
    eta_ch, eta_dis = battery["eta_ch"], battery["eta_dis"]
    loss = battery["self_disch"]
    soc = battery.get("soc_init", 0.0)
    margin = 1e-6 * max(cap, 1.0)   # keeps rounding from nudging past the limits

    charge, discharge = [], []
    for pv, load in zip(data["pv_avail"], data["dem_el"]):
        kept = (1 - loss) * soc
        surplus = pv - load
        ch = dis = 0.0
        if surplus > 0:
            room = max(0.0, cap - kept - margin)
            ch = min(surplus, p_ch, room / eta_ch)
        elif surplus < 0:
            avail = max(0.0, kept - margin)
            dis = min(-surplus, p_dis, avail * eta_dis)
        soc = kept + eta_ch * ch - dis / eta_dis
        charge.append(ch)
        discharge.append(dis)
    return charge, discharge
