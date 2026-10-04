# Seasonal-anomaly standardisation

Code: [seasonal.py](../src/modeling/seasonal.py) (`python -m src.modeling.seasonal`). Output (not committed): `data/processed/seasonal_models.csv`.

**Short answer:** standardising the predictors against a seasonal climatology makes the model worse, not better. The season-removed versions lose skill in every comparison (PR-AUC 0.04 to 0.08 vs 0.10 for the raw model). Season carries real information here, so the raw values plus month terms stay.

## Method
Each predictor is converted to z = (x - mean(day of year)) / sd(day of year), using a 2-harmonic annual fit for mean and sd. Rain is log(1 + mm) first. The climatology is refitted inside every leave-one-quarter-out fold on training days only (test quarter +/-7 days removed), so there is no leakage. Same 2,141 labelled days and 39 floods for every model; paired month-block bootstrap on PR-AUC against model A. Logistic regression, fixed C = 0.1, as elsewhere.

## Results
| Model | PR-AUC | ROC-AUC | Capture @10% | PR-AUC diff vs A (95% CI) |
|---|---|---|---|---|
| A: rain, 7-day rain, season, TCWV level and trailing anomaly (current) | 0.103 | 0.77 | 41% | |
| B: z rain(D-1), z TCWV | 0.049 | 0.70 | 28% | -0.052 (-0.114 to -0.003) |
| C: B + z 850 hPa humidity | 0.064 | 0.71 | 33% | -0.032 (-0.092 to +0.026) |
| D: C + season terms | 0.078 | 0.71 | 33% | -0.017 (-0.058 to +0.037) |
| E: z rain(D-1), z 3-day rain, z TCWV, z soil moisture | 0.044 | 0.69 | 36% | -0.058 (-0.123 to -0.009) |
| F: raw rain terms + season + z TCWV | 0.093 | 0.74 | 33% | -0.011 (-0.033 to +0.004) |
| G: A + z TCWV + z rain | 0.102 | 0.77 | 41% | -0.001 (-0.003 to +0.000) |
| H: fit-free composite rank, raw | 0.090 | 0.80 | 46% | |
| I: fit-free composite rank, z-scores | 0.060 | 0.74 | 36% | -0.032 vs H (-0.074 to -0.005) |

## Reading
- Raw water vapour is better than its seasonal anomaly. Floods concentrate in the wet-season months, and a moist column in those months is the useful warning; removing the climatology removes part of what predicts floods. The trailing 60-day anomaly already in model A (tcwv_anom_00) is a weaker form of the same idea and gets its value next to the raw level.
- Adding the z-scores on top of the raw features (G) does nothing (-0.001).
- Even adding the season terms back to z-scores (D) does not recover the raw model, so it is not just the loss of month terms.
- Caveat: climatology fitted from about 7 years in three separate blocks is noisy, and the 2-harmonic shape ignores the interannual state (ENSO). A longer record could change the size of the effect, but the direction here is consistent across all seven variants.

## What this closes
All time-series items from the plan are now done: lead-lag profile, antecedent windows, clustering ([timeseries-diagnostics.md](timeseries-diagnostics.md)), MJO ([mjo.md](mjo.md)) and seasonal anomalies (this note). None adds skill. Remaining improvement routes are the external ones in [improvement-options.md](improvement-options.md): more labelled years, dense rain observations, prospective river levels.
