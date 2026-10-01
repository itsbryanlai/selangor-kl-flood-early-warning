"""Hourly atmospheric state variables for the 5 grid points (moisture, heating, instability).

    python -m src.rainfall.atmos_state era5   # ERA5 surface variables, all study periods
    python -m src.rainfall.atmos_state nwp    # NWP state (CAPE, lifted index, 850/500 hPa), 2021-03 onward

era5: Open-Meteo archive (ERA5): temperature, dew point, humidity, pressure, wind, cloud, total column water vapour,
      boundary-layer height, shortwave radiation, soil moisture. The ERA5 archive does NOT serve CAPE or
      pressure-level fields.
nwp:  Open-Meteo historical-forecast API (stitched NWP, short lead, effectively analysis-like state):
      cape, lifted_index, temperature/humidity/wind at 850 hPa, temperature at 500 hPa. Coverage starts about 2021-04
      (empty for 2020 and earlier). convective_inhibition is returned as 0 everywhere, so it is not used.
      Also previous-runs `cape_previous_day1` (a genuine one-day-ahead CAPE forecast), 2024 onward.
Writes data/interim/atmos_{era5,nwp,cape_fc1}.parquet (hourly, Malaysia local time, columns time, point, ...).
"""
import sys
import time
from pathlib import Path

import httpx
import pandas as pd

from .openmeteo import POINTS

ERA5_URL = "https://archive-api.open-meteo.com/v1/archive"
NWP_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
PREV_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
ERA5_VARS = ["temperature_2m", "dew_point_2m", "relative_humidity_2m", "surface_pressure", "wind_speed_10m", "wind_direction_10m",
             "cloud_cover", "total_column_integrated_water_vapour", "boundary_layer_height", "shortwave_radiation", "soil_moisture_0_to_7cm"]
NWP_VARS = ["cape", "lifted_index", "temperature_850hPa", "relative_humidity_850hPa", "wind_speed_850hPa", "wind_direction_850hPa",
            "temperature_500hPa"]
ERA5_RANGES = [("2015-02-01", "2016-12-31"), ("2020-12-01", "2023-12-31"), ("2024-01-01", "2026-09-30")]


def _get(url: str, params: dict) -> dict:
    for attempt in range(6):
        try:
            r = httpx.get(url, params=params, timeout=120)
        except httpx.TransportError:
            time.sleep(5 * (attempt + 1)); continue
        if r.status_code == 429:
            time.sleep(30 * (attempt + 1)); continue
        r.raise_for_status()
        return r.json()["hourly"]
    raise RuntimeError(f"failed: {url} {params.get('start_date')}")


def _years(start: str, end: str):
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    for y in range(s.year, e.year + 1):
        yield max(s, pd.Timestamp(f"{y}-01-01")).date().isoformat(), min(e, pd.Timestamp(f"{y}-12-31")).date().isoformat()


def fetch(url: str, variables: list[str], ranges, out: Path) -> pd.DataFrame:
    frames = []
    for name, (lat, lon) in POINTS.items():
        for a, b in ranges:
            for y0, y1 in _years(a, b):
                h = _get(url, {"latitude": lat, "longitude": lon, "start_date": y0, "end_date": y1,
                               "hourly": ",".join(variables), "timezone": "Asia/Kuala_Lumpur"})
                df = pd.DataFrame({k: v for k, v in h.items()}).rename(columns={"time": "time"})
                df["time"] = pd.to_datetime(df["time"]); df["point"] = name
                frames.append(df)
                time.sleep(1.0)
    d = pd.concat(frames, ignore_index=True)
    d.to_parquet(out, index=False)
    return d


def main(which: str) -> None:
    if which == "era5":
        d = fetch(ERA5_URL, ERA5_VARS, ERA5_RANGES, Path("data/interim/atmos_era5.parquet"))
    elif which == "nwp":
        d = fetch(NWP_URL, NWP_VARS, [("2021-03-01", "2026-09-30")], Path("data/interim/atmos_nwp.parquet"))
        f = fetch(PREV_URL, ["cape_previous_day1"], [("2024-01-01", "2026-09-30")], Path("data/interim/atmos_cape_fc1.parquet"))
        print("cape_fc1", len(f), f.time.min(), f.time.max(), "null frac", f.cape_previous_day1.isna().mean().round(3))
    else:
        raise SystemExit("usage: era5 | nwp")
    print(which, len(d), d.time.min(), d.time.max(), "null frac:", d.drop(columns=["time", "point"]).isna().mean().round(3).to_dict())


if __name__ == "__main__":
    main(sys.argv[1])
