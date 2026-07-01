"""
engine.forecast.baseline
=======================
Starter forecasting methods (the "prognosis" idea, built clean from standard
techniques). These produce a forecast series the optimizer can use INSTEAD of
perfect-foresight actuals, so the model can be run as it would operate in
practice: deciding on predictions, not on the true future.

Implemented:
  - persistence_forecast: tomorrow looks like the most recent same-hour values
  - typeday_average_forecast: average profile per (weekday-type, hour)

These are deliberately simple baselines. More advanced methods (regression,
gradient boosting, neural nets) follow the same interface and can be added as
separate modules, each exposing fit()/predict().
"""
from __future__ import annotations


def persistence_forecast(series, period=24):
    """Forecast each step as the value `period` steps earlier (yesterday's same
    hour). The first `period` steps fall back to the series mean.
    """
    n = len(series)
    mean = sum(series) / n if n else 0.0
    out = []
    for i in range(n):
        out.append(series[i - period] if i >= period else mean)
    return out


def typeday_average_forecast(series, hour_of_day, daytype, period=24):
    """Average profile per (daytype, hour-of-day). `hour_of_day[i]` in 0..23 and
    `daytype[i]` a hashable label (e.g. 'work', 'half', 'free'). Returns, for each
    step, the historical mean for its (daytype, hour) bucket.
    """
    from collections import defaultdict
    sums = defaultdict(float)
    counts = defaultdict(int)
    for v, h, d in zip(series, hour_of_day, daytype):
        sums[(d, h)] += v
        counts[(d, h)] += 1
    out = []
    overall = sum(series) / len(series) if series else 0.0
    for h, d in zip(hour_of_day, daytype):
        key = (d, h)
        out.append(sums[key] / counts[key] if counts[key] else overall)
    return out
