# Data source findings

| Need | Source | Status |
|---|---|---|
| Rainfall history | Open-Meteo Historical Weather API (free, ERA5-based, back to 1940, ~9 km) | Solved, not yet pulled |
| Forecast/warnings | data.gov.my / MET Malaysia API (`api.data.gov.my/weather/forecast`, `/weather/warning`), 4 req/min | Live/forecast only, no history |
| River/water levels | Public InfoBanjir (DID/JPS) | Live only. No historical archive, no official API. Community scrapers (arma7x/publicinfobanjir, illusionikx/selangor-flood-tracker) don't publish history |
| Wayback backfill of InfoBanjir | ruled out | ~25 captures/4.5 yrs for Selangor, fragmented URLs, likely JS-unrendered |
| Flood labels (A) | Kaggle "Malaysia flood and flash flood dataset 2010-2026" (abdullahbinwaleed) | Synthetic rainfall-threshold label, not ground truth. Comparison baseline only |
| Flood labels (B, main) | GDELT via BigQuery (news-derived, independent of rainfall) | In progress |

Prospective river-level history needs a continuous live InfoBanjir/JPS scraper (Selangor + WP KL). Need 12 months minimum, 24-36 for robust evaluation.

Two-stream label design: (1) rainfall-threshold candidates, (2) independent GDELT/news sweep; union, dedupe, verify into `(date, location, confidence)`.

## Added later (tested)
| Need | Source | Status |
|---|---|---|
| Rain gauges | NOAA GHCN-Daily, Subang (MYM00048647) and KLIA (MYM00048650), no account | 2015 to 2025-08-24, gaps; 2 points; see [gauge-tide.md](gauge-tide.md) |
| Forecast rain with lead time | Open-Meteo Previous Runs API (forecasts issued 1 and 2 days earlier) | From 2024-01-19 |
| Measured tide | UHSLC station Kelang (Port Klang, id 140) via ERDDAP | 2005 to 2023-01-06 with gaps; fitted to predict tide 2015-2026 |
| Tide from API | Open-Meteo marine `sea_level_height_msl` | Only from about 2024 (empty for 2016/2020/2022) |
| Satellite rain | NASA GPM IMERG, JAXA GSMaP, CHIRPS | Not tested; IMERG needs an Earthdata account |

## BigQuery / GDELT facts
- Project `flood-prediction-510016`, Sandbox, 1 TiB/month free, resets monthly.
- `gdelt-bq.gdeltv2.gkg` is NOT partitioned (~2.4-2.56 TB per query). Do not use.
- `gdelt-bq.gdeltv2.gkg_partitioned` is partitioned by `DATE(_PARTITIONTIME)`; filter on `_PARTITIONTIME`. About 290-300 GB/year (2015-2016 = 593.53 GB; 2015-2018 = 1.17 TB, over cap).
- A query estimated above remaining quota is rejected. Free export: Save results -> Google Drive -> CSV (up to 1 GB); local download caps at 10 MB.
- `events_partitioned` exists for 2010-2015 Events pull; untested. `EventRootCode='19'` disaster filter is an unverified guess, check the CAMEO codebook.
- Flood themes: `NATURAL_DISASTER_FLOOD`, `_FLOODING`, `_FLOODS`, `_FLOODED`, `_HEAVY_RAIN`, `_MONSOON`; also seen `FLASH_FLOOD(S)`, `TORRENTIAL_RAIN`, `FLOODED_ROADS/AREAS`, `WB_154_FLOOD_PROTECTION`.

## Chunks
Done: 2015-2016 (57,087 rows). Remaining, one per monthly quota: 2017-18, 2019-20, 2021-22, 2023-24, 2025-2026-09.

## GKG columns and profiling
- `DATE` YYYYMMDDHHMMSS (15-min batch, ~publish time); `url`; `V2Locations` (`;`-separated `type#name#cc#ADM1#ADM2#lat#long#featureID#charOffset`); `V2Themes` (`THEME,charOffset;...`).
- Sample (2,278 rows, non-random): ~26% mention Selangor/KL; very noisy (median 17 places/article, max 1,371); false positives exist; MONSOON matches non-Malaysian stories; DATE is publish date, aftermath stories exist; many articles per event. A flood-theme-within-300-chars-of-place filter was insufficient.
- Output is candidate events, not ground truth; no severity/depth/duration.
