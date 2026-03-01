"""DAVARS Pipeline — Main Entry Point."""
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from src.coverage_check import run_coverage_check
from src.harmonize import run_harmonize
from src.cvi import run_cvi
from src.csi import run_csi
from src.yii import run_yii
from src.sii import run_sii
from src.icpi import run_icpi
from src.dars import run_dars, run_backtest
from src.report import run_report

if __name__ == "__main__":
    logging.info("Step 0: Coverage check and UBOS extraction")
    run_coverage_check()

    logging.info("Step 1: Harmonise")
    run_harmonize()

    logging.info("Step 2: CVI")
    run_cvi()

    logging.info("Step 3: CSI")
    run_csi()

    logging.info("Step 4: YII")
    run_yii()

    logging.info("Step 5: SII")
    run_sii()

    logging.info("Step 6: ICPI")
    run_icpi()

    logging.info("Step 7: DARS")
    run_dars()

    logging.info("Step 8: Backtest")
    run_backtest()

    logging.info("Step 9: Report")
    run_report()

    logging.info("Pipeline complete. Outputs in outputs/ folder.")
