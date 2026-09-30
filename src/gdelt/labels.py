"""Assemble the flood label table from candidate events and manual verdicts.

    python -m src.gdelt.labels data/interim/gdelt_gkg_2015_2016 annotations/event_verdicts_2015_2016.csv

Writes data/processed/flood_labels_2015_2016.csv with one row per confirmed/probable/uncertain
event: (event_id, date, district, lat, lon, flood_type, confidence, verdict, use, n_articles,
n_domains, sources, rain percentiles). `use` is True for confirmed/probable events only.
Verdicts are hand-reviewed (see docs/data-preprocessing.md sections 9-10); lat/lon are the
median of place mentions in the event's articles (approximate, KL is often a city centroid).
Events merged into others (e.g. 7 into 6) and rejected events are dropped.
"""
import sys
from pathlib import Path

import pandas as pd

KEEP = {"confirmed", "probable", "uncertain"}


def build_labels(stem: str, verdict_path: str) -> pd.DataFrame:
    ev = pd.concat(
        [pd.read_parquet(f"{stem}_events.parquet"), pd.read_parquet(f"{stem}_events2.parquet")],
        ignore_index=True,
    ).set_index("event_id")
    v = pd.read_csv(verdict_path)
    v = v[v.verdict.isin(KEEP) & v.event_id.isin(ev.index)].copy()
    j = ev.loc[v.event_id]
    out = pd.DataFrame({
        "event_id": v.event_id.values,
        "date": v.event_date.fillna(pd.Series(j.peak_day.astype(str).values, index=v.index)).values,
        "district": v.district.values,
        "lat": j.lat.round(4).values,
        "lon": j.lon.round(4).values,
        "flood_type": v.flood_type.values,
        "verdict": v.verdict.values,
        "confidence": v.confidence.values,
        "use": v.verdict.isin({"confirmed", "probable"}).values,
        "n_articles": j.n_articles.values,
        "n_domains": j.n_domains.values,
        "sources": j.domains.values,
        "rain_daily_pct": v.rain_daily_pct.values,
        "rain_hourly_pct": v.rain_hourly_pct.values,
        "evidence": v.evidence.values,
    })
    return out.sort_values("date").reset_index(drop=True)


def main(stem: str, verdict_path: str) -> None:
    out = build_labels(stem, verdict_path)
    path = Path("data/processed/flood_labels_2015_2016.csv")
    out.to_csv(path, index=False)
    print(f"{len(out)} rows ({int(out.use.sum())} usable) -> {path}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
