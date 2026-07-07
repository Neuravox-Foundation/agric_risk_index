# DAVARS

**District Agricultural Volatility and Adaptive Risk System**

A monthly agricultural risk index for five districts in Northern Uganda (Gulu, Arua,
Lira, Oyam, Nebbi). DAVARS combines price volatility, climate stress, production
instability, conflict and disaster shocks, and input cost pressure into a single
composite score from 0 to 100 per district-month. When the score crosses a
district-specific threshold, the month is flagged high risk: a period when deploying
growth capital into youth agribusinesses is statistically more likely to produce
income losses.

**Live dashboard: https://davars.org**

## What is in this repo

```
src/                Python pipeline that computes the index
run_pipeline.py     Entry point: runs the full pipeline end to end
data_cleaned/       Harmonized input data (prices, climate, yields, shocks, costs)
data_processed/     Pipeline output (DARS scores and sub-index scores)
outputs/            Backtests, bulletins, charts, and diagnostic reports
docs/               Methodology, data coverage, and decision protocol notes
site/               The static web dashboard (hosted on Cloudflare Pages)
tests/              Pipeline tests
```

## The index

DARS is a weighted blend of five sub-indices:

| Component | Weight | Data source | Coverage |
|-----------|:------:|-------------|----------|
| Commodity Volatility (CVI) | 25% | WFP VAM price data | Gulu, Arua, Lira only |
| Climate Stress (CSI) | 25% | NASA POWER | All districts |
| Yield Instability (YII) | 20% | FAOSTAT national crops | All districts, national signal |
| Shock Intensity (SII) | 20% | ACLED and disaster records | All districts |
| Input Cost Pressure (ICPI) | 10% | IFDC fertilizer data | All districts, national signal |

Full methodology is in [`docs/index_methodology.md`](docs/index_methodology.md).

**Limitations.** Oyam and Nebbi have no commodity price data, so their scores use four
components and are flagged `missing_price_component`. YII, ICPI, and the conflict part
of SII are national signals applied uniformly across districts. DAVARS is a prototype
volatility index; it does not measure household welfare, predict specific prices, or
replace field-level enterprise assessment.

## Running the pipeline

```bash
pip install -r requirements.txt
python run_pipeline.py
```

This reads `data_cleaned/`, writes scores to `data_processed/`, and produces the
backtests, bulletin, and reports under `outputs/`.

## The dashboard

The dashboard in `site/` is a static single-page app (HTML plus Plotly.js) with no
server. It reads a generated `site/data.json` and renders five views: Overview,
District Risk, Risk Breakdown, Validation, and IFRAD Bulletin. It supports light and
dark themes.

Regenerate the data bundle from the pipeline outputs:

```bash
python site/build_data.py     # reads the CSVs, writes site/data.json
```

Preview locally:

```bash
cd site && python3 -m http.server 8000
# open http://localhost:8000
```

See [`site/README.md`](site/README.md) for details.

## Hosting and deployment

The dashboard is hosted on **Cloudflare Pages**, connected to this repository. Every
push to `main` triggers a build that runs `python3 site/build_data.py` (regenerating
`data.json` from the committed pipeline outputs) and publishes `site/` to
`https://davars.org`. No manual data handling and no running server.

To refresh the live data: update the pipeline outputs and push. The build regenerates
`data.json` and redeploys automatically.
