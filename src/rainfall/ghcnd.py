"""NOAA GHCN-Daily rain-gauge totals for Subang (Petaling) and KLIA (Sepang). Free, no account.

    python -m src.rainfall.ghcnd 2015-01-01 2026-09-30

Writes data/interim/gauge_daily_{start}_{end}.parquet: day, station, mm (PRCP in tenths of mm / 10).
Daily totals (local standard-day convention of the station), gaps left as NaN (2020-21 and 2025 are sparse;
the record ends about 2025-08-24). Two points only.
"""
import sys
from pathlib import Path

import httpx
import pandas as pd

URL = "https://www.ncei.noaa.gov/access/services/data/v1"
STATIONS = {"MYM00048647": "subang", "MYM00048650": "klia"}


def fetch(start: str, end: str, out_dir: str = "data/interim") -> pd.DataFrame:
    frames = []
    for sid, name in STATIONS.items():
        r = httpx.get(URL, params={"dataset": "daily-summaries", "stations": sid, "startDate": start,
                                   "endDate": end, "dataTypes": "PRCP", "format": "json"}, timeout=180)
        r.raise_for_status()
        d = pd.DataFrame(r.json())
        d["day"] = pd.to_datetime(d.DATE)
        d["mm"] = pd.to_numeric(d.PRCP, errors="coerce") / 10.0
        frames.append(d.assign(station=name)[["day", "station", "mm"]])
    out = pd.concat(frames, ignore_index=True)
    out.to_parquet(Path(out_dir) / f"gauge_daily_{start}_{end}.parquet", index=False)
    return out


if __name__ == "__main__":
    d = fetch(*sys.argv[1:3])
    print(len(d), "rows", d.day.min().date(), d.day.max().date(), d.groupby("station").mm.count().to_dict())
