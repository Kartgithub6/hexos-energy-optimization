"""
Tests for engine.market.bidding.

These check the PROPERTIES the bidding layer must have, not specific numbers:
curves must be monotone (a market rule), clearing must be a correct step
lookup, committing the unconstrained optimum must cost the unconstrained
optimum, and the projections must do what they claim.
"""
import math

import pytest

from engine.data.io import make_data
from engine.market import (build_bid_curve, build_scenario_bid_curves,
                           quantile_price_paths, bootstrap_price_paths,
                           clear_curve, clear_day, price_grid_from_quantiles,
                           net_position_at_price, cost_of_committed_position,
                           self_schedule_position, perfect_foresight_cost)
from engine.market.bidding import (_monotone_clamp, _isotonic_decreasing,
                                   _project_monotone)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def cfg():
    return {
        "price_gas": 0.07,
        "grid": {"import_max": 1200.0, "export_max": 1200.0},
        "battery": {"E_cap": 400.0, "p_ch_max": 200.0, "p_dis_max": 200.0,
                    "eta_ch": 0.96, "eta_dis": 0.96, "self_disch": 0.0005,
                    "soc_init": 0.0},
        "chp": {"p_el_max": 200.0, "eta_el": 0.4, "htp_ratio": 1.5,
                "min_load": 0.4},
        "heatpump": {"q_max": 400.0},
        "rod": {"q_max": 300.0, "eta": 0.99},
        "heat_storage": {"E_cap": 1500.0, "p_ch_max": 400.0, "p_dis_max": 400.0,
                         "eta_ch": 0.98, "eta_dis": 0.98, "self_disch": 0.002,
                         "soc_init": 0.0},
    }


@pytest.fixture
def day():
    """A deterministic 24 h day: sinusoidal prices, PV, demand and heat."""
    n = 24
    T = list(range(n))
    price = [max(0.005, (45 + 30 * math.sin((t - 8) / 24 * 2 * math.pi)) / 1000)
             for t in T]
    pexp = [p * 0.88 for p in price]
    pv = [max(0.0, 130 * math.sin((t - 6) / 12 * math.pi)) if 6 <= t <= 18
          else 0.0 for t in T]
    dem = [150 + 40 * math.sin((t - 7) / 24 * 2 * math.pi) for t in T]
    heat = [220 + 70 * math.cos(t / 24 * 2 * math.pi) for t in T]
    return make_data(T, price, pexp, pv, dem, heat, [3.2] * n)


# ---------------------------------------------------------------------------
# Price grids
# ---------------------------------------------------------------------------
def test_price_grid_spans_band_and_includes_median():
    g = price_grid_from_quantiles(0.02, 0.045, 0.07, n_points=5)
    assert g == sorted(g)
    assert min(g) <= 0.02 + 1e-9 and max(g) >= 0.07 - 1e-9
    assert any(abs(x - 0.045) < 1e-9 for x in g)


def test_price_grid_widen_extends_the_band():
    narrow = price_grid_from_quantiles(0.02, 0.045, 0.07, n_points=5)
    wide = price_grid_from_quantiles(0.02, 0.045, 0.07, n_points=5, widen=0.5)
    assert min(wide) < min(narrow) and max(wide) > max(narrow)


def test_price_grid_handles_degenerate_band():
    """A flat forecast must still produce a usable grid, not a single point."""
    g = price_grid_from_quantiles(0.05, 0.05, 0.05, n_points=5)
    assert len(set(g)) > 1


def test_price_grid_rejects_too_few_points():
    with pytest.raises(ValueError):
        price_grid_from_quantiles(0.02, 0.045, 0.07, n_points=1)


# ---------------------------------------------------------------------------
# Monotone projections
# ---------------------------------------------------------------------------
def test_clamp_forces_non_increasing():
    pts = [(1.0, 100.0), (2.0, 120.0), (3.0, 80.0)]
    out, repairs = _monotone_clamp(pts)
    assert repairs == 1
    assert [q for _, q in out] == [100.0, 100.0, 80.0]


def test_clamp_leaves_valid_curve_untouched():
    pts = [(1.0, 100.0), (2.0, 80.0), (3.0, 50.0)]
    out, repairs = _monotone_clamp(pts)
    assert repairs == 0 and out == pts


def test_isotonic_is_non_increasing_and_preserves_mean():
    pts = [(1.0, 50.0), (2.0, 150.0), (3.0, 40.0)]
    out, pooled = _isotonic_decreasing(pts)
    qs = [q for _, q in out]
    assert all(qs[i] >= qs[i + 1] - 1e-9 for i in range(len(qs) - 1))
    assert pooled > 0
    # PAVA only averages within pooled blocks, so the total is preserved
    assert abs(sum(qs) - sum(q for _, q in pts)) < 1e-6


def test_isotonic_is_gentler_than_clamp():
    """The whole reason isotonic exists: the clamp drags everything down to the
    running minimum, isotonic only averages the violating run."""
    pts = [(1.0, 10.0), (2.0, 100.0), (3.0, 90.0)]
    iso, _ = _isotonic_decreasing(pts)
    clamp, _ = _monotone_clamp(pts)
    assert sum(q for _, q in iso) > sum(q for _, q in clamp)


def test_project_monotone_none_is_identity():
    pts = [(1.0, 50.0), (2.0, 150.0)]
    out, n = _project_monotone(pts, None)
    assert out == pts and n == 0


def test_project_monotone_rejects_unknown_method():
    with pytest.raises(ValueError):
        _project_monotone([(1.0, 1.0)], "nonsense")


# ---------------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------------
def _curve(points):
    return {"hour": 0, "points": points, "monotonicity_repairs": 0,
            "raw_points": points}


def test_clear_takes_step_at_or_below_price():
    c = _curve([(10.0, 300.0), (20.0, 200.0), (30.0, 100.0)])
    assert clear_curve(c, 25.0) == 200.0
    assert clear_curve(c, 20.0) == 200.0     # exactly on a step
    assert clear_curve(c, 19.9) == 300.0


def test_clear_clamps_outside_the_grid():
    c = _curve([(10.0, 300.0), (20.0, 200.0)])
    assert clear_curve(c, 1.0) == 300.0      # below the grid
    assert clear_curve(c, 999.0) == 200.0    # above the grid


def test_clear_empty_curve_raises():
    with pytest.raises(ValueError):
        clear_curve(_curve([]), 10.0)


def test_clear_day_covers_every_hour():
    curves = {h: _curve([(10.0, 100.0), (20.0, 50.0)]) for h in range(3)}
    acc = clear_day(curves, [5.0, 15.0, 25.0])
    assert acc == {0: 100.0, 1: 100.0, 2: 50.0}


# ---------------------------------------------------------------------------
# Parametric response
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_higher_price_never_increases_net_position(day, cfg):
    """The core economic property. A cost minimiser cannot want strictly more
    energy at a strictly higher price when nothing else changes."""
    lo = net_position_at_price(day, cfg, hour=14, price=0.01)
    hi = net_position_at_price(day, cfg, hour=14, price=0.30)
    assert hi <= lo + 1e-6


@pytest.mark.slow
def test_bid_curve_is_monotone_after_projection(day, cfg):
    grid = price_grid_from_quantiles(0.01, 0.05, 0.12, n_points=5)
    c = build_bid_curve(day, cfg, hour=12, price_grid=grid)
    qs = [q for _, q in c["points"]]
    assert all(qs[i] >= qs[i + 1] - 1e-6 for i in range(len(qs) - 1))
    assert len(c["raw_points"]) == len(grid)


@pytest.mark.slow
def test_scenario_curves_cover_all_hours_and_are_monotone(day, cfg):
    qh = [(p * 0.6, p, p * 1.6) for p in day["price_el"]]
    curves = build_scenario_bid_curves(day, cfg, quantile_price_paths(qh))
    assert set(curves) == set(day["T"])
    for c in curves.values():
        qs = [q for _, q in c["points"]]
        assert all(qs[i] >= qs[i + 1] - 1e-6 for i in range(len(qs) - 1))


# ---------------------------------------------------------------------------
# Path generators
# ---------------------------------------------------------------------------
def test_quantile_paths_are_ordered_and_non_negative():
    qh = [(0.02, 0.05, 0.09)] * 24
    paths = quantile_price_paths(qh, levels=(0.1, 0.5, 0.9))
    assert len(paths) == 3
    assert all(len(p) == 24 for p in paths)
    assert all(v >= 0 for p in paths for v in p)
    # higher level => higher price, hour by hour
    assert paths[0][0] < paths[1][0] < paths[2][0]


def test_bootstrap_paths_include_p50_and_are_reproducible():
    p50 = [0.05] * 24
    blocks = [[0.01] * 24, [-0.02] * 24, [0.0] * 24]
    a = bootstrap_price_paths(p50, blocks, n_paths=5, seed=3)
    b = bootstrap_price_paths(p50, blocks, n_paths=5, seed=3)
    assert a == b
    assert len(a) == 5
    assert a[0] == p50                       # first path is the point forecast


def test_bootstrap_paths_never_go_negative():
    p50 = [0.01] * 24
    blocks = [[-5.0] * 24]
    paths = bootstrap_price_paths(p50, blocks, n_paths=3, seed=0)
    assert all(v >= 0.0 for p in paths for v in p)


def test_bootstrap_with_no_blocks_returns_just_the_point_forecast():
    p50 = [0.05] * 24
    assert bootstrap_price_paths(p50, [], n_paths=5) == [p50]


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_committing_the_optimum_reproduces_the_optimum(day, cfg):
    """Sanity anchor: if you commit exactly what perfect foresight would have
    done, the commitment costs the same and deviates by nothing."""
    opt = perfect_foresight_cost(day, cfg)
    pos = self_schedule_position(day, cfg)      # same data => same solve
    r = cost_of_committed_position(day, cfg, pos, deviation_penalty=1.0)
    assert r["deviation_kwh"] < 1e-4
    assert abs(r["cost"] - opt) < 1e-4


@pytest.mark.slow
def test_committed_position_is_honoured(day, cfg):
    """The re-dispatch must actually deliver the committed net position, up to
    the reported deviation."""
    pos = {h: 100.0 for h in day["T"]}
    r = cost_of_committed_position(day, cfg, pos, deviation_penalty=5.0)
    res = r["results"]
    err = sum(abs((res["import"][i] - res["export"][i]) - 100.0)
              for i in range(len(day["T"])))
    assert abs(err - r["deviation_kwh"]) < 1e-3


@pytest.mark.slow
def test_no_strategy_beats_perfect_foresight(day, cfg):
    """The yardstick must actually be a bound."""
    opt = perfect_foresight_cost(day, cfg)
    qh = [(p * 0.6, p, p * 1.6) for p in day["price_el"]]
    curves = build_scenario_bid_curves(day, cfg, quantile_price_paths(qh))
    acc = clear_day(curves, day["price_el"])
    r = cost_of_committed_position(day, cfg, acc, deviation_penalty=1.0)
    assert r["cost"] >= opt - 1e-4
