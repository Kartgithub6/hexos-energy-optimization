"""
model_core.py
=============
HEXOS — Heat-Electricity eXchange Optimization System.

This module declares the *structure* of the model: the time set, all input
parameters, and all decision variables. Constraints and the objective live in
their own modules so each concern can be read and tested in isolation.

Carriers
--------
Two energy buses are modelled:
  - electricity  [kW]
  - heat         [kW thermal]

Technologies
------------
  grid          import / export of electricity
  pv            non-dispatchable solar (curtailable)
  battery       electrical storage
  chp           gas -> electricity + heat   (fixed heat-to-power ratio)
  heatpump      electricity -> heat         (COP, constant or time-varying)
  rod           electricity -> heat         (resistive, fixed efficiency)
  heat_storage  thermal storage

A technology is switched off by setting its capacity to 0 in the config, which
makes the model collapse gracefully to a smaller system (used heavily in tests).
"""

from __future__ import annotations
import pyomo.environ as pyo


def declare_sets_params(m: pyo.ConcreteModel, data: dict, cfg: dict, dt_hours: float):
    """Attach the time set and all parameters to the model."""
    m.T = pyo.Set(initialize=data["T"], ordered=True)
    m.dt = dt_hours  # plain attribute; used directly in rules

    # --- Time-series parameters (one value per time step) ---
    m.price_el = pyo.Param(m.T, initialize=dict(enumerate(data["price_el"])))
    m.price_exp = pyo.Param(m.T, initialize=dict(enumerate(data["price_exp"])))
    m.pv_avail = pyo.Param(m.T, initialize=dict(enumerate(data["pv_avail"])))
    m.dem_el = pyo.Param(m.T, initialize=dict(enumerate(data["dem_el"])))
    m.dem_heat = pyo.Param(m.T, initialize=dict(enumerate(data["dem_heat"])))

    # Heat-pump COP can be a single number (constant) or a per-step series.
    # data["cop"] is always supplied as a list (data_io expands a constant).
    m.cop = pyo.Param(m.T, initialize=dict(enumerate(data["cop"])))

    # --- Scalar parameters from config, stored as plain attributes ---
    # (Kept as attributes rather than Pyomo Params because they are fixed
    #  coefficients, not indexed data — simpler to read in the rules.)
    m.cfg = cfg
    m.price_gas = cfg["price_gas"]            # [currency/kWh of gas input]


def declare_variables(m: pyo.ConcreteModel):
    """Attach all decision variables. Continuous unless noted."""
    NN = pyo.NonNegativeReals

    # Grid
    m.p_import = pyo.Var(m.T, domain=NN)
    m.p_export = pyo.Var(m.T, domain=NN)

    # PV
    m.pv_used = pyo.Var(m.T, domain=NN)

    # Battery (electrical storage)
    m.p_ch = pyo.Var(m.T, domain=NN)
    m.p_dis = pyo.Var(m.T, domain=NN)
    m.soc = pyo.Var(m.T, domain=NN)

    # CHP: gas input, and the two coupled outputs
    m.chp_gas = pyo.Var(m.T, domain=NN)       # gas power in   [kW]
    m.chp_el = pyo.Var(m.T, domain=NN)        # electricity out[kW]
    m.chp_heat = pyo.Var(m.T, domain=NN)      # heat out       [kW]
    m.chp_on = pyo.Var(m.T, domain=pyo.Binary)  # on/off -> MILP

    # Heat pump: electricity in, heat out
    m.hp_el = pyo.Var(m.T, domain=NN)
    m.hp_heat = pyo.Var(m.T, domain=NN)

    # Heating rod: electricity in, heat out
    m.rod_el = pyo.Var(m.T, domain=NN)
    m.rod_heat = pyo.Var(m.T, domain=NN)

    # Heat storage
    m.h_ch = pyo.Var(m.T, domain=NN)
    m.h_dis = pyo.Var(m.T, domain=NN)
    m.h_soc = pyo.Var(m.T, domain=NN)
