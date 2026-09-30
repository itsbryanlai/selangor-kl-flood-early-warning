"""Automated article-text check for candidate flood events.

    python -m src.gdelt.textcheck data/interim/gdelt_gkg_2015_2016 annotations/event_verdicts_2015_2016.csv

For each candidate event (events + events2): fetch up to N_URLS Malaysian-domain articles
(cached in data/interim/article_cache/), score each article's text, and combine into an
event decision: accept / reject / review. Compares against hand verdicts if given.

Article score (best sentence): +1 non-figurative flood term, +1 Selangor/KL place in the same sentence, +1 event verb (hit, stranded, evacuated ...), -3 figurative use (rally, "flood of",
"flooding back" ...), -1 policy/preparedness wording, -1 hypothetical/warning wording, -2 other-year reference, -2 flood placed in another state. Pass if >= 3.
Rules were tuned on the same hand-labelled events they are compared against (about 40), so the
agreement figure is optimistic; re-check on new chunks.
"""
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from .verify import HEADERS, pick_urls

CACHE = Path("data/interim/article_cache_v2")
N_URLS = 10

FLOOD = re.compile(r"\b(flash[- ]?floods?|floods?|flooded|flooding|floodwaters?|banjir|inundat\w*|submerged|waterlogged)\b", re.I)
PLACE = re.compile(
    r"\b(selangor|kuala lumpur|klang|shah alam|petaling|subang|gombak|selayang|ampang|cheras|kajang|bangi|"
    r"sepang|puchong|rawang|batu caves|kapar|sabak bernam|sekinchan|kuala selangor|kuala langat|hulu langat|"
    r"hulu selangor|puncak alam|sentul|kepong|setapak|wangsa maju|damansara|bukit jalil|dbkl|putrajaya)\b|\bKL\b", re.I)
VERB = re.compile(
    r"\b(hit|struck|stranded|evacuat\w*|rescu\w*|swamped|engulf\w*|cut off|closed|traffic|damaged|affected|victims|"
    r"relief cent\w*|trapped|washed|overflow\w*|knee-deep|waist-deep|ankle-deep|metres?|feet|caused|downpour|heavy rain|"
    r"rain|jam|homes?|houses|villagers|residents|vehicles|cars|"
    r"mangsa|pps|pusat pemindahan|dilanda|terjejas|ditempatkan|kejadian|hujan lebat|limpahan|naik|dinaiki air|tenggelam)\b", re.I)
FIGURATIVE = re.compile(
    r"flooded the streets|rivers? of (yellow|red)|flooding back|came flooding|flood of|floodgates|"
    r"flooded (with|by) (calls|messages|requests|complaints|immigrants)|flooded (social media|the market)|"
    r"\b(rally|rallies|protest\w*|bersih|red[- ]shirts?|demonstrat\w*|by-?election|election)\b", re.I)
POLICY = re.compile(
    r"\b(mitigat\w*|allocat\w*|master plan|action plan|RCI|royal commission|budget|RM ?\d|sue|lawsuit|guidelines?|"
    r"preparedness|preparations?|standby|operations room|monitor\w*|identified|projects?|last year|previous|blueprint|proposal|study)\b", re.I)
OTHER = re.compile(
    r"\b(sarawak|sabah|johor|kelantan|terengganu|pahang|perak|kedah|perlis|penang|pulau pinang|melaka|malacca|"
    r"negeri sembilan|labuan|east coast|thailand|indonesia|myanmar|philippines)\b", re.I)
YEAR = re.compile(r"\b(19\d\d|20\d\d)\b")
TIME = re.compile(r"\b(yesterday|last night|this (morning|afternoon|evening)|on (mon|tues|wednes|thurs|fri|satur|sun)day|today)\b", re.I)
HYPO = re.compile(r"\b(may|might|could|will|expected to|prone|risk of|warn\w*|if)\b", re.I)


def fetch_cached(url: str) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if path.exists():
        return json.loads(path.read_text())
    rec = {"url": url}
    try:
        r = httpx.get(url, headers=HEADERS, timeout=25, follow_redirects=True)
        if r.status_code != 200:
            rec["error"] = f"HTTP {r.status_code}"
        else:
            soup = BeautifulSoup(r.text, "html.parser")
            meta = soup.find("meta", property="article:published_time")
            rec["meta_date"] = meta["content"][:10] if meta and meta.get("content") else ""
            for t in soup(["script", "style", "nav", "footer", "header", "aside"]):
                t.decompose()
            rec["title"] = soup.title.get_text(strip=True) if soup.title else ""
            paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
            body = "\n".join(p for p in paras if len(p) > 40) or soup.get_text(" ", strip=True)
            rec["text"] = re.sub(r"[ \t]+", " ", rec["title"] + "\n" + body)[:60000]
    except Exception as e:  # network/parse failures are expected for old URLs
        rec["error"] = type(e).__name__
    path.write_text(json.dumps(rec))
    return rec


DATELINE = re.compile(r"^\s*(?:[A-Za-z ]{0,60}\n)?\s*(KUALA LUMPUR|SHAH ALAM|PETALING JAYA|KLANG|SUBANG JAYA|SEPANG|PUTRAJAYA|KAJANG|GOMBAK)\b")


def place_regex(names) -> re.Pattern | None:
    """Regex for this article's own Selangor/KL place names (e.g. 'i-City', 'Kapar')."""
    toks = {n.split(",")[0].strip() for n in names or ()}
    toks = {t for t in toks if len(t) >= 4 and t.lower() not in ("malaysia", "federal territory of kuala lumpur")}
    return re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(toks)) + r")\b", re.I) if toks else None


def score_article(text: str, year: str = "", places=None) -> dict:
    sents = re.split(r"(?<=[.!?])\s+|\n", text)
    own = place_regex(places)
    here = bool(DATELINE.search(text[:400]))
    other_in_head = bool(OTHER.search(text[:300]))  # headline/first lines name another state
    best, best_s = -9, ""
    for i, s in enumerate(sents):
        if not FLOOD.search(s):
            continue
        s = re.sub(r"^[A-Z][A-Z .,'-]{3,30}:\s*", "", s)  # drop dateline ("KUALA LUMPUR:")
        weak = bool((own and own.search(s)) or (here and re.search(r"\bhere\b", s, re.I)))
        # GDELT sometimes geocodes other-state villages into Selangor/KL, so own/"here" matches
        # only count when the article head does not name another state
        has_place = bool(PLACE.search(s)) or (weak and not other_in_head)
        sc = 1 + (1 if has_place else 0) + (1 if VERB.search(s) or TIME.search(s) else 0)
        if not has_place and OTHER.search(s):
            sc -= 2  # flood is located in another state/country
        elif has_place and OTHER.search(s):
            sc -= 1  # mixed list of states
        if year and any(y != year for y in YEAR.findall(s)):
            sc -= 2  # refers to a different year (older flood, aftermath)
        sc -= 3 if FIGURATIVE.search(s) else 0
        sc -= 1 if POLICY.search(s) else 0
        sc -= 1 if HYPO.search(s) else 0
        if sc > best:
            best, best_s = sc, s
    return {"score": best, "passed": best >= 3, "sentence": best_s[:250]}


def url_date(url: str) -> str:
    m = re.search(r"/(20\d\d)/(\d\d)/(\d\d)/", url)
    return "-".join(m.groups()) if m else ""


def check_event(articles: pd.DataFrame, e, place_names: dict | None = None) -> dict:
    urls = pick_urls(articles, e.start, e.end, n=N_URLS)
    with ThreadPoolExecutor(8) as ex:
        recs = list(ex.map(fetch_cached, urls))
    ok = [r for r in recs if "text" in r]
    scored = [(r, score_article(r["text"], str(e.start)[:4], (place_names or {}).get(r["url"]))) for r in ok]
    passed = [(r, s) for r, s in scored if s["passed"]]
    dates = sorted(d for r, _ in passed if (d := r.get("meta_date") or url_date(r["url"])))
    n_pass, n_ok = len(passed), len(ok)
    if n_pass >= 2 or (n_pass == 1 and n_ok <= 3):
        decision = "accept"
    elif n_ok >= 2 and n_pass == 0:
        decision = "reject"
    else:
        decision = "review"
    return {
        "event_id": int(e.event_id), "n_urls": len(urls), "n_fetched": n_ok, "n_pass": n_pass,
        "decision": decision, "first_pass_date": dates[0] if dates else "",
        "best_sentence": max(scored, key=lambda x: x[1]["score"])[1]["sentence"] if scored else "",
    }


def main(stem: str, verdict_path: str | None = None) -> None:
    articles = pd.read_parquet(f"{stem}_articles.parquet")
    parts = [pd.read_parquet(f"{stem}_events.parquet")]
    if Path(f"{stem}_events2.parquet").exists():  # second-pass events exist only for the 2015-2016 chunk
        parts.append(pd.read_parquet(f"{stem}_events2.parquet"))
    events = pd.concat(parts, ignore_index=True)
    loc_path = Path(f"{stem}_target_locations.parquet")
    place_names = pd.read_parquet(loc_path).groupby("url").name.agg(list).to_dict() if loc_path.exists() else {}
    res = pd.DataFrame([check_event(articles, e, place_names) for e in events.itertuples()])
    out = Path(f"data/interim/textcheck_{Path(stem).name.replace('gdelt_gkg_', '')}.csv")
    res.to_csv(out, index=False)
    print(res.decision.value_counts().to_dict(), "->", out)
    if verdict_path:
        v = pd.read_csv(verdict_path)[["event_id", "verdict", "event_date"]]
        m = res.merge(v, on="event_id")
        m["truth"] = m.verdict.map(
            lambda x: "flood" if x in ("confirmed", "probable") else ("no" if x in ("reject", "merge into event 6") else "unsure")
        )
        print(pd.crosstab(m.truth, m.decision))
        print(m[(m.truth == "flood") & (m.decision != "accept") | (m.truth == "no") & (m.decision == "accept")]
              [["event_id", "verdict", "n_fetched", "n_pass", "decision", "best_sentence"]].to_string())


if __name__ == "__main__":
    main(*sys.argv[1:3])
