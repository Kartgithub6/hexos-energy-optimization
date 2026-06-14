"""
cop_variants.py
===============
Build the heat-pump COP series for the three-way fidelity comparison from a
single base dataset that already carries the real temperature-dependent COP.

The three cases:
  - "temp_dependent" : the real hourly COP series (ground-truth reference).
  - "mean_constant"  : a single COP equal to the annual mean of the real series.
                       Same average, but the hourly *shape* is removed -- isolates
                       the effect of ignoring time-variation.
  - "nameplate"      : a single fixed manufacturer-rated COP (default 3.0).
                       A different *level* -- isolates the effect of getting the
                       absolute value wrong, as a planner using a datasheet might.

Each variant returns a *copy* of the data dict with only the 'cop' field
replaced; every other series (price, demand, PV, load) is identical, so any
difference in the optimized result is attributable solely to the COP assumption.
"""

from __future__ import annotations
import copy


def make_cop_variants(data: dict, nameplate_cop: float = 3.0) -> dict:
    """Return {case_name: data_dict} for the three COP fidelity cases."""
    real = data["cop"]
    n = len(real)
    mean_cop = sum(real) / n

    def with_cop(series):
        d = copy.deepcopy(data)
        d["cop"] = series
        return d

    return {
        "temp_dependent": with_cop(list(real)),
        "mean_constant": with_cop([mean_cop] * n),
        "nameplate": with_cop([nameplate_cop] * n),
        # expose the scalar values used, for reporting
        "_mean_cop": mean_cop,
        "_nameplate_cop": nameplate_cop,
    }
