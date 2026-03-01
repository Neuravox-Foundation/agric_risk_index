"""Step 2 — Harmonize data into a district-month panel."""
import logging
import os
import pandas as pd
import numpy as np

from src.config import (
    DATA_CLEANED, DATA_PROCESSED,
    PILOT_DISTRICTS, DISTRICT_CANONICAL, DATE_START, DATE_END
)

logger = logging.getLogger(__name__)


def standardize_district(series):
    """Apply canonical district mapping. Log unmatched names."""
    mapped = series.map(DISTRICT_CANONICAL)
    unmatched = series[mapped.isna()].unique()
    for name in unmatched:
        if pd.notna(name):
            logger.warning("Unmatched district name: '%s'", name)
    return mapped


def standardize_date(series):
    """Convert dates to month-start format (YYYY-MM-01)."""
    parsed = pd.to_datetime(series, errors="coerce")
    unparseable = series[parsed.isna()]
    if len(unparseable) > 0:
        logger.warning("Skipping %d unparseable dates", len(unparseable))
    # Normalize to month-start
    return parsed.dt.to_period("M").dt.to_timestamp()


def build_master_panel():
    """Create a complete monthly date spine for each pilot district."""
    date_range = pd.date_range(start=DATE_START, end=DATE_END, freq="MS")
    rows = []
    for district in PILOT_DISTRICTS:
        for date in date_range:
            rows.append({"date": date, "district": district})

    panel = pd.DataFrame(rows)
    logger.info("Master panel: %d rows (%d districts x %d months)",
                len(panel), len(PILOT_DISTRICTS), len(date_range))
    return panel


def run_harmonize():
    """Main entry point for Step 2."""
    os.makedirs(DATA_PROCESSED, exist_ok=True)

    panel = build_master_panel()

    # Save
    panel.to_parquet(os.path.join(DATA_PROCESSED, "master_panel.parquet"), index=False)
    panel.to_csv(os.path.join(DATA_PROCESSED, "master_panel.csv"), index=False)

    logger.info("Master panel saved: %s", os.path.join(DATA_PROCESSED, "master_panel.parquet"))
    return panel
