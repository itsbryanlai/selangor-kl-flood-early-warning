# BigQuery query optimization (GDELT GKG)

How the GDELT query was made cheaper, what was measured, and what to watch for. Template: [sql/gdelt_gkg_v1_chunk.sql](../sql/gdelt_gkg_v1_chunk.sql). The first chunk (2015-2016) used the older [sql/gdelt_gkg_partitioned_chunk.sql](../sql/gdelt_gkg_partitioned_chunk.sql).

Constraints (unchanged): BigQuery Sandbox, no billing, 1 TiB/month free quota; never touch billing; run only what the user has approved. Dry runs (the console's "This query will process X GB") are free and do not use quota.

## 1. How BigQuery bills this
- On-demand cost = bytes of every column the query references, over every row in the partitions read. **Row filters (WHERE on values, LIMIT) do not reduce it.** Only fewer columns and fewer partitions do.
- `gdelt-bq.gdeltv2.gkg` is unpartitioned (~2.4 TB per scan). `gkg_partitioned` is partitioned by day: filter on `_PARTITIONTIME` (not the `DATE` column) so partitions are pruned.

## 2. What was changed and why
| Change | Effect |
|---|---|
| Use `gkg_partitioned` with `_PARTITIONTIME` range | Prune to the chunk's dates (already done for chunk 1) |
| Use V1 `Themes` and `Locations` instead of `V2Themes` and `V2Locations` | **About 52% cheaper** (June 2025: 3.21 GB vs 6.69 GB). V1 has no character offsets |
| Select only the columns needed | Adds `SourceCommonName`, `GKGRECORDID` (~0.16 GB/month); skips the other ~20 columns |
| Row filter `MY12`/`MY14` (Selangor/KL ADM1) or the names | No scan saving, but the export shrinks (about 57k rows in chunk 1 to about 13k) and the Missouri-style false positives go; the name match catches Selangor places coded `MY00` |
| Widen themes to `FLOOD` (any), `TORRENTIAL_RAIN`, heavy rain, monsoon | Free: the theme column is already scanned. Catches `FLASH_FLOOD`, `WB_154_FLOOD_PROTECTION`, etc. |
| Dry-run before every run | Stops a run that would exceed the quota (a query over the remaining quota is rejected outright) |

Offsets were dropped because the sentence-level article text check ([src/gdelt/textcheck.py](../src/gdelt/textcheck.py)) replaces the "flood within 300 characters of the place" tier.

## 3. Measured (dry runs, all free)
Per-column cost, June 2025 (one month):
| Columns | Scan |
|---|---|
| `DATE`, `DocumentIdentifier` | 506 MB |
| `Locations` (V1) | 552 MB |
| `Themes` (V1) | 2.18 GB |
| `DATE`, `DocumentIdentifier`, `Themes`, `Locations` | 3.21 GB (sum matches: costs are additive) |
| plus `SourceCommonName`, `GKGRECORDID` | 3.37 GB |
| V2 baseline: `DATE`, `DocumentIdentifier`, `V2Themes`, `V2Locations` | 6.69 GB |

Full query (V1 set), by date range:
| Range | Scan |
|---|---|
| 2017 | 160.2 GB |
| 2018-2019 | 251.4 GB |
| 2020-2021 | 180.6 GB |
| 2022-2023 | 168.4 GB |
| 2024 | 94.4 GB |
| 2025 | 83.8 GB |
| 2026-01-01 to 2026-09-29 | 59.1 GB |
| **2017 to Sep 2026** | **about 998 GB** (earlier estimate was about 3 TB) |
| 2024-01-01 to 2026-09-30 (one query) | 237.5 GB |

GDELT volume varies by year (2018-2019 heaviest), so per-year cost is not constant; the 2-year rows above are sums of two years, measured together to save time.

## 4. Plan and rules of thumb
- Run newest first: 2024-2026 (237.5 GB), then 2022-2023, 2020-2021, 2018-2019, 2017 as quota allows (about 761 GB for the rest; one month's 1 TiB is about 1,099 GB, so leave margin and split).
- Keep each chunk under ~900 GB and under the remaining monthly quota. Export via Save results -> Google Drive -> CSV (up to 1 GB; the local download is capped at 10 MB, Cloud Storage needs billing so avoid it).
- To try a change cheaply, dry-run a one-month slice first and compare to the table above.
- Rejected alternative: downloading GDELT's raw 15-minute files (about 2.4 TB English-only, about 6.1 TB with translations; measured about 10 MB/s) did not fit the user's roughly 100 GB bandwidth cap. Downloader kept in [src/gdelt/raw_download.py](../src/gdelt/raw_download.py) for small targeted windows only.

## 5. Run log
| Chunk | Run | Scan (dry run / actual billed) | Rows | Export |
|---|---|---|---|---|
| 2015-01-01 to 2016-12-31 (V2 columns, old query) | 2026-09-28 | 593.53 GB | 57,087 | Drive CSV, 280 MB |
| 2024-01-01 to 2026-09-30 (V1 columns, this doc's query) | 2026-10-01 00:06 UTC+8 (2026-09-30 16:06 UTC) | 237.5 GB / 237.5 GB (Sandbox quota, no charge) | 8,453 | Drive CSV (user downloads to `data/raw/`) |

- The dry-run estimate matched the billed bytes exactly, so dry runs are reliable for planning.
- The V1 `Locations` format is confirmed on real rows: `4#Kuala Lumpur, Kuala Lumpur, Malaysia#MY#MY14#3.16667#101.7#-2401322`, so the `#MY1[24]#` pattern works.
- Quota month boundary: the run happened at 16:06 UTC on Sep 30, so it may count against September's quota rather than October's (unconfirmed). September use was then about 594 + 237.5 = about 831 GB of about 1,099 GB.
- Row volume is much lower than 2015-2016 (about 3,000 per year against about 30,000), because GDELT's news volume dropped (raw file sizes fell from about 14 MB in 2016 to 3-6 MB per file by 2021-2025), so the earlier years are the bigger chunks.
- Some matched rows are noise: `KL` appears somewhere in a long location list of a foreign story (e.g. a bushfire story from an Australian outlet). The article text check and the Malaysian-domain filter handle these downstream.

## 6. Caveats
- V1 columns have no offsets, so `min_flood_loc_dist` cannot be computed for these chunks; the parser and daily series need a V1 variant.
- Translated (non-English) articles: BigQuery `gkg` merges the English and translation files, so Chinese-language Malaysian outlets appear in the results but cannot be read by the English text check.
- Console quirks when automating: the validator takes 10 to 40 s to refresh for long queries and the message disappears while it validates; reading page text after a wait works better than screenshots. Running a query in the console is one click on Run (never the Upgrade banner).
