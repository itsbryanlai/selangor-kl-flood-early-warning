"""Water-vapour predictors: level, anomaly, tendency and low-level moisture-flux convergence.

    python -m src.modeling.water_vapour

All features for day D use only information up to 00:00 local on D (a lead of hours to a day; no archived forecast of
water vapour exists in Open-Meteo, see docs/water-vapour.md):
  tcwv_00          total column water vapour (TCWV, kg/m2) at 00:00 on D, area mean over the 5 grid points
  tcwv_anom_00     tcwv_00 minus the mean of the previous 60 days (no leakage)
  tcwv_chg6_00     change over the last 6 h (18:00 D-1 to 00:00 D); tcwv_chg24_00 over 24 h
  tcwv_hi_hours_d1 hours of D-1 with TCWV above its 75th percentile (persistence of a moist column)
  mfc_00, mfc_d1_min  low-level moisture-flux convergence: -div(q*V) from a least-squares fit across the 5 points,
                   using 2 m specific humidity and 10 m wind (negative divergence = convergence); 00:00 value and
                   the most convergent hour of D-1
  q850_00, fluxu850_00, fluxv850_00, ivt_proxy_00  (2021-04 onward) specific humidity at 850 hPa, its zonal/meridional
                   flux with the 850 hPa wind, and TCWV x 850 hPa wind speed (a crude integrated-vapour-transport proxy)
ERA5 TCWV is missing for 2024-01 to 2024-06 in the Open-Meteo archive. A regression fill (dew point, humidity,
temperature, pressure) was tried and rejected (holdout R2 about 0.11); those days are dropped from the models.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from .evaluate import OBS, make_dataset, run, summarize
from .features import build_features
from .gauge_tide_analysis import tide_daily
from .instability import CAPE_SET, MOIST, PERIODS, hourly_area, paired_boot, part_a, state_features

POINTS = {"kuala_lumpur": (3.139, 101.687), "shah_alam": (3.073, 101.518), "klang": (3.045, 101.445),
          "kuala_selangor": (3.340, 101.250), "sepang": (2.690, 101.750)}
BASE = ["obs_1d_total_max", "obs_7d_mean", "month_sin", "month_cos"]


def filled_tcwv(era5: pd.DataFrame) -> tuple[pd.Series, pd.Series, dict]:
    """Area-mean hourly TCWV. The 2024-H1 gap is NOT filled: a regression on dew point, humidity, temperature and
    pressure was tried and is reported (holdout R2 about 0.11, so unusable); gap days are left missing and dropped
    from the models. Returns (series, missing flag, regression accuracy)."""
    a = hourly_area("data/interim/atmos_era5.parquet")
    pred_cols = ["dew_point_2m", "relative_humidity_2m", "temperature_2m", "surface_pressure"]
    tc = a.total_column_integrated_water_vapour
    have = tc.notna()
    train = have & (a.index < "2025-01-01")
    test = have & (a.index >= "2025-01-01")
    m = LinearRegression().fit(a.loc[train, pred_cols], tc[train])
    r2_test = m.score(a.loc[test, pred_cols], tc[test])
    resid_sd = float(np.std(tc[test] - m.predict(a.loc[test, pred_cols])))
    m = LinearRegression().fit(a.loc[have, pred_cols], tc[have])
    return tc, ~have, {"r2_holdout": r2_test, "resid_sd_holdout": resid_sd, "n_missing_hours": int((~have).sum())}


def divergence_features(era5_path="data/interim/atmos_era5.parquet") -> pd.DataFrame:
    """Hourly low-level moisture-flux divergence from a least-squares fit across the 5 points (per hour)."""
    d = pd.read_parquet(era5_path)
    rad = np.deg2rad(d.wind_direction_10m)
    d["u"], d["v"] = -d.wind_speed_10m * np.sin(rad), -d.wind_speed_10m * np.cos(rad)
    e = 6.112 * np.exp(17.67 * d.dew_point_2m / (d.dew_point_2m + 243.5))
    d["q"] = 0.622 * e / (d.surface_pressure - e)
    d["qu"], d["qv"] = d.q * d.u, d.q * d.v
    lat0, lon0 = 3.0, 101.5
    d["x_km"] = d.point.map(lambda p: (POINTS[p][1] - lon0) * 111.0 * np.cos(np.deg2rad(lat0)))
    d["y_km"] = d.point.map(lambda p: (POINTS[p][0] - lat0) * 111.0)
    A = np.c_[np.ones(len(POINTS)), [ (POINTS[p][1] - lon0) * 111.0 * np.cos(np.deg2rad(lat0)) for p in POINTS],
              [(POINTS[p][0] - lat0) * 111.0 for p in POINTS]]
    order = list(POINTS)
    pinv = np.linalg.pinv(A)
    out = {}
    for t, g in d.groupby("time"):
        g = g.set_index("point").reindex(order)
        if g.qu.isna().any():
            continue
        cu, cv = pinv @ g.qu.values, pinv @ g.qv.values  # [const, d/dx, d/dy] in per km
        out[t] = (cu[1] + cv[2]) / 1000.0  # per m
    s = pd.Series(out, name="div_qv")
    return (-s * 1e6)  # moisture-flux convergence, scaled (positive = convergence)


def wv_features() -> pd.DataFrame:
    st = state_features()
    a = hourly_area("data/interim/atmos_era5.parquet")
    tc, flag, acc = filled_tcwv(a)
    h = pd.DataFrame({"tcwv": tc})
    f = pd.DataFrame(index=st.index)
    daily = tc.groupby(tc.index.normalize()).mean()
    s00 = tc[tc.index.hour == 0]; s00 = s00.set_axis(s00.index.normalize())
    s18 = tc[tc.index.hour == 18]; s18.index = s18.index.normalize() + pd.Timedelta(days=1)  # 18:00 of D-1 labelled D
    f["tcwv_00"] = s00.reindex(f.index)
    f["tcwv_anom_00"] = f.tcwv_00 - daily.shift(1).rolling(60, min_periods=30).mean().reindex(f.index)
    f["tcwv_chg6_00"] = f.tcwv_00 - s18.reindex(f.index)
    f["tcwv_chg24_00"] = f.tcwv_00 - f.tcwv_00.shift(1)
    p75 = tc.quantile(0.75)
    f["tcwv_hi_hours_d1"] = (tc > p75).groupby(tc.index.normalize()).sum().shift(1).reindex(f.index)
    f["tcwv_missing"] = flag.groupby(flag.index.normalize()).mean().reindex(f.index).fillna(0)
    mfc = divergence_features()
    f["mfc_00"] = mfc[mfc.index.hour == 0].set_axis(mfc[mfc.index.hour == 0].index.normalize()).reindex(f.index)
    f["mfc_d1_min"] = (-mfc).groupby(mfc.index.normalize()).min().mul(-1).shift(1).reindex(f.index)  # most convergent hour of D-1
    f["mfc_d1_mean"] = mfc.groupby(mfc.index.normalize()).mean().shift(1).reindex(f.index)
    n = hourly_area("data/interim/atmos_nwp.parquet")
    es = 6.112 * np.exp(17.67 * n.temperature_850hPa / (n.temperature_850hPa + 243.5))
    e = n.relative_humidity_850hPa / 100 * es
    n["q850"] = 0.622 * e / (850 - 0.378 * e)
    n["fluxu"], n["fluxv"] = n.q850 * n.u850, n.q850 * n.v850
    n["spd850"] = np.hypot(n.u850, n.v850)
    n00 = n[n.index.hour == 0]; n00 = n00.set_axis(n00.index.normalize())
    f["q850_00"] = n00.q850.reindex(f.index) * 1000  # g/kg
    f["fluxu850_00"], f["fluxv850_00"] = n00.fluxu.reindex(f.index) * 1000, n00.fluxv.reindex(f.index) * 1000
    f["ivt_proxy_00"] = (f.tcwv_00 * n00.spd850.reindex(f.index))
    f.loc[f.index < "2021-04-01", ["q850_00", "fluxu850_00", "fluxv850_00", "ivt_proxy_00"]] = np.nan
    out = f.join(st[MOIST + CAPE_SET + ["cape_fc1_max"]], how="left")
    out.attrs["fill_accuracy"] = acc
    return out


def main() -> None:
    pd.set_option("display.width", 230, "display.max_columns", 30)
    wv = wv_features()
    acc = wv.attrs["fill_accuracy"]
    print(f"TCWV regression fill tried for 2024-H1: holdout R2 {acc['r2_holdout']:.3f}, residual sd {acc['resid_sd_holdout']:.2f} kg/m2 -> NOT used; {acc['n_missing_hours']} hours left missing and dropped")
    tide = tide_daily()
    labels = {k: pd.read_csv(v[2], parse_dates=["day"]) for k, v in PERIODS.items()}
    rain = pd.concat([build_features(r, f) for r, f, _ in PERIODS.values()]).sort_index()
    rain = rain[~rain.index.duplicated()]
    feats = wv.join(rain[["obs_1d_total_max", "obs_7d_mean", "nowcast_total_max", "fc1_total_max"]], how="left")
    new = ["tcwv_00", "tcwv_anom_00", "tcwv_chg6_00", "tcwv_chg24_00", "tcwv_hi_hours_d1", "mfc_00", "mfc_d1_min", "mfc_d1_mean",
           "q850_00", "fluxu850_00", "fluxv850_00", "ivt_proxy_00", "tcwv_d1_mean", "rh850_00", "obs_1d_total_max", "nowcast_total_max", "fc1_total_max"]
    print("\n=== Part A: flood-day percentile among +/-45-day controls (0.5 = no signal) ===")
    a = part_a(feats[new], labels)
    print(a.round(3).to_string(index=False))
    a.round(3).to_csv("data/processed/water_vapour_part_a.csv", index=False)
    # flood frequency by TCWV quintile (anomaly removes seasonality)
    lab = pd.concat(labels.values()); lab = lab[~lab.label_type.isin(["near_event", "uncertain_event"])].assign(y=lambda x: (x.label_type == "flood").astype(int))
    q = lab.set_index("day").join(wv[["tcwv_00", "tcwv_anom_00", "mfc_00"]]).dropna(subset=["tcwv_00", "tcwv_anom_00"])
    for col in ("tcwv_00", "tcwv_anom_00"):
        q["bin"] = pd.qcut(q[col], 5, labels=False)
        t = q.groupby("bin").agg(low=(col, "min"), high=(col, "max"), days=("y", "size"), floods=("y", "sum"))
        t["floods_per_100_days"] = (100 * t.floods / t.days).round(2)
        print(f"\nFlood frequency by {col} quintile:\n{t.round(1).to_string()}")
    # Part B
    parts = []
    for tag, (rain_p, fc, lab_p) in PERIODS.items():
        f = build_features(rain_p, fc).join(tide).join(wv, how="left")
        d = make_dataset(f, pd.read_csv(lab_p), "all"); d["period"] = tag; parts.append(d)
    data = pd.concat(parts).sort_index()
    data = data[data.tcwv_missing < 0.5]  # drop days with no TCWV (2024-01 to 2024-06) for every model, so comparisons are like for like
    sets_all = {"baseline (rain+season, sparse)": BASE,
                "baseline + tcwv_00": BASE + ["tcwv_00"],
                "baseline + tcwv level, anomaly, 12h-style tendency": BASE + ["tcwv_00", "tcwv_anom_00", "tcwv_chg6_00"],
                "baseline + tcwv set + moisture-flux convergence": BASE + ["tcwv_00", "tcwv_anom_00", "tcwv_chg6_00", "mfc_00", "mfc_d1_min"],
                "prior best-style: baseline + tcwv_d1/theta-e/soil (instability-features.md)": BASE + ["tcwv_d1_mean", "thetae_00", "soil_00"]}
    ranks = {"tcwv_00 alone": "tcwv_00", "tcwv anomaly alone": "tcwv_anom_00", "yesterday's rain (lead 1d)": "obs_1d_total_max"}
    cut_all = ["2021-07-01", "2022-01-01", "2022-07-01", "2023-01-01", "2023-07-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01"]
    res = run(data, cut_all, feature_sets=sets_all, rank_baselines=ranks)
    o = summarize(res); o.to_csv("data/processed/water_vapour_models_all.csv", index=False)
    print(f"\n=== Part B1: water-vapour features, 3 periods, test 2021-07..2026-09 ({int(o.n_flood.iloc[0])} floods) ===")
    print(o[["model", "n_days", "PR-AUC", "PR-AUC 95% CI", "perm p", "ROC-AUC", "hits", "false_alarms", "CSI", "FAR"]].round(3).to_string(index=False))
    months = np.asarray(res["index"].to_period("M").astype(str)); y = res["y"].values.astype(int)
    k0 = "logistic: baseline (rain+season, sparse)"
    for name in sets_all:
        if name.startswith("baseline (rain"):
            continue
        key = "logistic: " + name
        ok = (res["scores"][key].notna() & res["scores"][k0].notna()).values
        m, lo, hi, p = paired_boot(y[ok], res["scores"][key].values[ok], res["scores"][k0].values[ok], months[ok])
        print(f"  AP diff vs baseline: {name}: {m:+.3f} (95% CI {lo:+.3f} to {hi:+.3f}), share <= 0: {p:.2f}")
    d21 = data[data.index >= "2021-04-01"]
    sets21 = {"baseline": BASE, "baseline + tcwv set": sets_all["baseline + tcwv level, anomaly, 12h-style tendency"],
              "baseline + tcwv set + 850 hPa flux (u, v)": sets_all["baseline + tcwv level, anomaly, 12h-style tendency"] + ["fluxu850_00", "fluxv850_00"],
              "baseline + tcwv set + IVT proxy": sets_all["baseline + tcwv level, anomaly, 12h-style tendency"] + ["ivt_proxy_00"],
              "baseline + tcwv set + 850 hPa humidity": sets_all["baseline + tcwv level, anomaly, 12h-style tendency"] + ["rh850_00"],
              "prior best: baseline + ERA5 moisture + CAPE set": BASE + ["tcwv_d1_mean", "thetae_00", "soil_00"] + CAPE_SET}
    ranks21 = {"ivt proxy alone": "ivt_proxy_00", "q850 alone": "q850_00"}
    cut21 = ["2022-01-01", "2022-07-01", "2023-01-01", "2023-07-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01"]
    res21 = run(d21, cut21, feature_sets=sets21, rank_baselines=ranks21)
    o21 = summarize(res21); o21.to_csv("data/processed/water_vapour_models_2021plus.csv", index=False)
    print(f"\n=== Part B2: 2021-04 onward, with 850 hPa flux / IVT proxy ({int(o21.n_flood.iloc[0])} floods) ===")
    print(o21[["model", "n_days", "PR-AUC", "PR-AUC 95% CI", "perm p", "ROC-AUC", "hits", "false_alarms", "CSI", "FAR"]].round(3).to_string(index=False))
    months21 = np.asarray(res21["index"].to_period("M").astype(str)); y21 = res21["y"].values.astype(int)
    k0 = "logistic: baseline"
    for name in sets21:
        if name == "baseline":
            continue
        key = "logistic: " + name
        ok = (res21["scores"][key].notna() & res21["scores"][k0].notna()).values
        m, lo, hi, p = paired_boot(y21[ok], res21["scores"][key].values[ok], res21["scores"][k0].values[ok], months21[ok])
        print(f"  AP diff vs baseline: {name}: {m:+.3f} (95% CI {lo:+.3f} to {hi:+.3f}), share <= 0: {p:.2f}")


if __name__ == "__main__":
    main()
