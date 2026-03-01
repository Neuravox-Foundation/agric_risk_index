"""Step 4 — Climate Stress Index (CSI)."""
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


def run_csi():
    """Main entry point for CSI computation."""
    os.makedirs(DATA_PROCESSED, exist_ok=True)

    # Load climate data
    df = pd.read_csv(
        os.path.join(DATA_CLEANED, "climate_data_northern_uganda.csv"),
        parse_dates=["date"]
    )

    # Standardize
    df["district"] = standardize_district(df["district"])
    df["date"] = standardize_date(df["date"])
    df = df.dropna(subset=["date", "district"])

    # Filter to pilot districts + Adjumani (which has climate data)
    all_climate_districts = PILOT_DISTRICTS + ["Adjumani"]
    df = df[df["district"].isin(all_climate_districts)].copy()

    # Filter to analysis period
    df = df[(df["date"] >= DATE_START) & (df["date"] <= DATE_END)].copy()

    # Add month column
    df["month_of_year"] = df["date"].dt.month

    results = []

    for district in PILOT_DISTRICTS:
        ddf = df[df["district"] == district].copy()
        if len(ddf) == 0:
            logger.warning("No climate data for %s", district)
            continue

        ddf = ddf.sort_values("date").set_index("date")

        # --- Climatological normals ---
        normals = ddf.groupby("month_of_year").agg(
            rain_mean=("rainfall_mm", "mean"),
            rain_std=("rainfall_mm", "std"),
            temp_mean=("temperature_mean_c", "mean"),
            temp_std=("temperature_mean_c", "std"),
        )

        # --- Anomalies ---
        ddf = ddf.join(normals, on="month_of_year")

        # Rainfall anomaly
        ddf["rainfall_anomaly"] = np.where(
            (ddf["rain_std"] == 0) | ddf["rain_std"].isna(),
            0,
            (ddf["rainfall_mm"] - ddf["rain_mean"]) / ddf["rain_std"]
        )
        zero_rain_std = ((ddf["rain_std"] == 0) | ddf["rain_std"].isna()).sum()
        if zero_rain_std > 0:
            logger.info("%s: %d months with zero rainfall std, anomaly set to 0", district, zero_rain_std)

        # Temperature anomaly
        ddf["temp_anomaly"] = np.where(
            (ddf["temp_std"] == 0) | ddf["temp_std"].isna(),
            0,
            (ddf["temperature_mean_c"] - ddf["temp_mean"]) / ddf["temp_std"]
        )

        # Stress signals (directional)
        ddf["rainfall_stress"] = (-ddf["rainfall_anomaly"]).clip(lower=0)  # drought signal
        ddf["temp_stress"] = ddf["temp_anomaly"].clip(lower=0)  # heat signal

        # --- Lagged rainfall ---
        ddf["rainfall_lag1"] = (-ddf["rainfall_anomaly"]).clip(lower=0).shift(1)
        ddf["rainfall_lag2"] = (-ddf["rainfall_anomaly"]).clip(lower=0).shift(2)
        ddf["rainfall_lag3"] = (-ddf["rainfall_anomaly"]).clip(lower=0).shift(3)

        # --- CSI raw score ---
        ddf["csi_raw"] = (
            0.35 * ddf["rainfall_stress"] +
            0.20 * ddf["rainfall_lag1"] +
            0.15 * ddf["rainfall_lag2"] +
            0.10 * ddf["rainfall_lag3"] +
            0.20 * ddf["temp_stress"]
        )

        # Robust scale CSI per district
        valid = ddf["csi_raw"].dropna()
        if len(valid) > 0:
            ddf["csi_score"] = robust_scale_series(valid).reindex(ddf.index)
        else:
            ddf["csi_score"] = np.nan

        ddf["district"] = district
        results.append(ddf[["district", "csi_score", "rainfall_anomaly", "temp_anomaly",
                            "rainfall_stress", "temp_stress"]].reset_index())

    csi_df = pd.concat(results, ignore_index=True)
    csi_df = csi_df.sort_values(["district", "date"]).reset_index(drop=True)

    csi_df.to_parquet(os.path.join(DATA_PROCESSED, "csi_scores.parquet"), index=False)
    logger.info("CSI scores saved: %d rows", len(csi_df))
    return csi_df
