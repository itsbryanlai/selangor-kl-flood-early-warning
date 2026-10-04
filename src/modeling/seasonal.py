"""Seasonal-anomaly standardisation: replace raw values by z-scores against a smooth annual climatology.

    python -m src.modeling.seasonal

Raw rain, TCWV and humidity are high in the monsoon months, so a raw value partly encodes season. Here each predictor
is standardised as z = (x - mean(day of year)) / sd(day of year), with mean and sd from a 2-harmonic annual fit.
The climatology is refitted inside every blocked-CV fold on training days only (test quarter +/-7 days removed), so
there is no leakage. Rain is log(1 + mm) before standardising (it is highly skewed).
Compared in leave-one-quarter-out CV, same days for every model, with a paired month-block bootstrap on PR-AUC.
"""
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from .evaluate import _model
from .improve import BASE, WV, budget, build_all
from .instability import paired_boot
from .timeseries import daily_series


def design(index: pd.DatetimeIndex, k: int = 2) -> np.ndarray:
    t = 2 * np.pi * index.dayofyear.values / 365.25
    return np.column_stack([np.ones(len(index))] + [f(h * t) for h in range(1, k + 1) for f in (np.sin, np.cos)])


def zscore(series: pd.Series, train: pd.Series) -> pd.Series:
    """z-score of series against a harmonic mean and sd fitted on the days where train is True."""
    ok = train & series.notna()
    X = design(series.index)
    b = np.linalg.lstsq(X[ok.values], series[ok].values, rcond=None)[0]
    mean = X @ b
    res = np.abs(series[ok].values - mean[ok.values])
    g = np.linalg.lstsq(X[ok.values], res, rcond=None)[0]
    sd = np.maximum(X @ g * np.sqrt(np.pi / 2), 1e-6)
    return (series - mean) / sd


def anomalies(raw: pd.DataFrame, train: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"z_rain1": zscore(raw.lograin.shift(1), train), "z_rain3": zscore(raw.lograin3.shift(1), train),
                         "z_tcwv": zscore(raw.tcwv_00, train), "z_rh850": zscore(raw.rh850_00, train),
                         "z_soil": zscore(raw.soil_00, train)})


def blocked_cv_z(data: pd.DataFrame, raw: pd.DataFrame, cols: list[str], C: float = 0.1, purge: int = 7) -> pd.Series:
    q = data.index.to_period("Q")
    s = pd.Series(np.nan, index=data.index)
    for qq in q.unique():
        te = q == qq
        lo, hi = data.index[te].min() - pd.Timedelta(days=purge), data.index[te].max() + pd.Timedelta(days=purge)
        tr = (data.index < lo) | (data.index > hi)
        if data.loc[tr, "flood"].sum() < 3:
            continue
        train_days = pd.Series((raw.index < lo) | (raw.index > hi), index=raw.index)
        z = anomalies(raw, train_days).reindex(data.index)
        X = data.join(z)
        m = _model(cols, C).fit(X.loc[tr, cols], X.loc[tr, "flood"])
        s[te] = m.predict_proba(X.loc[te, cols])[:, 1]
    return s


def composite(data: pd.DataFrame, raw: pd.DataFrame, use_z: bool) -> pd.Series:
    """Fit-free average rank (within period) of water vapour, yesterday's rain and 850 hPa humidity; z version uses a
    climatology fitted on all days (descriptive: the ranks are within period and need no fitted parameters of skill)."""
    z = anomalies(raw, pd.Series(True, index=raw.index)).reindex(data.index)
    cols = ["z_tcwv", "z_rain1", "z_rh850"] if use_z else ["tcwv_00", "obs_1d_total_max", "rh850_00"]
    X = z if use_z else data
    return pd.concat([X[c].groupby(data.period).rank(pct=True) for c in cols], axis=1).mean(axis=1, skipna=True)


def main() -> None:
    pd.set_option("display.width", 220, "display.max_columns", 30)
    data = build_all()
    ser = daily_series()
    raw = ser.assign(lograin=np.log1p(ser.rain), lograin3=np.log1p(ser.rain.rolling(3, min_periods=3).sum()))
    d = data[~data.excl_strict].copy()
    y = d.flood.values; months = np.asarray(d.index.to_period("M").astype(str))
    sets = {
        "A  baseline + TCWV (raw, current best fitted)": ("raw", WV),
        "B  z-scores only: rain(D-1), TCWV": ("z", ["z_rain1", "z_tcwv"]),
        "C  z-scores: rain(D-1), TCWV, 850 hPa humidity": ("z", ["z_rain1", "z_tcwv", "z_rh850"]),
        "D  z-scores C + season terms": ("z", ["z_rain1", "z_tcwv", "z_rh850", "month_sin", "month_cos"]),
        "E  z rain(D-1), 3-day rain, TCWV + soil": ("z", ["z_rain1", "z_rain3", "z_tcwv", "z_soil"]),
        "F  raw rain terms + z TCWV": ("z", BASE + ["z_tcwv"]),
        "G  raw WV set + z TCWV and z rain": ("z", WV + ["z_tcwv", "z_rain1"]),
    }
    scores = {}
    for n, (kind, cols) in sets.items():
        if kind == "raw":
            from .improve import blocked_cv
            scores[n] = blocked_cv(d, cols, "flood")
        else:
            scores[n] = blocked_cv_z(d, raw, cols)
    scores["H  composite rank, raw (fit-free)"] = composite(d, raw, False)
    scores["I  composite rank, z-scores (fit-free)"] = composite(d, raw, True)
    rows = []
    for n, s in scores.items():
        ok = s.notna().values
        rows.append({"model": n, "n_days": int(ok.sum()), "n_pos": int(y[ok].sum()), "PR-AUC": average_precision_score(y[ok], s[ok]),
                     "ROC-AUC": roc_auc_score(y[ok], s[ok]), **budget(y[ok], s[ok].values)})
    res = pd.DataFrame(rows)
    res.round(3).to_csv("data/processed/seasonal_models.csv", index=False)
    print(f"=== Blocked CV, {len(d)} days, {int(y.sum())} floods; climatology refitted per fold ===")
    print(res.round(3).to_string(index=False))
    a = "A  baseline + TCWV (raw, current best fitted)"
    for n in scores:
        if n == a or n.startswith(("H", "I")):
            continue
        ok = (scores[n].notna() & scores[a].notna()).values
        m, lo, hi, p = paired_boot(y[ok], scores[n].values[ok], scores[a].values[ok], months[ok])
        print(f"  AP diff {n[:1]} minus A: {m:+.3f} (95% CI {lo:+.3f} to {hi:+.3f}), share <= 0: {p:.2f}")
    ok = (scores["I  composite rank, z-scores (fit-free)"].notna() & scores["H  composite rank, raw (fit-free)"].notna()).values
    m, lo, hi, p = paired_boot(y[ok], scores["I  composite rank, z-scores (fit-free)"].values[ok], scores["H  composite rank, raw (fit-free)"].values[ok], months[ok])
    print(f"  AP diff I minus H: {m:+.3f} (95% CI {lo:+.3f} to {hi:+.3f}), share <= 0: {p:.2f}")


if __name__ == "__main__":
    main()
