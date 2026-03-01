"""Step 0 — Data coverage check and UBOS PDF extraction."""
import logging
import os
import pandas as pd
import numpy as np
import pdfplumber
import matplotlib
matplotlib.use("Agg")
import seaborn as sns
import matplotlib.pyplot as plt

from src.config import (
    DATA_CLEANED, DATA_PROCESSED, CHARTS_DIR, DOCS_DIR,
    PILOT_DISTRICTS, DISTRICT_CANONICAL
)

logger = logging.getLogger(__name__)


def attempt_ubos_extraction():
    """Attempt to extract district-level crop data from UBOS Statistical Abstract."""
    pdf_path = os.path.join(DATA_CLEANED, "2023-Statistical-Abstract.pdf")
    if not os.path.exists(pdf_path):
        logger.warning("UBOS PDF not found at %s", pdf_path)
        return False

    target_districts = ["Gulu", "Oyam", "Arua", "Nebbi", "Lira", "Northern"]
    found_tables = []
    pages_checked = []
    agriculture_pages = []

    logger.info("Scanning UBOS PDF for district-level crop data...")

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        logger.info("PDF has %d pages", total_pages)

        for i, page in enumerate(pdf.pages):
            page_num = i + 1
            text = page.extract_text() or ""
            text_lower = text.lower()

            # Look for pages with agriculture/crop content
            has_agri = any(kw in text_lower for kw in [
                "crop production", "crop output", "agricultural production",
                "area planted", "area harvested", "yield", "tonnes",
                "maize", "beans", "sorghum", "millet", "cassava"
            ])

            has_district = any(d.lower() in text_lower for d in target_districts)

            if has_agri:
                agriculture_pages.append(page_num)

            if has_agri and has_district:
                pages_checked.append(page_num)
                logger.info("Page %d: found agriculture + district keywords", page_num)

                tables = page.extract_tables()
                for table in tables:
                    if table and len(table) > 1:
                        # Check if table contains district names and crop data
                        table_text = str(table).lower()
                        if any(d.lower() in table_text for d in target_districts):
                            found_tables.append({
                                "page": page_num,
                                "rows": len(table),
                                "data": table
                            })
                            logger.info("  -> Found table with %d rows on page %d",
                                        len(table), page_num)

    # Write documentation
    os.makedirs(DOCS_DIR, exist_ok=True)
    coverage_doc_path = os.path.join(DOCS_DIR, "data_coverage.md")

    with open(coverage_doc_path, "w") as f:
        f.write("# Data Coverage Report\n\n")
        f.write("## UBOS Statistical Abstract 2023 — District-Level Crop Data Extraction\n\n")

        if found_tables:
            f.write(f"### Result: District-level crop tables FOUND\n\n")
            f.write(f"Pages with agriculture content: {agriculture_pages[:20]}...\n\n")
            f.write(f"Pages with district-level crop data: {pages_checked}\n\n")
            for t in found_tables:
                f.write(f"- Page {t['page']}: table with {t['rows']} rows\n")

            # Attempt to parse into structured format
            try:
                _parse_ubos_tables(found_tables)
                f.write("\nExtracted data saved to `data_processed/ubos_district_crops.csv`\n")
                return True
            except Exception as e:
                f.write(f"\nTable parsing failed: {e}\n")
                f.write("Falling back to FAOSTAT national data for YII.\n")
                return False
        else:
            f.write("### Result: No district-level crop production tables found\n\n")
            f.write(f"Total pages scanned: {total_pages}\n")
            f.write(f"Pages with agriculture keywords: {agriculture_pages[:20]}")
            if len(agriculture_pages) > 20:
                f.write(f"... ({len(agriculture_pages)} total)")
            f.write("\n")
            f.write(f"Pages checked for district-level data: {pages_checked if pages_checked else 'None matched criteria'}\n\n")
            f.write("The Statistical Abstract contains national-level and regional aggregates,\n")
            f.write("but no district-disaggregated crop production or yield tables were identified\n")
            f.write("for the target pilot districts (Gulu, Oyam, Arua, Nebbi, Lira).\n\n")
            f.write("**Fallback**: Using FAOSTAT national data for YII computation.\n")
            return False


def _parse_ubos_tables(found_tables):
    """Attempt to parse extracted UBOS tables into a structured CSV."""
    rows = []
    for t in found_tables:
        header = t["data"][0]
        for row in t["data"][1:]:
            if row and any(cell for cell in row if cell):
                rows.append({
                    "page": t["page"],
                    "data": row,
                    "header": header,
                })

    if rows:
        df = pd.DataFrame([{
            "district": r["data"][0] if r["data"] else None,
            "raw_data": str(r["data"]),
            "header": str(r["header"]),
            "page": r["page"],
        } for r in rows])
        os.makedirs(DATA_PROCESSED, exist_ok=True)
        df.to_csv(os.path.join(DATA_PROCESSED, "ubos_district_crops.csv"), index=False)
    else:
        raise ValueError("No parseable rows found in UBOS tables")


def build_coverage_report():
    """Build coverage_report.csv scanning all datasets."""
    os.makedirs(DATA_PROCESSED, exist_ok=True)
    records = []

    # 1. Commodity prices - northern
    prices_path = os.path.join(DATA_CLEANED, "commodity_prices_northern_uganda.csv")
    if os.path.exists(prices_path):
        df = pd.read_csv(prices_path, parse_dates=["date"])
        df["district_std"] = df["district"].map(DISTRICT_CANONICAL)

        for (district, commodity), grp in df.groupby(["district_std", "commodity"]):
            ym = grp["date"].dt.to_period("M").nunique()
            records.append({
                "dataset": "commodity_prices_northern_uganda.csv",
                "district": district if pd.notna(district) else grp["district"].iloc[0],
                "commodity": commodity,
                "date_min": grp["date"].min().strftime("%Y-%m-%d"),
                "date_max": grp["date"].max().strftime("%Y-%m-%d"),
                "n_months": ym,
                "completeness_pct": round(ym / 180 * 100, 1),  # approx 2010-2024
                "notes": "pilot_district" if district in PILOT_DISTRICTS else ""
            })

        # Check for pilot districts with no data
        districts_with_data = set(df["district_std"].dropna().unique())
        for d in PILOT_DISTRICTS:
            if d not in districts_with_data:
                records.append({
                    "dataset": "commodity_prices_northern_uganda.csv",
                    "district": d,
                    "commodity": "ALL",
                    "date_min": "",
                    "date_max": "",
                    "n_months": 0,
                    "completeness_pct": 0.0,
                    "notes": "no_price_data"
                })

    # 2. Climate data
    climate_path = os.path.join(DATA_CLEANED, "climate_data_northern_uganda.csv")
    if os.path.exists(climate_path):
        df = pd.read_csv(climate_path, parse_dates=["date"])
        df["district_std"] = df["district"].map(DISTRICT_CANONICAL)

        for district, grp in df.groupby("district_std"):
            ym = grp["date"].dt.to_period("M").nunique()
            records.append({
                "dataset": "climate_data_northern_uganda.csv",
                "district": district if pd.notna(district) else grp["district"].iloc[0],
                "commodity": "",
                "date_min": grp["date"].min().strftime("%Y-%m-%d"),
                "date_max": grp["date"].max().strftime("%Y-%m-%d"),
                "n_months": ym,
                "completeness_pct": round(ym / 180 * 100, 1),
                "notes": "pilot_district" if district in PILOT_DISTRICTS else ""
            })

    # 3. Conflict data
    conflict_path = os.path.join(DATA_CLEANED, "conflict_events_uganda.csv")
    if os.path.exists(conflict_path):
        df = pd.read_csv(conflict_path, parse_dates=["date"])
        ym = df["date"].dt.to_period("M").nunique()
        records.append({
            "dataset": "conflict_events_uganda.csv",
            "district": "national",
            "commodity": "",
            "date_min": df["date"].min().strftime("%Y-%m-%d"),
            "date_max": df["date"].max().strftime("%Y-%m-%d"),
            "n_months": ym,
            "completeness_pct": round(ym / 348 * 100, 1),  # 1997-2026
            "notes": "national_level_only"
        })

    # 4. Disaster data
    disaster_path = os.path.join(DATA_CLEANED, "disaster_shock_events_northern_uganda.csv")
    if os.path.exists(disaster_path):
        df = pd.read_csv(disaster_path, parse_dates=["date"])
        df["district_std"] = df["district"].map(DISTRICT_CANONICAL)

        for district, grp in df.groupby("district_std"):
            records.append({
                "dataset": "disaster_shock_events_northern_uganda.csv",
                "district": district if pd.notna(district) else grp["district"].iloc[0],
                "commodity": "",
                "date_min": grp["date"].min().strftime("%Y-%m-%d"),
                "date_max": grp["date"].max().strftime("%Y-%m-%d"),
                "n_months": grp["date"].dt.to_period("M").nunique(),
                "completeness_pct": "",
                "notes": "sparse_event_records"
            })

    # 5. Crop production
    crop_path = os.path.join(DATA_CLEANED, "crop_production_uganda.csv")
    if os.path.exists(crop_path):
        df = pd.read_csv(crop_path)
        for commodity, grp in df.groupby("commodity"):
            records.append({
                "dataset": "crop_production_uganda.csv",
                "district": "national",
                "commodity": commodity,
                "date_min": str(int(grp["year"].min())),
                "date_max": str(int(grp["year"].max())),
                "n_months": len(grp),
                "completeness_pct": "",
                "notes": "FAOSTAT_national_annual"
            })

    # 6. Input costs
    input_path = os.path.join(DATA_CLEANED, "input_costs_uganda.csv")
    if os.path.exists(input_path):
        df = pd.read_csv(input_path)
        records.append({
            "dataset": "input_costs_uganda.csv",
            "district": "national",
            "commodity": "",
            "date_min": str(int(df["year"].min())),
            "date_max": str(int(df["year"].max())),
            "n_months": len(df),
            "completeness_pct": "",
            "notes": "national_annual"
        })

    report = pd.DataFrame(records)
    report.to_csv(os.path.join(DATA_PROCESSED, "coverage_report.csv"), index=False)
    logger.info("Coverage report saved with %d rows", len(report))
    return report


def build_coverage_heatmap():
    """Build coverage heatmap of price data per district-commodity pair."""
    os.makedirs(CHARTS_DIR, exist_ok=True)

    prices_path = os.path.join(DATA_CLEANED, "commodity_prices_northern_uganda.csv")
    df = pd.read_csv(prices_path, parse_dates=["date"])
    df["district_std"] = df["district"].map(DISTRICT_CANONICAL)

    pivot = df.groupby(["district_std", "commodity"]).apply(
        lambda g: g["date"].dt.to_period("M").nunique()
    ).unstack(fill_value=0)

    # Mark pilot districts
    pilot_labels = []
    for d in pivot.index:
        if d in PILOT_DISTRICTS:
            pilot_labels.append(f"* {d}")
        else:
            pilot_labels.append(d)
    pivot.index = pilot_labels

    fig, ax = plt.subplots(figsize=(14, 8))
    sns.heatmap(pivot, annot=True, fmt="d", cmap="YlOrRd", ax=ax,
                linewidths=0.5, cbar_kws={"label": "Months of data"})
    ax.set_title("Price Data Coverage: Months per District-Commodity\n(* = pilot district)")
    ax.set_ylabel("District")
    ax.set_xlabel("Commodity")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(os.path.join(CHARTS_DIR, "coverage_heatmap.png"), dpi=150)
    plt.close()
    logger.info("Coverage heatmap saved")


def run_coverage_check():
    """Main entry point for Step 0."""
    logger.info("Attempting UBOS PDF extraction...")
    attempt_ubos_extraction()

    logger.info("Building coverage report...")
    report = build_coverage_report()

    logger.info("Building coverage heatmap...")
    build_coverage_heatmap()

    logger.info("Step 0 complete.")
    return report
