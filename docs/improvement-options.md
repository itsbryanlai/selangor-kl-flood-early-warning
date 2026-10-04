# Options to improve the model with the data we already have

Code: [improve.py](../src/modeling/improve.py) (`python -m src.modeling.improve`). Outputs: `data/processed/improve_blockedcv_*.csv` (not committed).

**Short answer:** the cheap options are exhausted. A fit-free combination of three indicators is the best simple rule, and re-framing the result as "share of floods caught within a fixed alert budget" gives the most honest operational summary, but nothing tested here lifts skill materially. The remaining levers need new data (more years, a dense rain-gauge network, prospective river levels) or a different label source.

## 1. What was tested
All tests use the 39 flood days with water-vapour data (2,141 labelled days, three periods) and **blocked cross-validation** (leave-one-quarter-out with a 7-day purge on each side), so all 39 floods are test floods and every model is scored on the same days. This is not forward-chaining (later periods help predict earlier ones), so it checks stability rather than forecast skill; the expanding-window results elsewhere remain the strict test. "Capture@k%" = share of floods that fall in the k% highest-scored days (random would be k%).

| Model | PR-AUC (95% CI) | ROC-AUC | Capture @5% | @10% | @20% |
|---|---|---|---|---|---|
| Month of year only | 0.024 (0.014-0.042) | 0.54 | 5% | 5% | 36% |
| Baseline: yesterday's rain, 7-day rain, season (logistic) | 0.068 (0.031-0.159) | 0.70 | 21% | 44% | 51% |
| Baseline + water vapour (TCWV level and anomaly) | 0.103 (0.041-0.201) | 0.77 | 15% | 41% | 54% |
| Baseline + news precursors | 0.058 (0.028-0.140) | 0.69 | 21% | 41% | 51% |
| Baseline + water vapour + news precursors | 0.077 (0.036-0.175) | 0.77 | 15% | 41% | 54% |
| TCWV at 00:00 alone (rank) | 0.075 (0.039-0.152) | 0.79 | 21% | 33% | 56% |
| Yesterday's rain alone (rank) | 0.070 (0.026-0.142) | 0.73 | 18% | 31% | 44% |
| **Composite: average rank of TCWV, yesterday's rain, 850 hPa humidity (no fitting)** | **0.090 (0.048-0.182)** | **0.80** | **28%** | **46%** | **56%** |
Base rate 1.8%.

1. **News precursors do not help.** GDELT stories about heavy rain or monsoon (without a flood theme) and total coverage published before 00:00 on D, normalised by a 60-day mean, rank flood days at 0.56 (95% CI 0.49-0.64) and lower PR-AUC when added. Warnings reach the news too diffusely at this resolution.
2. **A 2-day alert window** (positive if a flood occurs on D or D+1, to absorb the +/-1-day label uncertainty) doubles the positives and raises absolute PR-AUC (baseline 0.101, + water vapour 0.139, composite 0.115) without changing the ranking of the models or the capture rates, so label-date noise is not hiding a better model.
3. **A fit-free composite is as good as the fitted models** (PR-AUC 0.090 vs 0.103; ROC 0.80 vs 0.77), catches the most floods at small budgets (28% of floods within the 5% most-scored days, 46% within 10%, 56% within 20%: 5.6, 4.6 and 2.8 times random), and has no parameters to over-fit with 39 floods. It is the best simple rule found.
4. **Forecast rain plus water vapour (2024-26, 8 test floods):** ROC-AUC 0.83 vs 0.79 for forecast rain alone, PR-AUC 0.19 vs 0.18 (forecast rain alone 0.29); no reliable gain, the sample is too small.
5. **A graded target (flood-news volume, 2,579 days)** is only weakly related to the predictors (Spearman within period-months: 7-day rain 0.15, TCWV 0.12, TCWV anomaly 0.09, yesterday's rain 0.08), so it gives no route to a much better model.

## 2. Audit: can more flood labels be recovered from the existing text?
159 events are unverified or auto-rejected (65 with 10 or more articles, 21 first-pass). I read the best sentence of the 28 highest-volume ones: none is a clear new flood. They are policy and parliament statements, aftermath of earlier floods, floods in other states or Nepal, election remarks, and a recurring sidebar headline ("Flash floods hit i-City") that is not article text. At best three are plausible (a Nov 2024 flood mention involving Kuang, a Feb 2025 Kuala Lumpur spike, Dec 2025 relief centres). Re-triaging would probably add fewer than 5 floods for hours of reading. The labeling method is limited by what GDELT flags, not by the text check being too strict.

## 3. Remaining options, ranked by expected value
| Option | Needs | Expected effect |
|---|---|---|
| Alert-budget framing for the current best rule (composite): "flag the top 10% of nights, catch about 46% of floods" | nothing | Honest operational summary; no skill gain |
| More labeled years (2017-2020, 507 GB; retry after the quota frees up, about Oct 28) | BigQuery quota | Out-of-sample test of the water-vapour result (ERA5 covers those years) and about 10 more floods |
| Dense rain-gauge or radar rain (DID InfoBanjir, MET Malaysia) at the flood location | formal data request; or start a live InfoBanjir scraper now to build a history | The most likely real improvement; two gauges and 9 km ERA5 cannot resolve local downpours |
| Prospective river levels (live InfoBanjir scraper, not started) | a host running continuously | Needs 12+ months before it is usable |
| A tidal rule as an OR condition (predicted high water at or above 6.1 m) | nothing | Catches the 3 labeled tidal floods at about 11 alert days a year; tiny change overall |
| Re-label more floods from Bernama/Bomba/DBKL statements instead of GDELT only | scraping and manual review | Recall gain, large effort |
| District-level modeling | district-level negatives (not available) | Blocked: only flood days have districts |
| Nonlinear models (boosting) | nothing | Unlikely with 39 positives |

## 4. Where this leaves the model
The best lead-hours-to-a-day predictors are column moisture (TCWV, 850 hPa humidity) and yesterday's rain. Together as an unfitted rank average they give ROC-AUC about 0.80 and catch roughly half of the floods in the top 10 to 20% of days, but about 90% of alerts would be false (FAR 0.92 in the fitted models). Reaching a usable early-warning level needs better rain observations and more labeled floods, not more modeling of the current data.

## 5. The alert-budget framing explained, with a past-only check
**Idea.** Each night at 00:00 the rule gives every upcoming day a score (the average rank of water vapour at midnight, yesterday's rain and 850 hPa humidity). Instead of choosing a probability threshold, choose an **alert budget**: "we can act on about 10% of nights." The rule flags the 10% highest-scored nights and we measure how many labelled floods land inside those nights. This separates two questions that a single threshold metric (CSI, false-alarm ratio) mixes up: how well the score ranks nights, and how many alerts an operator can afford. The budget would be set from the cost of a false alarm against the cost of a missed flood.

**Blocked-CV result (39 floods, 2,141 labelled days):** top 5% of nights catch 28% of floods, top 10% catch 46%, top 20% catch 56% (random: 5%, 10%, 20%). This ranked each night within its whole period, including later nights.

**Past-only version (what a live system could do):** rank each night only against earlier nights of the same period (at least 90 days of history), alert when the score reaches the trailing 90th percentile. Result over 1,601 labelled days (about 4.4 years; the first 90 days of each period have no history, so 6 floods drop out): **14 of 33 floods caught (42%)** with alerts on 8.7% of days (random would catch 9%). Of the alert days, 10.1% were flood days (base rate 2.1%), so **90% of alerts were quiet nights**. Per year this is about 32 alert nights, 3.2 floods caught, 29 false-alarm nights and 4.3 floods missed. By period: 2015-16 caught 5 of 11 (12% of days alerted), 2021-23 caught 5 of 14 (9%), 2024-26 caught 4 of 8 (5%).

**Fixed single-indicator rule:** TCWV at 00:00 of at least 59 kg/m2 (the top fifth of nights) alerts on 19% of days, catches 21 of 39 floods (54%), and 5.1% of its alert days are floods.

**What this does not show.** It is not a probability forecast and says nothing about which district; "caught" means the flood day falls on an alert night issued at 00:00 (most labelled onsets are 15:00 to 19:00, so about 15 to 19 hours of lead, but 4 of 22 timed events began before 08:00); the floods are those visible in GDELT news, so the real catch rate for all floods is unknown; 33 to 39 floods give wide uncertainty; alert nights probably cluster in wet spells (not measured); and the rule has not been tested prospectively.
