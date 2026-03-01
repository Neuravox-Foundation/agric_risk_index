"""DAVARS Prototype Configuration"""
import os

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_CLEANED = os.path.join(BASE_DIR, "data_cleaned")
DATA_PROCESSED = os.path.join(BASE_DIR, "data_processed")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
CHARTS_DIR = os.path.join(OUTPUTS_DIR, "charts")
REPORTS_DIR = os.path.join(OUTPUTS_DIR, "reports")
BULLETINS_DIR = os.path.join(OUTPUTS_DIR, "bulletins")
DOCS_DIR = os.path.join(BASE_DIR, "docs")

PILOT_DISTRICTS = ["Gulu", "Arua", "Lira", "Oyam", "Nebbi"]

PRICE_DISTRICTS = ["Gulu", "Arua", "Lira"]
NO_PRICE_DISTRICTS = ["Oyam", "Nebbi"]

# Minimum months required for a commodity-district to enter CVI scoring
# Set to 36 to exclude short Arua series and prevent normalisation instability
MIN_MONTHS_FOR_CVI = 36

COMMODITY_CANONICAL = {
    "Maize": "Maize",
    "Maize (white)": "Maize",
    "Maize flour": "Maize flour",
    "Beans": "Beans",
    "Sorghum": "Sorghum",
    "Millet": "Millet",
    "Cassava (fresh)": "Cassava",
    "Cassava flour": "Cassava flour",
}

DATE_START = "2010-01-01"
DATE_END = "2024-12-01"

COMPONENT_WEIGHTS = {
    "CVI": 0.25,
    "CSI": 0.25,
    "YII": 0.20,
    "SII": 0.20,
    "ICPI": 0.10,
}

HIGH_RISK_PERCENTILE = 75

# Backtesting reference events — all within 2010–2024 master panel window
KNOWN_SHOCK_EVENTS = [
    {"label": "2016-2017_drought", "year_start": 2016, "month_start": 6, "year_end": 2017, "month_end": 12},
    {"label": "2020_COVID_disruption", "year_start": 2020, "month_start": 3, "year_end": 2021, "month_end": 6},
    {"label": "2022-2023_inflation_shock", "year_start": 2022, "month_start": 1, "year_end": 2023, "month_end": 6},
]

# District canonical mapping
DISTRICT_CANONICAL = {
    "gulu": "Gulu", "Gulu": "Gulu", "GULU": "Gulu",
    "lira": "Lira", "Lira": "Lira", "LIRA": "Lira",
    "arua": "Arua", "Arua": "Arua", "ARUA": "Arua",
    "oyam": "Oyam", "Oyam": "Oyam", "OYAM": "Oyam",
    "nebbi": "Nebbi", "Nebbi": "Nebbi", "NEBBI": "Nebbi",
    "adjumani": "Adjumani", "Adjumani": "Adjumani",
}
