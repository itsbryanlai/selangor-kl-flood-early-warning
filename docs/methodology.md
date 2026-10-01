# Methodology: from raw GDELT to flood labels

One-page map of every data-processing decision so far, why it was made, and what went wrong on the way. Chronological detail and numbers are in [data-preprocessing.md](data-preprocessing.md); query cost work is in [bigquery-query-optimization.md](bigquery-query-optimization.md); source findings are in [data_sources.md](data_sources.md).

## 1. Pipeline at a glance
```
GDELT GKG (BigQuery, free sandbox)          Open-Meteo ERA5 hourly rain (5 grid points)
        |  sql/*.sql -> Drive CSV                    |  src/rainfall/openmeteo.py
        v                                            |
raw CSV (data/raw)                                   |
        |  parse.py (V2) / parse_v1.py (V1)          |
        v                                            |
articles + target_locations (data/interim)           |
        |  daily.py: tiers + spike detection         |
        v                                            |
daily series -> events.py: cluster spike days        |
        |                                            |
        +--> recall.py: 2nd-pass candidates  <-------+   (rain day AND news evidence)
        v
candidate events -> textcheck.py (auto) + manual read -> annotations/*.csv (verdicts, dates, districts)
        |
        v
labels.py (positives) + negatives.py (daily labels) -> data/processed
```

## 2. Label design (why two streams)
- No public flood ground truth exists for Selangor/KL. The Kaggle "flood dataset" is a synthetic rainfall-threshold label, so it cannot be ground truth or an independent check.
- Stream 1: rainfall-threshold candidates (ERA5). Stream 2: GDELT news flood articles, found without looking at rain. The union, deduplicated and verified by reading article text, gives `(date, district, confidence)` events.
- Reason for stream 2: ERA5 (about 9 km) smooths short convective downpours, so KL flash floods and tidal floods often show ordinary rainfall. 2016 example: confirmed floods on 2016-06-04, 06-19 and 09-19 had 2, 5 and 3 mm of ERA5 rain.

## 3. Extraction from BigQuery
| Decision | Why |
|---|---|
| Use `gkg_partitioned`, filter on `_PARTITIONTIME` | `gkg` is unpartitioned (~2.4 TB/scan); pruning by partition cuts the scan |
| Chunk by date range, one per free monthly quota | 1 TiB/month sandbox cap; a query over the remaining quota is rejected |
| Chunk 1 (2015-16): V2 columns, "Malaysia" anywhere | 593.5 GB; kept offsets, but too noisy (a Missouri story matched) |
| Chunk 2 (2024-26): V1 `Themes`/`Locations`, `MY12`/`MY14` or names, wider flood themes | 237.5 GB for 2.75 years; about 52% cheaper per column set; row filter is cheap noise control, not cost control |
| Dry run before every run | Estimates matched billed bytes exactly |
| Drive CSV export (<= 1 GB) | Local download caps at 10 MB; Cloud Storage needs billing (forbidden) |
| Raw GDELT files instead of BigQuery: rejected | 2.4 to 6.1 TB of downloads vs a ~100 GB bandwidth cap; downloader kept for small windows ([raw_download.py](../src/gdelt/raw_download.py)). Validation: identical content to BigQuery; translated (Chinese) outlets live in separate `.translation.gkg` files |

## 4. Parsing and cleaning (`parse.py`, `parse_v1.py`)
- Read everything as strings; deduplicate by URL keeping the earliest publish time (57,087 -> 57,054 in chunk 1).
- Locations: split on `;` then `#`. V2 has 9 fields (adds character offset); V1 has 7. Drop malformed entries and non-numeric coordinates.
- Selangor and KL by GDELT FIPS-style ADM1 code (`MY12`, `MY14`), plus the words "Selangor"/"Kuala Lumpur" in V1. Places coded `MY00` (Petaling, Morib) are missed in V2.
- Themes: flags for flood (any theme containing `FLOOD`), flash flood, heavy rain, monsoon, torrential rain.
- Source domain from the URL; Malaysian-domain flag (`.my` suffix or a hand list).
- Time: GDELT `DATE` is UTC publish time; day = Malaysia local date (+8 h). It is not the event date.
- V2 only: minimum character distance between a flood-theme offset and a Selangor/KL place offset. Missing (NaN) for V1, where the proximity check is skipped.

## 5. Tiers, spikes, events
- Tiers (all need a Selangor/KL place): loose (any theme in export), strict (flood theme, near a place if offsets exist, aggregators excluded), strict-Malaysian (`n_strict_my`).
- Aggregators (`reports.pr-inside.com`, `forums.asiaone.com`) excluded; they repost wire stories.
- Spike rule: robust z-score vs a centered 61-day rolling median/MAD, scale floored at 1, z >= 3.5, count >= 4. Run on `n_strict_my`, not `n_strict` (spam and foreign-flood stories produced false spikes).
- Events: spike days at most 2 days apart merge; evidence counted from strict Malaysian-domain articles in the window.
- Second pass (`recall.py`): relaxed news (z >= 2.5, >= 3 articles) plus rain-and-news days (ERA5 >= p95 daily or p99 hourly with >= 3 articles on day..day+1). Excludes days within 2 days of first-pass events. Roughly doubled confirmed floods in chunk 1 (4 to 8) at about 5 of 22 precision.

## 6. Verification
- Manual: read fetched article text per candidate; verdicts, event date, district and flood type go in `annotations/event_verdicts_*.csv` (committed; the only hand-made labels).
- Automatic ([textcheck.py](../src/gdelt/textcheck.py)): fetch up to 10 Malaysian-domain articles per event (paragraph text only, cached); score the best flood sentence: +flood term, +Selangor/KL place in the same sentence, +event verb; penalties for figurative use (rallies, "flood of"), policy or preparedness wording, hypotheticals/warnings, other-year references, floods in other states, mixed lists of states. Malay event words supported. Own geocoded place names and dateline "here" count as places, unless the headline names another state.
- Event decision: accept (>= 2 passing articles), reject (>= 2 fetched, none pass), else review. On chunk 1: all 8 confirmed events accepted, none of 19 rejected events accepted (11 land in review). Rules were tuned on these events, so treat that as optimistic.
- Limits: about 40% of old URLs do not fetch; Chinese-language articles are unreadable to the English rules; tidal and warning-type events are rejected by design.

## 7. Rainfall
Open-Meteo archive (ERA5, hourly, `Asia/Kuala_Lumpur`), 5 points (KL, Shah Alam, Klang, Kuala Selangor, Sepang); daily total/hourly max taken as the maximum across points. Percentiles are computed within the study period.

## 8. Negatives and daily labels (`negatives.py`)
Classes: `flood` (y=1), `easy_negative` (low rain and almost no flood news), `moderate_rain_negative` (rain-matched), `hard_news_negative` (read and rejected spike days), and unlabeled classes with empty y (`ambiguous_heavy_rain`, `near_event`, `uncertain_event`, `unlabeled`). "Negative" means no evidence of a flood, not proof of none. Known skew: negatives under-represent the monsoon.

## 9. Failure modes that shaped the design
| Failure | Fix |
|---|---|
| Foreign floods, spam and rallies inflated spikes | Malaysian-domain tier, text check with figurative filters |
| Whole-page text let sidebar junk win | Paragraph text only |
| Past-year references ("2014 floods") accepted | Year mismatch penalty |
| "KUALA LUMPUR:" dateline made Sarawak/Johor floods pass | Strip datelines; require place in the flood sentence; other-state penalty |
| GDELT geocoded a Penang village to KL | Own-place matches ignored when the headline names another state |
| Regex edit silently dropped a scoring term | Re-ran the validation table after every rule change |
| My raw-download estimate was 2 to 8x too low (sampled small overnight files) | Re-measured six times of day for ten years before recommending |
| Validator lag in the BigQuery console looked like an error | Poll the page text for up to 40 s |

## 10. Modeling (2024-2026 feasibility)
Feature design, label schemes, evaluation protocol and results: [modeling-2024-2026.md](modeling-2024-2026.md). Key choices: features only from before day D (ERA5 through D-1; forecasts from the Open-Meteo Previous Runs API issued 1 and 2 days before), expanding-window temporal splits, two label schemes (all vs labeled) because unlabeled days matter, single-feature rain baselines plus fixed-hyperparameter logistic regression, month-block bootstrap CIs and permutation tests because only 14 flood days exist.

Update: three label periods now exist (2015-16 V2 columns; 2021-23 and 2024-26 V1 columns) giving 40 hand-verified flood days; the combined evaluation is in [modeling-2024-2026.md](modeling-2024-2026.md). Text-check fetching now runs events in parallel with a 15 s timeout (old links hang otherwise).

## 11. Moisture and instability features
ERA5 moisture/heating and NWP CAPE/850 hPa state (2021-04 onward): [instability-features.md](instability-features.md). Column moisture is the only useful new predictor; CAPE and theta-e are not.

Water-vapour follow-up (level, anomaly, tendency, flux convergence, 850 hPa humidity; TCWV gap in 2024 H1 left missing after a rejected regression fill): [water-vapour.md](water-vapour.md).

## 12. Hour and district labels
Event date, onset hour, districts and coordinates for the 25 usable events: [hour-district-labels.md](hour-district-labels.md). Hand-reviewed extraction (rules are noisy), three date corrections, and a local-rain test showing precise labels help only slightly with ERA5.

## 12. Reproduce
```
python -m src.gdelt.parse_v1 data/raw/gdelt_gkg_v1_2024_2026.csv        # or src.gdelt.build_interim for V2
python -m src.gdelt.daily  data/interim/<stem>_articles.parquet
python -m src.gdelt.events data/interim/<stem>
python -m src.rainfall.openmeteo <start> <end>
python -m src.gdelt.recall data/interim/<stem> data/interim/rain_hourly_<start>_<end>.parquet
python -m src.gdelt.textcheck data/interim/<stem> [annotations/<verdicts>.csv]
python -m src.gdelt.labels / negatives  ...
```
