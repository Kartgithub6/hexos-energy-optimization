"""
engine.market — day-ahead market participation for the HEXOS site.

Everything in this package sits ON TOP of the dispatch optimiser. The MILP
itself is unchanged: it still minimises operating cost. What this package adds
is the step from "price taker" to "price responder" -- deriving what the site
would *want* to do at each candidate price, expressing that as a bid curve, and
settling it against the realised day-ahead price.

This is demand-side bidding, not speculative trading: the site holds no
position it does not physically intend to deliver, and takes no view on price
direction beyond its own forecast.
"""
from engine.market.bidding import (
    build_bid_curve,
    build_day_bid_curves,
    build_scenario_bid_curves,
    quantile_price_paths,
    bootstrap_price_paths,
    clear_curve,
    clear_day,
    price_grid_from_quantiles,
    net_position_at_price,
    cost_of_committed_position,
    self_schedule_position,
    perfect_foresight_cost,
)

__all__ = [
    "build_bid_curve",
    "build_day_bid_curves",
    "build_scenario_bid_curves",
    "quantile_price_paths",
    "bootstrap_price_paths",
    "clear_curve",
    "clear_day",
    "price_grid_from_quantiles",
    "net_position_at_price",
    "cost_of_committed_position",
    "self_schedule_position",
    "perfect_foresight_cost",
]
