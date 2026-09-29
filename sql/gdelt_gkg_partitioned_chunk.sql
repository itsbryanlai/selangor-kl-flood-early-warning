-- GDELT GKG flood-article candidates for Malaysia. Change the date range per chunk.
-- Table MUST be gkg_partitioned (gkg is unpartitioned, ~2.4 TB per scan). Filter on _PARTITIONTIME.
-- Check the estimated bytes in the console before running; keep each chunk under ~900 GB.
-- Sandbox free quota: 1 TiB/month. Export via Save results -> Google Drive -> CSV.
SELECT DATE, DocumentIdentifier AS url, V2Locations, V2Themes
FROM `gdelt-bq.gdeltv2.gkg_partitioned`
WHERE _PARTITIONTIME BETWEEN TIMESTAMP('2015-01-01') AND TIMESTAMP('2016-12-31')
  AND (
    REGEXP_CONTAINS(V2Themes, r'NATURAL_DISASTER_FLOOD(ING|S|ED)?')
    OR REGEXP_CONTAINS(V2Themes, r'NATURAL_DISASTER_HEAVY_RAIN')
    OR REGEXP_CONTAINS(V2Themes, r'NATURAL_DISASTER_MONSOON')
  )
  AND REGEXP_CONTAINS(V2Locations, r'Malaysia')
