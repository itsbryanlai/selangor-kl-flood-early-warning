"""Download GDELT GKG v2 raw 15-minute files and keep only Selangor/KL rows (no BigQuery).

    python -m src.gdelt.raw_download 2017-01-01 2017-01-31 [--workers 8] [--kinds gkg] [--out data/raw/gkg_selkl]

For each UTC day it fetches the 96 English files (<ts>.gkg.csv.zip) and 96 translation files
(<ts>.translation.gkg.csv.zip; BigQuery merges both, and Chinese-language Malaysian outlets are only there), streams
each through a filter and writes one gzip TSV per day: <out>/YYYYMMDD.tsv.gz. Resumable: days whose
file exists are skipped. Files that stay unavailable after retries are listed in
<out>/YYYYMMDD.missing (the day is still marked done; delete both files to retry).

Kept rows: V2Locations contains ADM1 code MY12 (Selangor) or MY14 (Kuala Lumpur), or the words
"Selangor"/"Kuala Lumpur" (catches Selangor places coded MY00). ALL themes are kept so the flood
filter can be redone locally without re-downloading. Columns kept: GKGRECORDID, DATE,
SourceCommonName, DocumentIdentifier, V2Themes, V2Locations, V2Tone, plus Collection (en/trans).
"""
import argparse
import gzip
import io
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

BASE = "https://data.gdeltproject.org/gdeltv2/{ts}.{kind}.csv.zip"
KINDS = {"gkg": "en", "translation.gkg": "trans"}  # English files and machine-translated (e.g. Chinese) files
# GKG 2.1 tab-separated column indices
KEEP_IDX = [0, 1, 3, 4, 8, 10, 15]
KEEP_NAMES = ["GKGRECORDID", "DATE", "SourceCommonName", "DocumentIdentifier", "V2Themes", "V2Locations", "V2Tone", "Collection"]
V2LOC = 10
TARGET = re.compile(r"#MY1[24]#|Selangor|Kuala Lumpur")
RETRIES = 4


def day_timestamps(day: date) -> list[str]:
    start = datetime(day.year, day.month, day.day)
    return [(start + timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S") for i in range(96)]


def fetch_filtered(client: httpx.Client, ts: str, kind: str = "gkg") -> tuple[list[str], bool]:
    """Return (kept lines, ok). ok=False if the file never downloaded (404 counts as missing)."""
    for attempt in range(RETRIES):
        try:
            r = client.get(BASE.format(ts=ts, kind=kind))
            if r.status_code == 404:
                return [], False
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                raw = z.read(z.namelist()[0]).decode("utf-8", errors="replace")
            out = []
            for line in raw.split("\n"):
                f = line.split("\t")
                if len(f) < 16 or not TARGET.search(f[V2LOC]):
                    continue
                out.append("\t".join([f[i] for i in KEEP_IDX] + [KINDS[kind]]))
            return out, True
        except (httpx.HTTPError, zipfile.BadZipFile, OSError):
            time.sleep(2 ** attempt)
    return [], False


def process_day(day: date, out_dir: Path, workers: int, kinds: tuple = tuple(KINDS)) -> tuple[int, int]:
    name = day.strftime("%Y%m%d")
    target = out_dir / f"{name}.tsv.gz"
    if target.exists():
        return -1, 0
    limits = httpx.Limits(max_connections=workers)
    with httpx.Client(timeout=60, limits=limits, headers={"User-Agent": "flood-research"}) as client:
        with ThreadPoolExecutor(workers) as ex:
            jobs = [(ts, k) for k in kinds for ts in day_timestamps(day)]
            results = list(ex.map(lambda j: fetch_filtered(client, *j), jobs))
    missing = [f"{ts}.{k}" for (ts, k), (_, ok) in zip(jobs, results) if not ok]
    rows = [line for lines, _ in results for line in lines]
    tmp = target.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        f.write("\t".join(KEEP_NAMES) + "\n")
        f.write("\n".join(rows) + ("\n" if rows else ""))
    if missing:
        (out_dir / f"{name}.missing").write_text("\n".join(missing) + "\n")
    tmp.rename(target)
    return len(rows), len(missing)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("start")
    ap.add_argument("end")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="data/raw/gkg_selkl")
    ap.add_argument("--kinds", default="gkg,translation.gkg", help="gkg (English) and/or translation.gkg")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    day, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    t0 = time.time()
    done = 0
    while day <= end:
        t = time.time()
        n, miss = process_day(day, out, a.workers, tuple(a.kinds.split(",")))
        if n >= 0:
            done += 1
            print(f"{day} rows={n} missing_files={miss} {time.time() - t:.0f}s", flush=True)
        day += timedelta(days=1)
    print(f"finished {done} days in {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
