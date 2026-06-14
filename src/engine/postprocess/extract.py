"""hexos.postprocess.extract — pull solved values into plain lists/dicts."""
import pyomo.environ as pyo


def extract_results(m):
    T = list(m.T)
    g = lambda v: [pyo.value(v[t]) for t in T]
    def csum(var):
        return [sum(pyo.value(var[c, t]) for c in m.CHP) for t in T]
    def evsum(var):
        return [sum(pyo.value(var[e, t]) for e in m.EV) for t in T]
    res = {
        "t": T,
        "import": g(m.p_import), "export": g(m.p_export), "pv_used": g(m.pv_used),
        "charge": g(m.p_ch), "discharge": g(m.p_dis), "soc": g(m.soc),
        "chp_gas": csum(m.chp_gas), "chp_el": csum(m.chp_el),
        "chp_heat": csum(m.chp_heat), "chp_on": csum(m.chp_on),
        "wood_fuel": g(m.wood_fuel), "wood_heat": g(m.wood_heat),
        "gas_fuel": g(m.gas_fuel), "gas_heat": g(m.gas_heat),
        "hp_el": g(m.hp_el), "hp_heat": g(m.hp_heat),
        "rod_el": g(m.rod_el), "rod_heat": g(m.rod_heat),
        "h_charge": g(m.h_ch), "h_discharge": g(m.h_dis), "h_soc": g(m.h_soc),
        "h_curtail": g(m.h_curtail),
        "ev_p": evsum(m.ev_p),
        "peak_import": pyo.value(m.peak_import),
        "cost": pyo.value(m.cost),
    }
    res["chp_units"] = {
        c: {"el": [pyo.value(m.chp_el[c, t]) for t in T],
            "heat": [pyo.value(m.chp_heat[c, t]) for t in T],
            "on": [pyo.value(m.chp_on[c, t]) for t in T]}
        for c in m.CHP
    }
    res["ev_units"] = {e: [pyo.value(m.ev_p[e, t]) for t in T] for e in m.EV}
    return res
