"""Real representative-day selection from the Munich weather file."""
import os
import pytest
from engine.data import daytypes

MOS = os.path.join(os.path.dirname(__file__), "..", "data", "weather",
                   "DEU_Munich_108660_IWEC.mos")
pytestmark = pytest.mark.skipif(not os.path.exists(MOS), reason="weather file absent")


def test_each_daytype_returns_24_real_hours():
    for dt in daytypes.DAY_TYPES:
        d = daytypes.representative(MOS, dt)
        assert len(d["pv"]) == 24 and len(d["cop"]) == 24 and len(d["heat"]) == 24


def test_sunny_has_more_pv_than_cloudy():
    sunny = daytypes.representative(MOS, "sunny")
    cloudy = daytypes.representative(MOS, "cloudy")
    assert sum(sunny["pv"]) > sum(cloudy["pv"])


def test_cold_snap_has_low_cop_and_high_heat():
    cold = daytypes.representative(MOS, "cold_snap")
    hot = daytypes.representative(MOS, "hot")
    # Colder day: lower average COP, higher peak heat demand.
    assert sum(cold["cop"]) / 24 < sum(hot["cop"]) / 24
    assert max(cold["heat"]) > max(hot["heat"])


def test_by_date_returns_requested_day():
    d = daytypes.by_date(MOS, 7, 23)   # Jul 23
    assert d["day_index"] == daytypes._day_index_of_date(7, 23)
    assert len(d["temp_C"]) == 24
