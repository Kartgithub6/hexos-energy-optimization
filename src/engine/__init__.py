"""
HEXOS — Heat-Electricity eXchange Optimization System.

Convenience re-exports so common entry points are available as:
    from engine import build_model, solve, extract_results, solve_rolling, load_timeseries
"""
from engine.data.io import load_timeseries, make_data
from engine.model.build import build_model
from engine.solve.single import solve
from engine.solve.rolling import solve_rolling
from engine.postprocess.extract import extract_results

__all__ = ["load_timeseries", "make_data", "build_model", "solve",
           "solve_rolling", "extract_results"]
