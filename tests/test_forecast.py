"""Baseline forecasting methods (the clean 'prognosis' starter)."""
import pytest
from engine.forecast.baseline import persistence_forecast, typeday_average_forecast


def test_persistence_repeats_previous_day():
    # 48 hours: day 2 should be forecast as day 1's same-hour values.
    series = list(range(24)) + [v + 100 for v in range(24)]
    f = persistence_forecast(series, period=24)
    # Hours 24..47 forecast from hours 0..23.
    assert f[24:48] == list(range(24))


def test_persistence_falls_back_to_mean_at_start():
    series = [2.0, 4.0, 6.0, 8.0]
    f = persistence_forecast(series, period=24)  # period > len -> all mean
    assert f == pytest.approx([5.0, 5.0, 5.0, 5.0])  # mean = 5


def test_typeday_average_buckets_by_daytype_and_hour():
    # Two 'work' days and the forecast for a (work, hour) bucket is the mean.
    series = [10.0, 20.0, 12.0, 24.0]         # two days, 2 hours each
    hour = [0, 1, 0, 1]
    daytype = ["work", "work", "work", "work"]
    f = typeday_average_forecast(series, hour, daytype, period=2)
    # (work,0): mean(10,12)=11 ; (work,1): mean(20,24)=22
    assert f == pytest.approx([11.0, 22.0, 11.0, 22.0])
