"""Combined evaluation over 2015-16, 2021-23 and 2024-26 (labels from three GDELT chunks).

    python -m src.modeling.run_combined

Observed-rain features exist for every period; forecast features only from 2024, so
  (a) observed-only models and rain baselines are evaluated over ALL test blocks (2021-2026), trained on
      everything earlier (expanding windows over the concatenated timeline);
  (b) forecast-based scores are evaluated on the 2024-26 blocks only (as before) for comparison.
Schemes: all (every non-excluded day is a negative) and labeled (only hand/rule-labelled days).
Tide high-water (predicted, known in advance) is tested as an extra feature.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from .evaluate import OBS, make_dataset, run, summarize
from .features import build_features
from .gauge_tide_analysis import tide_daily

PERIODS = {
    "2015-16": ("data/interim/rain_hourly_2015-02-01_2016-12-31.parquet", None, "data/processed/daily_labels_2015_2016.csv"),
    "2021-23": ("data/interim/rain_hourly_2020-12-01_2023-12-31.parquet", None, "data/processed/daily_labels_v1_2021_2023.csv"),
    "2024-26": ("data/interim/rain_hourly_2024-01-01_2026-09-30.parquet", "data/interim/fcst_hourly_2024-01-01_2026-09-30.parquet",
                "data/processed/daily_labels_v1_2024_2026.csv"),
}
CUTOFFS_ALL = ["2021-07-01", "2022-01-01", "2022-07-01", "2023-01-01", "2023-07-01", "2024-07-01", "2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01"]
CUTOFFS_P3 = ["2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01"]
SPARSE_OBS = ["obs_1d_total_max", "obs_7d_mean", "ne_monsoon"]
TIDE = ["tide_hw_max"]
SETS = {"obs (lead 1d)": OBS, "obs + tide": OBS + TIDE, "sparse obs (yesterday, 7d rain, monsoon)": SPARSE_OBS,
        "sparse obs + tide": SPARSE_OBS + TIDE, "obs + same-day rain (lead 0)": OBS + ["nowcast_total_max", "nowcast_hourly_max"]}
RANKS = {"same-day ERA5 rain (lead 0, detection)": "nowcast_total_max", "yesterday's rain (lead 1d)": "obs_1d_total_max",
         "tide high-water only (known in advance)": "tide_hw_max"}


def load(scheme: str) -> pd.DataFrame:
    tide = tide_daily()
    parts = []
    for tag, (rain, fc, lab) in PERIODS.items():
        if not Path(lab).exists():
            continue
        f = build_features(rain, fc).join(tide)
        d = make_dataset(f, pd.read_csv(lab), scheme)
        d["period"] = tag
        parts.append(d)
    data = pd.concat(parts).sort_index()
    return data


def main() -> None:
    pd.set_option("display.width", 250, "display.max_columns", 30)
    for scheme in ("all", "labeled"):
        data = load(scheme)
        print(f"\n##### scheme={scheme}: {len(data)} days, {int(data.y.sum())} floods "
              f"({data.groupby('period').y.sum().to_dict()})")
        res = run(data, CUTOFFS_ALL, feature_sets=SETS, rank_baselines=RANKS)
        o = summarize(res)
        o.to_csv(f"data/processed/model_results_combined_{scheme}.csv", index=False)
        print("(a) observed-only models, test blocks 2021-07..2026-09 pooled")
        print(o[["model", "n_days", "n_flood", "base_rate", "PR-AUC", "PR-AUC 95% CI", "perm p", "ROC-AUC", "hits", "false_alarms", "misses", "CSI", "FAR"]].round(3).to_string(index=False))
        p3 = data[data.period == "2024-26"]
        res3 = run(p3, CUTOFFS_P3)
        o3 = summarize(res3)
        o3.to_csv(f"data/processed/model_results_p3_{scheme}.csv", index=False)
        print("(b) 2024-26 only, with forecasts (as before)")
        print(o3[["model", "n_days", "n_flood", "PR-AUC", "PR-AUC 95% CI", "ROC-AUC", "CSI", "FAR"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
