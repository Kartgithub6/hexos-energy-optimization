"""Data feed: parsers, merge, gap finder and cross-check, all on sample
payloads in the shape the APIs return. Nothing here touches the network."""
import pandas as pd
import pytest

from engine.data import feed


def test_parse_energy_charts_and_hourly_mean():
    ts = [1759276800 + 900 * i for i in range(8)]          # 2025-10-01 00:00 UTC, 15 min
    s = feed.parse_energy_charts({"unix_seconds": ts, "price": [10, 20, 30, 40, 50, 50, 50, 50],
                                  "unit": "EUR / MWh"})
    h = feed.to_hourly(s)
    assert list(h.values) == [25.0, 50.0]
    assert str(h.index.tz) == "UTC"


def test_energy_charts_rejects_wrong_unit():
    with pytest.raises(ValueError):
        feed.parse_energy_charts({"unix_seconds": [0], "price": [1], "unit": "EUR / kWh"})


def test_parse_smard_skips_nulls():
    s = feed.parse_smard_series({"series": [[1735689600000, 50.0], [1735693200000, None],
                                            [1735696800000, 70.0]]})
    assert list(s.values) == [50.0, 70.0]
    assert feed.parse_smard_index({"timestamps": [3, 1, 2]}) == [1, 2, 3]


def test_parse_open_meteo():
    df = feed.parse_open_meteo({"hourly": {"time": ["2025-01-01T00:00", "2025-01-01T01:00"],
                                           "temperature_2m": [1.5, 1.0],
                                           "shortwave_radiation": [0, 0]}})
    assert list(df.columns) == ["temperature_2m", "shortwave_radiation"]
    assert len(df) == 2


def test_merge_new_values_win_and_keep_history():
    i = pd.date_range("2025-01-01", periods=4, freq="1h", tz="UTC")
    old = pd.DataFrame({"p": [1.0, 2.0, 3.0, 4.0]}, index=i)
    new = pd.DataFrame({"p": [30.0, 40.0, 50.0]}, index=i[2:].append(pd.DatetimeIndex(
        [i[-1] + pd.Timedelta("1h")])))
    m = feed.merge(old, new)
    assert list(m["p"]) == [1.0, 2.0, 30.0, 40.0, 50.0]


def test_gaps():
    i = pd.DatetimeIndex(pd.to_datetime(["2025-01-01 00:00", "2025-01-01 01:00",
                                         "2025-01-01 04:00", "2025-01-01 05:00"], utc=True))
    g = feed.gaps(i)
    assert len(g) == 1 and g[0][0].hour == 2 and g[0][1].hour == 3


def test_cross_check():
    i = pd.date_range("2025-01-01", periods=3, freq="1h", tz="UTC")
    c = feed.cross_check(pd.Series([1.0, 2.0, 3.0], index=i), pd.Series([1.0, 2.5, 3.0], index=i))
    assert c["overlap_h"] == 3 and abs(c["max_abs_diff"] - 0.5) < 1e-12
