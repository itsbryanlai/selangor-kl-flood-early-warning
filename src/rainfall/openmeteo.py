"""Open-Meteo Historical Weather API client (ERA5-based, free, no key).

    python -m src.rainfall.openmeteo 2015-02-01 2016-12-31

Writes data/interim/rain_hourly_{start}_{end}.parquet (hourly precipitation, mm, per point).
Timestamps are Malaysia local time (Asia/Kuala_Lumpur).
"""
import sys
import time
from pathlib import Path

import httpx
import pandas as pd

URL = "https://archive-api.open-meteo.com/v1/archive"
POINTS = {
    "kuala_lumpur": (3.139, 101.687),
    "shah_alam": (3.073, 101.518),
    "klang": (3.045, 101.445),
    "kuala_selangor": (3.340, 101.250),
    "sepang": (2.690, 101.750),
}


def fetch_hourly(lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
    params = {
        "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
        "hourly": "precipitation", "timezone": "Asia/Kuala_Lumpur",
    }
    for attempt in range(4):
        r = httpx.get(URL, params=params, timeout=60)
        if r.status_code == 429:
            time.sleep(20 * (attempt + 1))
            continue
        r.raise_for_status()
        h = r.json()["hourly"]
        return pd.DataFrame({"time": pd.to_datetime(h["time"]), "precip_mm": h["precipitation"]})
    raise RuntimeError("Open-Meteo rate limited")


def fetch_points(start: str, end: str, out_dir: str = "data/interim") -> pd.DataFrame:
    frames = []
    for name, (lat, lon) in POINTS.items():
        df = fetch_hourly(lat, lon, start, end)
        df["point"] = name
        frames.append(df)
        time.sleep(2)
    out = pd.concat(frames, ignore_index=True)
    out.to_parquet(Path(out_dir) / f"rain_hourly_{start}_{end}.parquet", index=False)
    return out


if __name__ == "__main__":
    d = fetch_points(*sys.argv[1:3])
    print(len(d), "rows", d.time.min(), d.time.max())
