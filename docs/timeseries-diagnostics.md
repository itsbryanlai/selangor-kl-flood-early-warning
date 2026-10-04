# Time-series diagnostics: lead-lag profile and flood clustering

Code: [timeseries.py](../src/modeling/timeseries.py) (`python -m src.modeling.timeseries`). Outputs (not committed): `data/processed/timeseries_lag_profile.csv`, `timeseries_derived_features.csv`, `timeseries_clustering.csv`. Uses the 40 flood days and existing ERA5/NWP series only.

**Short answer:** the useful memory of every predictor is 1 to 3 days. Windows of a week or more, exponentially weighted rain, wet-spell length and soil moisture add nothing over what the model already uses, and floods do not cluster in time beyond what season explains. This closes the "antecedent memory" and "hazard / recent-flood" ideas; longer lead would need a different kind of information (for example the MJO), not better handling of these series.

## 1. Lead-lag profile
For each flood day D and lag k, the percentile of the series value at D-k among the same series on control days within +/-45 days (flood days +/-3 days removed). 0.5 = no signal; the window removes season. Bootstrap CI over flood events. Rain is the area-maximum daily ERA5 total; atmosphere series are the 00:00 snapshots (lag 0 = 00:00 on D, before onset).

| Lag (days before D) | Rain | TCWV | 850 hPa humidity (29 events) | Soil moisture |
|---|---|---|---|---|
| 0 (rain: same day = detection) | 0.84 | 0.73 | 0.71 | 0.66 |
| 1 | 0.69 | 0.66 | 0.62 | 0.63 |
| 2 | 0.60 | 0.59 | 0.59 | 0.59 |
| 3 | 0.61 | 0.58 | 0.57 | 0.59 |
| 4 | 0.57 | 0.58 | 0.62 | 0.64 |
| 5 to 14 | 0.49 to 0.64 | 0.52 to 0.58 | 0.50 to 0.58 | 0.48 to 0.62 |

- Signal is strongest at lag 0 to 1 and fades to the edge of the confidence bands by lag 2 to 3 for all four series. Nothing beyond lag 4 is distinguishable from noise. The isolated rain value at lag 9 (0.64, CI 0.56-0.72) is one of 60 lag tests at 95% and is not trusted.
- Water vapour and soil moisture carry information one to two days earlier than rain does, but only about as much as rain at lag 1.

## 2. Derived antecedent features (28)
Same percentile test on windowed features. The best are the ones already in use or equivalent:

| Feature | Percentile (95% CI) |
|---|---|
| 850 hPa humidity at 00:00 (29 events) | 0.71 (0.63-0.80) |
| TCWV maximum, last 3 days | 0.71 (0.63-0.78) |
| TCWV mean, last 3 days | 0.70 (0.63-0.77) |
| Rain of D-1 | 0.69 (0.62-0.76) |
| Exponentially weighted rain, half-life 1, 2, 4 days | 0.69, 0.68, 0.68 |
| Rain sum 2, 3, 5, 7, 14 days | 0.67, 0.67, 0.66, 0.65, 0.64 |
| Soil moisture 00:00 | 0.66 (0.57-0.75) |
| Days since 20 mm | 0.67 (0.59-0.74), inverted |
| Wet-spell length / wet days in 7 / 30-day rain | 0.59 / 0.59 / 0.56 |

Longer windows are monotonically weaker, so there is no sign that wet spells matter beyond yesterday. The 3-day TCWV mean and maximum are no better than the single 00:00 value (0.73 at lag 0), so smoothing the water-vapour series gains nothing. These percentiles are descriptive; none of them has been put through the blocked-CV models.

## 3. Do floods cluster in time?
- Gaps between consecutive flood days: median 33 days; none within 3 days, 2 within 7, 9 within 14, 18 within 30. Within each period (floods per period 11, 15, 14).
- Permutation test (floods with another flood within w days; 5,000 random placements, either uniform over each period's days or keeping the floods-per-calendar-month counts):

| w | Observed | Uniform null mean (p) | Month-matched null mean (p) |
|---|---|---|---|
| 3 | 0 | 3.2 (1.00) | 3.8 (1.00) |
| 7 | 4 | 7.0 (0.90) | 8.3 (0.96) |
| 14 | 17 | 12.8 (0.16) | 14.8 (0.31) |
| 30 | 29 | 22.5 (0.04) | 25.4 (0.15) |

- Conditional rate: a flood day follows a flood in the previous 7 days 0.7% of the time (2 of 277), vs 1.5% unconditionally (the 14- and 30-day versions are 1.7% and 1.9%).
- Reading: no clustering at short range. Slight excess at 30 days that mostly disappears once the calendar month is matched, so it is season, not contagion. The deficit within 7 days is partly built in: events within about 2 days are merged into one when events are built, and labelled events had to be separated by hand review. So "days since last flood" is not a useful covariate and the 7-day purge in blocked CV is adequate.

## 4. Caveats
- 4 series x 15 lags plus 28 features is about 90 tests at 95%, so a few extreme-looking values are expected by chance; only the pattern (a smooth decay to 0.5) is interpreted.
- Controls are all non-flood days within 45 days, including unlabelled days that may hold floods GDELT missed, which dilutes every percentile slightly.
- Floods are the news-visible ones (heavy-rain skew), 2024-H1 TCWV is missing, and 850 hPa humidity exists only from 2021 (29 of 40 events).
- ERA5 area-maximum rain is a coarse proxy for local rain; a lag-profile with dense gauge data could look different.

## 5. What this changes in the plan
- Dropped: exponentially weighted rain, wet-spell and days-since features (idea 3 mostly), distributed lags beyond about 3 days (idea 5, a spline over 0 to 3 days would equal what is already used), and the hazard-model reformulation (idea 8).
- Left open: a short, cheap re-test of 3-day TCWV mean/max inside the blocked-CV models (the descriptive percentile is about equal to tcwv_00, so I expect no gain); seasonal-anomaly standardisation (idea 4); and the one external-data idea with a plausible route to longer lead, MJO phase and amplitude (idea 7), since tested: see [mjo.md](mjo.md) (no usable signal).
