"""Step 7 — Input Cost Pressure Index (ICPI)."""
import logging
import os
import pandas as pd
import numpy as np

from src.config import (
    DATA_CLEANED, DATA_PROCESSED,
    PILOT_DISTRICTS, DATE_START, DATE_END
)

logger = logging.getLogger(__name__)


def robust_scale_series(series):
    """Robust scaling: (value - median) / (p95 - p5), clipped to [0, 1]."""
    median = series.median()
    p5 = series.quantile(0.05)
    p95 = series.quantile(0.95)
    denom = p95 - p5
    if denom == 0 or pd.isna(denom):
        return pd.Series(0.0, index=series.index)
    scaled = (series - median) / denom
    return scaled.clip(0, 1)


def run_icpi(include_icpi: bool = True):
    """Main entry point for ICPI computation."""
    os.makedirs(DATA_PROCESSED, exist_ok=True)

    date_range = pd.date_range(start=DATE_START, end=DATE_END, freq="MS")

    if not include_icpi:
        # Return all-zero scores for sensitivity testing
        rows = []
        for district in PILOT_DISTRICTS:
            for dt in date_range:
                rows.append({
                    "date": dt,
                    "district": district,
                    "icpi_score": 0.0,
                    "icpi_resolution": "annual_interpolated",
                    "icpi_scope": "national"
                })
        icpi_df = pd.DataFrame(rows)
        icpi_df.to_parquet(os.path.join(DATA_PROCESSED, "icpi_scores.parquet"), index=False)
        logger.info("ICPI disabled — all-zero scores saved")
        return icpi_df

    # Load input costs
    input_df = pd.read_csv(os.path.join(DATA_CLEANED, "input_costs_uganda.csv"))
    logger.info("Input costs: %d rows, years: %d-%d",
                len(input_df), input_df["year"].min(), input_df["year"].max())

    # Compute year-over-year rate of change per item
    roc_records = []

    for item, grp in input_df.groupby("item"):
        grp = grp.sort_values("year").copy()
        grp["roc"] = grp["value"].pct_change() * 100
        # Only positive roc (rising costs = stress signal)
        grp["roc_positive"] = grp["roc"].clip(lower=0)
        roc_records.append(grp[["year", "item", "roc_positive"]])

    roc_df = pd.concat(roc_records, ignore_index=True)

    # Average across all items per year
    annual = roc_df.groupby("year")["roc_positive"].mean().reset_index()
    annual = annual.rename(columns={"roc_positive": "icpi_raw"})

    # Robust scale over 2018-2024
    valid = annual["icpi_raw"].dropna()
    if len(valid) > 0:
        annual["icpi_score"] = robust_scale_series(valid).reindex(annual.index)
    else:
        annual["icpi_score"] = 0.0

    # Interpolate to monthly and apply to all districts
    rows = []
    for district in PILOT_DISTRICTS:
        for dt in date_range:
            yr = dt.year
            score_row = annual[annual["year"] == yr]
            if len(score_row) > 0:
                score = score_row.iloc[0]["icpi_score"]
            else:
                score = np.nan

            rows.append({
                "date": dt,
                "district": district,
                "icpi_score": score if pd.notna(score) else 0.0,
                "icpi_resolution": "annual_interpolated",
                "icpi_scope": "national"
            })

    icpi_df = pd.DataFrame(rows)
    icpi_df.to_parquet(os.path.join(DATA_PROCESSED, "icpi_scores.parquet"), index=False)
    logger.info("ICPI scores saved: %d rows", len(icpi_df))
    return icpi_df
