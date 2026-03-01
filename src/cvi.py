"""Step 3 — Commodity Volatility Index (CVI)."""
import logging
import os
import pandas as pd
import numpy as np

from src.config import (
    DATA_CLEANED, DATA_PROCESSED,
    PILOT_DISTRICTS, PRICE_DISTRICTS, NO_PRICE_DISTRICTS,
    DISTRICT_CANONICAL, COMMODITY_CANONICAL, MIN_MONTHS_FOR_CVI,
    DATE_START, DATE_END
)
from src.harmonize import standardize_district, standardize_date

logger = logging.getLogger(__name__)


def robust_scale(series):
    """Robust scaling: (value - median) / (p95 - p5), clipped to [0, 1]."""
    median = series.median()
    p5 = series.quantile(0.05)
    p95 = series.quantile(0.95)
    denom = p95 - p5
    if denom == 0 or pd.isna(denom):
        return pd.Series(0.0, index=series.index)
    scaled = (series - median) / denom
    return scaled.clip(0, 1)


def run_cvi():
    """Main entry point for CVI computation."""
    os.makedirs(DATA_PROCESSED, exist_ok=True)

    # Load price data
    df = pd.read_csv(
        os.path.join(DATA_CLEANED, "commodity_prices_northern_uganda.csv"),
        parse_dates=["date"]
    )

    # Standardize district and date
    df["district"] = standardize_district(df["district"])
    df["date"] = standardize_date(df["date"])
    df = df.dropna(subset=["date", "district"])

    # Filter to pilot price districts
    df = df[df["district"].isin(PRICE_DISTRICTS)].copy()
    logger.info("Price data after district filter: %d rows", len(df))

    # --- Unit standardisation ---
    if "unit" in df.columns:
        units = df["unit"].unique()
        logger.info("Units found: %s", units)
        # All should be KG based on known data facts; log any anomalies
        non_kg = df[df["unit"] != "KG"]
        if len(non_kg) > 0:
            logger.warning("%d rows with non-KG units: %s", len(non_kg), non_kg["unit"].unique())
    else:
        logger.info("No 'unit' column found; assuming per-KG pricing")

    # --- Commodity harmonisation ---
    df["commodity_orig"] = df["commodity"]
    df["commodity"] = df["commodity"].map(COMMODITY_CANONICAL)
    unmapped = df[df["commodity"].isna()]["commodity_orig"].unique()
    if len(unmapped) > 0:
        logger.warning("Unmapped commodities dropped: %s", unmapped)
    df = df.dropna(subset=["commodity"])

    # Use price_local as the price column
    price_col = "price_local"
    if price_col not in df.columns:
        price_col = "price_usd"

    # For duplicates after commodity mapping (e.g. Maize + Maize (white) -> Maize),
    # keep the series with more observations per district-commodity-price_type
    df["ym"] = df["date"].dt.to_period("M")
    counts = df.groupby(["district", "commodity", "price_type", "commodity_orig"])["ym"].nunique()
    counts = counts.reset_index(name="obs_count")

    # For each district-commodity-price_type, keep the commodity_orig with the most observations
    best = counts.sort_values("obs_count", ascending=False).drop_duplicates(
        subset=["district", "commodity", "price_type"], keep="first"
    )
    keep_keys = set(zip(best["district"], best["commodity"], best["price_type"], best["commodity_orig"]))
    df = df[df.apply(lambda r: (r["district"], r["commodity"], r["price_type"], r["commodity_orig"]) in keep_keys, axis=1)].copy()

    # Aggregate to monthly: mean price per district-commodity-price_type-month
    monthly = df.groupby(["district", "commodity", "price_type", "date"])[price_col].mean().reset_index()
    monthly = monthly.rename(columns={price_col: "price"})
    monthly = monthly.sort_values(["district", "commodity", "price_type", "date"])

    # --- Minimum months filter ---
    month_counts = monthly.groupby(["district", "commodity", "price_type"])["date"].nunique().reset_index(name="n_months")
    excluded = month_counts[month_counts["n_months"] < MIN_MONTHS_FOR_CVI]
    for _, row in excluded.iterrows():
        logger.info("CVI EXCLUDED: %s / %s / %s — %d months (< %d)",
                     row["district"], row["commodity"], row["price_type"],
                     row["n_months"], MIN_MONTHS_FOR_CVI)

    qualifying = month_counts[month_counts["n_months"] >= MIN_MONTHS_FOR_CVI]
    qual_keys = set(zip(qualifying["district"], qualifying["commodity"], qualifying["price_type"]))
    monthly_q = monthly[monthly.apply(
        lambda r: (r["district"], r["commodity"], r["price_type"]) in qual_keys, axis=1
    )].copy()

    logger.info("Qualifying series: %d (excluded %d)", len(qual_keys), len(excluded))

    # --- Per-commodity-district computation ---
    detail_records = []

    for (district, commodity, ptype), grp in monthly_q.groupby(["district", "commodity", "price_type"]):
        grp = grp.sort_values("date").set_index("date")
        price = grp["price"]

        # Rolling std
        std_6m = price.rolling(window=6, min_periods=4).std()
        std_12m = price.rolling(window=12, min_periods=8).std()

        # Z-score spike flag
        rolling_mean_12 = price.rolling(window=12, min_periods=8).mean()
        rolling_std_12 = price.rolling(window=12, min_periods=8).std()
        z_score = (price - rolling_mean_12) / rolling_std_12
        spike_flag = pd.Series(np.nan, index=price.index)
        valid_std = rolling_std_12.notna() & (rolling_std_12 > 0)
        spike_flag[valid_std] = (z_score[valid_std] > 1.5).astype(float)

        # Robust scaling of std components
        scaled_6m = robust_scale(std_6m.dropna()).reindex(price.index)
        scaled_12m = robust_scale(std_12m.dropna()).reindex(price.index)

        # Commodity-level volatility score
        raw_score = 0.4 * scaled_6m + 0.4 * scaled_12m + 0.20 * spike_flag

        for dt in grp.index:
            detail_records.append({
                "date": dt,
                "district": district,
                "commodity": commodity,
                "price_type": ptype,
                "price": price.get(dt),
                "std_6m": std_6m.get(dt),
                "std_12m": std_12m.get(dt),
                "z_score": z_score.get(dt),
                "spike_flag": spike_flag.get(dt),
                "scaled_6m": scaled_6m.get(dt),
                "scaled_12m": scaled_12m.get(dt),
                "raw_score": raw_score.get(dt),
            })

    detail_df = pd.DataFrame(detail_records)

    # --- Retail-wholesale spread ---
    detail_df["spread_stress"] = np.nan

    for (district, commodity, date), subgrp in detail_df.groupby(["district", "commodity", "date"]):
        ptypes = subgrp["price_type"].unique()
        if "Retail" in ptypes and "Wholesale" in ptypes:
            retail_price = subgrp.loc[subgrp["price_type"] == "Retail", "price"].values[0]
            wholesale_price = subgrp.loc[subgrp["price_type"] == "Wholesale", "price"].values[0]
            if wholesale_price and wholesale_price > 0:
                spread = (retail_price - wholesale_price) / wholesale_price
                # Store spread value; threshold computed later
                idx = subgrp.index
                detail_df.loc[idx, "spread_value"] = spread

    # Compute spread stress per series
    if "spread_value" in detail_df.columns:
        for (district, commodity), grp in detail_df.groupby(["district", "commodity"]):
            mask = grp["spread_value"].notna()
            if mask.sum() > 0:
                p75 = grp.loc[mask, "spread_value"].quantile(0.75)
                stress = (grp["spread_value"] > p75).astype(float)
                stress[~mask] = np.nan
                detail_df.loc[grp.index, "spread_stress"] = stress

    # Save detail
    detail_df.to_parquet(os.path.join(DATA_PROCESSED, "cvi_commodity_detail.parquet"), index=False)

    # --- Aggregate to district-level CVI ---
    # Average raw_score across qualifying commodities per district-month
    # Use the best price_type per commodity (highest mean raw_score)
    best_ptype = detail_df.groupby(["district", "commodity", "price_type"])["raw_score"].mean().reset_index()
    best_ptype = best_ptype.sort_values("raw_score", ascending=False).drop_duplicates(
        subset=["district", "commodity"], keep="first"
    )
    best_keys = set(zip(best_ptype["district"], best_ptype["commodity"], best_ptype["price_type"]))

    agg_df = detail_df[detail_df.apply(
        lambda r: (r["district"], r["commodity"], r["price_type"]) in best_keys, axis=1
    )].copy()

    district_monthly = agg_df.groupby(["district", "date"]).agg(
        raw_cvi=("raw_score", "mean"),
        n_commodities_used=("raw_score", lambda x: x.notna().sum())
    ).reset_index()

    # If fewer than 2 commodities, set CVI = NaN
    district_monthly.loc[district_monthly["n_commodities_used"] < 2, "raw_cvi"] = np.nan
    low_count = (district_monthly["n_commodities_used"] < 2).sum()
    if low_count > 0:
        logger.warning("%d district-months with < 2 commodities set to NaN", low_count)

    # Robust scale CVI per district
    cvi_records = []
    for district, grp in district_monthly.groupby("district"):
        valid = grp["raw_cvi"].dropna()
        if len(valid) > 0:
            scaled = robust_scale(valid).reindex(grp.index)
            grp = grp.copy()
            grp["cvi_score"] = scaled
        else:
            grp = grp.copy()
            grp["cvi_score"] = np.nan
        grp["cvi_data_flag"] = "price_data_available"
        cvi_records.append(grp)

    cvi_df = pd.concat(cvi_records, ignore_index=True)
    cvi_df = cvi_df[["date", "district", "cvi_score", "cvi_data_flag", "n_commodities_used"]]

    # --- Add Oyam and Nebbi as NaN ---
    date_range = pd.date_range(start=DATE_START, end=DATE_END, freq="MS")
    for district in NO_PRICE_DISTRICTS:
        no_price = pd.DataFrame({
            "date": date_range,
            "district": district,
            "cvi_score": np.nan,
            "cvi_data_flag": "no_price_data",
            "n_commodities_used": 0
        })
        cvi_df = pd.concat([cvi_df, no_price], ignore_index=True)

    cvi_df = cvi_df.sort_values(["district", "date"]).reset_index(drop=True)
    cvi_df.to_parquet(os.path.join(DATA_PROCESSED, "cvi_scores.parquet"), index=False)

    logger.info("CVI scores saved: %d rows", len(cvi_df))
    return cvi_df
