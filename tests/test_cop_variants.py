"""
test_cop_variants.py
====================
Validate the COP-variant builder used by the fidelity comparison. The whole
comparison is only meaningful if each variant changes ONLY the COP series and
nothing else, so that is exactly what we test.
"""
import pytest
from engine import make_data, build_model, solve, extract_results, solve_rolling
from engine.postprocess.cop_variants import make_cop_variants
from helpers import TOL


def _base():
    return make_data(
        list(range(5)),
        [0.20] * 5, [0.05] * 5, [0] * 5, [3] * 5, [4] * 5,
        cop=[2.0, 3.0, 4.0, 5.0, 6.0],   # mean = 4.0
    )


def test_mean_constant_uses_the_real_average():
    v = make_cop_variants(_base())
    assert v["_mean_cop"] == pytest.approx(4.0, abs=TOL)
    assert v["mean_constant"]["cop"] == pytest.approx([4.0] * 5, abs=TOL)


def test_nameplate_is_the_fixed_value():
    v = make_cop_variants(_base(), nameplate_cop=3.0)
    assert v["nameplate"]["cop"] == pytest.approx([3.0] * 5, abs=TOL)


def test_temp_dependent_preserves_real_series():
    v = make_cop_variants(_base())
    assert v["temp_dependent"]["cop"] == pytest.approx([2.0, 3.0, 4.0, 5.0, 6.0], abs=TOL)


def test_only_cop_changes_everything_else_identical():
    base = _base()
    v = make_cop_variants(base)
    for case in ("temp_dependent", "mean_constant", "nameplate"):
        d = v[case]
        for key in ("T", "price_el", "price_exp", "pv_avail", "dem_el", "dem_heat"):
            assert d[key] == base[key], f"{case} altered {key}"


def test_variants_are_independent_copies():
    # Mutating one variant must not affect another or the base.
    base = _base()
    v = make_cop_variants(base)
    v["mean_constant"]["dem_heat"][0] = 999
    assert base["dem_heat"][0] == 4
    assert v["temp_dependent"]["dem_heat"][0] == 4
