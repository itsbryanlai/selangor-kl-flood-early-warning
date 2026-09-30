"""Astronomical tide at Port Klang from a harmonic fit of the UHSLC 'Kelang' record.

    python -m src.tide.harmonic

Steps: download hourly sea level (UHSLC ERDDAP, station 140, research quality, 2005 to 2023-01, with gaps),
fit tidal constituents with UTide (2005-2022), reconstruct hourly predicted tide for 2015-2026.
The prediction is the astronomical tide only (no storm surge or river discharge), and -- unlike rain --
is known in advance, so it is a legitimate lead-time feature. Heights are metres above chart datum;
times are UTC in the raw file and converted to Malaysia local time (+8 h) in the outputs.
"""
import io
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import utide

URL = ("https://uhslc.soest.hawaii.edu/erddap/tabledap/global_hourly_rqds.csv"
       "?time,sea_level&uhslc_id=140&time>=2005-01-01T00:00:00Z")
LAT = 3.05
RAW = Path("data/interim/tide_kelang_uhslc_hourly.parquet")
PRED = Path("data/interim/tide_kelang_predicted_hourly.parquet")


def load_measured() -> pd.Series:
    if not RAW.exists():
        r = httpx.get(URL, timeout=300)
        r.raise_for_status()
        pd.read_csv(io.StringIO(r.text), skiprows=[1], parse_dates=["time"]).to_parquet(RAW, index=False)
    d = pd.read_parquet(RAW)
    s = d.set_index(d.time.dt.tz_localize(None)).sea_level.dropna() / 1000.0  # mm -> m
    return s


def fit(s: pd.Series):
    t = s.index.to_pydatetime()
    return utide.solve(t, s.values, lat=LAT, method="ols", conf_int="none", trend=False, verbose=False)


def predict(coef, start: str, end: str) -> pd.Series:
    idx = pd.date_range(start, end, freq="h")
    out = utide.reconstruct(idx.to_pydatetime(), coef, verbose=False)
    return pd.Series(out.h, index=idx)


def main() -> None:
    s = load_measured()
    train, test = s[:"2021-12-31"], s["2022-01-01":]
    coef = fit(train)
    p = predict(coef, "2022-01-01", "2022-12-31 23:00")
    both = pd.concat([test.rename("obs"), p.rename("pred")], axis=1).dropna()
    err = both.obs - both.pred
    print(f"held-out 2022: n={len(both)} RMSE={np.sqrt((err**2).mean()):.3f} m, corr={both.obs.corr(both.pred):.3f}, "
          f"std obs={both.obs.std():.3f}, mean residual={err.mean():.3f}")
    coef = fit(s[:"2022-12-31"])
    pred = predict(coef, "2015-01-01", "2026-10-01 23:00")
    pred.index = pred.index + pd.Timedelta(hours=8)  # UTC -> Malaysia local time
    pred.rename("tide_m").to_frame().to_parquet(PRED)
    print("predicted", pred.index.min(), pred.index.max(), "| top constituents:",
          dict(zip(coef.name[np.argsort(coef.A)[::-1][:5]], np.sort(coef.A)[::-1][:5].round(2))))


if __name__ == "__main__":
    main()
