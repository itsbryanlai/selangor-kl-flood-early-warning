# Selangor + Kuala Lumpur Flood Early Warning

Binary classifier that predicts floods in Selangor and Kuala Lumpur *before* they happen, using only public data. Features from time t, label at t+lead (early warning, not detection).

## Evaluation plan
- Metrics: CSI/Threat Score, precision/recall/F1, PR-AUC, Brier, stratified by lead time.
- Splits: temporal only (never random), plus spatial holdout and seasonal stratification (NE monsoon Nov-Mar; inter-monsoon Apr-May, Oct-Nov).
- Baselines to beat: persistence, climatology.

## Docs
- [docs/methodology.md](docs/methodology.md): one-page map of every processing/cleaning decision
- [docs/data-preprocessing.md](docs/data-preprocessing.md): chronological log with numbers
- [docs/bigquery-query-optimization.md](docs/bigquery-query-optimization.md): query cost strategy and run log

## Data sources
See [docs/data_sources.md](docs/data_sources.md). Labels come from two streams: rainfall-threshold candidates (Open-Meteo) and an independent GDELT news sweep, unioned and verified.

## Constraints
- BigQuery runs in **Sandbox (no billing)**. Never touch billing. No new BigQuery queries without explicit user approval.
- Large data (`data/`, CSV, parquet) is never committed.

## Status
- GDELT chunks processed: 2015-2016, 2021-2023, 2024-2026 (40 hand-verified flood days). Remaining BigQuery chunks (2017-2020, 507.63 GB) are approved but were rejected on 2026-10-01 for exceeding the free quota (about 15 GB left; likely a rolling 30-day window, retry around 2026-10-28).
- Findings so far: rain-based signal exists (same-day rain), but lead-1 observed-rain models barely beat month climatology; gauges, tide and precise labels do not change that. See docs/modeling-2024-2026.md and docs/instability-features.md (column moisture helps modestly; CAPE does not), docs/water-vapour.md (floods are absent on dry nights; modest model gains).
- GDELT chunk 2015-2016 done (57,087 rows, in the user's Google Drive; place at `data/raw/gdelt_gkg_2015_2016.csv`).
- Next: clean/parse GDELT, build daily series, verify candidates, pull Open-Meteo rainfall, start InfoBanjir scraper. Full plan in [HANDOFF.md](HANDOFF.md).
