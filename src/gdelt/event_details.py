"""Extract event date, hour and districts for verified flood events from their article text.

    python -m src.gdelt.event_details

For each confirmed/probable event: take cached articles (up to N_URLS, fetched via textcheck's cache),
find flood sentences (with one sentence of context), and extract
  date  - explicit "(Oct 15)"/"15 Oct", weekday names, or relative words (yesterday, last night, semalam)
          resolved against the article's publish date;
  hour  - explicit clock times ("6pm", "4.30am", "jam 4 pagi") and period words (morning, petang ...);
  place - gazetteer matches (src/gdelt/gazetteer.py) mapped to districts and approximate coordinates.
Writes data/interim/event_details_auto.csv for hand review; the reviewed result lives in
annotations/event_details.csv. Rule-based, English and Malay; articles that do not state a time or date
simply contribute nothing.
"""
import re
from collections import Counter
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .gazetteer import GENERIC, PLACES, find_places
from .textcheck import FLOOD, fetch_cached, url_date
from .verify import pick_urls

N_URLS = 15
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTHS.update({"mac": 3, "mei": 5, "ogos": 8, "okt": 10, "dis": 12})
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
            "isnin": 0, "selasa": 1, "rabu": 2, "khamis": 3, "jumaat": 4, "sabtu": 5, "ahad": 6}
MON = r"(jan|feb|mar|apr|may|mei|jun|jul|aug|ogos|sep|oct|okt|nov|dec|dis)[a-z]*"
RE_MD = re.compile(rf"\b{MON}\.?\s+(\d{{1,2}})\b", re.I)          # Oct 15
RE_DM = re.compile(rf"\b(\d{{1,2}})\s+{MON}\b", re.I)             # 15 Oct
RE_WD = re.compile(r"\b(mon|tues|wednes|thurs|fri|satur|sun)day\b|\b(isnin|selasa|rabu|khamis|jumaat|sabtu|ahad)\b", re.I)
RE_YDAY = re.compile(r"\b(yesterday|last night|semalam|kelmarin|malam tadi)\b", re.I)
RE_TODAY = re.compile(r"\b(today|this (morning|afternoon|evening)|tonight|hari ini|pagi tadi|petang tadi|awal pagi)\b", re.I)
RE_CLOCK = re.compile(r"\b(\d{1,2})(?:[.:](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])", re.I)
RE_MALAY_CLOCK = re.compile(r"\b(?:jam|pukul)\s+(\d{1,2})(?:[.:](\d{2}))?\s*(pagi|tengah hari|petang|malam)?", re.I)
PERIODS = {"early morning": 5, "dawn": 5, "dini hari": 3, "subuh": 6, "morning": 9, "pagi": 9, "noon": 12, "tengah hari": 13,
           "afternoon": 15, "petang": 17, "evening": 19, "night": 21, "malam": 21, "midnight": 0, "tengah malam": 0}
RE_PERIOD = re.compile(r"\b(early morning|dawn|dini hari|subuh|morning|pagi|noon|tengah hari|afternoon|petang|evening|night|malam|midnight|tengah malam)\b", re.I)


def _hour(h: int, mer: str) -> int:
    mer = mer.lower().replace(".", "")
    return (h % 12) + (12 if mer.startswith("p") else 0)


def resolve_date(ctx: str, pub: date):
    m = RE_MD.search(ctx) or RE_DM.search(ctx)
    if m:
        g = m.groups()
        mon, day = (g[0], g[1]) if RE_MD.search(ctx) else (g[1], g[0])
        mon_n = MONTHS.get(mon[:3].lower()) or MONTHS.get(mon.lower())
        if mon_n and 1 <= int(day) <= 31:
            try:
                d = date(pub.year, mon_n, int(day))
                if d > pub + timedelta(days=3):
                    d = date(pub.year - 1, mon_n, int(day))
                return d, "explicit"
            except ValueError:
                pass
    w = RE_WD.search(ctx)
    if w:
        key = (w.group(1) or w.group(2)).lower()
        wd = WEEKDAYS.get(key[:3]) if w.group(1) else WEEKDAYS.get(key)
        if wd is not None:
            d = pub - timedelta(days=(pub.weekday() - wd) % 7)
            return d, "weekday"
    if RE_YDAY.search(ctx):
        return pub - timedelta(days=1), "yesterday"
    if RE_TODAY.search(ctx):
        return pub, "today"
    return None, None


RE_REPORT = re.compile(r"(as of|as at|until|till|by|setakat|sehingga|hingga|updated?|published|posted)\s*[:\-]?\s*$", re.I)


def extract_times(ctx: str) -> list[tuple[float, str]]:
    """Clock times and period words. Times that follow "as of/setakat/until..." are report times, not flood times."""
    out = []
    for m in RE_CLOCK.finditer(ctx):
        if RE_REPORT.search(ctx[max(0, m.start() - 14): m.start()]):
            continue
        h = int(m.group(1))
        if 1 <= h <= 12:
            out.append((_hour(h, m.group(3)) + (int(m.group(2)) / 60 if m.group(2) else 0), "clock"))
    for m in RE_MALAY_CLOCK.finditer(ctx):
        if RE_REPORT.search(ctx[max(0, m.start() - 14): m.start()]):
            continue
        h, per = int(m.group(1)), (m.group(3) or "").lower()
        if per in ("petang", "malam", "tengah hari") and h < 12:
            h += 12 if not (per == "tengah hari" and h in (11, 12)) else 0
        if h <= 23:
            out.append((h + (int(m.group(2)) / 60 if m.group(2) else 0), "clock"))
    if not out:
        out += [(float(PERIODS[p.lower()]), "period") for p in RE_PERIOD.findall(ctx)[:2]]
    return out


def flood_contexts(text: str) -> list[str]:
    sents = re.split(r"(?<=[.!?])\s+|\n", text)
    return [" ".join(sents[max(0, i - 1): i + 2]) for i, s in enumerate(sents) if FLOOD.search(s)][:8]


def event_details(articles: pd.DataFrame, ev, urls: list[str]) -> dict:
    pub_local = articles.set_index("url").date.add(pd.Timedelta(hours=8)).dt.date
    dates, hours, places = Counter(), [], Counter()
    n_used, evidence = 0, []
    for u in urls:
        rec = fetch_cached(u)
        if "text" not in rec:
            continue
        pub = None
        for cand in (rec.get("meta_date"), url_date(u)):
            try:
                pub = date.fromisoformat(cand[:10]) if cand else None
            except ValueError:  # some sites use dd/mm/yyyy etc.
                pub = None
            if pub:
                break
        pub = pub or pub_local.get(u)
        if pub is None:
            continue
        ctxs = flood_contexts(rec["text"])
        if not ctxs:
            continue
        n_used += 1
        for c in ctxs:
            d, rule = resolve_date(c, pub)
            if (d is not None or extract_times(c)) and len(evidence) < 6:
                evidence.append(f"[{pub}|{u.split('/')[2]}] {c[:260]}")
            if d is not None:
                dates[(d, rule)] += {"explicit": 3, "weekday": 2, "yesterday": 1, "today": 1}[rule]
            hours += [(h, k) for h, k in extract_times(c)]
            for p in find_places(c):
                places[p] += 1
    best_date = None
    if dates:
        agg = Counter()
        for (d, _), w in dates.items():
            agg[d] += w
        best_date = agg.most_common(1)[0][0]
    clock = [h for h, k in hours if k == "clock"]
    period = [h for h, k in hours if k == "period"]
    spec = {p: c for p, c in places.items() if p not in GENERIC} or dict(places)
    top = Counter(spec).most_common(5)
    districts = Counter()
    for p, c in spec.items():
        districts[PLACES[p][0]] += c
    lat = np.average([PLACES[p][1] for p in spec], weights=list(spec.values())) if spec else np.nan
    lon = np.average([PLACES[p][2] for p in spec], weights=list(spec.values())) if spec else np.nan
    return {"n_articles_used": n_used, "date_auto": best_date, "date_votes": str(dict(Counter({str(d): w for (d, _), w in dates.items()}).most_common(3))),
            "hour_clock": round(float(np.median(clock)), 1) if clock else np.nan, "clock_mentions": len(clock),
            "hour_period": round(float(np.median(period)), 1) if period else np.nan,
            "districts": "; ".join(f"{d} ({c})" for d, c in districts.most_common(3)),
            "places": "; ".join(f"{p} ({c})" for p, c in top), "lat": round(lat, 3), "lon": round(lon, 3),
            "evidence": " ## ".join(evidence)}


JOBS = [("2015-16", "data/interim/gdelt_gkg_2015_2016", "annotations/event_verdicts_2015_2016.csv"),
        ("2024-26", "data/interim/gdelt_gkg_v1_2024_2026", "annotations/event_verdicts_2024_2026.csv")]


def main() -> None:
    rows = []
    for tag, stem, vpath in JOBS:
        articles = pd.read_parquet(f"{stem}_articles.parquet")
        ev = pd.concat([pd.read_parquet(f"{stem}_events.parquet"),
                        pd.read_parquet(f"{stem}_events2.parquet")], ignore_index=True).set_index("event_id")
        v = pd.read_csv(vpath)
        v = v[v.verdict.isin(["confirmed", "probable"]) & v.event_id.isin(ev.index)]
        for r in v.itertuples():
            e = ev.loc[r.event_id]
            urls = pick_urls(articles, e.start, e.end, n=N_URLS)
            d = event_details(articles, e, urls)
            rows.append({"period": tag, "event_id": r.event_id, "date_manual": r.event_date, "district_manual": r.district,
                         "flood_type": r.flood_type, "n_urls": len(urls), **d})
    out = pd.DataFrame(rows)
    out.to_csv("data/interim/event_details_auto.csv", index=False)
    pd.set_option("display.width", 300, "display.max_colwidth", 70)
    print(out[["period", "event_id", "date_manual", "date_auto", "hour_clock", "hour_period", "clock_mentions", "districts", "n_articles_used"]].to_string(index=False))


if __name__ == "__main__":
    main()
