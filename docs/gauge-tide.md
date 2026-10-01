# Rain gauges and tide: do they help?

Code: [ghcnd.py](../src/rainfall/ghcnd.py) (gauges), [harmonic.py](../src/tide/harmonic.py) (tide), [gauge_tide_analysis.py](../src/modeling/gauge_tide_analysis.py) (analysis, `python -m src.modeling.gauge_tide_analysis`). Results CSVs are in `data/processed/model_results_tide_*.csv` (not committed).

> Note: the numbers in this doc were computed before three event-date corrections (see [hour-district-labels.md](hour-district-labels.md)). Re-running changes them slightly (2015-16 same-day ERA5 ROC-AUC 0.745 to 0.806, gauge 0.625 to 0.581; 2024-26 model PR-AUCs by 0.01 or less) and leaves every conclusion unchanged.

**Short answer:** two point gauges do not beat ERA5 at telling flood days apart, so ERA5's coarseness is not the only problem (label timing and location probably matter as much). Predicted tide adds nothing for flash floods but is a strong, known-in-advance signal for the tidal floods we have labeled.

## 1. Rain gauges (NOAA GHCN-Daily, free, no account)
- Stations: Subang (MYM00048647, Petaling) and KLIA (MYM00048650, Sepang). Daily totals 2015-01-01 to 2025-08-24 (about 200 to 365 days per year; 2020-21 and 2025 are sparse). Only two points, 10 to 40 km from most flood sites.
- **Agreement with ERA5 is low.** Daily correlation with the nearest ERA5 point is 0.12 to 0.28 same-day, 0.27 to 0.34 when the gauge reading is paired with the previous day's ERA5 (i.e. the reading dated D+1). ERA5 shows 30 mm or more on only 3 to 21% of the days when a gauge reads 30 mm or more, so ERA5 misses many heavy-rain days.
- **Date convention is unclear.** In 2015-16 the next-morning alignment discriminates flood days better (AP 0.097 vs 0.034), in 2024-26 the same-date alignment does (0.143 vs 0.059). Either the reporting convention changed or eight flood days is too few to tell. Treat gauge timing as unresolved (would need the station's observation time).
- **Flood-day discrimination (same-day rain as the score, all flood days with gauge data: 19 floods, 934 days, base rate 2.0%):**

| Score | PR-AUC | ROC-AUC | Median on flood days | Median on other days |
|---|---|---|---|---|
| ERA5 area max | 0.076 | 0.77 | 27.6 mm | 8.9 mm |
| Gauge, same date | 0.063 | 0.68 | 9.1 mm | 2.8 mm |
| Gauge, next-morning reading | 0.063 | 0.72 | 18.3 mm | 2.3 mm |

  The gauges are not better than ERA5. Flood days are not reliably the days these two gauges see the most rain, which points at spatial mismatch (floods are local) and date error in the labels, not only at ERA5's resolution.
- Not used as model features: the record ends in Aug 2025 with gaps, so a model using it would be imputed for much of the 2025-26 test window.

## 2. Tide (Port Klang)
- Data: UHSLC research-quality hourly sea level, station "Kelang" (id 140, 3.05 N, 101.36 E), via ERDDAP. 2005-01 to 2023-01-06 with gaps (2016: 3,884 hours, 2020: none). Nothing for 2023-26.
- Model: UTide harmonic fit on 2005-2022, then predicted hourly tide for 2015 to 2026 (Malaysia local time). **Held-out 2022: RMSE 0.154 m, correlation 0.995** (tide standard deviation 1.13 m; mean residual +0.106 m). Top constituents M2 1.37 m, S2 0.69, N2 0.26, K2 0.19, K1 0.19. Astronomical tide only (no surge or river discharge). Because tide is predictable, it is a legitimate lead-time feature.
- Open-Meteo's marine sea level works only from 2024 (empty for 2016, 2020, 2022), so it is not needed.
- Daily high water (HW) quantiles 2015-26: median 5.26 m, p75 5.61, p90 5.88, p97 6.14, max 6.49.
- **Flood days vs tide (25 flood days, chance = 25% above p75, 10% above p90):** 44% above p75 and 24% above p90. The three tidal floods are extreme: 2016-09-19 (HW 6.15 m, 97th percentile), 2016-10-16 (6.26 m, 99th), 2016-11-14 (6.21 m, 98th). Flash floods sit anywhere (for example 2024-04-17 at the 1st percentile).
- **High-tide days (HW at or above p97, about 11 per year):** 2015-16: 29 days, three episodes carry a labeled flood within +/- 1 day, all three being the tidal floods above (roughly one high-tide episode in four or five). 2024-26: 27 high-tide days, 2 near labeled floods, both flash floods (2024-08-22/23, 2024-11-14/15); no tidal flood is labeled in 2024-26 and news volume on high-tide days is no higher than on other days (median 3 strict Malaysian articles vs 3), so either tidal floods went unreported or our news filter misses them.

## 3. Do they improve the models?
2024-26 expanding windows (8 test floods), PR-AUC (base rate 1.4% for scheme all):

| Model | all | labeled |
|---|---|---|
| Sparse (forecast, 7-day rain, monsoon) | 0.216 | 0.276 |
| Sparse + tide | 0.208 | 0.279 |
| Observed only | 0.049 | 0.228 |
| Observed + tide | 0.033 | 0.323 |
| Tide high-water alone | 0.018 (chance) | 0.053 (chance) |

Transfer (train 2015-16, test 2024-26, 14 floods): observed 0.051 (all) and 0.220 (labeled); observed + tide 0.053 and 0.225; tide alone 0.028 and 0.097. All differences are well inside the confidence intervals (see [modeling-2024-2026.md](modeling-2024-2026.md)). So tide does not help the all-flood model; it is tied to a subset (tidal floods).

## 4. What this means
1. Gauges: add nothing at two stations; the real prize is a dense gauge network (DID InfoBanjir, historical data by formal request, and a scraper for new data) with exact observation times.
2. Tide: useful as a separate rule, not as a feature in the general model. A tidal-flood alert could be "predicted HW at or above about 6.1 m (p97)". It captured 3 of 3 labeled tidal floods at a cost of about 11 alert days a year, but the precision is low (about one episode in four or five) and there are only three tidal events to learn from.
3. Both of the suggested data upgrades leave the main limit unchanged: too few, imprecisely dated and located flood labels (next: hour and district labels, then more years).

## 5. Caveats
- Three tidal events and 8 to 19 flood days give very wide uncertainty; percentile statements are descriptive, not tested.
- Predicted tide uses fixed 2005-2022 constituents; sea-level rise, a +0.1 m mean offset in 2022 and no surge mean real tide heights differ by about +/- 0.15 m or more.
- The UHSLC record and GHCN-D gauges are sparse in exactly the years that matter most (2020-21).
