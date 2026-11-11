#!/usr/bin/env python3
"""TGJU -> BahaBar JSON bridge.

The output deliberately matches the JSON shape already consumed by BahaBar's
BahaApiClient, so the current APK can be tested by pasting the raw GitHub URL
into Settings -> HTTPS API. No Android source change is required for this test.

Values exposed to BahaBar are normalized to TOMAN. TGJU's domestic tables are
published in IRR (rial), therefore they are divided by 10. Ounce and crypto
USD-only fallbacks are converted using the scraped USD/IRR rate.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple
from urllib.parse import quote

from bs4 import BeautifulSoup

HOME_URL = "https://www.tgju.org/"
PARSIAN_URL = "https://www.tgju.org/" + quote("قیمت-سکه-پارسیان")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 "
    "BahaBar-TGJU-Bridge/1.0"
)

# API key -> TGJU row slug. All except the parsian variants are on the homepage.
MARKETS = {
    "gold": {
        "GOLD18K": ("geram18", "irr"),
        "GOLD24K": ("geram24", "irr"),
        "OUNCE": ("ons", "usd"),
        "MAZANEH": ("mesghal", "irr"),
        "SEKE_BAHAR": ("sekeb", "irr"),
        "SEKE_EMAMI": ("sekee", "irr"),
        "SEKE_NIM": ("nim", "irr"),
        "SEKE_ROB": ("rob", "irr"),
        "SEKE_1G": ("gerami", "irr"),
    },
    "currency": {
        "USD": ("price_dollar_rl", "irr"),
        "EUR": ("price_eur", "irr"),
        "GBP": ("price_gbp", "irr"),
        "AED": ("price_aed", "irr"),
        "TRY": ("price_try", "irr"),
    },
    "crypto": {
        "BTC": ("crypto-bitcoin", "crypto_irr"),
        "ETH": ("crypto-ethereum", "crypto_irr"),
        "USDT": ("crypto-tether", "crypto_irr"),
        "XRP": ("crypto-ripple", "crypto_irr"),
    },
}


# Additional BahaBar currencies actually present in the supplied TGJU HTML.
# IQD and AMD are quoted per ONE unit on TGJU but per 100 in BahaBar.
# TGJU's JPY table price already represents 100 JPY (confirmed by USD/JPY scale).
# USD_IST does not appear on the supplied page; never invent its value.
EXTRA_CURRENCIES = {
    "CNY": ("price_cny", 1.0),
    "CAD": ("price_cad", 1.0),
    "AUD": ("price_aud", 1.0),
    "RUB": ("price_rub", 1.0),
    "AFN": ("price_afn", 1.0),
    "CHF": ("price_chf", 1.0),
    "SAR": ("price_sar", 1.0),
    "OMR": ("price_omr", 1.0),
    "INR": ("price_inr", 1.0),
    "JPY100": ("price_jpy", 1.0),
    "IQD100": ("price_iqd", 100.0),
    "MYR": ("price_myr", 1.0),
    "GEL": ("price_gel", 1.0),
    "AZN": ("price_azn", 1.0),
    "AMD100": ("price_amd", 100.0),
    "THB": ("price_thb", 1.0),
}

PARSIAN_MARKETS = {
    "SEKE_PRS100": "0/100",
    "SEKE_PRS200": "0/200",
    "SEKE_PRS400": "0/400",
    "SEKE_PRS500": "0/500",
    "SEKE_PRS700": "0/700",
}

CORE_KEYS = {
    "GOLD18K", "GOLD24K", "OUNCE", "MAZANEH",
    "SEKE_BAHAR", "SEKE_EMAMI", "SEKE_NIM", "SEKE_ROB", "SEKE_1G",
    "USD", "EUR", "GBP", "AED", "TRY",
    "BTC", "ETH", "USDT", "XRP",
}

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


@dataclass(frozen=True)
class RawQuote:
    value: float
    source_value: float
    source_unit: str
    label: str = ""
    observed_label: str = ""
    app_unit_multiplier: float = 1.0


def normalize_digits(text: str) -> str:
    return text.translate(PERSIAN_DIGITS).translate(ARABIC_DIGITS)


def number(text: object) -> Optional[float]:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        value = float(text)
        return value if math.isfinite(value) else None
    s = normalize_digits(str(text))
    s = s.replace("٬", "").replace(",", "").replace(" ", "")
    s = s.replace("٫", ".").replace("−", "-")
    # Keep only the first numeric token; this avoids percentages/timestamps.
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        value = float(m.group(0))
        return value if math.isfinite(value) else None
    except ValueError:
        return None


def text_of(node) -> str:
    return " ".join(node.stripped_strings) if node else ""


def candidate_rows(soup: BeautifulSoup, slug: str):
    """A slug appears in multiple widgets AND tables; never treat data-price as current."""
    return soup.select(f'[data-market-row="{slug}"]')


def visible_cells(row):
    """Only directly rendered table cells represent TGJU's current quotation."""
    return row.find_all("td", recursive=False) if row.name == "tr" else []


def quote_time(row, cells) -> str:
    node = row.select_one(".market-time")
    if node is not None:
        return text_of(node)
    if len(cells) >= 5:
        return text_of(cells[4])
    return ""


def visible_quote(soup: BeautifulSoup, slug: str, *, crypto: bool = False) -> Optional[Tuple[float, str, str, str]]:
    """Read *visible* prices, with an explicit unit. Never read data-price.

    TGJU's data-price attribute is used by chart/transition code and can be the
    previous value. For example the Nov-12 snapshot shows 2,599,000 in that
    attribute for USD, while the visible market-price is 2,640,700 IRR.

    Crypto tables have TWO independent prices: IRR in .market-price-irr and
    USD in .market-price. Picking td[0] from the USD-only row is an error.
    """
    candidates = []
    for row in candidate_rows(soup, slug):
        cells = visible_cells(row)
        label = text_of(row.find("th")) or text_of(row.select_one(".summary-widget-title"))
        if crypto:
            if cells:
                irr_node = row.select_one("td.market-price-irr")
                if irr_node is not None:
                    raw = number(text_of(irr_node))
                    if raw and raw > 0:
                        candidates.append((100, raw, "IRR", label, quote_time(row, cells)))
                        continue
                # Older TGJU tables may have unlabeled, enriched rows. Distinguish
                # these by empty data-price and the presence of >=6 columns, not
                # by arbitrary magnitude thresholds (which fail for cheap crypto).
                if len(cells) >= 6 and not str(row.get("data-price") or "").strip():
                    raw = number(text_of(cells[0]))
                    if raw and raw > 0:
                        candidates.append((90, raw, "IRR", label, quote_time(row, cells)))
                        continue
                usd_node = row.select_one('td[data-market-name="p"], td.market-price')
                if usd_node is None and cells:
                    usd_node = cells[0]
                raw = number(text_of(usd_node)) if usd_node else None
                if raw and raw > 0:
                    candidates.append((10, raw, "USD", label, quote_time(row, cells)))
            continue

        if cells:
            # A table's .market-price is preferred; other tables put the
            # displayed current price in their first TD (often class="nf").
            node = row.select_one('td[data-market-name="p"], td.market-price') or cells[0]
            raw = number(text_of(node))
            if raw and raw > 0:
                candidates.append((100, raw, "USD" if slug == "ons" else "IRR", label, quote_time(row, cells)))
        else:
            # Summary cards may be the only representation of a market.
            node = row.select_one('[data-market-name="p"], .summary-widget-price')
            raw = number(text_of(node)) if node else None
            if raw and raw > 0:
                candidates.append((20, raw, "USD" if slug == "ons" else "IRR", label, ""))

    if not candidates:
        return None
    # Prefer the precise market table over summary cards, irrespective of DOM
    # order. Ambiguous rows at equal priority must agree within 2%.
    priority = max(x[0] for x in candidates)
    best = [x for x in candidates if x[0] == priority]
    if len({x[2] for x in best}) != 1:
        raise ValueError(f"Mixed price units in visible TGJU rows for {slug}")
    low, high = min(x[1] for x in best), max(x[1] for x in best)
    if high / low > 1.02:
        raise ValueError(f"Conflicting visible TGJU quotes for {slug}: {low} .. {high}")
    _, raw, unit, label, observed = best[0]
    return raw, unit, label, observed


def parse_domestic_irr(soup: BeautifulSoup, slug: str) -> Optional[Tuple[float, str]]:
    quote = visible_quote(soup, slug)
    if quote is None:
        return None
    value, unit, label, _ = quote
    if unit != "IRR":
        raise ValueError(f"{slug} must be IRR, got {unit}")
    return value, label


def parse_usd_value(soup: BeautifulSoup, slug: str) -> Optional[Tuple[float, str]]:
    quote = visible_quote(soup, slug)
    if quote is None:
        return None
    value, unit, label, _ = quote
    if unit != "USD":
        raise ValueError(f"{slug} must be USD, got {unit}")
    return value, label


def parse_crypto_irr(soup: BeautifulSoup, slug: str) -> Optional[Tuple[float, str]]:
    """Compatibility wrapper; main parser uses explicit currency tagging."""
    quote = visible_quote(soup, slug, crypto=True)
    return (quote[0], quote[2]) if quote else None


def parse_parsian_page(html: str) -> Dict[str, RawQuote]:
    soup = BeautifulSoup(html, "html.parser")
    result: Dict[str, RawQuote] = {}
    targets = {k: normalize_digits(v) for k, v in PARSIAN_MARKETS.items()}

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label = normalize_digits(text_of(cells[0])).replace("۰", "0")
        compact = re.sub(r"\s+", "", label)
        if "پارسیان" not in label:
            continue
        current = number(text_of(cells[1]))
        if not current or current <= 0:
            continue
        for api_key, target in targets.items():
            if target in compact and api_key not in result:
                result[api_key] = RawQuote(
                    value=current / 10.0,
                    source_value=current,
                    source_unit="IRR",
                    label=text_of(cells[0]),
                )
    return result


def parse_homepage(html: str) -> Dict[str, RawQuote]:
    soup = BeautifulSoup(html, "html.parser")
    usd_quote = visible_quote(soup, "price_dollar_rl")
    if not usd_quote or usd_quote[1] != "IRR":
        raise ValueError("Could not find a displayed TGJU USD/IRR quote")
    usd_toman = usd_quote[0] / 10.0

    result: Dict[str, RawQuote] = {}
    for group, entries in MARKETS.items():
        for api_key, (slug, mode) in entries.items():
            parsed = visible_quote(soup, slug, crypto=mode == "crypto_irr")
            if not parsed:
                continue
            raw, unit, label, observed = parsed
            if mode == "irr" and unit != "IRR":
                raise ValueError(f"{slug}: expected IRR price, received {unit}")
            if mode == "usd" and unit != "USD":
                raise ValueError(f"{slug}: expected USD price, received {unit}")
            value = raw / 10.0 if unit == "IRR" else raw * usd_toman
            result[api_key] = RawQuote(value, raw, unit, label, observed)
    for api_key, (slug, multiplier) in EXTRA_CURRENCIES.items():
        parsed = visible_quote(soup, slug)
        if parsed is None:
            continue
        raw, unit, label, observed = parsed
        if unit != "IRR":
            raise ValueError(f"{slug}: expected IRR, got {unit}")
        result[api_key] = RawQuote(raw / 10.0 * multiplier, raw, "IRR", label, observed, multiplier)
    return result



def load_state(path: Optional[Path]) -> dict:
    if not path or not path.exists():
        return {"version": 1, "samples": {}}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict) or not isinstance(obj.get("samples"), dict):
            raise ValueError("bad state")
        return obj
    except Exception:
        return {"version": 1, "samples": {}}


def update_state(state: dict, quotes: Dict[str, RawQuote], now_ms: int) -> dict:
    cutoff = now_ms - 60 * 60 * 1000
    samples = state.setdefault("samples", {})
    for key, quote in quotes.items():
        series = samples.get(key, [])
        kept = []
        for item in series:
            try:
                ts = int(item[0]); val = float(item[1])
            except Exception:
                continue
            if ts >= cutoff and math.isfinite(val) and val > 0:
                kept.append([ts, val])
        # Coalesce if Actions is re-run within ~30 seconds with the same value.
        if not kept or now_ms - kept[-1][0] >= 30_000 or kept[-1][1] != quote.value:
            kept.append([now_ms, quote.value])
        samples[key] = kept[-20:]  # 5-minute schedule => <=13/h; keep a little margin.
    # Drop extinct keys after pruning.
    for key in list(samples):
        samples[key] = [x for x in samples[key] if int(x[0]) >= cutoff]
        if not samples[key]:
            samples.pop(key, None)
    state["updated_at"] = datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat()
    return state


def rolling_range(state: dict, key: str, current: float) -> Tuple[float, float]:
    vals = []
    for item in state.get("samples", {}).get(key, []):
        try:
            v = float(item[1])
            if math.isfinite(v) and v > 0:
                vals.append(v)
        except Exception:
            pass
    vals.append(current)
    return min(vals), max(vals)


def build_payload(quotes: Dict[str, RawQuote], state: dict, now_ms: int) -> dict:
    api_group_for_key = {}
    for group, entries in MARKETS.items():
        for key in entries:
            api_group_for_key[key] = group
    for key in PARSIAN_MARKETS:
        api_group_for_key[key] = "gold"
    for key in EXTRA_CURRENCIES:
        api_group_for_key[key] = "currency"

    data = {"date": datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat(),
            "gold": {}, "currency": {}, "crypto": {}}

    for key, q in sorted(quotes.items()):
        group = api_group_for_key.get(key)
        if not group:
            continue
        low, high = rolling_range(state, key, q.value)
        data[group][key] = {
            "current": round(q.value, 8),
            "min": {"1hour": round(low, 8)},
            "max": {"1hour": round(high, 8)},
            "source": {
                "provider": "tgju.org",
                "raw_value": round(q.source_value, 8),
                "raw_unit": q.source_unit,
                "label": q.label,
                "observed_label": q.observed_label or None,
                "price_basis": "visible_market_price",
                "app_unit_multiplier": q.app_unit_multiplier,
            },
        }

    found = {k for group in ("gold", "currency", "crypto") for k in data[group]}
    missing_core = sorted(CORE_KEYS - found)
    if missing_core:
        raise ValueError("Missing core markets: " + ", ".join(missing_core))

    return {
        "ok": True,
        "schema": "bahabar-market-v1",
        "generated_at": data["date"],
        "source": {
            "name": "TGJU",
            "url": HOME_URL,
            "attribution": "Prices scraped from public TGJU pages",
            "extractor_version": 2,
            "price_basis": "visible_market_price",
            "unit": "TOMAN",
            "sampled_at": data["date"],
        },
        "market_count": len(found),
        "data": data,
    }


def fetch_html(url: str, timeout: int = 25) -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.7,en;q=0.6",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "DNT": "1",
    }
    errors = []

    # Fast/normal path.
    try:
        import requests
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if r.status_code == 200 and len(r.text) > 10_000:
            return r.text
        errors.append(f"requests HTTP {r.status_code}, {len(r.content)} bytes")
    except Exception as exc:
        errors.append(f"requests: {exc}")

    # Browser-TLS fallback for anti-bot/CDN differences seen from datacenter IPs.
    try:
        from curl_cffi import requests as cffi_requests
        for attempt in range(3):
            try:
                r = cffi_requests.get(
                    url,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=True,
                    impersonate="chrome",
                )
                if r.status_code == 200 and len(r.text) > 10_000:
                    return r.text
                errors.append(f"curl_cffi HTTP {r.status_code}, {len(r.content)} bytes")
            except Exception as exc:
                errors.append(f"curl_cffi attempt {attempt + 1}: {exc}")
            time.sleep(2 ** attempt)
    except Exception as exc:
        errors.append(f"curl_cffi import/use: {exc}")

    raise RuntimeError(f"Failed to fetch {url}: " + " | ".join(errors))


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("build/latest.json"))
    ap.add_argument("--health", type=Path, default=Path("build/health.json"))
    ap.add_argument("--state-in", type=Path)
    ap.add_argument("--state-out", type=Path, default=Path("build/history.json"))
    ap.add_argument("--home-fixture", type=Path, help="Parse a saved TGJU homepage instead of the network")
    ap.add_argument("--parsian-fixture", type=Path, help="Optional saved Parsian page")
    ap.add_argument("--skip-parsian", action="store_true")
    args = ap.parse_args()

    now_ms = int(time.time() * 1000)
    started = time.monotonic()

    try:
        if args.home_fixture:
            home_html = args.home_fixture.read_text(encoding="utf-8", errors="ignore")
        else:
            home_html = fetch_html(HOME_URL)

        quotes = parse_homepage(home_html)
        parsian_error = None
        if not args.skip_parsian:
            try:
                if args.parsian_fixture:
                    parsian_html = args.parsian_fixture.read_text(encoding="utf-8", errors="ignore")
                elif args.home_fixture:
                    # Offline fixture mode: don't unexpectedly access network.
                    parsian_html = ""
                else:
                    parsian_html = fetch_html(PARSIAN_URL)
                if parsian_html:
                    quotes.update(parse_parsian_page(parsian_html))
            except Exception as exc:
                # Parsian coins are useful but not allowed to take down the primary feed.
                parsian_error = str(exc)

        state = update_state(load_state(args.state_in), quotes, now_ms)
        payload = build_payload(quotes, state, now_ms)
        write_json(args.output, payload)
        write_json(args.state_out, state)

        health = {
            "ok": True,
            "generated_at": payload["generated_at"],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "market_count": payload["market_count"],
            "expected_market_count": 23,
            "parsian_error": parsian_error,
            "source": HOME_URL,
            "extractor_version": 2,
            "price_basis": "visible_market_price",
        }
        write_json(args.health, health)

        data = payload["data"]
        print(f"OK: {payload['market_count']} markets")
        print(f"USD: {data['currency']['USD']['current']:,.0f} toman")
        print(f"Gold 18K: {data['gold']['GOLD18K']['current']:,.0f} toman")
        print(f"Emami: {data['gold']['SEKE_EMAMI']['current']:,.0f} toman")
        print(f"BTC: {data['crypto']['BTC']['current']:,.0f} toman")
        if parsian_error:
            print(f"WARNING: Parsian page unavailable: {parsian_error}", file=sys.stderr)
        return 0
    except Exception as exc:
        write_json(args.health, {
            "ok": False,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "error": str(exc),
            "source": HOME_URL,
        })
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
