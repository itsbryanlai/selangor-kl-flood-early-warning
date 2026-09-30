-- GDELT GKG Selangor/KL flood-article candidates, trimmed for scan cost (V1 columns, no offsets).
-- Change the _PARTITIONTIME range per chunk. Check the console's estimated bytes first (free).
-- Sandbox free quota: 1 TiB/month. Export: Save results -> Google Drive -> CSV.
-- Rationale and measured costs: docs/bigquery-query-optimization.md
SELECT GKGRECORDID, DATE, SourceCommonName, DocumentIdentifier, Themes, Locations
FROM `gdelt-bq.gdeltv2.gkg_partitioned`
WHERE _PARTITIONTIME BETWEEN TIMESTAMP('2024-01-01') AND TIMESTAMP('2026-09-30')
  -- V1 Locations entries: type#name#countrycode#ADM1code#lat#long#featureID (MY12 Selangor, MY14 KL)
  AND REGEXP_CONTAINS(Locations, r'#MY1[24]#|Selangor|Kuala Lumpur')
  AND REGEXP_CONTAINS(Themes, r'FLOOD|TORRENTIAL_RAIN|NATURAL_DISASTER_HEAVY_RAIN|NATURAL_DISASTER_MONSOON')
