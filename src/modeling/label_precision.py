"""Does precise location and hour matching make rain separate flood events from ordinary days?

    python -m src.modeling.label_precision

For each hand-reviewed event in annotations/event_details.csv (25 events) pull ERA5 hourly rain at the
event's own coordinates (Open-Meteo archive) for +/-60 days. Compare how high the event ranks among nearby
non-flood "control" days (same place, +/-45 days, not within 3 days of any flood) under four rain statistics:
  A  day-level area max (the 5-point daily total used so far)             -- coarse space, whole day
  B  local daily total at the event location                              -- right place, whole day
  C  local peak 3-hour rain within the event day                          -- right place, peak intensity
  D  local peak 3-hour rain in the window onset-3h..onset+3h (events with an hour)  -- right place and time
Score per event = percentile rank of the event value among its controls (0.5 = chance, 1 = top).
"""
import time
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

URL = "https://archive-api.open-meteo.com/v1/archive"
CACHE = Path("data/interim/local_rain")
FLOODS = {"2015-16": "data/processed/daily_labels_2015_2016.csv", "2021-23": "data/processed/daily_labels_v1_2021_2023.csv", "2024-26": "data/processed/daily_labels_v1_2024_2026.csv"}
AREA = {"2015-16": "data/interim/rain_hourly_2015-02-01_2016-12-31.parquet", "2021-23": "data/interim/rain_hourly_2020-12-01_2023-12-31.parquet", "2024-26": "data/interim/rain_hourly_2024-01-01_2026-09-30.parquet"}


def local_rain(key: str, lat: float, lon: float, start: str, end: str) -> pd.Series:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{key}.parquet"
    if not path.exists():
        for attempt in range(6):
            try:
                r = httpx.get(URL, params={"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
                                            "hourly": "precipitation", "timezone": "Asia/Kuala_Lumpur"}, timeout=90)
            except httpx.TransportError:
                time.sleep(5 * (attempt + 1)); continue
            if r.status_code == 429:
                time.sleep(20 * (attempt + 1)); continue
            r.raise_for_status(); break
        else:
            raise RuntimeError(f"could not fetch {key}")
        h = r.json()["hourly"]
        pd.DataFrame({"time": pd.to_datetime(h["time"]), "mm": h["precipitation"]}).to_parquet(path)
        time.sleep(1.5)
    d = pd.read_parquet(path)
    return d.set_index("time").mm.astype(float)


def pct_rank(value: float, controls: np.ndarray) -> float:
    controls = controls[~np.isnan(controls)]
    return float((controls < value).mean() + 0.5 * (controls == value).mean()) if len(controls) else np.nan


def main() -> None:
    ev = pd.read_csv("annotations/event_details.csv", parse_dates=["event_date"])
    flood_days = set()
    for tag, p in FLOODS.items():
        l = pd.read_csv(p, parse_dates=["day"])
        flood_days |= set(l.loc[l.label_type == "flood", "day"]) | set(ev.event_date)
    flood_buffer = {d + pd.Timedelta(days=k) for d in flood_days for k in range(-3, 4)}
    area, area_r3 = {}, {}
    for tag, p in AREA.items():
        h = pd.read_parquet(p); h["day"] = h.time.dt.normalize()
        area[tag] = h.groupby(["point", "day"]).precip_mm.sum().unstack(0).max(axis=1)
        hp = h.pivot(index="time", columns="point", values="precip_mm")
        area_r3[tag] = hp.rolling(3, min_periods=3).sum().max(axis=1)  # regional hourly 3h peak (max over 5 points)
    rows = []
    for r in ev.itertuples():
        d0 = r.event_date
        rain = local_rain(f"{r.period}_{r.event_id}", r.lat, r.lon, str((d0 - pd.Timedelta(days=65)).date()), str((d0 + pd.Timedelta(days=65)).date()))
        r3 = rain.rolling(3, min_periods=3).sum()
        daily = rain.groupby(rain.index.normalize()).sum()
        peak3 = r3.groupby(r3.index.normalize()).max()
        cdays = [d for d in pd.date_range(d0 - pd.Timedelta(days=45), d0 + pd.Timedelta(days=45)) if d not in flood_buffer and d in daily.index]
        def win_peak3(day, hour):
            h = int(round(hour)); lo, hi = day + pd.Timedelta(hours=max(h - 3, 0)), day + pd.Timedelta(hours=min(h + 3, 23))
            s = r3[lo:hi]
            return s.max() if len(s) else np.nan
        row = {"period": r.period, "event_id": r.event_id, "date": d0.date(), "n_controls": len(cdays),
               "A_area_day": pct_rank(area[r.period].get(d0, np.nan), area[r.period].reindex(cdays).values),
               "B_local_day": pct_rank(daily.get(d0, np.nan), daily.reindex(cdays).values),
               "C_local_peak3h": pct_rank(peak3.get(d0, np.nan), peak3.reindex(cdays).values),
               "F_area_peak3h_day": pct_rank(area_r3[r.period].groupby(area_r3[r.period].index.normalize()).max().get(d0, np.nan),
                                             area_r3[r.period].groupby(area_r3[r.period].index.normalize()).max().reindex(cdays).values),
               "D_window_peak3h": np.nan, "E_area_window_peak3h": np.nan, "stream": "news" if r.event_id < 100 else "rain+news", "has_hour": not np.isnan(r.onset_hour), "local_peak3h_mm": round(float(peak3.get(d0, np.nan)), 1)}
        if row["has_hour"]:
            row["D_window_peak3h"] = pct_rank(win_peak3(d0, r.onset_hour), np.array([win_peak3(c, r.onset_hour) for c in cdays]))
            a3 = area_r3[r.period]
            def awin(day, hour=r.onset_hour):
                h = int(round(hour)); s_ = a3[day + pd.Timedelta(hours=max(h - 3, 0)): day + pd.Timedelta(hours=min(h + 3, 23))]
                return s_.max() if len(s_) else np.nan
            row["E_area_window_peak3h"] = pct_rank(awin(d0), np.array([awin(c) for c in cdays]))
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv("data/processed/label_precision.csv", index=False)
    pd.set_option("display.width", 220)
    print(out.round(2).to_string(index=False))
    rng = np.random.default_rng(0)
    def summ(col, sub):
        v = sub[col].dropna().values
        b = [rng.choice(v, len(v)).mean() for _ in range(2000)]
        return f"{col}: mean pct {v.mean():.2f} (95% CI {np.percentile(b, 2.5):.2f}-{np.percentile(b, 97.5):.2f}), >=0.9: {(v >= 0.9).mean():.2f}, n={len(v)}"
    cols = ("A_area_day", "F_area_peak3h_day", "B_local_day", "C_local_peak3h")
    for name, sub in (("all events", out), ("news-only events (not selected on rain)", out[out.stream == "news"]),
                      ("rain+news events (selected on regional rain, A is inflated)", out[out.stream != "news"])):
        print(f"\n{name}:"); [print("  " + summ(c, sub)) for c in cols]
    for name, sub in (("events with an onset hour", out[out.has_hour]), ("... news-only with hour", out[out.has_hour & (out.stream == "news")])):
        print(f"\n{name}:"); [print("  " + summ(c, sub)) for c in cols + ("D_window_peak3h", "E_area_window_peak3h")]


if __name__ == "__main__":
    main()
