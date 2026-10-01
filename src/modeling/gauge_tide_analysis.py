"""Do rain gauges and predicted tide add anything? (2015-2016 and 2024-2026 labels)

    python -m src.modeling.gauge_tide_analysis

Part 1: gauge vs ERA5 (agreement, flood-day discrimination). Part 2: tide on flood days. Part 3: models
with and without the tide feature (2024-26 expanding windows; train 2015-16 -> test 2024-26).
"""
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from .evaluate import OBS, SPARSE, make_dataset, run, run_transfer, summarize
from .features import build_features

PAIRS = {"2015-16": ("data/interim/rain_hourly_2015-02-01_2016-12-31.parquet", "data/processed/daily_labels_2015_2016.csv"),
         "2021-23": ("data/interim/rain_hourly_2020-12-01_2023-12-31.parquet", "data/processed/daily_labels_v1_2021_2023.csv"),
         "2024-26": ("data/interim/rain_hourly_2024-01-01_2026-09-30.parquet", "data/processed/daily_labels_v1_2024_2026.csv")}
pd.set_option("display.width", 250, "display.max_columns", 30)


def era5_daily(path: str) -> pd.DataFrame:
    h = pd.read_parquet(path)
    h["day"] = h.time.dt.normalize()
    d = h.groupby(["point", "day"]).precip_mm.sum().unstack(0)
    d["era5_max"] = d.max(axis=1)
    return d


def tide_daily() -> pd.DataFrame:
    t = pd.read_parquet("data/interim/tide_kelang_predicted_hourly.parquet").tide_m
    g = t.groupby(t.index.normalize())
    return pd.DataFrame({"tide_hw_max": g.max(), "tide_lw_min": g.min()})


def main() -> None:
    gauge = pd.read_parquet("data/interim/gauge_daily_2015-01-01_2026-09-30.parquet").pivot(index="day", columns="station", values="mm")
    gauge["gauge_max"] = gauge[["subang", "klia"]].max(axis=1, skipna=True).where(gauge[["subang", "klia"]].notna().any(axis=1))
    tide = tide_daily()
    print("=== Part 1a: gauge vs ERA5 (daily totals) ===")
    for tag, (rp, lp) in PAIRS.items():
        e = era5_daily(rp)
        j = e.join(gauge, how="inner")
        for g, ep in (("subang", "shah_alam"), ("klia", "sepang")):
            x = j[[g, ep]].dropna()
            lag = {k: x[g].corr(x[ep].shift(k)) for k in (-1, 0, 1)}
            heavy = x[g] >= 30
            print(f"{tag} {g} vs ERA5 {ep}: n={len(x)} corr={lag[0]:.2f} (lag -1/+1: {lag[-1]:.2f}/{lag[1]:.2f}) "
                  f"mean gauge={x[g].mean():.1f} ERA5={x[ep].mean():.1f} | gauge>=30mm days: {int(heavy.sum())}, ERA5>=30 on those: {(x.loc[heavy, ep] >= 30).mean():.2f}")
    print("\n=== Part 1b: flood-day discrimination, same days (scheme all; same-day rain as score) ===")
    gmax = gauge[["subang", "klia"]].max(axis=1).where(gauge[["subang", "klia"]].notna().any(axis=1))
    frames = []
    for tag, (rp, lp) in PAIRS.items():
        lab = pd.read_csv(lp, parse_dates=["day"]).set_index("day")
        lab = lab[~lab.label_type.isin(["near_event", "uncertain_event"])]
        d = lab.join(era5_daily(rp)[["era5_max"]]).join(tide)
        d["gauge_same_date"] = gmax.reindex(d.index)
        d["gauge_next_morning"] = gmax.shift(-1, freq="D").reindex(d.index)
        d["y"] = (d.label_type == "flood").astype(int)
        d["period"] = tag
        frames.append(d)
    allp = pd.concat(frames)
    ok = allp.dropna(subset=["era5_max", "gauge_same_date", "gauge_next_morning"])
    rows = []
    for per, grp in [("pooled", ok)] + list(ok.groupby("period")):
        for name in ("era5_max", "gauge_same_date", "gauge_next_morning", "tide_hw_max"):
            rows.append({"period": per, "score": name, "n_days": len(grp), "n_flood": int(grp.y.sum()), "base": round(grp.y.mean(), 4),
                         "AP": round(average_precision_score(grp.y, grp[name]), 3), "ROC": round(roc_auc_score(grp.y, grp[name]), 3),
                         "median_flood": round(grp.loc[grp.y == 1, name].median(), 1), "median_other": round(grp.loc[grp.y == 0, name].median(), 1)})
    print(f"flood days with gauge data: {int(ok.y.sum())} of {int(allp.y.sum())}")
    print(pd.DataFrame(rows).to_string(index=False))
    print("\n=== Part 2: predicted tide on flood days (daily high-water vs all days 2015-2026) ===")
    allhw = tide.tide_hw_max
    q90, q75 = allhw.quantile(0.9), allhw.quantile(0.75)
    print(f"daily HW quantiles: median {allhw.median():.2f}, p75 {q75:.2f}, p90 {q90:.2f}, max {allhw.max():.2f} m")
    out = []
    for tag, (rp, lp) in PAIRS.items():
        lab = pd.read_csv(lp, parse_dates=["day"]).set_index("day")
        fl = lab[lab.label_type == "flood"].join(tide)
        ver = pd.read_csv({"2015-16": "annotations/event_verdicts_2015_2016.csv", "2021-23": "annotations/event_verdicts_2021_2023.csv",
                           "2024-26": "annotations/event_verdicts_2024_2026.csv"}[tag])
        ver = ver[ver.verdict.isin(["confirmed", "probable"])].set_index(pd.to_datetime(ver[ver.verdict.isin(["confirmed", "probable"])].event_date))
        fl = fl.join(ver[["flood_type", "district"]].loc[~ver.index.duplicated()], how="left")
        fl["hw_pct"] = fl.tide_hw_max.map(lambda v: (allhw < v).mean())
        out.append(fl[["tide_hw_max", "hw_pct", "flood_type", "district"]].assign(period=tag))
    f = pd.concat(out)
    print(f.round(2).to_string())
    print(f"flood days with HW above p75: {(f.tide_hw_max > q75).mean():.2f}, above p90: {(f.tide_hw_max > q90).mean():.2f} (expected 0.25 / 0.10 by chance)")
    print("\n=== Part 3: models with vs without the predicted-tide feature ===")
    sets = {"sparse (forecast+7d rain+monsoon)": SPARSE, "sparse + tide": SPARSE + ["tide_hw_max"],
            "obs": OBS, "obs + tide": OBS + ["tide_hw_max"]}
    ranks = {"tide high-water only (known in advance)": "tide_hw_max", "1-day forecast rain (lead ~1d)": "fc1_total_max"}
    feats = build_features(PAIRS["2024-26"][0], "data/interim/fcst_hourly_2024-01-01_2026-09-30.parquet").join(tide)
    labels = pd.read_csv(PAIRS["2024-26"][1])
    for scheme in ("all", "labeled"):
        data = make_dataset(feats, labels, scheme)
        res = run(data, ["2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01"], feature_sets=sets, rank_baselines=ranks)
        o = summarize(res)
        print(f"\n2024-26 expanding windows, scheme={scheme}")
        print(o[["model", "n_days", "base_rate", "PR-AUC", "PR-AUC 95% CI", "perm p", "ROC-AUC", "Brier"]].round(3).to_string(index=False))
        o.to_csv(f"data/processed/model_results_tide_2024_2026_{scheme}.csv", index=False)
    f_old = build_features(PAIRS["2015-16"][0]).join(tide)
    l_old = pd.read_csv(PAIRS["2015-16"][1])
    sets_t = {"obs": OBS, "obs + tide": OBS + ["tide_hw_max"]}
    for scheme in ("all", "labeled"):
        res = run_transfer(make_dataset(f_old, l_old, scheme), make_dataset(feats, labels, scheme), feature_sets=sets_t, rank_baselines=ranks)
        o = summarize(res)
        print(f"\ntransfer train 2015-16 -> test 2024-26, scheme={scheme}")
        print(o[["model", "n_days", "n_flood", "base_rate", "PR-AUC", "PR-AUC 95% CI", "perm p", "ROC-AUC"]].round(3).to_string(index=False))
        o.to_csv(f"data/processed/model_results_tide_transfer_{scheme}.csv", index=False)


if __name__ == "__main__":
    main()
