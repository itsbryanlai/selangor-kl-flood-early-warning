"""CLI: raw GKG CSV -> data/interim/{articles,target_locations}.parquet

    python -m src.gdelt.build_interim data/raw/gdelt_gkg_2015_2016.csv
"""
import sys
from pathlib import Path

import pandas as pd

from .parse import build_tables


def main(path: str, out_dir: str = "data/interim") -> None:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    articles, locations = build_tables(df)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(path).stem
    articles.to_parquet(out / f"{stem}_articles.parquet", index=False)
    locations.to_parquet(out / f"{stem}_target_locations.parquet", index=False)
    print(f"{len(df)} rows -> {len(articles)} unique articles, "
          f"{articles.has_target.sum()} with Selangor/KL, {len(locations)} location rows")


if __name__ == "__main__":
    main(*sys.argv[1:])
