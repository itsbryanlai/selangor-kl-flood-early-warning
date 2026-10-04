"""Time-series diagnostics: which lags matter (superposed epoch / lead-lag) and do floods cluster in time.

    python -m src.modeling.timeseries

Part 1 (lead-lag profile): for each flood day D and each lag k, the percentile of the series value at D-k among the
    same series' values at D'-k for +/-45-day control days D' (flood days +/-3 days removed). 0.5 = no signal. The
    +/-45-day window removes seasonality. CI: bootstrap over flood events. Rain at lag k is the rain total of day D-k
    (k >= 1 is before the flood day); atmosphere series are the 00:00 snapshots (lag 0 = 00:00 on D, still before onset).
Part 2 (window shapes): the same percentile for derived antecedent features (sums, exponentially weighted rain,
    wet-spell length, days since heavy rain, multi-day TCWV statistics, soil moisture).
Part 3 (clustering): do flood days sit closer to other flood days than chance, given the number of floods per
    period and per calendar month? Permutation test.
All three use only existing data on disk.
"""
import numpy as np
import pandas as pd

from .features import build_features
from .instability import PERIODS, part_a  # noqa: F401 - part_a kept for reference
from .water_vapour import wv_features

RNG = np.random.default_rng(0)
LAGS = list(range(0, 15))


def daily_series() -> pd.DataFrame:
    """Daily rain (area max of daily totals) and 00:00 atmospheric snapshots on a continuous daily index."""
    rain = []
    for rain_p, fc, _ in PERIODS.values():
        h = pd.read_parquet(rain_p)
        h["day"] = h.time.dt.normalize()
        d = h.groupby(["point", "day"]).precip_mm.sum().groupby("day").max()
        rain.append(d)
    rain = pd.concat(rain).sort_index()
    rain = rain[~rain.index.duplicated()]
    wv = wv_features()
    s = pd.DataFrame({"rain": rain}).join(wv[["tcwv_00", "rh850_00", "soil_00"]], how="outer")
    return s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"))


def flood_days() -> list[pd.Timestamp]:
    out = []
    for _, _, lab in PERIODS.values():
        l = pd.read_csv(lab, parse_dates=["day"])
        out += list(l.loc[l.label_type == "flood", "day"])
    return sorted(out)


def percentiles(series: pd.Series, floods: list[pd.Timestamp], lag: int = 0, window: int = 45) -> np.ndarray:
    """Percentile of series[D-lag] among series[D'-lag] over control days D' within +/-window of each flood D."""
    buf = {d + pd.Timedelta(days=k) for d in floods for k in range(-3, 4)}
    sl = series.shift(lag)
    out = []
    for d0 in floods:
        v = sl.get(d0, np.nan)
        ctrl = [d for d in pd.date_range(d0 - pd.Timedelta(days=window), d0 + pd.Timedelta(days=window)) if d not in buf]
        cv = sl.reindex(ctrl).dropna().values
        if np.isnan(v) or len(cv) < 20:
            out.append(np.nan)
        else:
            out.append((cv < v).mean() + 0.5 * (cv == v).mean())
    return np.array(out)


def summarise(p: np.ndarray, n_boot: int = 2000) -> tuple[float, float, float, int]:
    p = p[~np.isnan(p)]
    b = [RNG.choice(p, len(p)).mean() for _ in range(n_boot)]
    return p.mean(), np.percentile(b, 2.5), np.percentile(b, 97.5), len(p)


def derived(s: pd.DataFrame) -> pd.DataFrame:
    """Antecedent features for day D from rain through D-1 and 00:00 atmosphere on D (series shifted so row D is usable)."""
    f = pd.DataFrame(index=s.index)
    r = s.rain.shift(1)  # row D holds rain of D-1
    for n in (1, 2, 3, 5, 7, 14, 30):
        f[f"rain_sum_{n}d"] = r.rolling(n, min_periods=n).sum()
    for hl in (1, 2, 4, 8, 16):
        f[f"rain_ewm_hl{hl}d"] = r.ewm(halflife=hl, min_periods=hl).mean()
    wet = (r > 1).astype(float).where(r.notna())
    f["wet_days_7d"] = wet.rolling(7, min_periods=7).sum()
    spell = []
    run = 0
    for v in wet:
        run = np.nan if np.isnan(v) else (run + 1 if v == 1 else 0) if not np.isnan(run) else (1 if v == 1 else 0)
        spell.append(run)
    f["wet_spell_len"] = spell
    since = []
    c = np.nan
    for v in r:
        if np.isnan(v):
            c = np.nan
        elif v >= 20:
            c = 0
        elif not np.isnan(c):
            c += 1
        since.append(c)
    f["days_since_20mm"] = np.array(since)
    f["dry_days_7d"] = 7 - f.wet_days_7d
    t = s.tcwv_00
    for n in (3, 7):
        f[f"tcwv_mean_{n}d"] = t.rolling(n, min_periods=n).mean()
    f["tcwv_max_3d"] = t.rolling(3, min_periods=3).max()
    f["tcwv_min_7d"] = t.rolling(7, min_periods=7).min()
    f["tcwv_slope_3d"] = (t - t.shift(2)) / 2
    f["tcwv_chg_1d"] = t - t.shift(1)
    f["tcwv_hi_days_7d"] = (t > t.quantile(0.75)).astype(float).where(t.notna()).rolling(7, min_periods=7).sum()
    f["tcwv_dev_from_14d"] = t - t.shift(1).rolling(14, min_periods=10).mean()
    f["soil_00"] = s.soil_00
    f["soil_mean_3d"] = s.soil_00.rolling(3, min_periods=3).mean()
    f["soil_chg_3d"] = s.soil_00 - s.soil_00.shift(3)
    f["rh850_00"] = s.rh850_00
    f["rh850_mean_3d"] = s.rh850_00.rolling(3, min_periods=3).mean()
    return f


def clustering(floods: list[pd.Timestamp], n_sim: int = 5000) -> None:
    spans = {}
    for tag, (_, _, lab) in PERIODS.items():
        l = pd.read_csv(lab, parse_dates=["day"])
        spans[tag] = (l.day.min(), l.day.max(), l.loc[l.label_type == "flood", "day"].tolist())
    all_days = {t: pd.date_range(a, b) for t, (a, b, _) in spans.items()}
    print("\nFlood days per period:", {t: len(v[2]) for t, v in spans.items()})
    gaps = np.diff(np.array(floods, dtype="datetime64[D]")).astype(int)
    print("Gaps between consecutive flood days (days):", gaps.tolist())
    print(f"Median gap {np.median(gaps):.0f}; gaps <= 3 d: {(gaps <= 3).sum()}, <= 7 d: {(gaps <= 7).sum()}, <= 14 d: {(gaps <= 14).sum()}, <= 30 d: {(gaps <= 30).sum()}")

    def stat(per: dict[str, np.ndarray]) -> dict:
        res = {w: 0 for w in (3, 7, 14, 30)}
        for v in per.values():
            v = np.sort(v)
            for i, d in enumerate(v):
                nb = [abs(d - x) for j, x in enumerate(v) if j != i]
                for w in res:
                    res[w] += int(len(nb) and min(nb) <= w)
        return res

    obs = stat({t: np.array([(d - spans[t][0]).days for d in v[2]]) for t, v in spans.items()})
    # null A: uniform over the days of each period; null B: keep the number of floods per calendar month inside each period
    simA = {w: [] for w in obs}; simB = {w: [] for w in obs}
    for _ in range(n_sim):
        a, b = {}, {}
        for t, (lo, hi, fl) in spans.items():
            days = all_days[t]
            a[t] = RNG.choice(len(days), len(fl), replace=False)
            months = pd.Series(days.month, index=np.arange(len(days)))
            pick = []
            for m, k in pd.Series([d.month for d in fl]).value_counts().items():
                pool = months[months == m].index.values
                pick += list(RNG.choice(pool, min(k, len(pool)), replace=False))
            b[t] = np.array(pick)
        sa, sb = stat(a), stat(b)
        for w in obs:
            simA[w].append(sa[w]); simB[w].append(sb[w])
    print("\nFloods with another flood within +/-w days (observed vs random placement)")
    print(f"{'w':>4} {'observed':>9} {'null A mean':>12} {'p(A)':>7} {'null B mean':>12} {'p(B)':>7}")
    rows = []
    for w in obs:
        pa = (np.array(simA[w]) >= obs[w]).mean(); pb = (np.array(simB[w]) >= obs[w]).mean()
        print(f"{w:>4} {obs[w]:>9} {np.mean(simA[w]):>12.1f} {pa:>7.3f} {np.mean(simB[w]):>12.1f} {pb:>7.3f}")
        rows.append({"window_days": w, "observed": obs[w], "null_uniform_mean": np.mean(simA[w]), "p_uniform": pa,
                     "null_month_matched_mean": np.mean(simB[w]), "p_month_matched": pb})
    pd.DataFrame(rows).round(4).to_csv("data/processed/timeseries_clustering.csv", index=False)
    # conditional rate: P(flood day | a flood in the previous 1..w days) vs unconditional, over each period's days
    print("\nConditional flood rate: flood day given a flood in the previous w days (all days of the periods)")
    for w in (7, 14, 30):
        num = den = 0
        base_n = base_d = 0
        for t, (lo, hi, fl) in spans.items():
            y = pd.Series(0, index=all_days[t]); y[fl] = 1
            prev = y.shift(1).rolling(w, min_periods=1).max().fillna(0).astype(bool)
            num += int(y[prev].sum()); den += int(prev.sum()); base_n += int(y.sum()); base_d += len(y)
        print(f"  w={w:>2}: {num}/{den} = {100 * num / max(den, 1):.1f}% vs unconditional {base_n}/{base_d} = {100 * base_n / base_d:.1f}%")


def main() -> None:
    pd.set_option("display.width", 220, "display.max_columns", 30)
    s = daily_series()
    floods = [d for d in flood_days()]
    print(f"{len(floods)} flood days; series {s.index.min().date()} to {s.index.max().date()}")
    rows = []
    for name in ("rain", "tcwv_00", "rh850_00", "soil_00"):
        for k in LAGS:
            m, lo, hi, n = summarise(percentiles(s[name], floods, k))
            rows.append({"series": name, "lag_days": k, "mean_pct": m, "ci_lo": lo, "ci_hi": hi, "n_events": n})
    prof = pd.DataFrame(rows)
    prof.round(3).to_csv("data/processed/timeseries_lag_profile.csv", index=False)
    print("\n=== Part 1: lead-lag profile (mean percentile of flood days among +/-45-day controls; 0.5 = no signal) ===")
    piv = prof.pivot(index="lag_days", columns="series", values="mean_pct").round(2)
    ci = prof.assign(ci=lambda x: x.ci_lo.round(2).astype(str) + "-" + x.ci_hi.round(2).astype(str)).pivot(index="lag_days", columns="series", values="ci")
    print(pd.concat({"pct": piv, "95% CI": ci}, axis=1).to_string())
    # day-to-day change (does the value jump into the flood day, i.e. is it a trend or a state?)
    f = derived(s)
    rows = []
    for c in f.columns:
        m, lo, hi, n = summarise(percentiles(f[c], floods, 0))
        rows.append({"feature": c, "n_events": n, "mean_pct": m, "ci_lo": lo, "ci_hi": hi, "dist_from_0.5": abs(m - 0.5)})
    d = pd.DataFrame(rows).sort_values("dist_from_0.5", ascending=False)
    d.round(3).to_csv("data/processed/timeseries_derived_features.csv", index=False)
    print("\n=== Part 2: derived antecedent features (percentile on flood days vs +/-45-day controls) ===")
    print(d.round(3).to_string(index=False))
    clustering(floods)


if __name__ == "__main__":
    main()
