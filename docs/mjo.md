# MJO test: does the intraseasonal state add lead time or skill?

Code: [mjo.py](../src/modeling/mjo.py) (`python -m src.modeling.mjo`). Outputs (not committed): `data/processed/mjo_lag_profile.csv`, `mjo_models.csv`. Data: NOAA PSL OLR-based MJO Index (OMI), daily PC1, PC2, amplitude (free text file, [omi.1x.txt](https://psl.noaa.gov/mjo/mjoindex/omi.1x.txt), downloaded once to `data/external/omi.txt`, 450 KB, git-ignored). The BoM RMM file returns HTTP 403 for automated access (their site asks users not to scrape), so it was not used and not worked around. The OMI file ends 2026-06-24, so the last three months drop out (39 of 40 flood days covered, 38 in the model comparison).

**Short answer:** no usable MJO signal. Linear MJO features do not help, and the only pattern (a phase sector with more floods than expected) is not significant and was found after looking. This closes the one external idea that could have extended the lead beyond 2 to 3 days.

## 1. Lead-lag profile
Percentile of OMI on flood days among +/-45-day controls (0.5 = none), lags 1 to 28 days:

| Series | Range of mean percentile | Every CI includes 0.5? |
|---|---|---|
| Amplitude | 0.43 to 0.52 | yes |
| PC1 | 0.44 to 0.57 | yes |
| PC2 | 0.41 to 0.57 (lowest 0.41 at lag 14, CI 0.31-0.51) | yes |

## 2. Floods by MJO phase sector
Eight sectors by angle in the PC1-PC2 plane (rotation in time is counterclockwise); "weak" = amplitude below 1 (56% of days are active). Chi-square against the share of days, with a permutation test that keeps floods per period and calendar month (5,000 shuffles).

| Lag (MJO state N days before D) | Omnibus p | Most floods vs expected |
|---|---|---|
| 1 | 0.17 | sector 4: 7 floods in 189 days (3.7 per 100 days) vs 2.8 expected |
| 7 | 0.80 | sector 3: 4 vs 2.6 |
| 14 | 0.07 | sector 1: 7 in 171 days (4.1 per 100 days) vs 2.5 |

The sectors line up (the MJO moves about 1 sector per 5 to 6 days, so a state in sector 4 was in sector 3 a week earlier and sector 1 to 2 two weeks earlier), but that is the same events seen at three lags, not three independent tests. Evidence is 7 of 38 floods in one sector at one lag with p = 0.17; the sector was picked after looking. I have not mapped these sectors to the official OMI phase numbers 1 to 8, so I do not claim a physical reading.

## 3. Blocked-CV models (2,054 days, 38 floods, same days for every model)
| Model | PR-AUC | ROC-AUC | Capture @10% |
|---|---|---|---|
| Baseline (rain + season) | 0.070 | 0.70 | 45% |
| Baseline + MJO (PC1, PC2, amplitude) at lag 1 | 0.063 | 0.70 | 34% |
| Baseline + MJO at lag 7 | 0.063 | 0.68 | 39% |
| Baseline + TCWV | 0.111 | 0.77 | 45% |
| Baseline + TCWV + MJO lag 1 | 0.098 | 0.76 | 42% |
| Baseline + TCWV + MJO lag 7 | 0.106 | 0.76 | 34% |
| MJO lag 7 + season only | 0.021 | 0.52 | 5% |

Paired PR-AUC differences (month-block bootstrap): adding MJO lowers PR-AUC by 0.006 to 0.013 in every comparison; two of the four intervals exclude zero on the negative side, so MJO state is mildly harmful or pure noise as a linear predictor. MJO alone with season is at chance (ROC-AUC 0.52).

## 4. Caveats
- Linear PC1/PC2 terms cannot represent a single-sector effect. A sector indicator was not model-tested because the sector was chosen by looking at the same floods; a fair test needs the sector chosen on training years only, or more years of floods (the 2017-2020 chunk would give an independent check of "sector 4 at lag 1").
- 38 floods across an index with an eight-sector, 40 to 50 day cycle gives only about 2 to 3 floods per sector expected, so the test has little power.
- The MJO is also only one influence on the region; the Borneo vortex and cold surges (not tested) act on a shorter scale.
