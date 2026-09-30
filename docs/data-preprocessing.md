# Data preprocessing: GDELT GKG (chunk 2015-2016)

Log of what was done to the raw GDELT export, so results can be traced and reproduced.
Code: [src/gdelt/parse.py](../src/gdelt/parse.py), [src/gdelt/build_interim.py](../src/gdelt/build_interim.py). Commit `e41d71a`.

## 1. Raw input
- File: `data/raw/gdelt_gkg_2015_2016.csv` (293.7 MB, not committed). Exported from BigQuery via Save results -> Google Drive -> CSV. The original Drive name was `bq-results-20260928-170009-1790687821641.csv`, renamed locally.
- Produced by [sql/gdelt_gkg_partitioned_chunk.sql](../sql/gdelt_gkg_partitioned_chunk.sql) on `gdelt-bq.gdeltv2.gkg_partitioned`, `_PARTITIONTIME` 2015-01-01 to 2016-12-31 (593.53 GB scanned).
- Filter used at query time: flood, heavy-rain or monsoon theme (`NATURAL_DISASTER_FLOOD(ING|S|ED)?`, `_HEAVY_RAIN`, `_MONSOON`) AND `V2Locations` contains "Malaysia".
- Checks: 57,087 rows (matches the BigQuery result); 57,054 unique URLs; no nulls; `DATE` range 2015-02-21 to 2016-12-31 (23 months; GKG v2 starts late Feb 2015, so this is expected).
- Columns (4): `DATE`, `url`, `V2Locations`, `V2Themes`.

## 2. Format of the raw columns
- `DATE`: `YYYYMMDDHHMMSS`, 15-minute GDELT batch, approximately article publish time (not event date).
- `V2Locations`: `;`-separated entries `type#name#countrycode#ADM1code#ADM2code#lat#long#featureID#charOffset` (9 fields).
- `V2Themes`: `;`-separated `THEME,charOffset`.
- GDELT ADM1 codes for Malaysia are FIPS-style, verified from the data: `MY12` = Selangor, `MY14` = Kuala Lumpur (others include MY01 Johor, MY06 Pahang, MY03 Kelantan; `MY00` = "Malaysia (General)").

## 3. Processing steps
Run: `python -m src.gdelt.build_interim data/raw/gdelt_gkg_2015_2016.csv` (about 10 s). Outputs go to `data/interim/` (not committed).

1. Read all columns as strings.
2. Sort by `DATE`, drop duplicate `url`, keep the earliest (57,087 -> 57,054).
3. Parse `V2Locations` into entries. Drop entries without exactly 9 fields or with non-numeric lat/lon/offset (53 entries had 10 fields).
4. Parse `V2Themes` into (theme, offset) pairs.
5. Keep Selangor/KL mentions: entries with ADM1 in {`MY12`, `MY14`}.
6. Compute article-level features (below) and the target-location table.

## 4. Output tables

### `gdelt_gkg_2015_2016_articles.parquet`: 57,054 rows, one per unique URL
| Feature | From | Definition |
|---|---|---|
| `date` | `DATE` | Parsed to datetime (publish time) |
| `url` | `url` | Unchanged; dedupe key |
| `domain` | `url` | Hostname without leading `www.` |
| `my_domain` | `url` | Domain ends in `.my` or is on a hand-listed Malaysian outlet list (`MY_DOMAINS` in `parse.py`) |
| `n_locations` | `V2Locations` | Distinct place names in the article |
| `n_my_places` | `V2Locations` | Distinct Malaysian places below country level (country `MY`, ADM1 != `MY`) |
| `has_selangor` | `V2Locations` | Any place with ADM1 `MY12` |
| `has_kl` | `V2Locations` | Any place with ADM1 `MY14` |
| `has_target` | `V2Locations` | `has_selangor` or `has_kl` |
| `flood` | `V2Themes` | Any theme name contains "FLOOD" |
| `flash_flood` | `V2Themes` | Any theme name contains "FLASH_FLOOD" |
| `heavy_rain` | `V2Themes` | `NATURAL_DISASTER_HEAVY_RAIN` present |
| `monsoon` | `V2Themes` | `NATURAL_DISASTER_MONSOON` present |
| `min_flood_loc_dist` | `V2Themes` + `V2Locations` | Min character gap between any flood-theme offset and any Selangor/KL place offset; null if either is missing |

### `gdelt_gkg_2015_2016_target_locations.parquet`: 27,391 rows, one per Selangor/KL place mention
Columns: `date`, `url`, `region` (Selangor/Kuala Lumpur), `type` (1 country, 2 state, 3 city ...), `name`, `country`, `adm1`, `adm2`, `lat`, `lon`, `feature_id`, `offset` (character position in article text).

## 5. Results (2015-2016 chunk)
- 13,222 articles (23%) mention Selangor/KL.
- 3,923 of those have a flood theme within 300 characters of a Selangor/KL place; 1,194 of those are from a Malaysian domain.
- 12,655 of the 13,222 list 10 or fewer Malaysian places (weak filter on its own).
- 78% of all articles have a flood theme; the rest matched on heavy rain or monsoon only.
- Monthly Selangor/KL article counts: about 300-950; peaks Dec 2015 (1,413), Nov 2015 (954), Aug 2015 (912). Dec 2015 likely reflects national coverage of the Kelantan flood.
- Top Selangor/KL sources: `reports.pr-inside.com` (893), `thestar.com.my` (627), `orientaldaily.com.my` (452), `malaysiandigest.com` (307), `themalaymailonline.com` (249), `nst.com.my` (243), `thesundaily.my` (234), `forums.asiaone.com` (232).

## 6. Known limitations
- Selangor places coded `MY00` (e.g. Petaling, Morib) are not matched by the ADM1 filter.
- `date` is publish time, not event date; aftermath stories exist.
- Aggregators/forums (`reports.pr-inside.com`, `forums.asiaone.com`) repost wire stories and inflate counts; not yet excluded.
- `my_domain` uses a hand-maintained list plus the `.my` suffix, so some Malaysian outlets (e.g. `.com`/`.net` domains) may be missed.
- A few `V2Locations` entries have a country code that does not match their ADM1 (e.g. `CH` with Malaysian-looking values); not investigated.
- Output is candidate signal, not ground truth. No severity, depth or duration.

## 7. Daily series and spike detection
Code: [src/gdelt/daily.py](../src/gdelt/daily.py). Run: `python -m src.gdelt.daily data/interim/gdelt_gkg_2015_2016_articles.parquet` -> `data/interim/gdelt_gkg_2015_2016_daily.parquet` (680 days, 2015-02-21 to 2016-12-31).

- Day = Malaysia local date (`date` + 8h; GDELT is UTC). Still publish date, not event date.
- Tiers (all require a Selangor/KL place): `n_loose` (any theme in the export); `n_strict` (flood theme within 300 chars of a Selangor/KL place, excluding aggregators `reports.pr-inside.com`, `forums.asiaone.com`); `n_strict_my` (strict AND `my_domain`). Also `n_strict_domains`, `n_strict_selangor`, `n_strict_kl`.
- Spike rule: robust z-score against a centered 61-day rolling median/MAD (scale floored at 1), z >= 3.5 and count >= min_count.
- **First attempt on `n_strict` (43 spike days) was wrong.** Inspection showed false spikes: 2016-11-20 (175 articles) is spam site `newsviewsnreviews.com` with unrelated stories; 2015-08-05 is foreign Myanmar flood-aid coverage; 2016-07-19 is a global heat report. Lesson: the "Malaysia" plus "Kuala Lumpur" location signal is polluted by non-Malaysian stories.
- Current default: spikes on `n_strict_my`, min_count 4 -> **24 spike days**. Clusters: mid-Mar 2015, Sep 2015, 29 Dec 2015, Feb 2016, 12-17 May 2016 (peak 13 May; KL flash floods, verified from article URLs), 23-24 May 2016, Jun-Nov 2016.
- Caveats: spike days are unverified candidates. 2016-07-19 still passes (10 Malaysian-domain articles) and looks like the heat report, so it needs checking. Quiet Malaysian-domain days can hide real events because the `my_domain` list is incomplete. 18% of days have zero strict articles.

## 8. Candidate event clustering
Code: [src/gdelt/events.py](../src/gdelt/events.py). Run: `python -m src.gdelt.events data/interim/gdelt_gkg_2015_2016` -> `{stem}_events.parquet` and `.csv`.

- Spike days (section 7) at most 2 days apart merge into one event. Evidence is counted from strict, Malaysian-domain articles inside the event window.
- Columns: `event_id`, `start`, `end`, `n_spike_days`, `peak_day`, `peak_count`, `n_articles`, `n_domains`, `n_selangor`, `n_kl`, `top_places` (city-level and below, with counts), `lat`/`lon` (median of those places), `domains`, `sample_urls` (3 articles with fewest Malaysian places, for verification).
- Result: **13 candidate events** from the 24 spike days. Largest: event 6, 12-17 May 2016 (80 articles, 12 domains, KL flash floods). Others: 16-17 Mar 2015, 17 Sep 2015, 25-26 Sep 2015, 29 Dec 2015, 9-11 Feb 2016, 23-24 May 2016, 20 Jun 2016, 19 Jul 2016, 30 Aug 2016, 20-21 Sep 2016 (Kapar, Sabak Bernam, Kuala Selangor), 16-18 Oct 2016 (Selangor coast: Kapar, Port Klang), 14 Nov 2016.
- Caveats: "Kuala Lumpur" dominates `top_places` and is often just a city centroid or dateline, so district resolution for KL is poor. Event 9 (19 Jul 2016) is likely the non-flood heat report (Kampung Nelayan appears 9 times). All 13 are unverified candidates; dates are publish dates.

## 9. Verification of candidate events
Code: [src/gdelt/verify.py](../src/gdelt/verify.py) (fetches up to 6 Malaysian-domain sample articles per event, distinct domains, extracts title and flood sentences), [src/rainfall/openmeteo.py](../src/rainfall/openmeteo.py) (hourly precipitation, 5 grid points: KL, Shah Alam, Klang, Kuala Selangor, Sepang; 2015-02-01 to 2016-12-31, saved to `data/interim/rain_hourly_*.parquet`).
Verdicts (manual read of the fetched text): `annotations/event_verdicts_2015_2016.csv` (committed; hand-reviewed, includes second-pass ids 101+, event dates, districts and flood types).

| Verdict | Events |
|---|---|
| Confirmed | 6 (KL flash flood, 12 May 2016), 8 (KL, 19 Jun 2016), 10 (Klang Valley/Selayang, 30 Aug 2016), 11 (Kapar/Klang, 19-20 Sep 2016) |
| Probable, low confidence | 12 (Selangor coast high tide, Oct 2016), 13 (Klang/Sabak Bernam high-tide warning, 14 Nov 2016) |
| Uncertain / unverified | 4 (Klang, Dec 2015, date unclear), 5 (Feb 2016, no article fetchable) |
| Merge | 7 into 6 (aftermath) |
| Rejected | 1 (aftermath of East Coast floods), 2 and 3 (red-shirt rally, "flooded the streets"), 9 (Penang flood) |

Precision of the candidate list was therefore about 4-6 of 13. Most false positives were aftermath, figurative or non-Selangor/KL stories, so the theme/place filter alone is not enough and article-text review is needed.

Rainfall cross-check (max over the 5 points; percentile within all days 2015-02..2016-12; climatology daily p90/p95/p99 = 22.7/29.5/42.4 mm, hourly 6.9/8.4/12.3 mm):
- Only event 6 stands out clearly (daily 96th percentile, 32 mm).
- Confirmed events 8, 10 and 11 show ordinary ERA5 rainfall (51st, 85th, 47th percentile). Two causes: ERA5 at ~9 km smooths short convective downpours, which drive KL flash floods; and events 11-13 are tidal floods that depend on tides, not rainfall.
- Consequence: a rainfall-threshold label built from ERA5 alone would miss these events, which supports the two-stream label design. Rainfall is also a weak predictor for them, so tide data or higher-resolution rain (e.g. radar/gauges) may be needed for a useful model.

Fetch problems: many URLs returned 404 (old links), connection errors (thesundaily.my) or HTTP 530 (astroawani English site); event 5 had no readable article. Publication dates lag the flood by up to a day (e.g. FMT dated 19 Jun for a GDELT day of 20 Jun).

## 10. Recall work: second-pass candidates
Code: [src/gdelt/recall.py](../src/gdelt/recall.py). Run: `python -m src.gdelt.recall data/interim/gdelt_gkg_2015_2016 data/interim/rain_hourly_2015-02-01_2016-12-31.parquet` -> `{stem}_events2.parquet/.csv`; then `python -m src.gdelt.verify <stem> <out.json> events2`. Verdicts are in `annotations/event_verdicts_2015_2016.csv` (ids 101+).

Two extra streams, excluding days within 2 days of first-pass events:
- `relaxed_news`: robust z >= 2.5 and >= 3 strict Malaysian-domain articles (was z >= 3.5, >= 4).
- `rain_news`: ERA5 rain candidate day (daily max over 5 points >= 29.5 mm, or hourly >= 12.3 mm; climatology p95/p99) with >= 3 strict Malaysian-domain articles on day..day+1.
Result: 28 extra days -> 22 candidate events (ids 101-122).

Verification (same method as section 9): 4 confirmed, 1 probable, 3 uncertain, 14 rejected.

| Event | Date | Verdict | Evidence | Rain pct (daily/hourly) |
|---|---|---|---|---|
| 110 | 2015-11-02 | confirmed | NST: heavy continuous rain, floods in Klang Valley | 94/90 |
| 112 | 2015-11-16 | confirmed | Puncak Alam flash floods, Klang Valley chaos after downpour | 98/96 |
| 116 | 2016-06-04 | confirmed | Flash floods around Batu Muda/Sentul during hailstorm | 91/82 |
| 119 | 2016-07-22 | confirmed | NST: two-metre flood waters in parts of Klang Valley (date to confirm) | 97/88 |
| 120 | 2016-10-31 | probable | The Star: flash floods may occur in KL (warning) | 99/100 |
| 111, 113, 121 | | uncertain | Precautions/policy/relief-centre mentions, no confirmed event | |

Findings:
- Confirmed floods roughly double: 4 (first pass) -> 8, plus 1 probable. Every new confirmed event has a high rainfall percentile (91st-98th), unlike the earlier events that ERA5 missed, so the two streams are complementary.
- Second-pass precision is low (about 5 of 22). Typical false positives: East Coast flood aftermath, election politics, figurative "flooded" and policy stories. The news side is noisy whenever a story mentions floods and a Selangor/KL place.
- Rain-only candidates without news support are not labeled: the largest ERA5 rain days (22 Oct 2016, 82 mm; 7-8 May 2016, 76 and 50 mm) have essentially no Selangor/KL flood news, so they are either non-flood or outside the news filter.
- Still open: events 4, 5, 111, 113 (unresolved); event 119 date; tidal floods with no rainfall signal remain hard to find.

## 11. Label table
Code: [src/gdelt/labels.py](../src/gdelt/labels.py). Run: `python -m src.gdelt.labels data/interim/gdelt_gkg_2015_2016 annotations/event_verdicts_2015_2016.csv` -> `data/processed/flood_labels_2015_2016.csv` (not committed; regenerable).

- Source of truth for hand review: `annotations/event_verdicts_2015_2016.csv` (committed). `.gitignore` has a negation so this folder is tracked even though `*.csv` is ignored.
- Columns: `event_id`, `date` (event date; falls back to peak publish day if none), `district`, `lat`, `lon`, `flood_type` (flash / tidal / tidal_or_flash / unknown), `verdict`, `confidence`, `use` (True for confirmed/probable), `n_articles`, `n_domains`, `sources`, `rain_daily_pct`, `rain_hourly_pct`, `evidence`.
- Result: 15 rows, **11 usable** (8 confirmed + 3 probable; 4 uncertain kept with `use=False`). Rejected, merged (event 7 into 6) and unverified (event 5) events are dropped.
- Usable dates: 2015-11-02, 2015-11-16, 2016-05-12, 2016-06-04, 2016-06-19, 2016-07-22, 2016-08-30, 2016-09-19, 2016-10-16, 2016-10-31, 2016-11-14. Districts: KL (5), Klang Valley (3), Selayang, Kapar/Klang, Selangor coast, Klang/Sabak Bernam.
- Caveats: 11 events in 22 months is far below the true flood frequency; treat the table as a high-precision, low-recall seed, not a complete inventory. `lat`/`lon` are the median of place mentions (often the KL centroid 3.1667, 101.70) so they are approximate, not flood-site coordinates. Dates are journalist/publish based, accurate to about one day. Three flood types (flash, tidal, unknown) behave differently and may need separate models.
- Unusable as negatives: days absent from this table are not verified flood-free.

## 12. Next
Recall and negatives are the modeling risk: build a negative set (days with no news evidence and low rain) with clear caveats, run more BigQuery chunks (2017-2024) through the same pipeline once you approve, and automate the article-text check to reduce manual review.
