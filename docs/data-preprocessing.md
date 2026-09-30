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

## 12. Automated article-text check
Code: [src/gdelt/textcheck.py](../src/gdelt/textcheck.py). Run: `python -m src.gdelt.textcheck data/interim/gdelt_gkg_2015_2016 annotations/event_verdicts_2015_2016.csv` -> `data/interim/textcheck_2015_2016.csv`. Fetched pages are cached in `data/interim/article_cache_v2/` (paragraph text only; whole-page text let sidebar junk swamp the article).

- Per event: up to 10 Malaysian-domain articles (distinct domains); each article is scored on its best flood sentence: +1 non-figurative flood term, +1 Selangor/KL place in the same sentence (dateline stripped), +1 event verb or time word (hit, stranded, evacuated, yesterday...), -3 figurative (rally, "flood of", "flooding back"), -1 policy/preparedness wording, -1 hypothetical/warning wording, -2 other-year reference, -2 flood placed in another state, -1 mixed list of states. Pass if score >= 3.
- Event decision: accept if >= 2 passing articles (or 1 with <= 3 fetched); reject if >= 2 fetched and none pass; otherwise review.
- Agreement with hand verdicts (35 events; rules were tuned on these, so it is optimistic):

| Hand verdict | accept | review | reject |
|---|---|---|---|
| Confirmed/probable (11) | 8 | 0 | 3 |
| Rejected (19) | 1 | 11 | 7 |
| Uncertain/unverified/merged (5) | 2 | 0 | 3 |

- All 8 confirmed events are accepted; the 3 rejected true-labelled events are the low-confidence probables (tidal or warning stories: 12, 13, 120), where the articles report policy or a warning, not a flood. The single "accepted" rejected event is event 7 (aftermath of the real event 6). No hand-rejected event is accepted otherwise; 11 of 19 fall in "review" and would still need a human.
- Publish date of passing articles matches my event dates within one day for 7 of 8 confirmed events (11: 09-20 vs 09-19; 116: 06-03 vs 06-04).
- Limits: only about 40% of URLs fetch (404s, connection errors, HTTP 530); events with no readable article stay in review. Tidal or warning-style events are rejected by design, so accept/reject is a floor, not a full labeler. Re-validate on each new chunk before trusting it.

## 13. Negative set and daily labels
Code: [src/gdelt/negatives.py](../src/gdelt/negatives.py). Run: `python -m src.gdelt.negatives data/interim/gdelt_gkg_2015_2016 data/interim/rain_hourly_2015-02-01_2016-12-31.parquet annotations/event_verdicts_2015_2016.csv` -> `data/processed/daily_labels_2015_2016.csv` (671 days, 2015-03-01 to 2016-12-30).

| label_type | days | y | Rule |
|---|---|---|---|
| flood | 11 | 1 | Event date of a confirmed/probable event |
| easy_negative | 98 | 0 | ERA5 daily and hourly rain below p75, prior 3 days below p75, <= 1 strict Malaysian-domain article on day..day+1, not within 3 days of a non-rejected candidate |
| moderate_rain_negative | 39 | 0 | Same news/proximity rule but rain between p75 and heavy (rain-matched to floods) |
| hard_news_negative | 11 | 0 | Days of flood-news spikes whose sampled articles were read and rejected (rally, aftermath, Penang) |
| ambiguous_heavy_rain | 56 | empty | Rain >= p90 daily or p95 hourly and no confirmed flood: unknown, not negative |
| near_event / uncertain_event | 112 / 5 | empty | Within 3 days of a non-rejected candidate, or an uncertain event |
| unlabeled | 339 | empty | Everything else |

Totals: 11 positives vs 148 negatives.

**Caveats (read before modeling):**
- A negative means "no news evidence of a flood and low-to-moderate rain", not "no flood". GDELT and this pipeline miss small, local and tidal floods, so some negatives are false negatives, and they are most likely exactly on the events that matter.
- Negatives are skewed away from the monsoon: the Oct-Dec 2015 quarter has only 3 negatives (news and rain are busy everywhere), while 2015 Q1-Q3 and 2016 Q1 have none of the positives. A model will find "season" and "rain intensity" too easy. Evaluate stratified by season and rain level; use moderate/hard negatives for headline metrics, not easy ones.
- Flood days have median rain 17 mm (p75-p90) versus 3 mm for easy negatives. Several floods occurred with almost no ERA5 rain (2016-06-04: 2 mm, 2016-06-19: 5 mm, 2016-09-19: 3 mm) and would be missed by any rain-only baseline.
- 11 positives is too few for a model or even stable metrics; treat this chunk as a pipeline test, and expect the 2017-2024 chunks to be needed.
- The 4 extra thresholds (p75, p90/p95, 3-day buffer, news <= 1) were set by judgment, not tuned; sensitivity has not been checked.

## 14. Chunk 2: 2024-01-01 to 2026-09-30 (V1 columns)
Raw: `data/raw/gdelt_gkg_v1_2024_2026.csv` (13.6 MB, 8,453 rows, columns `GKGRECORDID, DATE, SourceCommonName, DocumentIdentifier, Themes, Locations`; query and cost in [bigquery-query-optimization.md](bigquery-query-optimization.md)). All 8,453 URLs are unique; rows per year 3,331 / 3,465 / 1,657; top sources thestar.com.my (1,403), orientaldaily.com.my (962), chinapress.com.my (470), thesun.my (311), enanyang.my (215), kwongwah.com.my (202). About 22% are Chinese-language outlets that the English text check cannot read.

Pipeline (same tables and code paths as chunk 1):
1. `python -m src.gdelt.parse_v1 data/raw/gdelt_gkg_v1_2024_2026.csv` ([parse_v1.py](../src/gdelt/parse_v1.py)): V1 Locations have 7 fields (`type#name#cc#ADM1#lat#lon#featureID`), V1 Themes have no offsets, so `min_flood_loc_dist` is NaN. Adds `torrential_rain` and `source`. Result: 8,453 articles, 4,353 Malaysian domains, 9,457 Selangor/KL location rows.
2. `python -m src.gdelt.daily data/interim/gdelt_gkg_v1_2024_2026_articles.parquet`: `near_flood()` in [daily.py](../src/gdelt/daily.py) treats a missing distance as "no proximity check", so the strict tier is now flood theme + Selangor/KL + non-aggregator. Median strict Malaysian-domain articles per day is 3 (was 1 in chunk 1), i.e. a noisier baseline. 38 spike days.
3. `python -m src.gdelt.events data/interim/gdelt_gkg_v1_2024_2026`: 21 candidate events.
4. `python -m src.gdelt.textcheck data/interim/gdelt_gkg_v1_2024_2026`: 5 accept, 3 review, 13 reject.

Text-check changes made on this chunk (chunk-1 validation unchanged afterwards: 8/8 confirmed accepted, no new false accepts):
- Malay event words (mangsa, PPS, dilanda, terjejas, kejadian, hujan lebat...).
- Each article's own parsed Selangor/KL place names count as places (catches e.g. i-City), and "here" counts when the article has a Selangor/KL dateline.
- Those weak place matches are ignored when the headline or first lines name another state, because GDELT sometimes geocodes other-state villages into KL (Penang's "Kampung Nelayan" was tagged KL; this caused a false accept before the guard).

Automatic decisions (not hand-verified):
| Decision | Events (window) |
|---|---|
| Accept | 6 (2024-08-23/24, flash floods at the KL World Trade Centre car park), 8 (2024-10-15 to 18, KL flash floods then Selangor), 12 (2025-04-11/12, Klang/Kapar), 18 (2025-11-23 to 12-01, floods in seven states incl. Selangor), 20 (2026-07-18, Klang Valley) |
| Review | 9 (2024-11-29 to 12-03, mostly East Coast/Hat Yai coverage), 13 (2025-04-23, Selangor flash floods, looks real), 19 (2026-05-06, PJ/KL flash floods, looks real) |
| Reject | 1, 2, 3, 4, 5, 7, 10, 11, 14, 15, 16, 17, 21 |
Known false reject: event 3 (2024-04-18, Malay article on floods in Selangor, Negeri Sembilan and Melaka) fails because the "mixed list of states" penalty cancels the place match; treat rejected events with large article counts or Malay text as candidates for manual look. Events 1, 2, 4, 5, 10, 11 were rejected because the only flood sentence found was a recurring The Star sidebar item ("Flash floods hit i-City"), i.e. the article body had no flood sentence.

## 15. Second pass, hand review and labels for 2024-2026
- Rainfall: `python -m src.rainfall.openmeteo 2024-01-01 2026-09-30` (ERA5, 120,480 rows) and `python -m src.rainfall.previous_runs 2024-01-01 2026-09-30` (forecasts issued 1/2 days before, from 2024-01-19).
- `python -m src.gdelt.recall <stem> <rain.parquet>`: 161 extra days -> 75 second-pass candidates (streams: relaxed news, rain + news). Text check on all 96 events: 12 accept, 12 review, 72 reject.
- Hand review of every accepted/reviewed event (annotations/event_verdicts_2024_2026.csv): 13 confirmed, 1 probable (2025-11-24, 7-state floods, Selangor unconfirmed), 1 uncertain, 6 rejected, 4 unverified, 71 `reject_auto` (text-check reject, not hand-read; never used as verified negatives). Overrides of the automatic decision: events 116 and 108 (policy stories, false accepts) and 147 (recap of an earlier flood) rejected; events 3, 9, 159, 165 promoted to confirmed from evidence.
- `python -m src.gdelt.labels` -> 14 usable flood days (2024-04-17, 08-23, 10-04, 10-15, 11-14, 11-29; 2025-04-11, 04-23, 11-24, 12-04; 2026-02-16, 05-06, 06-25, 07-18).
- `python -m src.gdelt.negatives <stem> <rain> <verdicts> 4` -> daily labels; `news_max=4` (35th percentile of 2-day strict Malaysian-domain articles; the V1 chunk has no proximity filter so its baseline is 3x noisier). Now takes date ranges from the data and writes `daily_labels_<tag>.csv` per chunk; `reject_auto` verdicts do not create hard negatives.
- Caveat: about half of the labels came from the rain + news stream, so positives skew toward heavy-rain floods.

## 16. Next
Hand-review the review and accept events above and add them to `annotations/` (only after reading); resolve event 3. Then rebuild the label table and daily labels over both chunks (2015-2016 and 2024-2026) and download Open-Meteo for 2024-2026. Remaining BigQuery chunks (2017-2023, about 761 GB) are on hold until the user approves; the 2017-2023 gap matters for training data continuity.
