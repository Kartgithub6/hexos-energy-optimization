"""
engine.control.simulator
========================
A simple plant simulator for closed-loop MPC testing.

In real-time control the optimiser plans a schedule, but only the FIRST step is
actually applied; then reality moves forward (often differing from the plan) and
the controller re-plans from the new true state. The simulator plays the role of
"reality": given the control set-points the controller chose for one hour, and
the TRUE conditions of that hour, it advances the storage states by one hour.

It deliberately mirrors the model's own storage dynamics so that, under perfect
forecasts, the simulated state matches the optimiser's predicted state exactly
(a property the tests check).

State carried: battery SOC and heat-storage SOC.
"""

from __future__ import annotations


def step_storage(soc, charge, discharge, eta_ch, eta_dis, self_disch, dt=1.0):
    """Advance one storage by one hour using the same dynamics as the model."""
    return (1 - self_disch) * soc + eta_ch * charge * dt - (discharge / eta_dis) * dt


def advance_one_hour(state, applied, cfg, dt=1.0):
    """Advance battery + heat-storage SOC by one hour given the applied controls.

    state:   {"batt_soc":..., "hstor_soc":...}
    applied: {"charge":.., "discharge":.., "h_charge":.., "h_discharge":..}
    Returns the new state dict.
    """
    b = cfg.get("battery", {})
    s = cfg.get("heat_storage", {})
    new = dict(state)
    if b.get("E_cap", 0) > 0:
        new["batt_soc"] = step_storage(
            state["batt_soc"], applied["charge"], applied["discharge"],
            b["eta_ch"], b["eta_dis"], b["self_disch"], dt)
        new["batt_soc"] = max(0.0, min(b["E_cap"], new["batt_soc"]))
    if s.get("E_cap", 0) > 0:
        new["hstor_soc"] = step_storage(
            state["hstor_soc"], applied["h_charge"], applied["h_discharge"],
            s["eta_ch"], s["eta_dis"], s["self_disch"], dt)
        new["hstor_soc"] = max(0.0, min(s["E_cap"], new["hstor_soc"]))
    return new
