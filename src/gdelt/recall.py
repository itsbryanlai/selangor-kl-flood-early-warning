"""Second-pass candidate events to improve recall over the strict spike rule.

    python -m src.gdelt.recall data/interim/gdelt_gkg_2015_2016 data/interim/rain_hourly_2015-02-01_2016-12-31.parquet

Two extra streams, both excluding days within EXCLUDE_DAYS of the first-pass events:
  relaxed_news - robust z >= 2.5 and >= 3 strict Malaysian-domain articles
  rain_news    - ERA5 rain candidate day (daily max over points >= 29.5 mm or hourly >= 12.3 mm,
                 i.e. climatology p95/p99) with >= 3 strict Malaysian-domain articles on day..day+1
Writes {stem}_events2.parquet/.csv in the same format as events.py.
"""
import sys

import pandas as pd

from .daily import detect_spikes
from .events import build_events, cluster_days

EXCLUDE_DAYS = 2
RAIN_DAILY_MM, RAIN_HOURLY_MM = 29.5, 12.3


def rain_daily(path: str) -> pd.DataFrame:
    r = pd.read_parquet(path)
    r["day"] = r.time.dt.normalize()
    d = r.groupby(["point", "day"]).precip_mm.agg(["sum", "max"]).reset_index()
    return d.groupby("day").agg(rain_daily=("sum", "max"), rain_hourly=("max", "max"))


def extra_days(daily: pd.DataFrame, rain: pd.DataFrame, first_pass: pd.DataFrame) -> pd.DataFrame:
    relaxed = detect_spikes(daily, z=2.5, min_count=3).spike
    d = daily.join(rain, how="left")
    nxt = d.n_strict_my + d.n_strict_my.shift(-1, fill_value=0)
    rain_cand = (d.rain_daily >= RAIN_DAILY_MM) | (d.rain_hourly >= RAIN_HOURLY_MM)
    d["relaxed_news"] = relaxed
    d["rain_news"] = rain_cand & (nxt >= 3)
    covered = pd.Series(False, index=d.index)
    for e in first_pass.itertuples():
        lo = pd.Timestamp(e.start) - pd.Timedelta(days=EXCLUDE_DAYS)
        hi = pd.Timestamp(e.end) + pd.Timedelta(days=EXCLUDE_DAYS)
        covered[lo:hi] = True
    d["extra"] = (d.relaxed_news | d.rain_news) & ~covered
    return d


def main(stem: str, rain_path: str) -> None:
    daily = pd.read_parquet(f"{stem}_daily.parquet")
    articles = pd.read_parquet(f"{stem}_articles.parquet")
    locations = pd.read_parquet(f"{stem}_target_locations.parquet")
    first = pd.read_parquet(f"{stem}_events.parquet")
    d = extra_days(daily, rain_daily(rain_path), first)
    x = daily.copy()
    x["spike"] = d.extra
    ev = build_events(x, articles, locations)
    # tag which stream(s) flagged each event
    ev["streams"] = [
        "+".join(
            n for n in ("relaxed_news", "rain_news")
            if d.loc[pd.Timestamp(r.start):pd.Timestamp(r.end), n].any()
        )
        for r in ev.itertuples()
    ]
    ev["event_id"] += 100  # keep ids distinct from first-pass events
    ev.to_parquet(f"{stem}_events2.parquet", index=False)
    ev.to_csv(f"{stem}_events2.csv", index=False)
    print(f"{int(d.extra.sum())} extra days -> {len(ev)} second-pass candidate events")


if __name__ == "__main__":
    main(*sys.argv[1:3])
