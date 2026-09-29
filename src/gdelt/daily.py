"""Daily Selangor/KL flood-article series and spike detection.

    python -m src.gdelt.daily data/interim/gdelt_gkg_2015_2016_articles.parquet

Tiers (both restricted to articles mentioning Selangor or KL):
  loose  - any flood / heavy-rain / monsoon theme (everything in the export)
  strict - flood theme within STRICT_DIST chars of a Selangor/KL place, non-aggregator domain
Dates are Malaysia local (GDELT DATE is UTC, +8h) and are publish dates, not event dates.
"""
import sys
from pathlib import Path

import pandas as pd

STRICT_DIST = 300
AGGREGATORS = {"reports.pr-inside.com", "forums.asiaone.com"}


def daily_series(articles: pd.DataFrame) -> pd.DataFrame:
    a = articles[articles.has_target].copy()
    a["day"] = (a["date"] + pd.Timedelta(hours=8)).dt.normalize()
    a["strict"] = (
        a.flood
        & (a.min_flood_loc_dist <= STRICT_DIST)
        & ~a.domain.isin(AGGREGATORS)
    )
    s = a[a.strict]
    out = pd.DataFrame({
        "n_loose": a.groupby("day").size(),
        "n_strict": s.groupby("day").size(),
        "n_strict_my": s[s.my_domain].groupby("day").size(),
        "n_strict_domains": s.groupby("day").domain.nunique(),
        "n_strict_selangor": s[s.has_selangor].groupby("day").size(),
        "n_strict_kl": s[s.has_kl].groupby("day").size(),
    })
    full = pd.date_range(out.index.min(), out.index.max(), freq="D", name="day")
    return out.reindex(full).fillna(0).astype(int)


def detect_spikes(d: pd.DataFrame, col="n_strict_my", window=61, z=3.5, min_count=4) -> pd.DataFrame:
    """Robust z-score vs a centered rolling median/MAD baseline."""
    x = d[col]
    med = x.rolling(window, center=True, min_periods=15).median()
    mad = (x - med).abs().rolling(window, center=True, min_periods=15).median()
    scale = (1.4826 * mad).clip(lower=1.0)
    d = d.copy()
    d["baseline"] = med
    d["z"] = (x - med) / scale
    d["spike"] = (d.z >= z) & (x >= min_count)
    return d


def main(path: str, out_dir: str = "data/interim") -> None:
    d = detect_spikes(daily_series(pd.read_parquet(path)))
    out = Path(out_dir) / (Path(path).stem.replace("_articles", "") + "_daily.parquet")
    d.to_parquet(out)
    print(f"{len(d)} days, {int(d.spike.sum())} spike days -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
