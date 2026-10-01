"""Options to improve the model with data already collected.

    python -m src.modeling.improve

Tests, on the existing 40 flood days:
  1. News precursors: heavy-rain/monsoon/warning-type GDELT articles about Selangor/KL published before 00:00 on D
     (human/NWP warnings reach the news before the flood), normalised by the trailing 60-day mean.
  2. A 2-day alert window: positive if a flood occurs on D or D+1 (label dates are only good to about +/-1 day).
  3. Alert-budget metrics: share of floods caught when only the top 5/10/20% highest-scored days raise an alert.
  4. Blocked cross-validation (leave-one-quarter-out with a 7-day purge) so that all 40 floods are test floods.
  5. A fit-free composite: average rank of pre-specified indicators.
"""
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from .evaluate import EXCLUDE_ALL, OBS, _model
from .features import build_features
from .water_vapour import wv_features

PERIODS = {
    "2015-16": ("data/interim/rain_hourly_2015-02-01_2016-12-31.parquet", None, "data/processed/daily_labels_2015_2016.csv", "data/interim/gdelt_gkg_2015_2016_articles.parquet"),
    "2021-23": ("data/interim/rain_hourly_2020-12-01_2023-12-31.parquet", None, "data/processed/daily_labels_v1_2021_2023.csv", "data/interim/gdelt_gkg_v1_2021_2023_articles.parquet"),
    "2024-26": ("data/interim/rain_hourly_2024-01-01_2026-09-30.parquet", "data/interim/fcst_hourly_2024-01-01_2026-09-30.parquet", "data/processed/daily_labels_v1_2024_2026.csv", "data/interim/gdelt_gkg_v1_2024_2026_articles.parquet"),
}
BASE = ["obs_1d_total_max", "obs_7d_mean", "month_sin", "month_cos"]
WV = BASE + ["tcwv_00", "tcwv_anom_00"]
NEWS = ["news_warn_ratio_d1", "news_any_ratio_d1"]


def news_features(art_path: str) -> pd.DataFrame:
    """Daily counts of target-place articles published before 00:00 local on D, normalised by the trailing 60-day mean."""
    a = pd.read_parquet(art_path)
    a = a[a.has_target].copy()
    a["day"] = (a["date"] + pd.Timedelta(hours=8)).dt.normalize()
    warn = a[(a.heavy_rain | a.monsoon | a.get("torrential_rain", False)) & ~a.flood]  # rain/monsoon stories without a flood theme
    d = pd.DataFrame({"warn": warn.groupby("day").size(), "any": a.groupby("day").size()})
    d = d.reindex(pd.date_range(d.index.min(), d.index.max(), freq="D")).fillna(0)
    out = pd.DataFrame(index=d.index)
    for c in ("warn", "any"):
        prev = d[c].shift(1)  # day D-1 published before 00:00 on D
        trail = d[c].shift(2).rolling(60, min_periods=20).mean()
        out[f"news_{c}_ratio_d1"] = (prev + 1) / (trail + 1)
    return out


def build_all() -> pd.DataFrame:
    wv = wv_features()
    parts = []
    for tag, (rain, fc, lab, art) in PERIODS.items():
        f = build_features(rain, fc).join(wv, how="left").join(news_features(art), how="left")
        lb = pd.read_csv(lab, parse_dates=["day"]).set_index("day")
        d = f.join(lb[["label_type"]], how="inner")
        d["flood"] = (d.label_type == "flood").astype(int)
        d["period"] = tag
        parts.append(d)
    data = pd.concat(parts).sort_index()
    data = data[data.tcwv_missing < 0.5]
    # 2-day alert window: positive if a flood occurs on D or D+1
    nxt = data.flood.shift(-1, freq="D").reindex(data.index).fillna(0)
    data["flood_tol"] = ((data.flood + nxt) > 0).astype(int)
    data["excl_strict"] = data.label_type.isin(EXCLUDE_ALL)
    # tolerant scheme keeps the day before a flood (it is a positive); other near-event days stay excluded
    data["excl_tol"] = data.label_type.isin(EXCLUDE_ALL) & (data.flood_tol == 0)
    return data


def blocked_cv(data: pd.DataFrame, cols: list[str], ycol: str, C: float = 0.1, purge: int = 7) -> pd.Series:
    q = data.index.to_period("Q")
    s = pd.Series(np.nan, index=data.index)
    for qq in q.unique():
        te = q == qq
        lo, hi = data.index[te].min() - pd.Timedelta(days=purge), data.index[te].max() + pd.Timedelta(days=purge)
        tr = (data.index < lo) | (data.index > hi)
        if data.loc[tr, ycol].sum() < 3:
            continue  # score every quarter, including those without floods, so all models use the same days
        m = _model(cols, C).fit(data.loc[tr, cols], data.loc[tr, ycol])
        s[te] = m.predict_proba(data.loc[te, cols])[:, 1]
    return s


def budget(y: np.ndarray, s: np.ndarray, fractions=(0.05, 0.10, 0.20)) -> dict:
    out = {}
    for f in fractions:
        thr = np.quantile(s, 1 - f)
        alert = s >= thr
        out[f"capture@{int(f * 100)}%"] = (y[alert].sum() / y.sum()) if y.sum() else np.nan
    return out


def boot_ap(y, s, months, n=1000, seed=0):
    rng = np.random.default_rng(seed)
    u = pd.Series(months).unique(); idx = {m: np.where(months == m)[0] for m in u}
    b = []
    for _ in range(n):
        ii = np.concatenate([idx[u[k]] for k in rng.choice(len(u), len(u))])
        if y[ii].sum():
            b.append(average_precision_score(y[ii], s[ii]))
    return np.percentile(b, 2.5), np.percentile(b, 97.5)


def evaluate_sets(data, sets, ycol, excl, title):
    d = data[~data[excl]].copy()
    rows = []
    for name, cols in sets.items():
        if isinstance(cols, str) and cols == "composite":
            # fit-free: average of within-period ranks of pre-specified indicators (rh850 exists from 2021 only)
            s = pd.concat([d.groupby("period")[c].rank(pct=True) for c in ("tcwv_00", "obs_1d_total_max", "rh850_00")], axis=1).mean(axis=1, skipna=True)
        elif isinstance(cols, str):
            s = d[cols].fillna(d[cols].median()).rank(pct=True)  # single-indicator rank baseline
        else:
            s = blocked_cv(d, cols, ycol)
        ok = s.notna()
        y = d.loc[ok, ycol].values; sc = s[ok].values
        lo, hi = boot_ap(y, sc, np.asarray(d.index[ok].to_period("M").astype(str)))
        rows.append({"model": name, "n_days": int(ok.sum()), "n_pos": int(y.sum()), "base": y.mean(), "PR-AUC": average_precision_score(y, sc),
                     "CI": f"{lo:.3f}-{hi:.3f}", "ROC-AUC": roc_auc_score(y, sc), **budget(y, sc)})
    out = pd.DataFrame(rows)
    print(f"\n=== {title} ===")
    print(out.round(3).to_string(index=False))
    return out


def part_a_news(data):
    from .instability import part_a
    labels = {t: pd.read_csv(v[2], parse_dates=["day"]) for t, v in PERIODS.items()}
    print("\n=== Part A: news precursor percentile on flood days (+/-45-day controls; 0.5 = none) ===")
    print(part_a(data[NEWS + ["tcwv_00", "obs_1d_total_max"]], labels).round(3).to_string(index=False))


def main() -> None:
    pd.set_option("display.width", 250, "display.max_columns", 30)
    data = build_all()
    print(f"{len(data)} days; floods {int(data.flood.sum())}; tolerant positives {int(data.flood_tol.sum())}")
    part_a_news(data)
    sets = {"climatology proxy: month only": ["month_sin", "month_cos"], "baseline (rain+season)": BASE,
            "baseline + TCWV": WV, "baseline + news precursors": BASE + NEWS, "baseline + TCWV + news precursors": WV + NEWS,
            "rank: tcwv_00 alone": "tcwv_00", "rank: yesterday's rain alone": "obs_1d_total_max", "composite rank (tcwv_00, yesterday rain, rh850)": "composite"}
    d = data.copy()
    # rh850 only from 2021; composite ranks within the available subset
    r1 = evaluate_sets(d, sets, "flood", "excl_strict", "Blocked CV (leave-one-quarter-out, 7-day purge), strict day label, all 40 floods are test floods")
    r2 = evaluate_sets(d, sets, "flood_tol", "excl_tol", "Blocked CV, 2-day alert window (flood on D or D+1)")
    r1.to_csv("data/processed/improve_blockedcv_strict.csv", index=False); r2.to_csv("data/processed/improve_blockedcv_window.csv", index=False)


if __name__ == "__main__":
    main()
