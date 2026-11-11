# TGJU GitHub crawler — visible price fix

This is the corrected crawler paired with BahaBar Android 4.5.1.

## Root cause

The original crawler sometimes read the `data-price` attribute, which did not match the visible market price in the user's saved TGJU homepage. For example, USD `data-price` was 2,599,000 IRR, but the visible market table had **2,640,700 IRR** (264,070 toman). Gold 18K and Emami coin had the same mismatch.

**The fixed crawler never uses `data-price` to obtain a current quotation.** It prioritizes visible table cells, extracts the IRR crypto column explicitly, normalizes all domestic values from rial to toman, and records the visible time label for transparency. The emitted feed is marked `extractor_version: 2`, `price_basis: visible_market_price`, `unit: TOMAN`.

The 2026-11-12 supplied HTML also contains commented-out historical rows; BeautifulSoup ignores them. Kotlin's direct-HTML parser must strip comments explicitly and has a matching regression test.

## Source and output

- GitHub Actions fetches `https://www.tgju.org/` on its scheduled runs, with a safe failure mode.
- 18 core markets are required. 16 more currencies appear in the supplied homepage and are included when present. Optional Parsian coins continue to use their separate site page (up to five additional markets).
- No prices are synthesized for unavailable markets, notably USD Istanbul.
- The existing market-data branch and raw JSON URL remain unchanged.
- The unit of every `current` field is **toman**. The untouched `raw_value`, `raw_unit`, `observed_label`, and any app unit multiplier are retained in each record's `source` metadata.
- If the HTML changes, the test/validator fails and the last successful published GitHub snapshot is left intact. The Android app still verifies snapshot age and may switch to backup when the latest file is stale.

## Local regression

```sh
python -m pip install -r requirements.txt pytest
pytest -q
python scripts/tgju_crawler.py \
  --home-fixture tests/fixtures/tgju-20261112-visible-rows.html \
  --skip-parsian \
  --output build/latest.json \
  --state-out build/history.json \
  --health build/health.json
python scripts/validate_json.py build/latest.json
```

In the fixture the corrected output is **USD 264,070**, **18K gold 25,178,700**, **Emami 254,365,000**, and **BTC 19,712,096,400** toman. These are captured historical figures, not live November 2026 prices. The workflow also runs the same historical regression before every real crawl.

## Deploy

Replace the files in your existing `AASoftIR/prices` repo on its default branch, including `.github/workflows/update-tgju-prices.yml`. **Do not replace its `.git` directory.** Run Actions → Update TGJU market data → Run workflow. After success, inspect:

`https://raw.githubusercontent.com/AASoftIR/prices/market-data/data/latest.json`

Note: the crawl timestamp describes when a snapshot was taken, **not** necessarily when the last trade happened. Check `data.<group>.<symbol>.source.observed_label`.
