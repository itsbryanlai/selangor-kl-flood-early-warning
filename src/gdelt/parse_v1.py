"""Parse the trimmed V1 GKG export (GKGRECORDID, DATE, SourceCommonName, DocumentIdentifier, Themes, Locations).

    python -m src.gdelt.parse_v1 data/raw/gdelt_gkg_v1_2024_2026.csv

V1 Locations entry: type#name#countrycode#ADM1code#lat#long#featureID (7 fields, no offsets).
V1 Themes: `;`-separated theme names, no offsets. So `min_flood_loc_dist` is unavailable (NaN);
downstream code treats a missing distance as "no proximity check". Output tables have the same
columns as the V2 pipeline (articles / target_locations) so daily.py, events.py etc. work unchanged.
Same limitation as V2: Selangor places coded MY00 are matched only if the name text says Selangor/KL.
"""
import re
import sys
from pathlib import Path

import pandas as pd

from .parse import TARGET_ADM1, domain_of, is_my_domain

LOC_COLUMNS = ["type", "name", "country", "adm1", "lat", "lon", "feature_id"]
NAME_MATCH = re.compile(r"Selangor|Kuala Lumpur")


def parse_locations_v1(s: str) -> list[dict]:
    out = []
    for entry in s.split(";"):
        p = entry.split("#")
        if len(p) != 7:
            continue
        try:
            lat, lon = float(p[4]), float(p[5])
        except ValueError:
            continue
        out.append(dict(zip(LOC_COLUMNS, [p[0], p[1], p[2], p[3], lat, lon, p[6]])))
    return out


def build_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("DATE").drop_duplicates("DocumentIdentifier", keep="first")
    arts, locs = [], []
    for r in df.itertuples(index=False):
        places = parse_locations_v1(r.Locations)
        themes = set(r.Themes.split(";"))
        dom = domain_of(r.DocumentIdentifier)
        target = [l for l in places if l["adm1"] in TARGET_ADM1]
        my_names = {l["name"] for l in places if l["country"] == "MY" and l["adm1"] != "MY"}
        sel = any(l["adm1"] == "MY12" for l in target) or bool(
            re.search("Selangor", r.Locations))
        kl = any(l["adm1"] == "MY14" for l in target) or bool(re.search("Kuala Lumpur", r.Locations))
        arts.append({
            "date": r.DATE, "url": r.DocumentIdentifier, "domain": dom, "source": r.SourceCommonName,
            "my_domain": is_my_domain(dom), "n_locations": len({l["name"] for l in places}),
            "n_my_places": len(my_names), "has_selangor": sel, "has_kl": kl, "has_target": sel or kl,
            "flood": any("FLOOD" in t for t in themes),
            "flash_flood": any("FLASH_FLOOD" in t for t in themes),
            "heavy_rain": "NATURAL_DISASTER_HEAVY_RAIN" in themes,
            "monsoon": "NATURAL_DISASTER_MONSOON" in themes,
            "torrential_rain": "TORRENTIAL_RAIN" in themes,
            "min_flood_loc_dist": float("nan"),
        })
        for l in target:
            locs.append({"date": r.DATE, "url": r.DocumentIdentifier, "region": TARGET_ADM1[l["adm1"]], **l})
    articles = pd.DataFrame(arts)
    articles["date"] = pd.to_datetime(articles["date"], format="%Y%m%d%H%M%S")
    locations = pd.DataFrame(locs)
    locations["date"] = pd.to_datetime(locations["date"], format="%Y%m%d%H%M%S")
    return articles, locations


def main(path: str, out_dir: str = "data/interim") -> None:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    articles, locations = build_tables(df)
    out = Path(out_dir)
    stem = Path(path).stem
    articles.to_parquet(out / f"{stem}_articles.parquet", index=False)
    locations.to_parquet(out / f"{stem}_target_locations.parquet", index=False)
    print(f"{len(df)} rows -> {len(articles)} unique articles, {articles.has_target.sum()} with Selangor/KL, "
          f"{articles.my_domain.sum()} Malaysian domains, {len(locations)} location rows")


if __name__ == "__main__":
    main(*sys.argv[1:3])
