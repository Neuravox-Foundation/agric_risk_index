"""Step 5 — Yield Instability Index (YII)."""
import logging
import os
import pandas as pd
import numpy as np
from scipy import stats as scipy_stats

from src.config import (
    DATA_CLEANED, DATA_PROCESSED,
    PILOT_DISTRICTS, DATE_START, DATE_END
)

logger = logging.getLogger(__name__)

YII_COMMODITIES = ["Maize", "Beans (dry)", "Sorghum", "Millet", "Cassava"]
# Map to FAOSTAT names which may differ
FAOSTAT_NAME_MAP = {
    "Maize": "Maize",
    "Beans (dry)": "Beans (dry)",
    "Sorghum": "Sorghum",
    "Millet": "Millet",
    "Cassava": "Cassava",
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


def run_yii():
    """Main entry point for YII computation."""
    os.makedirs(DATA_PROCESSED, exist_ok=True)

    # Check for UBOS district data
    ubos_path = os.path.join(DATA_PROCESSED, "ubos_district_crops.csv")
    use_ubos = os.path.exists(ubos_path)

    if use_ubos:
        logger.info("UBOS district data found — using for YII where available")
    else:
        logger.info("No UBOS district data — using FAOSTAT national data for YII")

    # Load FAOSTAT national data
    crop_df = pd.read_csv(os.path.join(DATA_CLEANED, "crop_production_uganda.csv"))
    logger.info("FAOSTAT data: %d rows, commodities: %s",
                len(crop_df), crop_df["commodity"].unique())

    # Filter to YII commodities
    available = crop_df["commodity"].unique()
    commodities_used = [c for c in YII_COMMODITIES if c in available]
    # Also try partial matches
    if "Beans (dry)" not in available and "Beans" in available:
        commodities_used = [c if c != "Beans (dry)" else "Beans" for c in commodities_used]

    logger.info("YII commodities used: %s", commodities_used)
    crop_df = crop_df[crop_df["commodity"].isin(commodities_used)].copy()

    # Compute yield trend and residuals per commodity
    commodity_instability = []

    for commodity in commodities_used:
        cdf = crop_df[crop_df["commodity"] == commodity].sort_values("year").copy()

        if "yield_kg_per_ha" not in cdf.columns or cdf["yield_kg_per_ha"].isna().all():
            logger.warning("No yield data for %s, skipping", commodity)
            continue

        cdf = cdf.dropna(subset=["yield_kg_per_ha"])

        # Linear trend via OLS
        x = cdf["year"].values
        y = cdf["yield_kg_per_ha"].values

        if len(x) < 5:
            logger.warning("Too few years for %s (%d), skipping", commodity, len(x))
            continue

        slope, intercept, _, _, _ = scipy_stats.linregress(x, y)
        cdf["trend"] = intercept + slope * cdf["year"]
        cdf["residual"] = cdf["yield_kg_per_ha"] - cdf["trend"]

        # 5-year rolling mean of production
        if "production_tonnes" in cdf.columns:
            cdf["rolling_5yr_mean"] = cdf["production_tonnes"].rolling(window=5, min_periods=3).mean()
        else:
            cdf["rolling_5yr_mean"] = cdf["yield_kg_per_ha"].rolling(window=5, min_periods=3).mean()

        # Yield instability
        cdf["yield_instability"] = np.where(
            (cdf["rolling_5yr_mean"] == 0) | cdf["rolling_5yr_mean"].isna(),
            np.nan,
            np.abs(cdf["residual"]) / cdf["rolling_5yr_mean"]
        )

        commodity_instability.append(cdf[["year", "commodity", "yield_instability"]])

    if not commodity_instability:
        logger.error("No commodity instability data computed")
        # Return empty
        date_range = pd.date_range(start=DATE_START, end=DATE_END, freq="MS")
        rows = []
        for district in PILOT_DISTRICTS:
            for dt in date_range:
                rows.append({
                    "date": dt, "district": district, "yii_score": np.nan,
                    "yii_resolution": "annual_interpolated",
                    "yii_scope": "national", "yii_source": "faostat_national"
                })
        yii_df = pd.DataFrame(rows)
        yii_df.to_parquet(os.path.join(DATA_PROCESSED, "yii_scores.parquet"), index=False)
        return yii_df

    all_instab = pd.concat(commodity_instability, ignore_index=True)

    # Average across commodities per year
    annual = all_instab.groupby("year")["yield_instability"].mean().reset_index()
    annual = annual.rename(columns={"yield_instability": "yii_raw"})

    # Robust scale
    valid = annual["yii_raw"].dropna()
    if len(valid) > 0:
        annual["yii_score"] = robust_scale_series(valid).reindex(annual.index)
    else:
        annual["yii_score"] = np.nan

    # Interpolate to monthly and apply to districts
    date_range = pd.date_range(start=DATE_START, end=DATE_END, freq="MS")
    start_year = int(DATE_START[:4])
    end_year = int(DATE_END[:4])

    rows = []
    for district in PILOT_DISTRICTS:
        for dt in date_range:
            yr = dt.year
            score_row = annual[annual["year"] == yr]
            if len(score_row) > 0:
                score = score_row.iloc[0]["yii_score"]
            else:
                score = np.nan

            rows.append({
                "date": dt,
                "district": district,
                "yii_score": score,
                "yii_resolution": "annual_interpolated",
                "yii_scope": "national",
                "yii_source": "ubos_district" if use_ubos else "faostat_national"
            })

    yii_df = pd.DataFrame(rows)
    yii_df.to_parquet(os.path.join(DATA_PROCESSED, "yii_scores.parquet"), index=False)
    logger.info("YII scores saved: %d rows", len(yii_df))
    return yii_df
