"""Expanding-window temporal evaluation of flood early-warning scores on daily labels.

Label schemes (y=1 on hand-verified flood days):
  all      - every day that is not near_event/uncertain_event counts as negative (pessimistic: missed
             floods and heavy-rain days without a flood report count against the model)
  labeled  - only days with a hand/rule label: flood, easy/moderate/hard negatives (optimistic: heavy-rain
             days without a verdict, the hardest negatives, are absent)
Folds: train on all days before a cutoff, test on the next block; test predictions are pooled.
Metrics: PR-AUC (average precision) with a month-block bootstrap CI and a permutation p-value,
ROC-AUC, and CSI/POD/FAR for an alert rule fixed on the training data.
"""
import warnings

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

EXCLUDE_ALL = {"near_event", "uncertain_event"}
NEG_LABELED = {"easy_negative", "moderate_rain_negative", "hard_news_negative"}
OBS = ["obs_1d_total_mean", "obs_1d_total_max", "obs_1d_hourly_max", "obs_3d_mean", "obs_7d_mean",
       "obs_14d_mean", "obs_30d_mean", "obs_wet_days_7d", "month_sin", "month_cos", "ne_monsoon"]
FC = ["fc1_total_mean", "fc1_total_max", "fc1_hourly_max"]
NOW = ["nowcast_total_max", "nowcast_hourly_max"]
SPARSE = ["fc1_total_max", "obs_7d_mean", "ne_monsoon"]  # chosen a priori (forecast, antecedent wetness, season), not tuned
FEATURE_SETS = {"obs (lead 1d, no forecast)": OBS, "obs+forecast (lead ~1d)": OBS + FC,
                "sparse: forecast+7d rain+monsoon (lead ~1d)": SPARSE, "obs+same-day rain (lead 0)": OBS + NOW}
RANK_BASELINES = {"same-day ERA5 rain (lead 0, detection)": "nowcast_total_max",
                  "1-day forecast rain (lead ~1d)": "fc1_total_max",
                  "2-day forecast rain (lead ~2d)": "fc2_total_max",
                  "yesterday's rain (lead 1d)": "obs_1d_total_max"}


def make_dataset(features: pd.DataFrame, daily_labels: pd.DataFrame, scheme: str) -> pd.DataFrame:
    lab = daily_labels.set_index(pd.to_datetime(daily_labels.day))[["label_type"]]
    d = features.join(lab, how="inner")
    if scheme == "all":
        d = d[~d.label_type.isin(EXCLUDE_ALL)]
    elif scheme == "labeled":
        d = d[d.label_type.isin(NEG_LABELED | {"flood"})]
    else:
        raise ValueError(scheme)
    d["y"] = (d.label_type == "flood").astype(int)
    return d


def expanding_folds(index: pd.DatetimeIndex, cutoffs: list[str]):
    edges = [pd.Timestamp(c) for c in cutoffs] + [index.max() + pd.Timedelta(days=1)]
    for a, b in zip(edges[:-1], edges[1:]):
        yield index < a, (index >= a) & (index < b)


def _model(cols, C):
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=C, max_iter=2000))


def _csi(y, alert):
    hits, fa, miss = int((y & alert).sum()), int((~y & alert).sum()), int((y & ~alert).sum())
    return {"hits": hits, "false_alarms": fa, "misses": miss,
            "CSI": hits / max(hits + fa + miss, 1), "POD": hits / max(hits + miss, 1), "FAR": fa / max(hits + fa, 1)}


def _best_threshold(score, y):
    """Threshold maximising CSI on training data (candidate cut points are training scores)."""
    best, thr = -1, np.inf
    for t in np.unique(np.quantile(score, np.linspace(0.5, 0.995, 60))):
        c = _csi(y, score >= t)["CSI"]
        if c > best:
            best, thr = c, t
    return thr


warnings.filterwarnings("ignore")


def run(data: pd.DataFrame, cutoffs: list[str], C: float = 0.1) -> dict:
    scores = {}
    y_all = data.y.values.astype(bool)
    alerts = {}
    def collect(name, fn):
        s = pd.Series(np.nan, index=data.index); a = pd.Series(0.0, index=data.index)
        for tr, te in expanding_folds(data.index, cutoffs):
            if data.y[tr].sum() < 2:
                continue
            s[te], thr = fn(tr, te)
            a[te] = (s[te] >= thr).astype(float)
        scores[name], alerts[name] = s, a.astype(bool)
    # climatology: month base rate learned on training days
    def clim(tr, te):
        rate = data[tr].groupby(data[tr].index.month).y.mean()
        base = data[tr].y.mean()
        s = pd.Series(data[te].index.month.map(rate).fillna(base).values, index=data[te].index)
        return s, np.quantile(rate.values, 0.75)
    collect("climatology (month base rate)", clim)
    for name, col in RANK_BASELINES.items():
        def rank(tr, te, col=col):
            x = data[col]
            thr = _best_threshold(x[tr].fillna(x[tr].median()).values, data.y[tr].values.astype(bool))
            return x[te].fillna(x[tr].median()), thr
        collect(name, rank)
    for name, cols in FEATURE_SETS.items():
        def fit(tr, te, cols=cols):
            m = _model(cols, C).fit(data.loc[tr, cols], data.y[tr])
            p_tr = m.predict_proba(data.loc[tr, cols])[:, 1]
            thr = _best_threshold(p_tr, data.y[tr].values.astype(bool))
            return pd.Series(m.predict_proba(data.loc[te, cols])[:, 1], index=data[te].index), thr
        collect("logistic: " + name, fit)
    return {"scores": scores, "alerts": alerts, "y": data.y, "index": data.index}


def summarize(res: dict, n_boot: int = 2000, n_perm: int = 2000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    y = res["y"]
    rows = []
    months = res["index"].to_period("M")
    for name, s in res["scores"].items():
        ok = s.notna()
        yy, ss, mm = y[ok].values, s[ok].values, months[ok]
        ap = average_precision_score(yy, ss)
        uniq = pd.Series(mm).unique()
        idx_by_m = {m: np.where(mm == m)[0] for m in uniq}
        boots = []
        for _ in range(n_boot):
            pick = rng.choice(len(uniq), len(uniq))
            ii = np.concatenate([idx_by_m[uniq[k]] for k in pick])
            if yy[ii].sum() > 0:
                boots.append(average_precision_score(yy[ii], ss[ii]))
        perm = np.mean([average_precision_score(rng.permutation(yy), ss) >= ap for _ in range(n_perm)])
        c = _csi(yy.astype(bool), res["alerts"][name][ok].values)
        prob = name.startswith(("logistic", "climatology", "transfer"))
        rows.append({"Brier": brier_score_loss(yy, ss) if prob else np.nan, "model": name, "n_days": int(ok.sum()), "n_flood": int(yy.sum()), "base_rate": yy.mean(),
                     "PR-AUC": ap, "PR-AUC 95% CI": f"{np.percentile(boots, 2.5):.3f}-{np.percentile(boots, 97.5):.3f}",
                     "perm p": perm, "ROC-AUC": roc_auc_score(yy, ss), **{k: c[k] for k in ("hits", "false_alarms", "misses", "CSI", "POD", "FAR")}})
    return pd.DataFrame(rows)


def run_transfer(train: pd.DataFrame, test: pd.DataFrame, C: float = 0.1) -> dict:
    """Train on one period, score another (cross-period test). Same outputs as run()."""
    scores, alerts = {}, {}
    ytr = train.y.values.astype(bool)
    for name, cols in {k: v for k, v in FEATURE_SETS.items() if not set(v) & set(FC)}.items():
        m = _model(cols, C).fit(train[cols], train.y)
        thr = _best_threshold(m.predict_proba(train[cols])[:, 1], ytr)
        p = pd.Series(m.predict_proba(test[cols])[:, 1], index=test.index)
        scores["transfer logistic: " + name], alerts["transfer logistic: " + name] = p, p >= thr
    for name, col in {k: v for k, v in RANK_BASELINES.items() if not v.startswith("fc")}.items():
        thr = _best_threshold(train[col].fillna(train[col].median()).values, ytr)
        x = test[col].fillna(train[col].median())
        scores[name], alerts[name] = x, x >= thr
    return {"scores": scores, "alerts": alerts, "y": test.y, "index": test.index}
