# Selangor + Kuala Lumpur Flood Early Warning

Binary classifier that predicts floods in Selangor and Kuala Lumpur *before* they happen, using only public data. Features from time t, label at t+lead (early warning, not detection).

## Evaluation plan
- Metrics: CSI/Threat Score, precision/recall/F1, PR-AUC, Brier, stratified by lead time.
- Splits: temporal only (never random), plus spatial holdout and seasonal stratification (NE monsoon Nov-Mar; inter-monsoon Apr-May, Oct-Nov).
- Baselines to beat: persistence, climatology.

## Data sources
See [docs/data_sources.md](docs/data_sources.md). Labels come from two streams: rainfall-threshold candidates (Open-Meteo) and an independent GDELT news sweep, unioned and verified.

## Constraints
- BigQuery runs in **Sandbox (no billing)**. Never touch billing. No new BigQuery queries without explicit user approval.
- Large data (`data/`, CSV, parquet) is never committed.

## Status
- GDELT chunk 2015-2016 done (57,087 rows, in the user's Google Drive; place at `data/raw/gdelt_gkg_2015_2016.csv`).
- Next: clean/parse GDELT, build daily series, verify candidates, pull Open-Meteo rainfall, start InfoBanjir scraper. Full plan in [HANDOFF.md](HANDOFF.md).
