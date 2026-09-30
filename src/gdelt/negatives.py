"""Daily label table: positives, cautious negatives, and excluded days.

    python -m src.gdelt.negatives data/interim/gdelt_gkg_2015_2016 \
        data/interim/rain_hourly_2015-02-01_2016-12-31.parquet annotations/event_verdicts_2015_2016.csv

Writes data/processed/daily_labels_2015_2016.csv, one row per day with a label_type:
  flood                - event date of a confirmed/probable event (y=1)
  easy_negative        - low rain, no Selangor/KL flood news, far from any candidate (y=0)
  moderate_rain_negative - rain between p75 and heavy thresholds but no flood news (y=0, harder)
  hard_news_negative   - flood-news spike day whose sampled articles were read and rejected (y=0)
  ambiguous_heavy_rain - heavy ERA5 rain but no confirmed flood (y empty; unknown)
  near_event           - within BUFFER days of a candidate that is not rejected (y empty)
  uncertain_event      - date of an uncertain/unverified candidate (y empty)
  unlabeled            - everything else (y empty)

CAVEAT: a negative means "no evidence of a flood in the news and low rain", not "no flood".
GDELT/news coverage misses small or tidal floods, so easy negatives are noisy on the rare
events that matter most. Do not treat unlabeled days as negatives.
"""
import sys
from pathlib import Path

import pandas as pd

from .recall import rain_daily

BUFFER = 3          # days around a non-rejected candidate window excluded from negatives
RAIN_LOW_Q = 0.75   # easy negative needs daily/hourly max rain below this climatology quantile
RAIN_HEAVY_DAILY, RAIN_HEAVY_HOURLY = 0.90, 0.95
NEWS_MAX = 1        # max strict Malaysian-domain articles on day and day+1 for an easy negative


def build_daily_labels(stem: str, rain_path: str, verdict_path: str) -> pd.DataFrame:
    news = pd.read_parquet(f"{stem}_daily.parquet")[["n_loose", "n_strict", "n_strict_my"]]
    rain = rain_daily(rain_path)
    d = news.join(rain, how="inner")
    d = d.loc["2015-03-01":"2016-12-30"].copy()  # 2015-02 has partial GDELT coverage; leave a rain lead-in
    d["rain_daily_3d_prior_max"] = rain.rain_daily.shift(1).rolling(3).max().reindex(d.index)
    d["news_my_2d"] = d.n_strict_my + d.n_strict_my.shift(-1, fill_value=0)

    ev = pd.concat(
        [pd.read_parquet(f"{stem}_events.parquet"), pd.read_parquet(f"{stem}_events2.parquet")],
        ignore_index=True,
    )
    v = pd.read_csv(verdict_path)
    ev = ev.merge(v[["event_id", "verdict", "event_date"]], on="event_id", how="left")
    ev["verdict"] = ev.verdict.fillna("unverified")

    d["label_type"] = "unlabeled"
    d["y"] = pd.NA
    low_d, low_h = rain.rain_daily.quantile(RAIN_LOW_Q), rain.rain_hourly.quantile(RAIN_LOW_Q)
    heavy_d, heavy_h = rain.rain_daily.quantile(RAIN_HEAVY_DAILY), rain.rain_hourly.quantile(RAIN_HEAVY_HOURLY)

    near = pd.Series(False, index=d.index)
    for e in ev[~ev.verdict.eq("reject")].itertuples():
        near[pd.Timestamp(e.start) - pd.Timedelta(days=BUFFER): pd.Timestamp(e.end) + pd.Timedelta(days=BUFFER)] = True

    heavy = (d.rain_daily >= heavy_d) | (d.rain_hourly >= heavy_h)
    easy = (
        (d.rain_daily < low_d) & (d.rain_hourly < low_h) & (d.rain_daily_3d_prior_max < low_d)
        & (d.news_my_2d <= NEWS_MAX) & ~near
    )
    moderate = (
        ~easy & ~heavy & ~near & (d.news_my_2d <= NEWS_MAX)
        & ((d.rain_daily >= low_d) | (d.rain_hourly >= low_h))
    )
    d.loc[moderate, ["label_type", "y"]] = ["moderate_rain_negative", 0]
    d.loc[easy, ["label_type", "y"]] = ["easy_negative", 0]
    d.loc[heavy & ~near, "label_type"] = "ambiguous_heavy_rain"
    d.loc[near & (d.label_type == "unlabeled"), "label_type"] = "near_event"

    for e in ev[ev.verdict.eq("reject")].itertuples():  # verified non-events with flood chatter
        w = d.loc[pd.Timestamp(e.start): pd.Timestamp(e.end)]
        ok = w.index[(w.label_type.isin(["unlabeled", "near_event"])) & ~heavy.reindex(w.index) & ~near.reindex(w.index)]
        d.loc[ok, ["label_type", "y"]] = ["hard_news_negative", 0]

    for e in ev[ev.verdict.isin(["uncertain", "unverified"])].itertuples():
        day = pd.Timestamp(e.event_date) if isinstance(e.event_date, str) else pd.Timestamp(e.peak_day)
        if day in d.index:
            d.loc[day, ["label_type", "y"]] = ["uncertain_event", pd.NA]
    for e in ev[ev.verdict.isin(["confirmed", "probable"])].itertuples():
        day = pd.Timestamp(e.event_date)
        d.loc[day, ["label_type", "y"]] = ["flood", 1]
    d.index.name = "day"
    return d.reset_index()


def main(stem: str, rain_path: str, verdict_path: str) -> None:
    d = build_daily_labels(stem, rain_path, verdict_path)
    out = Path("data/processed/daily_labels_2015_2016.csv")
    d.to_csv(out, index=False)
    print(d.label_type.value_counts().to_string(), f"\n-> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
