# Water-vapour predictors

Code: [water_vapour.py](../src/modeling/water_vapour.py) (`python -m src.modeling.water_vapour`), building on [atmos_state.py](../src/rainfall/atmos_state.py) and [instability.py](../src/modeling/instability.py). Outputs: `data/processed/water_vapour_*.csv` (not committed). Follows [instability-features.md](instability-features.md), where column moisture was the only useful new signal.

**Short answer:** how much water vapour is in the air column at midnight is a strong, monotonic marker of flood days: **none of 423 days in the driest fifth had a flood; in the wettest fifth the rate is 5.0 per 100 days (21 of 39 floods).** As a model input it lifts PR-AUC from about 0.07 to 0.09 to 0.12 and ROC-AUC from 0.72 to about 0.79, but the improvement over the rain-and-season baseline is mostly inside the confidence intervals (only the 850 hPa humidity variant is clearly significant), and alerts are still 83 to 94% false.

## 1. What was and was not available
- **No archived forecast of water vapour.** Open-Meteo's historical-forecast archive has TCWV only from late 2024 and no previous-day variants, and the previous-runs API returns nothing for it. A genuine lead-1 water-vapour forecast cannot be built. Features use the observed state at 00:00 local on day D (a lead of hours to a day, shorter than one day for a flood that day).
- **ERA5 TCWV is missing for January to June 2024** (source gap). A regression fill from dew point, humidity, temperature and pressure was tried and **rejected** (holdout R2 0.11, residual sd 4.3 kg/m2, against typical TCWV of 54 kg/m2). The 4,368 hours (one flood, 2024-04-17) are left missing and those days are dropped from every model, so all comparisons are like for like (1,441 test days, 27 test floods).
- Moisture-flux **convergence** from the 5 grid points (about 40 km apart) is noisy; it was estimated by a least-squares fit across the points.

## 2. Features (up to 00:00 on D)
`tcwv_00` (level), `tcwv_anom_00` (minus the previous 60 days' mean), `tcwv_chg6_00` and `tcwv_chg24_00` (tendency), `tcwv_hi_hours_d1` (hours of D-1 above the 75th percentile), `mfc_00` and `mfc_d1_min` (low-level moisture-flux convergence from 2 m humidity and 10 m wind), and from 2021-04 `q850_00` (850 hPa specific humidity), 850 hPa moisture flux (u, v), and an IVT proxy (TCWV times 850 hPa wind speed).

## 3. Part A: does it differ on flood days? (percentile among +/-45-day non-flood days; 0.5 = no signal)
| Feature | Mean percentile (95% CI) | Events |
|---|---|---|
| Same-day rain | 0.84 (0.80-0.88) | 40 |
| 1-day forecast rain | 0.83 (0.76-0.91) | 14 |
| **850 hPa specific humidity at 00:00** | **0.74 (0.65-0.83)** | 29 |
| **TCWV at 00:00** | **0.73 (0.66-0.80)** | 39 |
| **TCWV anomaly at 00:00** | **0.73 (0.65-0.80)** | 39 |
| 850 hPa relative humidity at 00:00 | 0.71 (0.62-0.80) | 29 |
| Yesterday's rain | 0.69 (0.62-0.76) | 40 |
| TCWV yesterday (mean) | 0.65 (0.58-0.73) | 39 |
| Moisture-flux convergence, most convergent hour of D-1 | 0.63 (0.54-0.73) | 40 |
| Hours above p75 yesterday | 0.61 (0.53-0.69) | 40 |
| TCWV 24 h change | 0.59 (0.51-0.67) | 39 |
| TCWV 6 h change | 0.57 (0.49-0.65) | 39 |
| 850 hPa zonal flux | 0.39 (0.29-0.50) | 29 |
| IVT proxy | 0.36 (0.26-0.46) | 28 |
| Moisture-flux convergence at 00:00 / 850 hPa meridional flux | 0.47 / 0.49 | no signal |
Reading: the best advance indicators are the amount of moisture (level, anomaly, 850 hPa humidity), better than yesterday's rain. Tendency, flux and convergence add little. The IVT proxy is inversely related (strong low-level winds with moist air are less typical of flood days), so it is not the useful way to combine wind and moisture here.

## 4. Flood frequency by water-vapour level (all labelled days, flood days vs non-flood days)
| TCWV at 00:00 (kg/m2) | Days | Floods | Floods per 100 days |
|---|---|---|---|
| 30.9 to 50.3 | 423 | 0 | 0.0 |
| 50.3 to 53.7 | 424 | 2 | 0.5 |
| 53.8 to 56.1 | 421 | 4 | 1.0 |
| 56.2 to 58.9 | 426 | 12 | 2.8 |
| 59.0 to 69.0 | 418 | 21 | 5.0 |
By anomaly (TCWV minus the previous 60 days): 0.2, 1.0, 0.7, 3.3 and 4.0 floods per 100 days from lowest to highest fifth. A day in the wettest fifth is about 2.6 times more likely than average to have a flood (5.0 vs 1.9 per 100), and nearly all floods (33 of 39) occur in the upper three fifths.

## 5. Part B: models (expanding windows, test 2021-07 to 2026-09)
Baseline = yesterday's rain, 7-day rain, month sin/cos (sparse). Difference = paired month-block bootstrap of the PR-AUC gain.

**B1: all three periods (27 test floods, 1,441 days, base rate 1.9%)**

| Model | PR-AUC (95% CI) | ROC-AUC | Gain vs baseline (95% CI) |
|---|---|---|---|
| Month climatology | 0.038 (0.017-0.083) | 0.64 | |
| TCWV at 00:00 alone | 0.092 (0.045-0.208) | 0.81 | |
| Yesterday's rain alone | 0.093 (0.032-0.195) | 0.78 | |
| Baseline (rain + season) | 0.073 (0.035-0.179) | 0.73 | |
| Baseline + TCWV | 0.103 (0.041-0.214) | 0.79 | +0.029 (-0.037 to +0.100) |
| Baseline + TCWV level, anomaly, 6 h tendency | 0.124 (0.042-0.245) | 0.79 | +0.049 (-0.031 to +0.134) |
| ... + moisture-flux convergence | 0.101 (0.040-0.228) | 0.78 | +0.034 (-0.042 to +0.117) |
| Prior moisture set (D-1 TCWV, theta-e, soil) | 0.073 (0.035-0.146) | 0.77 | -0.004 |

**B2: from 2021-04 (25 test floods, 1,280 days)**

| Model | PR-AUC (95% CI) | ROC-AUC | Gain vs baseline (95% CI) |
|---|---|---|---|
| Baseline | 0.069 (0.028-0.163) | 0.72 | |
| 850 hPa specific humidity alone | 0.072 (0.037-0.142) | 0.77 | |
| Baseline + TCWV set | 0.094 (0.037-0.209) | 0.77 | +0.028 (-0.003 to +0.073) |
| + 850 hPa zonal/meridional flux | 0.081 (0.032-0.176) | 0.76 | +0.015 (-0.012 to +0.059) |
| + IVT proxy | 0.103 (0.038-0.251) | 0.78 | +0.042 (-0.038 to +0.129) |
| **+ 850 hPa relative humidity** | **0.107 (0.039-0.251)** | **0.78** | **+0.041 (+0.002 to +0.108)**, share at or below 0: 0.01 |
| Prior best (ERA5 moisture + CAPE set) | 0.083 (0.048-0.150) | 0.82 | +0.015 (-0.051 to +0.069) |
Best alert rule (baseline + TCWV set + 850 hPa humidity): CSI 0.067, 3 hits, 20 false alarms, 22 misses (FAR 0.87); the TCWV set alone CSI 0.075 with 15 false alarms (FAR 0.83) but 3 hits in 25 floods.

## 6. Interpretation
1. **Water vapour is the best advance predictor found**, comparable to yesterday's rain and ahead of CAPE, theta-e, tendency and flux terms: floods concentrate on the most humid fifth of nights.
2. **As a forecast aid its skill is modest.** PR-AUC about 0.09 to 0.12 means roughly 5 to 6 times the base rate, but alert rules still miss most floods or raise 5 to 6 false alarms per hit; and most gains over the baseline are not statistically separated.
3. **Tendency and flux convergence do not help**, perhaps because the 5-point grid and 9 km data cannot resolve them.
4. **Moisture is necessary rather than sufficient:** very dry columns almost never flood (0 of 423 days), while most humid-column days (95%) still have no labelled flood.

## 7. Caveats
- The water-vapour feature sets were chosen after the previous analysis had shown TCWV to be strong, using the same 40 flood days, so this is hypothesis-supported, not independently confirmed. The 2017-2020 labels (about 507 GB of BigQuery, needs approval) are untouched data on which the water-vapour result could be tested out of sample (ERA5 TCWV exists back to 2015; CAPE and 850 hPa fields do not).
- 25 to 27 test floods; intervals are wide.
- The flood-frequency table counts days over the whole labelled period (not an out-of-sample forecast).
- January to June 2024 is excluded (one flood lost).
