"""Stochastic vs reproducible forecast noise."""
from engine.control.forecasters import noisy_factory
from engine import make_data


def _data(n=6):
    return make_data(list(range(n)), [0.2]*n, [0.05]*n,
                     [10.0]*n, [5.0]*n, [3.0]*n, cop=3.0)


def test_seeded_forecast_is_reproducible():
    data = _data()
    f1 = noisy_factory(seed=42)(data, 0, 6)
    f2 = noisy_factory(seed=42)(data, 0, 6)
    assert f1["pv_avail"] == f2["pv_avail"]


def test_unseeded_forecast_varies():
    data = _data()
    f1 = noisy_factory(seed=None)(data, 0, 6)
    f2 = noisy_factory(seed=None)(data, 0, 6)
    # Extremely unlikely to be identical across all hours when unseeded.
    assert f1["pv_avail"] != f2["pv_avail"]


def test_current_hour_stays_accurate():
    data = _data()
    f = noisy_factory(seed=1)(data, 0, 6)
    assert f["pv_avail"][0] == data["pv_avail"][0]   # hour 0 not perturbed
