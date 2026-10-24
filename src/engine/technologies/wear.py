"""
engine.technologies.wear
========================
Battery wear (degradation) as a cost inside the optimiser.

Without this, the optimiser treats every kWh pushed through the battery as
free, so it cycles whenever a price spread covers the round-trip losses. Real
cells lose capacity with every cycle, and how much depends on how DEEP the
cycle is. This module puts that loss into the objective so dispatch only cycles
when the spread pays for the wear too.

Two models, switched on with `cfg["battery"]["wear"]` (off by default, so
every existing config and result is unchanged):

  "throughput"   every kWh charged or discharged costs the same:
                     c_thr = capex / (2 * cycle_life_efc)     [EUR per kWh AC]
                 One equivalent full cycle (E charged + E discharged) then costs
                 capex * E / cycle_life_efc, i.e. one cycle's share of the cells.
                 Linear, simple, blind to cycle depth.

  "cycle_depth"  the piecewise-linear cycle-depth model of Xu, Oudalov,
                 Ulbig, Andersson & Kirschen (2018), "Modeling of lithium-ion
                 battery degradation for cell life assessment", IEEE Trans.
                 Smart Grid 9(2), and its market version (Xu et al. 2018,
                 IEEE Trans. Power Systems 33(2)). Life lost by one cycle of
                 depth d (0..1) is
                     Phi(d) = d ** b / cycle_life_efc
                 With b > 1 a deep cycle hurts more than two half-depth cycles.
                 The battery's energy is split into J equal segments, segment 1
                 the shallowest. Energy discharged from segment j costs
                     c_j = capex * J * (Phi(j/J) - Phi((j-1)/J)) / eta_dis
                 per kWh AC. The costs rise with j, so the LP uses shallow
                 segments first without any binaries. Still a pure LP.

Parameters inside cfg["battery"]["wear"]:
  model               "throughput" or "cycle_depth"
  capex_eur_per_kwh   value of the cells being worn out [EUR/kWh of capacity]
  cycle_life_efc      equivalent full cycles to end of life (at 100 % depth)
  dod_exponent        b in Phi(d); cycle_depth only (default 1.5)
  segments            J; cycle_depth only (default 5)

HEXOS works in kW / kWh / EUR per kWh, so capex is in EUR per kWh as well.

Limits, stated plainly:
  * The parameters are ILLUSTRATIVE, not fitted to a cell. Fitting Phi(d) to a
    specific chemistry and cell is exactly the job of a degradation model; this
    module is the hook where such a model plugs into dispatch.
  * Calendar ageing is not priced here (it barely depends on dispatch in this
    simple form). engine.postprocess.wear reports it separately.
  * In a rolling-horizon solve the window's starting energy is spread over the
    segments shallowest-first, which is optimistic for the first hours of each
    window.
"""
from __future__ import annotations

import pyomo.environ as pyo


def wear_cfg(b: dict) -> dict | None:
    """Return a completed wear config, or None when wear is off."""
    w = b.get("wear")
    if not w:
        return None
    w = dict(w)
    model = w.get("model", "throughput")
    if model not in ("throughput", "cycle_depth"):
        raise ValueError(f"battery.wear.model must be 'throughput' or 'cycle_depth', got {model!r}")
    for k in ("capex_eur_per_kwh", "cycle_life_efc"):
        if k not in w:
            raise ValueError(f"battery.wear needs '{k}'")
        if w[k] <= 0:
            raise ValueError(f"battery.wear.{k} must be > 0")
    w["model"] = model
    w.setdefault("dod_exponent", 1.5)
    w.setdefault("segments", 5)
    if int(w["segments"]) < 1:
        raise ValueError("battery.wear.segments must be >= 1")
    return w


def throughput_cost(w: dict) -> float:
    """EUR per kWh AC charged or discharged."""
    return w["capex_eur_per_kwh"] / (2.0 * w["cycle_life_efc"])


def phi(depth: float, w: dict) -> float:
    """Fraction of cycle life used by one full cycle of the given depth (0..1)."""
    return (max(0.0, min(1.0, depth)) ** w["dod_exponent"]) / w["cycle_life_efc"]


def segment_costs(w: dict, eta_dis: float) -> list[float]:
    """Marginal wear cost of discharging each segment, EUR per kWh AC."""
    J = int(w["segments"])
    R = w["capex_eur_per_kwh"]
    return [R * J * (phi(j / J, w) - phi((j - 1) / J, w)) / eta_dis for j in range(1, J + 1)]


def initial_split(soc_init: float, E_cap: float, J: int) -> list[float]:
    """Spread the starting energy over the segments, shallowest first."""
    size = E_cap / J
    out, left = [], soc_init
    for _ in range(J):
        e = min(max(left, 0.0), size)
        out.append(e)
        left -= e
    return out


def add_wear(m, b: dict):
    """Attach wear variables/constraints and store the wear cost expression on
    the model as m.wear_cost (picked up by the objective). No-op when off."""
    w = wear_cfg(b)
    m.wear_cost_terms = None
    if w is None:
        return
    m.wear_par = w

    if w["model"] == "throughput":
        c = throughput_cost(w)
        m.wear_cost_terms = lambda m: sum(c * (m.p_ch[t] + m.p_dis[t]) * m.dt for t in m.T)
        return

    # cycle-depth: J parallel energy segments that together are the battery
    J = int(w["segments"])
    E = b["E_cap"]
    m.SEG = pyo.RangeSet(1, J)
    NN = pyo.NonNegativeReals
    m.seg_e = pyo.Var(m.SEG, m.T, domain=NN)
    m.seg_ch = pyo.Var(m.SEG, m.T, domain=NN)
    m.seg_dis = pyo.Var(m.SEG, m.T, domain=NN)
    e0 = initial_split(b.get("soc_init", 0.0), E, J)

    def seg_dyn(m, j, t):
        prev = e0[j - 1] if t == m.T.first() else m.seg_e[j, t - 1]
        return (m.seg_e[j, t] == (1 - b["self_disch"]) * prev
                + b["eta_ch"] * m.seg_ch[j, t] * m.dt - (m.seg_dis[j, t] / b["eta_dis"]) * m.dt)
    m.seg_dynamics = pyo.Constraint(m.SEG, m.T, rule=seg_dyn)
    m.seg_cap = pyo.Constraint(m.SEG, m.T, rule=lambda m, j, t: m.seg_e[j, t] <= E / J)
    m.seg_ch_sum = pyo.Constraint(m.T, rule=lambda m, t: m.p_ch[t] == sum(m.seg_ch[j, t] for j in m.SEG))
    m.seg_dis_sum = pyo.Constraint(m.T, rule=lambda m, t: m.p_dis[t] == sum(m.seg_dis[j, t] for j in m.SEG))
    m.seg_soc_sum = pyo.Constraint(m.T, rule=lambda m, t: m.soc[t] == sum(m.seg_e[j, t] for j in m.SEG))

    costs = segment_costs(w, b["eta_dis"])
    m.wear_seg_cost = costs
    m.wear_cost_terms = lambda m: sum(costs[j - 1] * m.seg_dis[j, t] * m.dt
                                      for j in m.SEG for t in m.T)
