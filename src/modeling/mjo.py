"""Madden-Julian Oscillation (MJO) test: does the large-scale intraseasonal state add lead time or skill?

    python -m src.modeling.mjo

Index: NOAA PSL OLR-based MJO Index (OMI), daily PC1, PC2 and amplitude, 1991 to present (a free public text file,
downloaded once to data/external/omi.txt). The BoM RMM file was not used: the BoM site blocks automated access.
OMI for day X uses OLR of day X, so the features here use the OMI value of D-lag with lag >= 1 (what is known before
D). A lag of 7 tests whether a week-old MJO state still carries information, i.e. what an MJO forecast of that lead
could add. OMI in the download ends 2026-06-24; later days drop out of every comparison.

Part A: lead-lag profile of PC1, PC2 and amplitude (percentile on flood days among +/-45-day controls) and flood rate by
        MJO phase sector, with a permutation test that keeps floods per period and calendar month.
Part B: blocked-CV (leave-one-quarter-out) logistic models, baseline + water vapour with and without MJO features,
        paired month-block bootstrap on the difference in PR-AUC.
"""
import os
import urllib.request

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from .improve import BASE, WV, blocked_cv, budget, build_all
from .instability import PERIODS, paired_boot
from .timeseries import flood_days, percentiles, summarise

OMI_URL = "https://psl.noaa.gov/mjo/mjoindex/omi.1x.txt"
OMI_PATH = "data/external/omi.txt"
SECTORS = 8


def load_omi() -> pd.DataFrame:
    if not os.path.exists(OMI_PATH):
        os.makedirs(os.path.dirname(OMI_PATH), exist_ok=True)
        urllib.request.urlretrieve(OMI_URL, OMI_PATH)
    d = pd.read_csv(OMI_PATH, sep=r"\s+", header=None, names=["y", "m", "d", "pc1", "pc2", "amp"])
    d["day"] = pd.to_datetime(dict(year=d.y, month=d.m, day=d.d))
    d = d.set_index("day")[["pc1", "pc2", "amp"]].replace(-999, np.nan)
    d["sector"] = (np.floor((np.arctan2(d.pc2, d.pc1) + np.pi) / (2 * np.pi / SECTORS)).astype(int)) % SECTORS
    return d


def sector_test(omi: pd.DataFrame, lag: int, n_sim: int = 5000, seed: int = 0) -> pd.DataFrame:
    """Flood count by MJO sector (active = amplitude >= 1) vs expected from the share of days, with a permutation p
    for the chi-square statistic when flood dates are shuffled within each period and calendar month."""
    rng = np.random.default_rng(seed)
    cat = pd.Series(np.where(omi.amp >= 1, omi.sector, SECTORS), index=omi.index).shift(lag, freq="D")  # SECTORS = weak
    days, fl = [], []
    for _, _, lab in PERIODS.values():
        l = pd.read_csv(lab, parse_dates=["day"])
        d = pd.date_range(l.day.min(), l.day.max())
        days.append(pd.DataFrame({"day": d, "period": lab, "flood": d.isin(l.loc[l.label_type == "flood", "day"]).astype(int)}))
    t = pd.concat(days).set_index("day")
    t["cat"] = cat.reindex(t.index)
    t = t.dropna(subset=["cat"])
    t["pm"] = t.period + "_" + t.index.to_period("M").astype(str).str[-2:]  # period x calendar month
    ncat = SECTORS + 1
    share = np.bincount(t.cat.astype(int), minlength=ncat) / len(t)

    def chi(cats: np.ndarray, flood: np.ndarray) -> float:
        obs = np.bincount(cats[flood == 1], minlength=ncat)
        exp = flood.sum() * share
        return float(((obs - exp) ** 2 / np.maximum(exp, 1e-9)).sum())

    cats, flood = t.cat.astype(int).values, t.flood.values
    stat = chi(cats, flood)
    pm = t.pm.values
    groups = [np.where(pm == g)[0] for g in np.unique(pm)]
    sims = []
    for _ in range(n_sim):
        f2 = np.zeros_like(flood)
        for ix in groups:
            k = flood[ix].sum()
            if k:
                f2[rng.choice(ix, k, replace=False)] = 1
        sims.append(chi(cats, f2))
    p = float((np.array(sims) >= stat).mean())
    rows = pd.DataFrame({"category": [f"sector {i}" for i in range(SECTORS)] + ["weak (amp<1)"],
                         "days": np.bincount(cats, minlength=ncat), "floods": np.bincount(cats[flood == 1], minlength=ncat)})
    rows["floods_per_100d"] = (100 * rows.floods / rows.days.clip(lower=1)).round(2)
    rows["expected"] = (flood.sum() * share).round(1)
    rows.attrs["p"] = p
    return rows


def main() -> None:
    pd.set_option("display.width", 220, "display.max_columns", 30)
    omi = load_omi()
    print(f"OMI {omi.index.min().date()} to {omi.index.max().date()}; amplitude >= 1 on {100 * (omi.amp >= 1).mean():.0f}% of days")
    floods = [d for d in flood_days() if d <= omi.index.max() + pd.Timedelta(days=1)]
    print(f"{len(floods)} flood days covered")

    # Part A1: lead-lag profile
    rows = []
    for name in ("pc1", "pc2", "amp"):
        for k in (1, 2, 3, 5, 7, 10, 14, 21, 28):
            m, lo, hi, n = summarise(percentiles(omi[name], floods, k))
            rows.append({"series": name, "lag": k, "mean_pct": m, "ci": f"{lo:.2f}-{hi:.2f}", "n": n})
    prof = pd.DataFrame(rows)
    prof.round(3).to_csv("data/processed/mjo_lag_profile.csv", index=False)
    print("\n=== Part A1: percentile of OMI on flood days among +/-45-day controls (0.5 = none) ===")
    print(prof.pivot(index="lag", columns="series", values="mean_pct").round(2).to_string())
    print(prof.pivot(index="lag", columns="series", values="ci").to_string())

    # Part A2: flood rate by phase
    print("\n=== Part A2: floods by MJO sector at lag 1 and 7 days (8 sectors by angle in the PC1-PC2 plane; weak = amplitude < 1) ===")
    for lag in (1, 7, 14):
        t = sector_test(omi, lag)
        print(f"\nlag {lag} d: chi-square permutation p = {t.attrs['p']:.3f} (floods per period-month preserved)")
        print(t.to_string(index=False))

    # Part B: model test
    data = build_all()
    for k in (1, 7):
        for c in ("pc1", "pc2", "amp"):
            data[f"{c}_l{k}"] = omi[c].shift(k, freq="D").reindex(data.index)
    mj = {k: [f"pc1_l{k}", f"pc2_l{k}", f"amp_l{k}"] for k in (1, 7)}
    d = data[~data.excl_strict & data[mj[1] + mj[7]].notna().all(axis=1)].copy()
    sets = {"baseline (rain+season)": BASE, "baseline + MJO lag 1": BASE + mj[1], "baseline + MJO lag 7": BASE + mj[7],
            "baseline + TCWV": WV, "baseline + TCWV + MJO lag 1": WV + mj[1], "baseline + TCWV + MJO lag 7": WV + mj[7],
            "MJO lag 7 + season only": ["month_sin", "month_cos"] + mj[7]}
    scores = {n: blocked_cv(d, c, "flood") for n, c in sets.items()}
    y = d.flood.values; months = np.asarray(d.index.to_period("M").astype(str))
    out = []
    for n, s in scores.items():
        ok = s.notna().values
        out.append({"model": n, "n_days": int(ok.sum()), "n_pos": int(y[ok].sum()), "PR-AUC": average_precision_score(y[ok], s[ok]),
                    "ROC-AUC": roc_auc_score(y[ok], s[ok]), **budget(y[ok], s[ok].values)})
    res = pd.DataFrame(out)
    res.round(3).to_csv("data/processed/mjo_models.csv", index=False)
    print(f"\n=== Part B: blocked CV, same {len(d)} days for every model ({int(y.sum())} floods) ===")
    print(res.round(3).to_string(index=False))
    for a, b in (("baseline + MJO lag 1", "baseline (rain+season)"), ("baseline + MJO lag 7", "baseline (rain+season)"),
                 ("baseline + TCWV + MJO lag 1", "baseline + TCWV"), ("baseline + TCWV + MJO lag 7", "baseline + TCWV")):
        ok = (scores[a].notna() & scores[b].notna()).values
        m, lo, hi, p = paired_boot(y[ok], scores[a].values[ok], scores[b].values[ok], months[ok])
        print(f"  AP diff {a} minus {b}: {m:+.3f} (95% CI {lo:+.3f} to {hi:+.3f}), share <= 0: {p:.2f}")


if __name__ == "__main__":
    main()
