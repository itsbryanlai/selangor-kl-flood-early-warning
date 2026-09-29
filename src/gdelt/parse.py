"""Parse GDELT GKG exports (DATE, url, V2Locations, V2Themes) into article-level features.

V2Locations entry: type#name#countrycode#ADM1code#ADM2code#lat#long#featureID#charOffset
V2Themes entry:    THEME,charOffset

ADM1 codes for Malaysia are FIPS-style: MY12 = Selangor, MY14 = Kuala Lumpur.
Known limitation: some Selangor places (e.g. Petaling, Morib) are coded MY00
("Malaysia (General)") and are not matched by the ADM1 filter.
"""
from __future__ import annotations

from urllib.parse import urlparse

import pandas as pd

TARGET_ADM1 = {"MY12": "Selangor", "MY14": "Kuala Lumpur"}
MY_DOMAINS = (
    "malaymail.com", "freemalaysiatoday.com", "bernama.com", "malaysiakini.com",
    "theedgemarkets.com", "astroawani.com", "themalaysianinsight.com",
    "thestar.com.my", "nst.com.my", "malaysia-today.net", "theborneopost.com",
)
LOC_COLUMNS = ["type", "name", "country", "adm1", "adm2", "lat", "lon", "feature_id", "offset"]


def parse_locations(s: str) -> list[dict]:
    out = []
    for entry in s.split(";"):
        p = entry.split("#")
        if len(p) != 9:
            continue
        try:
            lat, lon, off = float(p[5]), float(p[6]), int(p[8])
        except ValueError:
            continue
        out.append(dict(zip(LOC_COLUMNS, [p[0], p[1], p[2], p[3], p[4], lat, lon, p[7], off])))
    return out


def parse_themes(s: str) -> list[tuple[str, int]]:
    out = []
    for entry in s.split(";"):
        theme, _, off = entry.partition(",")
        if theme and off.isdigit():
            out.append((theme, int(off)))
    return out


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_my_domain(domain: str) -> bool:
    return domain.endswith(".my") or any(domain.endswith(d) for d in MY_DOMAINS)


def article_features(row) -> tuple[dict, list[dict]]:
    """Return (article feature dict, list of Selangor/KL location rows)."""
    locs = parse_locations(row.V2Locations)
    themes = parse_themes(row.V2Themes)
    names = {t for t, _ in themes}
    flood_offsets = [o for t, o in themes if "FLOOD" in t]
    dom = domain_of(row.url)

    target = [l for l in locs if l["adm1"] in TARGET_ADM1]
    my_names = {l["name"] for l in locs if l["country"] == "MY" and l["adm1"] != "MY"}
    all_names = {l["name"] for l in locs}
    min_dist = min(
        (abs(l["offset"] - o) for l in target for o in flood_offsets), default=None
    )
    art = {
        "date": row.DATE,
        "url": row.url,
        "domain": dom,
        "my_domain": is_my_domain(dom),
        "n_locations": len(all_names),
        "n_my_places": len(my_names),
        "has_selangor": any(l["adm1"] == "MY12" for l in target),
        "has_kl": any(l["adm1"] == "MY14" for l in target),
        "flood": bool(flood_offsets),
        "flash_flood": any("FLASH_FLOOD" in t for t in names),
        "heavy_rain": "NATURAL_DISASTER_HEAVY_RAIN" in names,
        "monsoon": "NATURAL_DISASTER_MONSOON" in names,
        "min_flood_loc_dist": min_dist,
    }
    art["has_target"] = art["has_selangor"] or art["has_kl"]
    tloc = [
        {"date": row.DATE, "url": row.url, "region": TARGET_ADM1[l["adm1"]], **l}
        for l in target
    ]
    return art, tloc


def build_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Dedupe URLs (keep earliest) and return (articles, target_locations)."""
    df = df.sort_values("DATE").drop_duplicates("url", keep="first")
    arts, locs = [], []
    for row in df.itertuples(index=False):
        a, l = article_features(row)
        arts.append(a)
        locs.extend(l)
    articles = pd.DataFrame(arts)
    articles["date"] = pd.to_datetime(articles["date"], format="%Y%m%d%H%M%S")
    locations = pd.DataFrame(locs)
    if not locations.empty:
        locations["date"] = pd.to_datetime(locations["date"], format="%Y%m%d%H%M%S")
    return articles, locations
