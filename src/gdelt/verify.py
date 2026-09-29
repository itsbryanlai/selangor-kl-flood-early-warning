"""Fetch sample article text for each candidate event and pull flood-related evidence.

    python -m src.gdelt.verify data/interim/gdelt_gkg_2015_2016 [out.json] [events|events2]

For each event: up to N_SAMPLE Malaysian-domain articles (distinct domains) from the event
window; fetch, extract text, keep the title and the first sentences mentioning flood terms.
Output is for manual/LLM review, not an automatic label.
"""
import json
import re
import sys

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from .daily import AGGREGATORS, STRICT_DIST

N_SAMPLE = 6
FLOOD_RE = re.compile(r"flash flood|flood|banjir|inundat|heavy rain|waterlogged", re.I)
HEADERS = {"User-Agent": "Mozilla/5.0 (research; flood-label-verification)"}


def pick_urls(articles: pd.DataFrame, start, end, n=N_SAMPLE) -> list[str]:
    a = articles.copy()
    a["day"] = (a["date"] + pd.Timedelta(hours=8)).dt.normalize()
    w = a[
        a.has_target & a.flood & (a.min_flood_loc_dist <= STRICT_DIST)
        & ~a.domain.isin(AGGREGATORS) & a.my_domain
        & (a.day >= pd.Timestamp(start)) & (a.day <= pd.Timestamp(end))
    ].sort_values(["n_my_places", "date"])
    return w.drop_duplicates("domain").url.head(n).tolist()


def fetch_text(url: str) -> dict:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=25, follow_redirects=True)
        if r.status_code != 200:
            return {"url": url, "error": f"HTTP {r.status_code}"}
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "nav", "footer", "header"]):
            t.decompose()
        title = soup.title.get_text(strip=True) if soup.title else ""
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        sents = [s for s in re.split(r"(?<=[.!?])\s+", text) if FLOOD_RE.search(s)]
        return {"url": url, "title": title, "flood_sentences": [s[:300] for s in sents[:4]]}
    except Exception as e:  # network/parse failures are expected for old news URLs
        return {"url": url, "error": type(e).__name__}


def main(stem: str, out: str = "verify_samples.json", kind: str = "events") -> None:
    events = pd.read_parquet(f"{stem}_{kind}.parquet")
    articles = pd.read_parquet(f"{stem}_articles.parquet")
    result = {}
    for e in events.itertuples():
        urls = pick_urls(articles, e.start, e.end)
        result[int(e.event_id)] = {
            "start": str(e.start), "end": str(e.end),
            "articles": [fetch_text(u) for u in urls],
        }
        ok = sum("error" not in a for a in result[int(e.event_id)]["articles"])
        print(f"event {e.event_id}: {ok}/{len(urls)} fetched")
    with open(out, "w") as f:
        json.dump(result, f, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
