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

## 9. Next
Verify each candidate: fetch article text, confirm a flood occurred and extract the event date and location; cross-check Open-Meteo rainfall; assign confidence. Then output the label table `(date, district, lat, lon, confidence, n_articles, sources)`.
