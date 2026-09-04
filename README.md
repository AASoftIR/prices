# BahaBar TGJU crawler — test bridge

This repository/workflow is intentionally **separate from the Android changes**. It lets you prove the TGJU feed first, then point the already-built BahaBar APK at it from **Settings → HTTPS API**.

## What it does

- Crawls `https://www.tgju.org/` every 5 minutes.
- Also crawls TGJU's Parsian-coin page for the 100/200/400/500/700 sot entries.
- Parses the exact `data-market-row` / `summary-widget` structures found in the saved HTML supplied with BahaBar.
- Uses normal HTTP first and `curl_cffi` Chrome TLS impersonation as a fallback for CDN/anti-bot differences on GitHub-hosted runners.
- Normalizes Iranian prices from **rial → toman**.
- Converts ounce to toman with the scraped USD rate.
- Uses TGJU's IRR crypto column so BTC/ETH/USDT/XRP are also stored in toman, which matches BahaBar's existing formatter.
- Maintains a rolling 1-hour sample state and emits real `min.1hour` / `max.1hour` values.
- Refuses to publish if any of the 18 core markets disappear or numeric sanity checks fail.
- On a bad TGJU response, the previous good `market-data` branch stays untouched.
- Publishes to a force-updated `market-data` branch with only one snapshot commit, avoiding hundreds of permanent commits per day.

## Output schema

The important part is that `data/latest.json` matches the JSON shape the current BahaBar `BahaApiClient` already expects:

```json
{
  "data": {
    "gold": {
      "GOLD18K": {
        "current": 23518800,
        "min": { "1hour": 23518800 },
        "max": { "1hour": 23518800 }
      }
    },
    "currency": {
      "USD": { "current": 221060, "min": {"1hour": 221060}, "max": {"1hour": 221060} }
    },
    "crypto": {
      "BTC": { "current": 16894505300, "min": {"1hour": 16894505300}, "max": {"1hour": 16894505300} }
    }
  }
}
```

Extra metadata is present but ignored safely by the current Android parser.

## GitHub setup

1. Copy these files into a **public GitHub repository** (a dedicated small repo is ideal for the test).
2. Push to the default branch.
3. Open **Actions → Update TGJU market data → Run workflow**.
4. After it succeeds, a `market-data` branch is created automatically.
5. Your feed becomes:

```text
https://raw.githubusercontent.com/OWNER/REPOSITORY/market-data/data/latest.json
```

6. In the already-built BahaBar app, go to **Settings → HTTPS API**, paste that URL, then press **Save & test**.

No Android rebuild is needed for this first test.

> Important: GitHub Actions officially supports a minimum scheduled interval of **5 minutes**, not every 1 minute. Scheduled jobs can also start late during GitHub load; this is not a real-time scheduler.

## Local fixture test

```bash
python -m pip install -r requirements.txt pytest
pytest -q
python scripts/tgju_crawler.py \
  --home-fixture tests/fixtures/home-mini.html \
  --parsian-fixture tests/fixtures/parsian-mini.html \
  --output build/latest.json \
  --state-out build/history.json \
  --health build/health.json
python scripts/validate_json.py build/latest.json
```

To test against your browser-saved TGJU homepage, replace `--home-fixture` with the path to the saved `.html` file.

## Failure behavior

If TGJU returns 403/429/503, a Cloudflare challenge, or the page layout changes enough that core values cannot be parsed:

- the workflow fails;
- diagnostics are uploaded as a GitHub Actions artifact;
- **the last good `market-data/data/latest.json` remains online**;
- the app keeps reading the last valid snapshot instead of a broken/empty response.

This is deliberate fail-safe behavior.
