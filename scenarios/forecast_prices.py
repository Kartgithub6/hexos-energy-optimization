"""
forecast_prices.py
==================
Probabilistic day-ahead price forecasting for HEXOS, evaluated honestly.

What this does
--------------
1. Loads a year of hourly day-ahead prices from a CSV.
2. Builds simple, explainable features (calendar + lagged prices).
3. Trains one quantile model per target quantile (P10 / P50 / P90).
4. Backtests with rolling-origin (walk-forward) validation: for each day,
   train ONLY on data strictly before that day, predict its 24 hours, roll on.
   No future data ever enters training (no leakage).
5. Scores with pinball loss, empirical P10-P90 coverage vs the 80% target,
   and MAE/RMSE on the P50 point forecast.
6. Writes forecasts-vs-actuals to CSV and a calibration plot to PNG.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# Configuration — edit these to match your file.
# ----------------------------------------------------------------------------
CSV_PATH = os.path.join("data", "year_DE_2019.csv") 
TIMESTAMP_COL = "t"       # column with the time index (integer hour or datetime)
PRICE_COL = "price_el"    # column with the day-ahead price
OUT_CSV = os.path.join("results", "price_forecasts.csv")
OUT_PLOT = os.path.join("results", "forecast_calibration.png")

QUANTILES = [0.10, 0.50, 0.90]   # the P10 / P50 / P90 forecasts
WARMUP_DAYS = 35                 # initial history before the first test day
                                 # (must exceed 7 days so the 168h lag exists)
RETRAIN_EVERY_DAYS = 7           # 1 = retrain daily (slowest, most faithful);
                                 # 7 = retrain weekly (faster, still leak-free)
CALIB_DAYS = 30                  # trailing days of past out-of-sample errors
                                 # used for conformal band calibration
TARGET_COVERAGE = 0.80           # nominal coverage of the P10-P90 band
RANDOM_SEED = 42

# ----------------------------------------------------------------------------
# Model backend — LightGBM if available, else scikit-learn. Both use the
# pinball (quantile) objective, so the swap changes speed, not methodology.
# ----------------------------------------------------------------------------
try:
    import lightgbm as lgb
    BACKEND = "lightgbm"
except ImportError:  # graceful fallback, made explicit at runtime
    from sklearn.ensemble import GradientBoostingRegressor
    BACKEND = "sklearn"


def make_model(quantile: float):
    """One boosted-tree model per quantile, both trained on pinball loss."""
    if BACKEND == "lightgbm":
        return lgb.LGBMRegressor(
            objective="quantile", alpha=quantile,
            n_estimators=300, learning_rate=0.05,
            num_leaves=31, min_child_samples=20,
            random_state=RANDOM_SEED, verbosity=-1,
        )
    return GradientBoostingRegressor(
        loss="quantile", alpha=quantile,
        n_estimators=200, learning_rate=0.05,
        max_depth=3, random_state=RANDOM_SEED,
    )


# ----------------------------------------------------------------------------
# 1. Load data — fail loudly if the file is absent. Never invent prices.
# ----------------------------------------------------------------------------
def load_prices() -> pd.DataFrame:
    if not os.path.exists(CSV_PATH):
        sys.exit(
            f"ERROR: input file not found: {CSV_PATH}\n"
            "This script refuses to generate synthetic prices. Point CSV_PATH "
            "at your real price file (e.g. run prepare_year.py first)."
        )
    df = pd.read_csv(CSV_PATH, comment="#")
    for col in (TIMESTAMP_COL, PRICE_COL):
        if col not in df.columns:
            sys.exit(f"ERROR: column '{col}' not in {CSV_PATH}. "
                     f"Available: {list(df.columns)}")

    ts = df[TIMESTAMP_COL]
    if np.issubdtype(ts.dtype, np.number):
        # Integer hour index (0..N-1), as produced by prepare_year.py.
        # Anchor to the data year so calendar features are meaningful.
        stamps = pd.date_range("2019-01-01", periods=len(df), freq="h")
    else:
        stamps = pd.to_datetime(ts)

    out = pd.DataFrame({"timestamp": stamps, "price": df[PRICE_COL].astype(float)})
    out = out.sort_values("timestamp").reset_index(drop=True)
    return out


# ----------------------------------------------------------------------------
# 2. Features — deliberately simple and explainable:
#    calendar position (hour, weekday, month) captures the daily/weekly shape;
#    lagged prices (24h, 168h) capture "yesterday same hour" and
#    "last week same hour", the two classic day-ahead anchors.
# ----------------------------------------------------------------------------
FEATURES = ["hour", "dayofweek", "month", "lag_24", "lag_168"]


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["hour"] = df["timestamp"].dt.hour
    df["dayofweek"] = df["timestamp"].dt.dayofweek
    df["month"] = df["timestamp"].dt.month
    df["lag_24"] = df["price"].shift(24)    # same hour yesterday
    df["lag_168"] = df["price"].shift(168)  # same hour last week
    return df


# ----------------------------------------------------------------------------
# 3+4. Walk-forward backtest.
#      For each test day D: train on all rows strictly before D's first hour,
#      predict D's 24 hours, append, move to D+1. Lags are computed on the
#      full frame but only PAST values are ever referenced (shift() looks
#      backwards), so a day's features never contain that day's own prices
#      beyond hour t-24 — i.e. information genuinely available day-ahead.
# ----------------------------------------------------------------------------
def walk_forward(df: pd.DataFrame) -> pd.DataFrame:
    df = add_features(df)
    n = len(df)
    first_test = WARMUP_DAYS * 24
    if first_test >= n:
        sys.exit(f"ERROR: only {n} rows; need more than WARMUP_DAYS*24 = {first_test}.")

    preds = {q: np.full(n, np.nan) for q in QUANTILES}
    models = {}          # current model per quantile
    last_trained_day = -10**9

    test_days = range(first_test // 24, n // 24)
    for day in test_days:
        start, end = day * 24, min((day + 1) * 24, n)

        # Retrain when due, on data strictly BEFORE this day.
        if day - last_trained_day >= RETRAIN_EVERY_DAYS:
            train = df.iloc[:start].dropna(subset=FEATURES + ["price"])
            X_tr, y_tr = train[FEATURES], train["price"]
            for q in QUANTILES:
                m = make_model(q)
                m.fit(X_tr, y_tr)
                models[q] = m
            last_trained_day = day

        X_te = df.iloc[start:end][FEATURES]
        ok = X_te.notna().all(axis=1)
        for q in QUANTILES:
            yhat = models[q].predict(X_te[ok])
            preds[q][start:end][ok.to_numpy()] = yhat

    out = df[["timestamp", "price"]].copy()
    for q in QUANTILES:
        out[f"p{int(q*100):02d}"] = preds[q]
    out = out.iloc[first_test:].dropna().reset_index(drop=True)

    # ------------------------------------------------------------------
    # Conformal calibration of the P10-P90 band (rolling, leak-free).
    # For each day, look at the trailing CALIB_DAYS of *already-made*
    # out-of-sample predictions, compute the conformity score
    #     s = max(P10 - y, y - P90)   (how far outside the band y fell;
    #                                  negative when inside)
    # and widen (or narrow) today's band by the empirical
    # TARGET_COVERAGE-quantile of those scores. Only past errors are used,
    # so no future information leaks into any adjustment.
    # Reference: Conformalized Quantile Regression (Romano et al., 2019).
    # ------------------------------------------------------------------
    y_all = out["price"].to_numpy()
    lo_raw = out["p10"].to_numpy().copy()
    hi_raw = out["p90"].to_numpy().copy()
    scores = np.maximum(lo_raw - y_all, y_all - hi_raw)  # per-hour conformity
    n_out = len(out)
    adj = np.zeros(n_out)
    warm_h = CALIB_DAYS * 24
    for d0 in range(0, n_out, 24):
        d1 = min(d0 + 24, n_out)
        if d0 >= warm_h:
            window = scores[d0 - warm_h:d0]          # strictly past hours
            k = int(np.ceil((len(window) + 1) * TARGET_COVERAGE)) - 1
            k = min(max(k, 0), len(window) - 1)
            adj[d0:d1] = np.sort(window)[k]
        else:
            adj[d0:d1] = np.nan                       # not yet calibratable
    calibrated = ~np.isnan(adj)
    out["p10_cal"] = np.where(calibrated, lo_raw - adj, np.nan)
    out["p90_cal"] = np.where(calibrated, hi_raw + adj, np.nan)
    out.attrs["n_calibrated"] = int(calibrated.sum())

    # Quantile crossing can occur with independent per-quantile models;
    # enforce P10 <= P50 <= P90 by sorting, and report how often it happened.
    trio = out[["p10", "p50", "p90"]].to_numpy()
    crossed = (np.diff(trio, axis=1) < 0).any(axis=1).mean()
    trio.sort(axis=1)
    out[["p10", "p50", "p90"]] = trio
    out.attrs["crossing_rate"] = crossed
    return out


# ----------------------------------------------------------------------------
# 5. Scoring.
#    Pinball loss: the proper scoring rule for quantiles (lower = better).
#    Coverage: share of actuals inside [P10, P90]; target is 80% by design.
#    MAE/RMSE on P50: familiar point-forecast reference numbers.
# ----------------------------------------------------------------------------
def pinball(y: np.ndarray, yhat: np.ndarray, q: float) -> float:
    diff = y - yhat
    return float(np.mean(np.maximum(q * diff, (q - 1) * diff)))


def score(out: pd.DataFrame) -> dict:
    y = out["price"].to_numpy()
    s = {}
    for q in QUANTILES:
        s[f"pinball_p{int(q*100):02d}"] = pinball(y, out[f"p{int(q*100):02d}"].to_numpy(), q)
    s["pinball_avg"] = float(np.mean([s[f"pinball_p{int(q*100):02d}"] for q in QUANTILES]))
    inside = (y >= out["p10"].to_numpy()) & (y <= out["p90"].to_numpy())
    s["coverage_p10_p90"] = float(inside.mean())
    if "p10_cal" in out.columns:
        ok = out["p10_cal"].notna().to_numpy()
        if ok.any():
            yin = (y[ok] >= out["p10_cal"].to_numpy()[ok]) & (y[ok] <= out["p90_cal"].to_numpy()[ok])
            s["coverage_calibrated"] = float(yin.mean())
            s["n_calibrated_hours"] = int(ok.sum())
            width_raw = float(np.mean(out["p90"].to_numpy()[ok] - out["p10"].to_numpy()[ok]))
            width_cal = float(np.mean(out["p90_cal"].to_numpy()[ok] - out["p10_cal"].to_numpy()[ok]))
            s["band_width_raw"] = width_raw
            s["band_width_cal"] = width_cal
    err = y - out["p50"].to_numpy()
    s["mae_p50"] = float(np.mean(np.abs(err)))
    s["rmse_p50"] = float(np.sqrt(np.mean(err ** 2)))
    return s


# ----------------------------------------------------------------------------
# 6. Outputs: forecasts CSV + reliability (calibration) plot.
#    The plot asks: "when the model claims quantile q, how often is the actual
#    below it?" A calibrated model tracks the diagonal.
# ----------------------------------------------------------------------------
def save_outputs(out: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    out.to_csv(OUT_CSV, index=False)

    y = out["price"].to_numpy()
    nominal = np.array(QUANTILES)
    observed = np.array([np.mean(y <= out[f"p{int(q*100):02d}"].to_numpy())
                         for q in QUANTILES])

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect calibration")
    ax.plot(nominal, observed, "o-", color="tab:blue", label="model")
    for q_nom, q_obs in zip(nominal, observed):
        ax.annotate(f"{q_obs:.2f}", (q_nom, q_obs),
                    textcoords="offset points", xytext=(6, -4), fontsize=9)
    ax.set_xlabel("Nominal quantile")
    ax.set_ylabel("Observed frequency (actual <= forecast)")
    ax.set_title("Forecast calibration (reliability)")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_PLOT, dpi=150)
    plt.close(fig)


# ----------------------------------------------------------------------------
# Main.
# ----------------------------------------------------------------------------
def main() -> None:
    print(f"Backend: {BACKEND}  (quantile objective; one model per quantile)")
    df = load_prices()
    print(f"Loaded {len(df)} hourly prices "
          f"({df['timestamp'].iloc[0]} .. {df['timestamp'].iloc[-1]})")

    out = walk_forward(df)
    s = score(out)
    save_outputs(out)

    n_days = len(out) // 24
    print("\n================ SUMMARY (quote these) ================")
    print(f"Out-of-sample horizon : {len(out)} hours (~{n_days} days), "
          f"walk-forward, retrain every {RETRAIN_EVERY_DAYS} day(s)")
    print(f"Pinball loss  P10     : {s['pinball_p10']:.4f}")
    print(f"Pinball loss  P50     : {s['pinball_p50']:.4f}")
    print(f"Pinball loss  P90     : {s['pinball_p90']:.4f}")
    print(f"Pinball loss  average : {s['pinball_avg']:.4f}")
    print(f"P10-P90 coverage (raw): {s['coverage_p10_p90']*100:.1f}%   (target: {TARGET_COVERAGE*100:.0f}%)")
    if "coverage_calibrated" in s:
        print(f"P10-P90 coverage (conformal-calibrated): {s['coverage_calibrated']*100:.1f}%"
              f"   on {s['n_calibrated_hours']} h   (target: {TARGET_COVERAGE*100:.0f}%)")
        print(f"Mean band width raw -> calibrated : {s['band_width_raw']:.4f} -> {s['band_width_cal']:.4f} (price units)")
    print(f"P50 MAE               : {s['mae_p50']:.4f}  (price units)")
    print(f"P50 RMSE              : {s['rmse_p50']:.4f}  (price units)")
    cross = out.attrs.get("crossing_rate", 0.0)
    print(f"Quantile crossings fixed by sorting: {cross*100:.2f}% of hours")
    print(f"Forecasts CSV : {OUT_CSV}")
    print(f"Calibration   : {OUT_PLOT}")
    print("=======================================================")


if __name__ == "__main__":
    main()
