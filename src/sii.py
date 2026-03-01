"""Step 6 — Shock Intensity Index (SII)."""
import logging
import os
import pandas as pd
import numpy as np

from src.config import (
    DATA_CLEANED, DATA_PROCESSED,
    PILOT_DISTRICTS, DISTRICT_CANONICAL, DATE_START, DATE_END
)
from src.harmonize import standardize_district, standardize_date

logger = logging.getLogger(__name__)

SEVERITY_MAP = {
    "low": 0.25, "minor": 0.25,
    "medium": 0.50, "moderate": 0.50,
    "high": 0.75, "major": 0.75, "severe": 0.75,
    "critical": 1.0, "extreme": 1.0
}


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


def run_sii():
    """Main entry point for SII computation."""
    os.makedirs(DATA_PROCESSED, exist_ok=True)

    # --- Conflict component (national) ---
    conflict_df = pd.read_csv(
        os.path.join(DATA_CLEANED, "conflict_events_uganda.csv"),
        parse_dates=["date"]
    )
    conflict_df["date"] = standardize_date(conflict_df["date"])
    conflict_df = conflict_df.dropna(subset=["date"])

    # Replace NaN fatalities with 0
    conflict_df["fatalities"] = conflict_df["fatalities"].fillna(0)

    # Monthly totals across all categories
    conflict_monthly = conflict_df.groupby("date").agg(
        total_event_count=("event_count", "sum"),
        total_fatalities=("fatalities", "sum")
    ).reset_index()

    # Robust scale each component over full available period
    conflict_monthly["scaled_events"] = robust_scale_series(conflict_monthly["total_event_count"])
    conflict_monthly["scaled_fatalities"] = robust_scale_series(conflict_monthly["total_fatalities"])

    conflict_monthly["conflict_signal_national"] = (
        0.6 * conflict_monthly["scaled_events"] +
        0.4 * conflict_monthly["scaled_fatalities"]
    )

    # Filter to analysis period
    conflict_monthly = conflict_monthly[
        (conflict_monthly["date"] >= DATE_START) &
        (conflict_monthly["date"] <= DATE_END)
    ].copy()

    # --- Disaster component (district-level) ---
    disaster_df = pd.read_csv(
        os.path.join(DATA_CLEANED, "disaster_shock_events_northern_uganda.csv"),
        parse_dates=["date"]
    )
    disaster_df["district"] = standardize_district(disaster_df["district"])
    disaster_df["date"] = standardize_date(disaster_df["date"])
    disaster_df = disaster_df.dropna(subset=["date", "district"])

    # Map severity to numeric
    if "severity" in disaster_df.columns:
        disaster_df["severity_score"] = disaster_df["severity"].str.lower().str.strip().map(SEVERITY_MAP)
        unmapped = disaster_df[disaster_df["severity_score"].isna()]["severity"].unique()
        if len(unmapped) > 0:
            logger.warning("Unmapped severity values: %s — defaulting to 0.50", unmapped)
            disaster_df["severity_score"] = disaster_df["severity_score"].fillna(0.50)
    else:
        disaster_df["severity_score"] = 0.50

    # Monthly per-district: max severity, flag
    disaster_monthly = disaster_df.groupby(["district", "date"]).agg(
        disaster_severity_score=("severity_score", "max"),
        disaster_count=("severity_score", "count")
    ).reset_index()
    disaster_monthly["disaster_flag"] = 1

    # --- Build full panel and combine ---
    date_range = pd.date_range(start=DATE_START, end=DATE_END, freq="MS")
    rows = []

    for district in PILOT_DISTRICTS:
        for dt in date_range:
            # Conflict (national)
            conflict_row = conflict_monthly[conflict_monthly["date"] == dt]
            conflict_val = conflict_row["conflict_signal_national"].values[0] if len(conflict_row) > 0 else 0.0

            # Disaster (district)
            disaster_row = disaster_monthly[
                (disaster_monthly["district"] == district) & (disaster_monthly["date"] == dt)
            ]
            if len(disaster_row) > 0:
                disaster_sev = disaster_row["disaster_severity_score"].values[0]
                disaster_flag = 1
            else:
                disaster_sev = 0.0
                disaster_flag = 0

            rows.append({
                "date": dt,
                "district": district,
                "conflict_signal_national": conflict_val,
                "disaster_flag": disaster_flag,
                "disaster_severity_score": disaster_sev,
            })

    sii_df = pd.DataFrame(rows)

    # Combine
    sii_df["sii_raw"] = (
        0.55 * sii_df["conflict_signal_national"] +
        0.45 * sii_df["disaster_severity_score"]
    )

    # Robust scale SII per district over 2010-2024
    for district in PILOT_DISTRICTS:
        mask = sii_df["district"] == district
        valid = sii_df.loc[mask, "sii_raw"].dropna()
        if len(valid) > 0:
            sii_df.loc[mask, "sii_score"] = robust_scale_series(valid).values
        else:
            sii_df.loc[mask, "sii_score"] = np.nan

    sii_df = sii_df[["date", "district", "sii_score", "conflict_signal_national",
                      "disaster_flag", "disaster_severity_score"]]
    sii_df = sii_df.sort_values(["district", "date"]).reset_index(drop=True)

    sii_df.to_parquet(os.path.join(DATA_PROCESSED, "sii_scores.parquet"), index=False)
    logger.info("SII scores saved: %d rows", len(sii_df))
    return sii_df
