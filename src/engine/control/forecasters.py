"""
engine.control.forecasters
==========================
Forecasters for the MPC loop. Each takes (data, k, horizon) and returns the
forecast window the controller will optimise against. Reality (the true data)
is used separately by the simulator.

  perfect            : forecast == truth (recovers perfect foresight)
  noisy_factory      : multiplicative noise on PV/demand to emulate forecast
                       error; deterministic given a seed so runs are repeatable
  persistence_factory: "tomorrow == today" style, using a lag
"""

from __future__ import annotations
import random

from engine.control.mpc import _window, perfect_forecaster

perfect = perfect_forecaster


def noisy_factory(pv_sigma=0.15, dem_sigma=0.10, seed=0):
    """Forecaster that perturbs PV and demand by lognormal-ish multiplicative
    noise. The current hour (index 0) is kept accurate (you know 'now'); error
    grows mildly with how far ahead the hour is.
    """
    rng = random.Random(seed)

    def fc(data, k, h):
        w = _window(data, k, h)
        w = {kk: (list(v) if isinstance(v, list) else v) for kk, v in w.items()}
        for i in range(1, len(w["T"])):       # hour 0 stays accurate
            fade = min(1.0, i / 12.0)          # error grows over ~12 h
            w["pv_avail"][i] = max(0.0, w["pv_avail"][i] * (1 + rng.gauss(0, pv_sigma) * fade))
            w["dem_el"][i] = max(0.0, w["dem_el"][i] * (1 + rng.gauss(0, dem_sigma) * fade))
            w["dem_heat"][i] = max(0.0, w["dem_heat"][i] * (1 + rng.gauss(0, dem_sigma) * fade))
        return w
    return fc
