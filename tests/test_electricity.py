"""
test_electricity.py
===================
Validation of the electricity side of the model: grid, PV, and battery. Every
case has an answer that can be worked out on paper.
"""

import pytest
import data_io as D
import build_model as B
from helpers import base_cfg, with_battery, mixed_system, TOL


def test_import_equals_demand_when_no_supply():
    # No PV, no battery -> the only way to meet demand is to import it.
    data = D.make_data([0, 1, 2], [0.30] * 3, [0.05] * 3, [0] * 3, [4, 6, 2], [0] * 3, cop=3.0)
    m = B.build_model(data, base_cfg()); B.solve(m); r = B.extract_results(m)
    assert r["import"] == pytest.approx([4, 6, 2], abs=TOL)
    assert r["cost"] == pytest.approx(3.60, abs=TOL)   # 0.30 * 12


def test_pv_exactly_covers_demand():
    # PV equals demand every hour -> zero import, zero export, zero cost.
    data = D.make_data([0, 1, 2], [0.30] * 3, [0.05] * 3, [5] * 3, [5] * 3, [0] * 3, cop=3.0)
    m = B.build_model(data, base_cfg()); B.solve(m); r = B.extract_results(m)
    assert r["import"] == pytest.approx([0, 0, 0], abs=TOL)
    assert r["export"] == pytest.approx([0, 0, 0], abs=TOL)
    assert r["cost"] == pytest.approx(0.0, abs=TOL)


def test_battery_arbitrages_price_spread():
    # Cheap hour then expensive hour: a rational battery charges cheap and
    # discharges expensive, beating the no-battery baseline of 1.20.
    data = D.make_data([0, 1], [0.10, 0.50], [0, 0], [0, 0], [2, 2], [0, 0], cop=3.0)
    m = B.build_model(data, with_battery(base_cfg(), 5.0, 5.0)); B.solve(m); r = B.extract_results(m)
    assert r["charge"][0] > TOL
    assert r["discharge"][1] > TOL
    assert r["cost"] < 1.20 - TOL


def test_electricity_balance_invariant():
    # Sources == sinks on the electricity bus, every hour, for any solution.
    data, r = mixed_system()
    for i, t in enumerate(r["t"]):
        src = r["import"][i] + r["pv_used"][i] + r["discharge"][i] + r["chp_el"][i]
        snk = (data["dem_el"][i] + r["export"][i] + r["charge"][i]
               + r["hp_el"][i] + r["rod_el"][i])
        assert src == pytest.approx(snk, abs=1e-4), f"electricity balance broke at t={t}"
