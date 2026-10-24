"""
engine.data.feed
================
A self-updating store of the open data HEXOS runs on, refreshed daily by a
GitHub Action (.github/workflows/data_feed.yml).

Sources (all free, no token, CC BY 4.0):

  Energy-Charts (Fraunhofer ISE)  DE-LU day-ahead price
      https://api.energy-charts.info/price?bzn=DE-LU&start=YYYY-MM-DD&end=YYYY-MM-DD
  SMARD (Bundesnetzagentur)        DE-LU day-ahead price, used as a second
                                   source to cross-check Energy-Charts
      https://www.smard.de/app/chart_data/4169/DE-LU/index_<res>.json
      https://www.smard.de/app/chart_data/4169/DE-LU/4169_DE-LU_<res>_<ms>.json
  Open-Meteo                       Munich temperature and solar radiation
      https://archive-api.open-meteo.com/v1/archive   (history)
      https://api.open-meteo.com/v1/forecast          (today + tomorrow)

The day-ahead auction moved to 15-minute products on 1 Oct 2025. The store
keeps whatever resolution the source returns in a `_15min` file and an hourly
mean in the main file, because the HEXOS year files are hourly.

Every fetch is split from its parser so the parsers are unit-tested on stored
sample payloads; nothing in the tests touches the network. A failed fetch
raises; nothing is ever filled in or invented.

CLI:
    python -m engine.data.feed                 # update from the last stored day
    python -m engine.data.feed --since 2025-01-01
    python -m engine.data.feed --check         # print gaps and the EC-vs-SMARD diff
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
STORE = os.path.join(ROOT, "data", "feed")
EC_URL = "https://api.energy-charts.info/price"
SMARD_URL = "https://www.smard.de/app/chart_data"
SMARD_PRICE_FILTER = 4169
OM_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OM_FORECAST = "https://api.open-meteo.com/v1/forecast"
MUNICH = (48.137, 11.575)
UA = {"User-Agent": "HEXOS-data-feed (github.com/Kartgithub6/hexos-energy-optimization)"}


def _get_json(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ------------------------------------------------------------- Energy-Charts
def parse_energy_charts(payload) -> pd.Series:
    if "unix_seconds" not in payload or "price" not in payload:
        raise ValueError(f"unexpected Energy-Charts payload, keys {list(payload)}")
    unit = str(payload.get("unit", "EUR / MWh"))
    if "MWh" not in unit:
        raise ValueError(f"unexpected Energy-Charts unit {unit!r}")
    idx = pd.to_datetime(payload["unix_seconds"], unit="s", utc=True)
    s = pd.Series(payload["price"], index=idx, name="price_eur_mwh", dtype="float64")
    return s[~s.index.duplicated()].dropna().sort_index()


def fetch_energy_charts(start: date, end: date, bzn="DE-LU") -> pd.Series:
    q = urllib.parse.urlencode({"bzn": bzn, "start": start.isoformat(), "end": end.isoformat()})
    return parse_energy_charts(_get_json(f"{EC_URL}?{q}"))


# --------------------------------------------------------------------- SMARD
def parse_smard_index(payload) -> list[int]:
    return sorted(int(t) for t in payload["timestamps"])


def parse_smard_series(payload) -> pd.Series:
    rows = [(t, v) for t, v in payload["series"] if v is not None]
    if not rows:
        return pd.Series(dtype="float64", name="price_eur_mwh")
    idx = pd.to_datetime([t for t, _ in rows], unit="ms", utc=True)
    return pd.Series([v for _, v in rows], index=idx, name="price_eur_mwh",
                     dtype="float64").sort_index()


def fetch_smard(start: date, end: date, region="DE-LU", resolution="quarterhour") -> pd.Series:
    """SMARD serves one-week chunks; fetch every chunk that overlaps [start, end]."""
    base = f"{SMARD_URL}/{SMARD_PRICE_FILTER}/{region}"
    chunks = parse_smard_index(_get_json(f"{base}/index_{resolution}.json"))
    t0 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp() * 1000)
    t1 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp() * 1000) + 86_400_000
    week = 7 * 86_400_000
    parts = []
    for c in chunks:
        if c + week < t0 or c > t1:
            continue
        url = f"{base}/{SMARD_PRICE_FILTER}_{region}_{resolution}_{c}.json"
        parts.append(parse_smard_series(_get_json(url)))
    if not parts:
        return pd.Series(dtype="float64", name="price_eur_mwh")
    s = pd.concat(parts)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s[(s.index >= pd.Timestamp(t0, unit="ms", tz="UTC")) &
             (s.index < pd.Timestamp(t1, unit="ms", tz="UTC"))]


# ---------------------------------------------------------------- Open-Meteo
OM_VARS = ("temperature_2m", "shortwave_radiation")


def parse_open_meteo(payload) -> pd.DataFrame:
    h = payload["hourly"]
    idx = pd.to_datetime(h["time"], utc=True)
    return pd.DataFrame({v: h[v] for v in OM_VARS}, index=idx).dropna(how="all")


def fetch_open_meteo(start: date, end: date, lat=MUNICH[0], lon=MUNICH[1]) -> pd.DataFrame:
    common = {"latitude": lat, "longitude": lon, "hourly": ",".join(OM_VARS), "timezone": "UTC"}
    recent = date.today() - timedelta(days=5)
    frames = []
    if start <= recent:      # the archive lags by a few days
        q = dict(common, start_date=start.isoformat(), end_date=min(end, recent).isoformat())
        frames.append(parse_open_meteo(_get_json(f"{OM_ARCHIVE}?{urllib.parse.urlencode(q)}")))
    if end > recent:
        q = dict(common, past_days=7, forecast_days=2)
        frames.append(parse_open_meteo(_get_json(f"{OM_FORECAST}?{urllib.parse.urlencode(q)}")))
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df[(df.index.date >= start) & (df.index.date <= end)]


# --------------------------------------------------------------------- store
def to_hourly(s: pd.Series) -> pd.Series:
    """Hourly mean; a 15-minute day becomes 24 values, an hourly day is unchanged."""
    return s.resample("1h").mean().dropna()


def merge(old: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """New values win where both exist (sources revise recent days)."""
    if old is None or old.empty:
        out = new
    else:
        out = new.combine_first(old)
    out = out[~out.index.duplicated(keep="first")].sort_index()
    return out


def read_store(name: str) -> pd.DataFrame | None:
    p = os.path.join(STORE, f"{name}.csv")
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, index_col=0, parse_dates=True)


def write_store(name: str, df: pd.DataFrame):
    os.makedirs(STORE, exist_ok=True)
    df.index.name = "utc"
    df.to_csv(os.path.join(STORE, f"{name}.csv"), float_format="%.4f")


def gaps(index: pd.DatetimeIndex, freq="1h") -> list[tuple]:
    """(first missing, last missing) pairs inside the stored span."""
    if len(index) < 2:
        return []
    full = pd.date_range(index.min(), index.max(), freq=freq)
    missing = full.difference(index)
    if missing.empty:
        return []
    out, run = [], [missing[0], missing[0]]
    step = pd.Timedelta(freq)
    for t in missing[1:]:
        if t - run[1] == step:
            run[1] = t
        else:
            out.append(tuple(run)); run = [t, t]
    out.append(tuple(run))
    return out


def cross_check(a: pd.Series, b: pd.Series) -> dict:
    """Compare two hourly price series over their overlap."""
    j = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if j.empty:
        return {"overlap_h": 0}
    d = (j["a"] - j["b"]).abs()
    return {"overlap_h": int(len(j)), "max_abs_diff": float(d.max()),
            "mean_abs_diff": float(d.mean()), "hours_over_1eur": int((d > 1.0).sum())}


def update(since: date | None = None, until: date | None = None, verbose=True) -> dict:
    prices = read_store("de_lu_day_ahead")
    if since is None:
        since = (prices.index.max().date() - timedelta(days=2)) if prices is not None \
            else date(date.today().year, 1, 1)
    until = until or (date.today() + timedelta(days=1))   # tomorrow clears ~12:45 CET

    ec_raw = fetch_energy_charts(since, until)
    sm_raw = fetch_smard(since, until)
    new = pd.DataFrame({"energy_charts": to_hourly(ec_raw), "smard": to_hourly(sm_raw)})
    new["price_eur_mwh"] = new["energy_charts"].fillna(new["smard"])
    prices = merge(prices, new)
    write_store("de_lu_day_ahead", prices)

    raw = merge(read_store("de_lu_day_ahead_15min"),
                pd.DataFrame({"energy_charts": ec_raw, "smard": sm_raw}))
    write_store("de_lu_day_ahead_15min", raw)

    wx = merge(read_store("munich_weather"), fetch_open_meteo(since, min(until, date.today() + timedelta(days=1))))
    write_store("munich_weather", wx)

    report = {"since": since.isoformat(), "until": until.isoformat(),
              "price_rows": int(len(prices)), "last_price_utc": str(prices.index.max()),
              "price_gaps": [(str(a), str(b)) for a, b in gaps(prices.index)][-5:],
              "check": cross_check(prices["energy_charts"], prices["smard"])}
    if verbose:
        print(json.dumps(report, indent=2))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="Refresh the HEXOS open-data store")
    ap.add_argument("--since", type=date.fromisoformat, default=None)
    ap.add_argument("--until", type=date.fromisoformat, default=None)
    ap.add_argument("--check", action="store_true", help="report only, fetch nothing")
    ap.add_argument("--max-diff", type=float, default=5.0,
                    help="fail if Energy-Charts and SMARD differ by more (EUR/MWh)")
    a = ap.parse_args(argv)
    if a.check:
        p = read_store("de_lu_day_ahead")
        if p is None:
            sys.exit("no store yet")
        print(json.dumps({"rows": len(p), "last": str(p.index.max()),
                          "gaps": [(str(x), str(y)) for x, y in gaps(p.index)][-5:],
                          "check": cross_check(p["energy_charts"], p["smard"])}, indent=2))
        return
    rep = update(a.since, a.until)
    c = rep["check"]
    if c.get("overlap_h", 0) and c["max_abs_diff"] > a.max_diff:
        sys.exit(f"Energy-Charts and SMARD disagree by up to {c['max_abs_diff']:.2f} EUR/MWh")


if __name__ == "__main__":
    main()
