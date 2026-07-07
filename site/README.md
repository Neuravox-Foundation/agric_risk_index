# DAVARS static dashboard

A **serverless replacement** for the old Streamlit dashboard (`dashboard/app.py`).
Same five views — Overview, District Risk, Risk Breakdown, Validation, IFRAD
Bulletin — but rendered client-side with [Plotly.js](https://plotly.com/javascript/).
No Python server runs in production, so it can be hosted on Cloudflare Pages
(always-on, global CDN, free).

## Files

| File | Purpose |
|------|---------|
| `index.html` | The entire dashboard (HTML + CSS + JS in one file). |
| `data.json` | Pre-computed data bundle read by the page at load. **Generated — commit it.** |
| `build_data.py` | Reads the pipeline CSVs and writes `data.json`. |
| `_headers` | Cloudflare Pages cache rules. |

## How the data flows

```
run_pipeline.py  ->  data_processed/*.csv, outputs/**/*.csv
                     |
   python site/build_data.py   (reads those CSVs)
                     |
                 site/data.json   (committed to git)
                     |
   Cloudflare Pages serves site/ as static files
```

The dashboard does **zero** server-side computation — it only reads `data.json`.
Regenerate and commit `data.json` whenever the pipeline output changes:

```bash
python run_pipeline.py          # refresh pipeline outputs (as before)
python site/build_data.py       # rebuild data.json
git add site/data.json && git commit -m "chore: refresh dashboard data"
```

## Local preview

```bash
cd site
python3 -m http.server 8799
# open http://localhost:8799/index.html
```

## Deploy to Cloudflare Pages

1. Cloudflare dashboard → **Workers & Pages** → **Create** → **Pages** →
   **Connect to Git** → pick `Neuravox-Foundation/agric_risk_index`.
2. Build settings:
   - **Framework preset:** None
   - **Build command:** *(leave empty)* — `data.json` is committed, so no build is needed.
   - **Build output directory:** `site`
3. **Save and Deploy.** Every push to the default branch redeploys automatically.

That's it. To use a custom domain, add it under the Pages project → **Custom domains**.

### Optional: regenerate data.json at build time

If you would rather Cloudflare rebuild the data on each deploy (instead of
committing `data.json`), set:

- **Build command:** `python3 site/build_data.py`
- **Build output directory:** `site`

The Pages build image includes Python 3. Committing `data.json` (the default
above) is simpler and cannot fail a build, so prefer that unless you have a
reason not to.
