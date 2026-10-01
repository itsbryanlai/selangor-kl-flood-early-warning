# Hour and district labels

Goal: replace day-level, publish-date flood labels with event date, onset hour and district, so rain can be matched in time and space. Code: [gazetteer.py](../src/gdelt/gazetteer.py), [event_details.py](../src/gdelt/event_details.py), [label_precision.py](../src/modeling/label_precision.py). Reviewed result: [annotations/event_details.csv](../annotations/event_details.csv) (committed).

**Short answer:** all 25 usable events now have a hand-checked date, district and coordinates, and 13 have an onset hour (7 from explicit clock times, 6 from words like "evening"). Fixing dates helped the models a little. But with ERA5 rain, precise place and hour add only a small, statistically unclear gain, because ERA5's local cell does not capture short local downpours.

## 1. Method
1. **Gazetteer** ([gazetteer.py](../src/gdelt/gazetteer.py)): about 130 Selangor/KL place names (neighbourhoods, roads, towns) mapped by hand to a district (9 Selangor districts, Kuala Lumpur, Putrajaya) with approximate coordinates (1 to 3 km). Longest match wins; generic names ("Klang Valley", "Selangor") are dropped when a specific place is present.
2. **Extraction** ([event_details.py](../src/gdelt/event_details.py)): for each verified event, up to 15 cached articles; flood sentences with one sentence of context; then
   - date: explicit ("(Oct 15)", "15 Oct"), weekday names, or relative words (yesterday, last night, semalam) resolved against the article's publish date;
   - hour: explicit clock times ("6pm", "4.35pm", "jam 4 pagi"), skipping report times ("as of", "setakat", "until"), else period words (morning, petang, evening);
   - places and districts from the gazetteer.
   English and Malay.
3. **Manual review** of every event's matched sentences, since the rules are noisy. The reviewed result (date, basis, onset hour, districts, places, coordinates, note) is [annotations/event_details.csv](../annotations/event_details.csv). Some events have only thin text (marked WEAK in the notes).

## 2. How good was the automatic extraction?
Against my hand-reviewed dates (19 events where the rules produced a date): 11 exact, 6 within one day, 2 wrong (one year-parsing slip, one picking up a Sumatra flood story). The rules reproduced the hours I read by hand for the events with explicit times (10:00, 04:00, 06:00, 15:30, 16:35, 20:30, 18:00, 19:00). Common failure modes: report times mistaken for flood times ("as of 6am"), articles about floods elsewhere (Thailand, Sumatra), and the sampled articles not including the best report (event 159). Hence the manual review.

Correcting my earlier publish-date-based dates mattered: 3 of 25 were a day off (the FMT report for 2016-06-03 had been dated 06-04; DBKL's "this afternoon" statement was 2024-11-15, not 11-14; the Bukit Changgang embankment burst was "yesterday" in a 25 June article, so 2026-06-24). Rebuilding the labels and re-running the 2024-26 evaluation moved the same-day ERA5 score from ROC-AUC 0.863 to 0.906 (PR-AUC 0.296 to 0.308) and the sparse 3-feature model from 0.794 to 0.828 (PR-AUC 0.216 to 0.221), with its false-alarm ratio falling from 0.92 to 0.75 (2 hits, 6 false alarms against 24 before). Small samples, but the direction supports the claim that date errors limit performance.

## 3. Reviewed event table
| Event date | Onset hour (local) | Districts | Places used | Hour basis |
|---|---|---|---|---|
| 2015-11-02 | - | Kuala Lumpur | kuala lumpur | - |
| 2015-11-16 | 17:00 | Kuala Selangor; Petaling | puncak alam; petaling jaya | period (evening gridlock; Star 8:54pm) |
| 2016-05-12 | 19:00 | Kuala Lumpur | jalan duta; jalan semantan; bangsar; pudu | period (evening) |
| 2016-06-03 | 19:00 | Kuala Lumpur | batu muda; sentul; pudu | clock (7pm) |
| 2016-06-19 | 18:00 | Kuala Lumpur | jalan raja chulan; jalan duta | clock (about 6pm) |
| 2016-07-22 | - | Kuala Lumpur | kuala lumpur | - |
| 2016-08-30 | 07:30 | Gombak | taman selayang | period (morning rush hour) |
| 2016-09-19 | - | Klang | kapar | - |
| 2016-10-16 | - | Sabak Bernam | sekinchan | - |
| 2016-10-31 | - | Kuala Lumpur | kuala lumpur | - |
| 2016-11-14 | - | Klang; Sabak Bernam | klang; sabak bernam | - |
| 2024-04-17 | - | Klang; Kuala Selangor | klang; kuala selangor | - |
| 2024-08-23 | - | Sepang | dengkil | - |
| 2024-10-04 | 22:00 | Gombak; Kuala Selangor; Petaling | shah alam; gombak; kuala selangor | period (sejak malam tadi) |
| 2024-10-15 | 10:00 | Kuala Lumpur | kuala lumpur | clock (morning downpour, Dewan Rakyat adjourned) |
| 2024-11-15 | 15:00 | Kuala Lumpur | pudu; kuala lumpur | period (afternoon) |
| 2024-11-29 | - | Klang | meru | - |
| 2025-04-11 | 04:00 | Klang | meru; taman sri jaya | period (awal pagi; rain since night) |
| 2025-04-23 | 06:00 | Petaling | sungai buloh; shah alam | clock (early morning; 6.5 median) |
| 2025-11-24 | - | Sepang | sepang | - |
| 2025-12-04 | - | Gombak; Hulu Langat; Kuala Lumpur; Petaling | kuala lumpur; petaling jaya; gombak; kajang | - |
| 2026-02-16 | 20:30 | Petaling | subang | clock (about 8.30pm) |
| 2026-05-06 | 15:30 | Petaling | petaling jaya | clock (3.30pm) |
| 2026-06-24 | - | Kuala Langat | bukit changgang | - |
| 2026-07-18 | 16:36 | Petaling | petaling jaya | clock (4.35pm distress call) |

## 4. Does precise place and hour help the rain signal?
Test ([label_precision.py](../src/modeling/label_precision.py)): for each event, pull ERA5 hourly rain at the event's coordinates (Open-Meteo) and compare how high the event ranks among about 60 to 80 nearby non-flood days (same place, +/-45 days, not within 3 days of any flood). Score = percentile rank (0.5 chance, 1.0 top):

| Statistic | All 25 events | News-only events (15, not selected on rain) | Rain+news events (10, selected on regional rain) |
|---|---|---|---|
| A: regional daily total (max of 5 points) | 0.87 | 0.82 | 0.95 |
| F: regional peak 3-hour | 0.84 | 0.78 | 0.93 |
| B: local daily total at the event location | 0.80 | 0.75 | 0.87 |
| C: local peak 3-hour at the location | 0.76 | 0.70 | 0.85 |

For the 13 events with an onset hour (8 news-only): local peak 3-hour in the day (C) 0.78 (0.72 news-only), local peak 3-hour in the onset window +/-3 h (D) 0.84 (0.78 news-only); regional peak 3-hour in the onset window (E) 0.85 (0.80 news-only). 95% confidence intervals are wide (about +/-0.1 for n=13 to 25).

Reading:
1. **Hour matching helps a little:** restricting the local peak to the onset window raises the rank from 0.72 to 0.78 (news-only events with an hour), but the intervals overlap.
2. **Local ERA5 is not better than regional ERA5.** The regional maximum over five grid points (A: 0.82) ranks floods higher than the rain at the flood's own coordinates (B: 0.75, C: 0.70). ERA5's cell at the event location misses short local downpours (for example 2016-06-19, local peak 3-hour of 1.9 mm for a flash flood reported at 6 pm), while the regional maximum acts as an indicator of convective activity anywhere in the valley.
3. **A is inflated for the rain+news events**, because those candidates were selected using the regional daily total. Use the news-only column for an unbiased comparison.
4. So precise labels are necessary but not sufficient: the next step up needs rain measured at the right place (dense gauges or radar), not another label refinement.

## 5. Limits
- 25 events, 13 with an hour; all uncertainty statements are rough.
- Gazetteer coordinates are approximate and mostly neighbourhood-level; "district" is the district of the main named places, and several events span multiple districts (listed).
- Onset hours are mostly derived from "about 6pm" style statements about when rain or reports began, not when water first rose; hour precision is roughly +/- 1 to 2 hours; period-based hours (evening = 19:00, morning rush hour = 07:30) are coarser.
- Events 11, 12, 13 (tidal), 9, 18 and 120 rest on thin evidence and are marked WEAK or low-confidence in the notes.
- The unbiased sample is small, and the event set was found through news coverage, which favours Klang Valley urban flash floods.

## 6. Reproduce
```
python -m src.gdelt.event_details               # automatic extraction -> data/interim/event_details_auto.csv (review by hand)
python -m src.gdelt.negatives / labels ...      # rebuild labels after any date change (see methodology.md)
python -m src.modeling.label_precision          # local-rain rank test -> data/processed/label_precision.csv
```

## 7. Update with 2021-2023 added (40 events)
- 15 more events were hand-reviewed and added to annotations/event_details.csv (two probable). 22 of the 40 events now have an onset hour (12 from explicit clock times).
- **Automatic extraction (34 events with an automatic date):** 22 exact, 32 within one day, 2 wrong. In 2021-23 all 15 were within a day (9 exact).
- **Local-rain test with 40 events (21 news-only):** news-only mean percentile rank among nearby non-flood days: regional daily total 0.82, local daily total 0.79, local peak 3-hour 0.73, local peak 3-hour in the onset window 0.80 (11 events with an hour; 0.74 for the whole-day peak on the same events), regional peak 3-hour in the onset window 0.83. Rain+news events: regional 0.87, local daily 0.81. Intervals are about +/-0.1.
- Conclusion unchanged: hour matching adds about +0.06 to the local peak, the local ERA5 cell is now close to but not better than the regional maximum, and precise labels cannot replace better rain data.
