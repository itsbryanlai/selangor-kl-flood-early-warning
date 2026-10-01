"""Do moisture and instability predictors add skill beyond rain and season?

    python -m src.modeling.instability

Inputs (see src/rainfall/atmos_state.py): ERA5 surface state (all periods) and NWP state incl. CAPE
(2021-04 onward), averaged over the 5 grid points. Features for day D (Malaysia local date) use only information
available before D: the previous day's moisture/heating/instability summaries and the 00:00 snapshot of D.
`now_*` features describe day D itself (not available in advance; lead-0 benchmark only).

Part A: percentile rank of each feature on flood days among nearby non-flood days (+/-45 days), which removes
seasonality; Part B: expanding-window models with and without the new features, with a paired month-block
bootstrap of the PR-AUC difference against the rain-and-season baseline.
"""
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from .evaluate import OBS, make_dataset, run, summarize
from .features import build_features
from .gauge_tide_analysis import tide_daily

PERIODS = {
    "2015-16": ("data/interim/rain_hourly_2015-02-01_2016-12-31.parquet", None, "data/processed/daily_labels_2015_2016.csv"),
    "2021-23": ("data/interim/rain_hourly_2020-12-01_2023-12-31.parquet", None, "data/processed/daily_labels_v1_2021_2023.csv"),
    "2024-26": ("data/interim/rain_hourly_2024-01-01_2026-09-30.parquet", "data/interim/fcst_hourly_2024-01-01_2026-09-30.parquet",
                "data/processed/daily_labels_v1_2024_2026.csv"),
}


def theta_e(t_c: pd.Series, td_c: pd.Series, p_hpa: pd.Series) -> pd.Series:
    """Equivalent potential temperature (K), Bolton (1980). A standard surface convective-instability proxy."""
    t, td = t_c + 273.15, td_c + 273.15
    e = 6.112 * np.exp(17.67 * td_c / (td_c + 243.5))
    r = 0.622 * e / (p_hpa - e)
    tl = 1.0 / (1.0 / (td - 56.0) + np.log(t / td) / 800.0) + 0.0
    return t * (1000.0 / (p_hpa - e)) ** (0.2854 * (1 - 0.28 * r)) * np.exp((3.376 / tl - 0.00254) * (r * 1000) * (1 + 0.81 * r))


def hourly_area(path: str, rename: dict | None = None) -> pd.DataFrame:
    d = pd.read_parquet(path)
    cols = [c for c in d.columns if c not in ("time", "point")]
    # wind direction needs vector averaging: convert speed/direction to u,v first
    for sp, di, u, v in (("wind_speed_10m", "wind_direction_10m", "u10", "v10"), ("wind_speed_850hPa", "wind_direction_850hPa", "u850", "v850")):
        if sp in d.columns:
            rad = np.deg2rad(d[di])
            d[u], d[v] = -d[sp] * np.sin(rad), -d[sp] * np.cos(rad)
            cols += [u, v]
    return d.groupby("time")[[c for c in cols if c not in ("wind_direction_10m", "wind_direction_850hPa")]].mean()


def state_features(era5_path="data/interim/atmos_era5.parquet", nwp_path="data/interim/atmos_nwp.parquet",
                   cape_fc_path="data/interim/atmos_cape_fc1.parquet") -> pd.DataFrame:
    e = hourly_area(era5_path)
    e["theta_e"] = theta_e(e.temperature_2m, e.dew_point_2m, e.surface_pressure)
    f = pd.DataFrame(index=pd.date_range(e.index.min().normalize(), e.index.max().normalize(), freq="D", name="day"))
    day = e.index.normalize()
    g = e.groupby(day)
    prev = lambda s: s.shift(1).reindex(f.index)  # noqa: E731 - value of the previous day
    f["tcwv_d1_mean"] = prev(g.total_column_integrated_water_vapour.mean())
    f["tcwv_d1_max"] = prev(g.total_column_integrated_water_vapour.max())
    f["dewp_d1_mean"] = prev(g.dew_point_2m.mean())
    f["t2m_d1_max"] = prev(g.temperature_2m.max())
    f["thetae_d1_max"] = prev(g.theta_e.max())
    f["thetae_d1_mean"] = prev(g.theta_e.mean())
    f["rh_d1_mean"] = prev(g.relative_humidity_2m.mean())
    f["cloud_d1_mean"] = prev(g.cloud_cover.mean())
    f["sw_d1_sum"] = prev(g.shortwave_radiation.sum())
    f["blh_d1_max"] = prev(g.boundary_layer_height.max())
    f["u10_d1"], f["v10_d1"] = prev(g.u10.mean()), prev(g.v10.mean())
    snap = e[e.index.hour == 0]  # 00:00 local of day D (before any flood on D)
    s = snap.set_index(snap.index.normalize())
    f["tcwv_00"] = s.total_column_integrated_water_vapour.reindex(f.index)
    f["thetae_00"] = s.theta_e.reindex(f.index)
    f["dewp_00"] = s.dew_point_2m.reindex(f.index)
    f["soil_00"] = s.soil_moisture_0_to_7cm.reindex(f.index)
    f["tcwv_delta24"] = f.tcwv_00 - f.tcwv_00.shift(1)
    # day D itself (lead-0 benchmark only)
    f["now_tcwv_mean"] = g.total_column_integrated_water_vapour.mean().reindex(f.index)
    f["now_thetae_max"] = g.theta_e.max().reindex(f.index)
    f["now_t2m_max"] = g.temperature_2m.max().reindex(f.index)
    f["now_cloud_mean"] = g.cloud_cover.mean().reindex(f.index)
    if nwp_path:
        n = hourly_area(nwp_path)
        n["lapse_850_500"] = n.temperature_850hPa - n.temperature_500hPa
        gn = n.groupby(n.index.normalize())
        fi = f.index
        pn = lambda s_: s_.shift(1).reindex(fi)  # noqa: E731
        f["cape_d1_max"], f["cape_d1_mean"] = pn(gn.cape.max()), pn(gn.cape.mean())
        f["li_d1_min"] = pn(gn.lifted_index.min())
        f["lapse_d1_mean"] = pn(gn.lapse_850_500.mean())
        f["t850_d1_mean"], f["rh850_d1_mean"] = pn(gn.temperature_850hPa.mean()), pn(gn.relative_humidity_850hPa.mean())
        f["u850_d1"], f["v850_d1"] = pn(gn.u850.mean()), pn(gn.v850.mean())
        sn = n[n.index.hour == 0]; sn = sn.set_index(sn.index.normalize())
        f["cape_00"], f["rh850_00"], f["t850_00"] = sn.cape.reindex(fi), sn.relative_humidity_850hPa.reindex(fi), sn.temperature_850hPa.reindex(fi)
        f["now_cape_max"] = gn.cape.max().reindex(fi)
        f["now_li_min"] = gn.lifted_index.min().reindex(fi)
        f.loc[f.index < "2021-04-01", [c for c in f.columns if c.startswith(("cape", "li_", "lapse", "t850", "rh850", "u850", "v850", "now_cape", "now_li"))]] = np.nan
    if cape_fc_path:
        c = pd.read_parquet(cape_fc_path).groupby("time").cape_previous_day1.mean()
        f["cape_fc1_max"] = c.groupby(c.index.normalize()).max().reindex(f.index)
    return f


MOIST = ["tcwv_d1_mean", "thetae_d1_max", "thetae_00", "dewp_d1_mean", "soil_00", "cloud_d1_mean", "sw_d1_sum", "blh_d1_max"]
CAPE_SET = ["cape_d1_max", "li_d1_min", "lapse_d1_mean", "rh850_00", "t850_00"]


def paired_boot(y, a, b, months, n=2000, seed=0):
    """Mean and 95% CI of AP(a) - AP(b) over month-block bootstrap resamples; p = share of resamples with difference <= 0."""
    rng = np.random.default_rng(seed)
    uniq = pd.Series(months).unique()
    idx = {m: np.where(months == m)[0] for m in uniq}
    d = []
    for _ in range(n):
        ii = np.concatenate([idx[uniq[k]] for k in rng.choice(len(uniq), len(uniq))])
        if y[ii].sum() > 0:
            d.append(average_precision_score(y[ii], a[ii]) - average_precision_score(y[ii], b[ii]))
    d = np.array(d)
    return d.mean(), np.percentile(d, 2.5), np.percentile(d, 97.5), float((d <= 0).mean())


def part_a(feats: pd.DataFrame, label_frames: dict) -> pd.DataFrame:
    """Percentile of each feature on flood days among +/-45-day non-flood controls (0.5 = no difference)."""
    flood_days = sorted({d for lab in label_frames.values() for d in lab.loc[lab.label_type == "flood", "day"]})
    buf = {d + pd.Timedelta(days=k) for d in flood_days for k in range(-3, 4)}
    cols = [c for c in feats.columns if feats[c].notna().sum() > 100]
    rows = {c: [] for c in cols}
    for d0 in flood_days:
        ctrl = [d for d in pd.date_range(d0 - pd.Timedelta(days=45), d0 + pd.Timedelta(days=45)) if d not in buf and d in feats.index]
        for c in cols:
            v = feats[c].get(d0, np.nan)
            cv = feats[c].reindex(ctrl).dropna().values
            if np.isnan(v) or len(cv) < 20:
                continue
            rows[c].append((cv < v).mean() + 0.5 * (cv == v).mean())
    rng = np.random.default_rng(0)
    out = []
    for c, v in rows.items():
        if len(v) < 10:
            continue
        v = np.array(v); b = [rng.choice(v, len(v)).mean() for _ in range(2000)]
        out.append({"feature": c, "n_events": len(v), "mean_pct": v.mean(), "ci_lo": np.percentile(b, 2.5), "ci_hi": np.percentile(b, 97.5),
                    "dist_from_0.5": abs(v.mean() - 0.5)})
    return pd.DataFrame(out).sort_values("dist_from_0.5", ascending=False)


def main() -> None:
    pd.set_option("display.width", 220, "display.max_columns", 30)
    st = state_features()
    tide = tide_daily()
    labels = {k: pd.read_csv(v[2], parse_dates=["day"]) for k, v in PERIODS.items()}
    print("=== Part A: flood-day percentile among +/-45-day controls (seasonality removed); 0.5 = no signal ===")
    a = part_a(st, labels)
    a.round(3).to_csv("data/processed/instability_part_a.csv", index=False)
    print(a.round(3).to_string(index=False))
    parts = []
    for tag, (rain, fc, lab) in PERIODS.items():
        f = build_features(rain, fc).join(tide).join(st, how="left")
        d = make_dataset(f, pd.read_csv(lab), "all"); d["period"] = tag; parts.append(d)
    data = pd.concat(parts).sort_index()
    base = ["obs_1d_total_max", "obs_7d_mean", "month_sin", "month_cos"]
    sets_all = {"rain+season baseline (sparse)": base, "obs (all rain features)": OBS,
                "baseline + ERA5 moisture/theta-e": base + ["tcwv_d1_mean", "thetae_00", "soil_00"],
                "obs + all ERA5 moisture/heating": OBS + MOIST}
    ranks = {"yesterday's rain (lead 1d)": "obs_1d_total_max"}
    cut_all = ["2021-07-01", "2022-01-01", "2022-07-01", "2023-01-01", "2023-07-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01"]
    res = run(data, cut_all, feature_sets=sets_all, rank_baselines=ranks)
    o = summarize(res); o.to_csv("data/processed/instability_models_all_periods.csv", index=False)
    print(f"\n=== Part B1: ERA5 moisture/instability features, all 3 periods, test 2021-07..2026-09 ({int(o.n_flood.iloc[0])} floods) ===")
    print(o[["model", "n_days", "PR-AUC", "PR-AUC 95% CI", "perm p", "ROC-AUC", "Brier"]].round(3).to_string(index=False))
    months = np.asarray(res["index"].to_period("M").astype(str))
    y = res["y"].values.astype(int)
    for name in sets_all:
        if "baseline (sparse)" in name:
            continue
        key = "logistic: " + name; k0 = "logistic: rain+season baseline (sparse)"
        ok = res["scores"][key].notna() & res["scores"][k0].notna()
        m, lo, hi, p = paired_boot(y[ok.values], res["scores"][key][ok].values, res["scores"][k0][ok].values, months[ok.values])
        print(f"  AP difference vs sparse baseline: {name}: {m:+.3f} (95% CI {lo:+.3f} to {hi:+.3f}), share <= 0: {p:.2f}")
    d21 = data[data.index >= "2021-04-01"]
    sets_cape = {"baseline (sparse)": base, "baseline + CAPE/instability": base + ["cape_d1_max", "li_d1_min"],
                 "baseline + ERA5 moisture + CAPE set": base + ["tcwv_d1_mean", "thetae_00", "soil_00"] + CAPE_SET,
                 "obs + ERA5 moisture + CAPE set": OBS + MOIST + CAPE_SET,
                 "lead 0: baseline + same-day CAPE/theta-e/TCWV": base + ["now_cape_max", "now_thetae_max", "now_tcwv_mean"]}
    ranks2 = {"yesterday's rain (lead 1d)": "obs_1d_total_max", "same-day CAPE (lead 0)": "now_cape_max", "yesterday's max CAPE (lead 1d)": "cape_d1_max"}
    cut21 = ["2022-01-01", "2022-07-01", "2023-01-01", "2023-07-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01"]
    res2 = run(d21, cut21, feature_sets=sets_cape, rank_baselines=ranks2)
    o2 = summarize(res2); o2.to_csv("data/processed/instability_models_cape.csv", index=False)
    print(f"\n=== Part B2: CAPE and 850/500 hPa fields, periods from 2021-04, test 2022-01..2026-09 ({int(o2.n_flood.iloc[0])} floods) ===")
    print(o2[["model", "n_days", "PR-AUC", "PR-AUC 95% CI", "perm p", "ROC-AUC", "Brier"]].round(3).to_string(index=False))
    months2 = np.asarray(res2["index"].to_period("M").astype(str)); y2 = res2["y"].values.astype(int)
    for name in sets_cape:
        if name.startswith("baseline (sparse)"):
            continue
        key = "logistic: " + name; k0 = "logistic: baseline (sparse)"
        ok = res2["scores"][key].notna() & res2["scores"][k0].notna()
        m, lo, hi, p = paired_boot(y2[ok.values], res2["scores"][key][ok].values, res2["scores"][k0][ok].values, months2[ok.values])
        print(f"  AP difference vs sparse baseline: {name}: {m:+.3f} (95% CI {lo:+.3f} to {hi:+.3f}), share <= 0: {p:.2f}")
    # 2024-26: forecast CAPE (a real lead-1 forecast) against forecast rain
    p3 = data[data.period == "2024-26"]
    sets3 = {"baseline (sparse)": base, "baseline + forecast CAPE": base + ["cape_fc1_max"], "forecast rain + 7d rain + season": ["fc1_total_max", "obs_7d_mean", "month_sin", "month_cos"],
             "forecast rain + forecast CAPE + 7d rain + season": ["fc1_total_max", "cape_fc1_max", "obs_7d_mean", "month_sin", "month_cos"]}
    ranks3 = {"1-day forecast rain (lead ~1d)": "fc1_total_max", "1-day forecast CAPE (lead ~1d)": "cape_fc1_max"}
    res3 = run(p3, ["2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01"], feature_sets=sets3, rank_baselines=ranks3)
    o3 = summarize(res3); o3.to_csv("data/processed/instability_models_fc_2024_2026.csv", index=False)
    print(f"\n=== Part B3: 2024-26 only, 1-day forecast CAPE vs forecast rain ({int(o3.n_flood.iloc[0])} test floods) ===")
    print(o3[["model", "n_days", "PR-AUC", "PR-AUC 95% CI", "perm p", "ROC-AUC"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
