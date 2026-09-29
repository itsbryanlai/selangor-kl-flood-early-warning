# HANDOFF: Selangor + Kuala Lumpur flood early-warning model

Repo: `selangor-kl-flood-early-warning`

## 1. Project goal
Build a **binary classification model** that predicts floods in **Selangor and Kuala Lumpur (Malaysia) before they happen**, using only **publicly available data**. It must be a true early-warning task (features from time t, label at t+lead), not flood detection.

Confirmed earlier:
- No public flood-prediction model exists for this region. A private SMART Tunnel system covers one KL chokepoint, and some academic papers exist.
- Evaluation plan:
  - **Metrics:** CSI/Threat Score, precision/recall/F1, PR-AUC, Brier score, and performance stratified by lead time.
  - **Splits:** temporal train/test only (never random), plus a spatial holdout and seasonal stratification (NE monsoon Nov-Mar; inter-monsoon Apr-May and Oct-Nov).
  - **Baselines to beat:** persistence and climatology.

## 2. Data source findings
See [docs/data_sources.md](docs/data_sources.md) for the table and BigQuery/GDELT facts.

Design principle: **two-stream label set**.
1. Rainfall-threshold candidates (Open-Meteo/Kaggle).
2. An independent GDELT/news sweep not conditioned on rainfall, so low-rainfall and flash floods aren't systematically missed.
Union, deduplicate, and verify into a clean (date, location, confidence) event table.

Prospective river-level history needs a **live InfoBanjir/JPS scraper for Selangor and WP KL** running continuously. Not started. Need 12 months minimum, 24-36 for robust evaluation.

## 3. HARD CONSTRAINTS (from the user)
- **Never touch anything related to billing** in Google Cloud. Don't click "Upgrade", don't open billing settings, don't link a billing account. The project is intentionally in **BigQuery Sandbox (no billing)**, capping cost at the free 1 TiB/month.
- The user asked to **stop query experiments** for now. **Do not run new BigQuery queries unless the user explicitly says so.**
- Working style: BLUF and concise. Verify claims, and correct earlier mistakes openly.

## 4. Where we are: GDELT label sweep
- GCP project `flood-prediction-510016`, Sandbox. Use `gkg_partitioned`, filter on `_PARTITIONTIME`. Query template: [sql/gdelt_gkg_partitioned_chunk.sql](sql/gdelt_gkg_partitioned_chunk.sql).
- **Chunk 1 (2015-01-01 to 2016-12-31) done: 57,087 rows.** Full file (280.1 MB) is in the user's Google Drive as `bq-results-20260928-170009-1790614875839.csv`, not in this repo. A partial 2,278-row sample (10 MB browser download) was profiled; it is non-random (37 distinct dates, clustered).
- Remaining chunks (each a separate month's free quota; test estimate first, keep each under ~900 GB): 2017-18, 2019-20, 2021-22, 2023-24, 2025-2026-09. Optionally 2010-2015 via the events table (`EventRootCode='19'` is unverified; check CAMEO codebook).
- About 594 GB was used in September 2026.

## 5. Data features and profiling findings
Columns: `DATE` (YYYYMMDDHHMMSS, 15-min GDELT batch, ~publish time), `url`, `V2Locations` (`;`-separated `type#name#countrycode#ADM1code#ADM2code#lat#long#featureID#charOffset`; Malaysian entries reach district level), `V2Themes` (`THEME,charOffset` pairs).

Sample findings (2,278 rows):
- ~26% mention Selangor or KL place names.
- Top sources: The Star, Malay Mail, FMT, Bernama, NST, Malaysiakini, plus foreign outlets.
- **Very noisy.** Filter only requires "Malaysia" somewhere. Median article lists 17 places, max 1,371. False positives: a Missouri army-fort story, palm oil futures, politics.
- `MONSOON` also matches non-Malaysian regional stories.
- `DATE` is publication date, not event date. Aftermath stories exist. Many articles per event; need clustering.
- "Flood theme within 300 chars of a specific Malaysian place" was tried and was **not sufficient**.
- Output is candidate events, not ground truth. No severity, depth or duration.

## 6. Next steps
1. Set up the repo (done).
2. Get the full 2015-2016 CSV into `data/raw/gdelt_gkg_2015_2016.csv` (user downloads from Drive). If unavailable, work from a partial sample and say so.
3. **Clean and structure:** parse `V2Locations` into rows; keep MY entries with ADM1 in {Selangor, Kuala Lumpur (Wilayah Persekutuan)}; extract theme flags, source domain, lat/long; dedupe URLs; prefer articles where the flood theme and a Selangor/KL location are near each other AND the article is Malaysia-focused (Malaysian domain or few distinct locations).
4. **Daily series** of Selangor/KL flood-article counts, detect spikes, cluster into candidate events (date range, districts, article count, source diversity).
5. **Verify a sample:** fetch article text, confirm flood and extract event date/location. Cross-check against known events and Open-Meteo rainfall. Output label table `(date, district, lat, lon, confidence, n_articles, sources)`.
6. Pull **Open-Meteo hourly/daily rainfall** for Selangor/KL grid points (2015 onward); build the rainfall-threshold candidate stream; compare to Kaggle as baseline only.
7. Later, when the user approves: further BigQuery chunks with the same pipeline.
8. Start the **InfoBanjir/JPS scraper** (Selangor/WP KL stations); must run continuously (e.g. GitHub Actions cron or small VPS), storing timestamped snapshots.
9. Modeling: rainfall, antecedent rainfall, season, river level (when available), all at time t. Label = flood in next N hours/days (test several leads). Temporal splits, baselines, lead-stratified metrics.

## 7. Environment note
In the previous session the sandbox could not reach web.archive.org, and the GDELT DOC API returned repeated 429s. Rely on BigQuery exports and the free Open-Meteo API instead.
