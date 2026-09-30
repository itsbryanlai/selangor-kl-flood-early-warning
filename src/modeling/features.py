"""Daily features for predicting a flood on day D (Malaysia local date), using only information
available before D.

    observed (ERA5) - rainfall through the end of day D-1: last-day totals/peak, antecedent 3/7/14/30-day
                      area-mean sums, wet-day count, plus season (month sin/cos, NE-monsoon flag)
    forecast        - Open-Meteo Previous Runs forecast issued the day before (about 24 h lead) for day D
    nowcast_*       - observed rain ON day D. NOT available in advance: only for a detection benchmark
                      (lead 0), never used as a warning feature.
Rain over the 5 grid points is combined as area mean and max. ERA5 is a reanalysis: it stands in for
the rainfall one would observe, with no reporting delay modelled.
"""
import numpy as np
import pandas as pd


def _daily_stats(hourly: pd.DataFrame, col: str, prefix: str) -> pd.DataFrame:
    h = hourly.copy()
    h["day"] = h.time.dt.normalize()
    d = h.groupby(["point", "day"])[col].agg(["sum", "max"]).reset_index()
    g = d.groupby("day")
    return pd.DataFrame({
        f"{prefix}_total_mean": g["sum"].mean(),
        f"{prefix}_total_max": g["sum"].max(),
        f"{prefix}_hourly_max": g["max"].max(),
    })


def build_features(rain_path: str, fcst_path: str | None = None) -> pd.DataFrame:
    obs = _daily_stats(pd.read_parquet(rain_path), "precip_mm", "obs")
    days = pd.date_range(obs.index.min(), obs.index.max(), freq="D", name="day")
    obs = obs.reindex(days)
    f = pd.DataFrame(index=days)
    # antecedent conditions: everything shifted by one day so day D sees only D-1 and earlier
    prev = obs.shift(1)
    f["obs_1d_total_mean"] = prev.obs_total_mean
    f["obs_1d_total_max"] = prev.obs_total_max
    f["obs_1d_hourly_max"] = prev.obs_hourly_max
    for n in (3, 7, 14, 30):
        f[f"obs_{n}d_mean"] = obs.obs_total_mean.shift(1).rolling(n, min_periods=n).sum()
    f["obs_wet_days_7d"] = (obs.obs_total_mean.shift(1) > 1).rolling(7, min_periods=7).sum()
    m = f.index.month
    f["month_sin"], f["month_cos"] = np.sin(2 * np.pi * m / 12), np.cos(2 * np.pi * m / 12)
    f["ne_monsoon"] = np.isin(m, [11, 12, 1, 2, 3]).astype(int)
    # nowcast: observed rain on day D itself (detection benchmark only)
    f["nowcast_total_max"] = obs.obs_total_max
    f["nowcast_hourly_max"] = obs.obs_hourly_max
    if fcst_path:
        fc = pd.read_parquet(fcst_path)
        d1 = _daily_stats(fc.dropna(subset=["precip_fcst_d1"]), "precip_fcst_d1", "fc1")
        d2 = _daily_stats(fc.dropna(subset=["precip_fcst_d2"]), "precip_fcst_d2", "fc2")
        f = f.join(d1).join(d2)
        # a day needs (nearly) all 24 hours forecast to count; partial days are set missing
        hrs = fc.dropna(subset=["precip_fcst_d1"]).assign(day=lambda x: x.time.dt.normalize()).groupby("day").size() / fc.point.nunique()
        f.loc[f.index.isin(hrs[hrs < 22].index), [c for c in f.columns if c.startswith("fc1")]] = np.nan
    return f
