"""Run the 2024-2026 flood early-warning evaluation.

    python -m src.modeling.run_2024_2026
"""
from pathlib import Path

import matplotlib
import pandas as pd
from sklearn.metrics import precision_recall_curve

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .evaluate import make_dataset, run, run_transfer, summarize
from .features import build_features

CUTOFFS = ["2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01"]


def plot_pr(res: dict) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    show = ["climatology (month base rate)", "same-day ERA5 rain (lead 0, detection)", "1-day forecast rain (lead ~1d)",
            "2-day forecast rain (lead ~2d)", "logistic: sparse: forecast+7d rain+monsoon (lead ~1d)", "logistic: obs (lead 1d, no forecast)"]
    y = res["y"]
    for name in show:
        s = res["scores"][name]; ok = s.notna()
        p, r, _ = precision_recall_curve(y[ok], s[ok])
        ax.step(r, p, where="post", label=name.replace("logistic: ", "LR: "))
    ax.axhline(y[res["scores"][show[0]].notna()].mean(), color="k", ls=":", lw=1, label="base rate")
    ax.set_xlabel("Recall"); ax.set_ylabel("Precision"); ax.set_ylim(0, 1.02)
    ax.set_title("Pooled temporal test 2025-01 to 2026-09 (8 flood days; scheme: all)")
    ax.legend(fontsize=7)
    Path("docs/figures").mkdir(parents=True, exist_ok=True)
    fig.tight_layout(); fig.savefig("docs/figures/pr_2024_2026.png", dpi=130)


def main() -> None:
    feats = build_features("data/interim/rain_hourly_2024-01-01_2026-09-30.parquet",
                           "data/interim/fcst_hourly_2024-01-01_2026-09-30.parquet")
    labels = pd.read_csv("data/processed/daily_labels_v1_2024_2026.csv")
    pd.set_option("display.width", 250, "display.max_columns", 30)
    for scheme in ("all", "labeled"):
        data = make_dataset(feats, labels, scheme)
        res = run(data, CUTOFFS)
        if scheme == "all":
            plot_pr(res)
        out = summarize(res)
        out.to_csv(f"data/processed/model_results_2024_2026_{scheme}.csv", index=False)
        print(f"\n=== scheme={scheme}: {len(data)} days, {int(data.y.sum())} floods; test pooled over {CUTOFFS[0]}..end ===")
        print(out.drop(columns=["n_flood"]).round(3).to_string(index=False))
    # cross-period: train on 2015-2016 labels (observed-rain features only), test on all of 2024-2026
    f_old = build_features("data/interim/rain_hourly_2015-02-01_2016-12-31.parquet")
    l_old = pd.read_csv("data/processed/daily_labels_2015_2016.csv")
    for scheme in ("all", "labeled"):
        tr, te = make_dataset(f_old, l_old, scheme), make_dataset(feats, labels, scheme)
        res = run_transfer(tr, te)
        out = summarize(res)
        out.to_csv(f"data/processed/model_results_transfer_2015-16_to_2024-26_{scheme}.csv", index=False)
        print(f"\n=== transfer (train 2015-16: {len(tr)} days/{int(tr.y.sum())} floods; test 2024-26 scheme={scheme}: {len(te)} days/{int(te.y.sum())} floods) ===")
        print(out.drop(columns=["n_flood"]).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
