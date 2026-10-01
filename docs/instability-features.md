# Moisture and instability features (ERA5 and NWP state)

Code: [atmos_state.py](../src/rainfall/atmos_state.py) (fetch), [instability.py](../src/modeling/instability.py) (features, analysis; `python -m src.modeling.instability`). Outputs: `data/processed/instability_*.csv` (not committed).

**Short answer:** the useful new signal is **column moisture** (total column water vapour, 850 hPa humidity, soil moisture), not CAPE. Moisture ranks flood days well above nearby ordinary days and lifts ROC-AUC of the lead-1-day models from about 0.66 to 0.74-0.80, but PR-AUC stays at 0.05 to 0.06 and alerts are still 92 to 94% false. CAPE and theta-e add nothing; a one-day-ahead CAPE forecast has no skill.

## 1. Data
| Source | Variables | Coverage | Notes |
|---|---|---|---|
| Open-Meteo archive (ERA5) | temperature, dew point, humidity, pressure, 10 m wind, cloud, total column water vapour (TCWV), boundary-layer height, shortwave radiation, soil moisture | 2015-16, 2020-12 to 2023, 2024-26 | **Does not serve CAPE or any pressure-level field.** TCWV and boundary-layer height are missing for January to June 2024 (source gap; affects one flood, 2024-04-17, filled by the median in models) |
| Open-Meteo historical-forecast API (stitched NWP, short lead, analysis-like) | CAPE, lifted index, temperature/humidity/wind at 850 hPa, temperature at 500 hPa | about 2021-04 onward (empty for 2020 and earlier); 7% missing in 2021 | `convective_inhibition` is 0 everywhere, not used |
| Open-Meteo previous-runs API | `cape_previous_day1` (a genuine 1-day-ahead CAPE forecast) | 2024 onward | 14 flood days |
All averaged over the same 5 grid points as the rain data.

## 2. Features (only information before day D unless marked)
- Previous day (D-1) summaries: TCWV mean/max, dew point, afternoon temperature, theta-e (Bolton formula, surface instability proxy), relative humidity, cloud, shortwave sum, boundary-layer height, 10 m wind; NWP: CAPE max/mean, lifted-index minimum, 850 hPa humidity/temperature/wind, 850-500 hPa lapse rate.
- Snapshots at 00:00 local on D (before a typical flash flood): TCWV, theta-e, dew point, soil moisture, 850 hPa humidity/temperature/CAPE; TCWV change over 24 h.
- `now_*` (day D itself): benchmark for lead 0 only, not usable in advance.
- Part B feature sets were fixed before looking at results (physically motivated); Part A ranks all features on all 40 flood days, so Part A is descriptive, not an out-of-sample test.

## 3. Part A: does the feature differ on flood days? (seasonality removed)
For each flood day, the feature's percentile among non-flood days within +/-45 days (0.5 = no difference, 40 floods, 29 where CAPE data exist):

| Feature | Mean percentile (95% CI) | Lead |
|---|---|---|
| Same-day ERA5 rain | 0.84 (0.79-0.89) | 0 |
| 1-day forecast rain (14 floods) | 0.83 (0.76-0.91) | ~1 d |
| Same-day TCWV | 0.78 (0.72-0.83) | 0 |
| **TCWV at 00:00 on D** | **0.73 (0.66-0.80)** | hours to a day |
| **850 hPa humidity at 00:00 on D** (29) | **0.71 (0.63-0.80)** | hours to a day |
| Yesterday's rain | 0.69 (0.62-0.76) | 1 d |
| Soil moisture at 00:00 on D | 0.66 (0.58-0.75) | hours to a day |
| TCWV yesterday (mean) | 0.65 (0.58-0.73) | 1 d |
| 7-day rain | 0.65 (0.56-0.74) | 1 d |
| Yesterday's max CAPE (29) | 0.65 (0.54-0.76) | 1 d |
| Yesterday's minimum lifted index (29) | 0.36 (0.26-0.47) | 1 d (more unstable) |
| Theta-e at 00:00 / yesterday's max | 0.46 / 0.54 | no signal |
| 1-day forecast CAPE (14) | 0.41 (0.30-0.53) | ~1 d, no signal |
| Same-day CAPE (29) | 0.40 (0.30-0.50) | 0, flood days have lower CAPE because rain consumes it |
Same-day maximum temperature ranks 0.25 (cloud and rain cool the day: concurrent, not a predictor).
So column moisture on the night before beats yesterday's rain as an advance indicator; CAPE and lifted index show a weak positive signal; theta-e none. With about 35 features compared, a few spurious hits are expected, but the moisture family (TCWV, 850 hPa humidity, humidity, soil moisture, dew point) is coherent.

## 4. Part B: models
Expanding windows as before; paired month-block bootstrap of the PR-AUC difference against the rain-and-season baseline (yesterday's rain, 7-day rain, month sin/cos).

**B1: ERA5 moisture, all three periods (28 test floods, 1,610 days, base rate 1.7%)**

| Model | PR-AUC (95% CI) | ROC-AUC | Difference vs baseline (95% CI) |
|---|---|---|---|
| Month climatology | 0.037 (0.017-0.079) | 0.65 | |
| Yesterday's rain | 0.077 (0.027-0.171) | 0.76 | |
| LR rain + season (baseline) | 0.041 (0.022-0.095) | 0.68 | |
| LR all rain features | 0.052 (0.019-0.152) | 0.66 | +0.016 (-0.010 to +0.077) |
| LR baseline + TCWV, theta-e, soil moisture | 0.050 (0.026-0.111) | 0.74 | +0.009 (-0.019 to +0.044) |
| LR all rain + all ERA5 moisture/heating | 0.055 (0.024-0.166) | 0.74 | +0.021 (-0.004 to +0.079) |

**B2: with CAPE and 850/500 hPa fields, periods from 2021-04 (26 test floods, 1,449 days)**

| Model | PR-AUC (95% CI) | ROC-AUC | Difference vs baseline (95% CI) |
|---|---|---|---|
| Month climatology | 0.034 (0.015-0.058) | 0.58 | |
| Yesterday's max CAPE alone | 0.029 | 0.66 | |
| Same-day CAPE alone (lead 0) | 0.017 | 0.45 | |
| LR baseline (rain + season) | 0.036 (0.019-0.078) | 0.66 | |
| LR baseline + CAPE, lifted index | 0.041 (0.025-0.073) | 0.74 | +0.004 (-0.027 to +0.025) |
| **LR baseline + ERA5 moisture + CAPE set** | **0.059 (0.036-0.103)** | **0.80** | **+0.024 (-0.002 to +0.053)**, share of resamples at or below 0: 0.04 |
| LR all rain + ERA5 moisture + CAPE set | 0.050 (0.029-0.100) | 0.79 | +0.016 (-0.016 to +0.050) |
| Lead 0: baseline + same-day CAPE, theta-e, TCWV | 0.097 (0.030-0.209) | 0.78 | +0.058 (+0.005 to +0.144), share 0.01 |

**B3: 2024-26 only, 1-day forecast CAPE (8 test floods):** forecast CAPE alone PR-AUC 0.019 (chance 0.017); adding it to forecast rain lowers PR-AUC (0.186 vs 0.195 without it); forecast rain alone remains the best lead-1 score (0.287).

Alert rules (threshold maximising training CSI): best lead-1 model (baseline + moisture + CAPE set) CSI 0.065, 6 hits, 66 false alarms, 20 misses (FAR 0.92); all variants CSI 0.04 to 0.06, FAR 0.92 to 0.95.

## 5. Interpretation
1. **Moisture matters; instability indices do not.** The signal is in how moist the column is (TCWV, 850 hPa humidity, soil moisture), consistent with heavy-rain physics, not in CAPE or theta-e.
2. **Ranking improves, calibration of rare events does not.** Adding moisture raises ROC-AUC by 0.07 to 0.14 (to about 0.80 at lead ~0.5 to 1 day, matching the forecast-rain score available only from 2024) but PR-AUC by only 0.01 to 0.02 in absolute terms; the best 1-day model is about 3 times the base rate and only borderline significant against the rain baseline (resampled share 0.04). Lead 0 with moisture/CAPE is clearly better (+0.058).
3. **Forecast CAPE is useless here; forecast rain is not.**
4. Still not operationally useful: 92 to 95% false alarms.

## 6. Caveats
- 26 to 28 test floods; confidence intervals on PR-AUC are wide and the improvements against the baseline are mostly inside them.
- Part A uses all flood days, including those later used as test floods; B is the out-of-sample check.
- NWP "state" values from the historical-forecast archive are short-lead analysis-like fields, not archived 24 h forecasts, except `cape_previous_day1`.
- TCWV is missing for Jan-Jun 2024 and CAPE for 2020 and earlier, so the CAPE comparisons exclude the 2015-16 period (11 floods).
- Point values are 5-point area means; local convective environments are not resolved.

Follow-up on water vapour (level, anomaly, tendency, moisture-flux convergence, 850 hPa humidity): [water-vapour.md](water-vapour.md). Result: floods never occur in the driest fifth of nights and occur at 5.0 per 100 days in the wettest fifth; modeling gains are modest.

## 7. Ideas not tried
Moisture flux and convergence from 850 hPa winds, TCWV forecast (not just analysis), Borneo vortex / cold-surge / MJO indices, higher-resolution (radar or gauge) rain, and more labeled years. The measured moisture signal suggests tracking TCWV and its tendency as the next simple predictor.
