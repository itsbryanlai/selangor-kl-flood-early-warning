"""Open-Meteo Previous Runs API: archived forecasts issued 1 and 2 days before the valid time.

    python -m src.rainfall.previous_runs 2024-01-01 2026-09-30

Writes data/interim/fcst_hourly_{start}_{end}.parquet with, per point and hour:
  precip_fcst_d1 - precipitation forecast issued the previous day (about 24 h lead)
  precip_fcst_d2 - forecast issued two days before
Unlike the "historical forecast" API (stitched analyses), these are genuine lead-time forecasts,
so features built from them respect "features at time t, label at t+lead". Model: API default (best_match).
"""
import sys
import time
from pathlib import Path

import httpx
import pandas as pd

from .openmeteo import POINTS

URL = "https://previous-runs-api.open-meteo.com/v1/forecast"


def fetch_point(lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
    params = {
        "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
        "hourly": "precipitation_previous_day1,precipitation_previous_day2", "timezone": "Asia/Kuala_Lumpur",
    }
    for attempt in range(4):
        r = httpx.get(URL, params=params, timeout=120)
        if r.status_code == 429:
            time.sleep(20 * (attempt + 1))
            continue
        r.raise_for_status()
        h = r.json()["hourly"]
        return pd.DataFrame({
            "time": pd.to_datetime(h["time"]),
            "precip_fcst_d1": h["precipitation_previous_day1"],
            "precip_fcst_d2": h["precipitation_previous_day2"],
        })
    raise RuntimeError("Open-Meteo rate limited")


def fetch_points(start: str, end: str, out_dir: str = "data/interim") -> pd.DataFrame:
    frames = []
    for name, (lat, lon) in POINTS.items():
        df = fetch_point(lat, lon, start, end)
        df["point"] = name
        frames.append(df)
        time.sleep(2)
    out = pd.concat(frames, ignore_index=True)
    out.to_parquet(Path(out_dir) / f"fcst_hourly_{start}_{end}.parquet", index=False)
    return out


if __name__ == "__main__":
    d = fetch_points(*sys.argv[1:3])
    print(len(d), "rows", d.time.min(), d.time.max())
