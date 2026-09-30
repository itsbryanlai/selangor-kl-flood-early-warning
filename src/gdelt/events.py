"""Cluster spike days into candidate flood events.

    python -m src.gdelt.events data/interim/gdelt_gkg_2015_2016

Reads {stem}_daily / _articles / _target_locations parquet, writes {stem}_events.parquet and .csv.
Spike days at most MAX_GAP days apart merge into one event. Evidence is counted from
strict, Malaysian-domain articles inside the event window (start..end, Malaysia local dates).
"""
import sys

import pandas as pd

from .daily import AGGREGATORS, near_flood

MAX_GAP = 2


def cluster_days(spike_days: pd.DatetimeIndex, max_gap: int = MAX_GAP) -> list[tuple]:
    events, start, prev = [], None, None
    for d in sorted(spike_days):
        if start is None:
            start = prev = d
        elif (d - prev).days <= max_gap:
            prev = d
        else:
            events.append((start, prev))
            start = prev = d
    if start is not None:
        events.append((start, prev))
    return events


def build_events(daily, articles, locations, top_places: int = 5) -> pd.DataFrame:
    a = articles.copy()
    a["day"] = (a["date"] + pd.Timedelta(hours=8)).dt.normalize()
    ev = a[
        a.has_target & a.flood & near_flood(a)
        & ~a.domain.isin(AGGREGATORS) & a.my_domain
    ]
    rows = []
    for i, (start, end) in enumerate(cluster_days(daily.index[daily.spike]), 1):
        w = ev[(ev.day >= start) & (ev.day <= end)]
        d = daily.loc[start:end]
        loc = locations[locations.url.isin(w.url) & (locations.type.isin(["3", "4", "5"]))]
        places = loc.name.str.split(",").str[0].value_counts().head(top_places)
        rows.append({
            "event_id": i,
            "start": start.date(),
            "end": end.date(),
            "n_spike_days": int(d.spike.sum()),
            "peak_day": d.n_strict_my.idxmax().date(),
            "peak_count": int(d.n_strict_my.max()),
            "n_articles": len(w),
            "n_domains": w.domain.nunique(),
            "n_selangor": int(w.has_selangor.sum()),
            "n_kl": int(w.has_kl.sum()),
            "top_places": "; ".join(f"{n} ({c})" for n, c in places.items()),
            "lat": loc.lat.median() if len(loc) else None,
            "lon": loc.lon.median() if len(loc) else None,
            "domains": "; ".join(w.domain.value_counts().head(4).index),
            "sample_urls": " | ".join(w.sort_values("n_my_places").url.head(3)),
        })
    return pd.DataFrame(rows)


def main(stem: str) -> None:
    daily = pd.read_parquet(f"{stem}_daily.parquet")
    articles = pd.read_parquet(f"{stem}_articles.parquet")
    locations = pd.read_parquet(f"{stem}_target_locations.parquet")
    events = build_events(daily, articles, locations)
    events.to_parquet(f"{stem}_events.parquet", index=False)
    events.to_csv(f"{stem}_events.csv", index=False)
    print(f"{len(events)} candidate events -> {stem}_events.parquet")


if __name__ == "__main__":
    main(sys.argv[1])
