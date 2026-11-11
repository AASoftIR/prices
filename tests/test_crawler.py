import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import tgju_crawler as crawler


def test_fixture_parsing():
    home = (ROOT / "tests/fixtures/home-mini.html").read_text(encoding="utf-8")
    parsian = (ROOT / "tests/fixtures/parsian-mini.html").read_text(encoding="utf-8")
    q = crawler.parse_homepage(home)
    q.update(crawler.parse_parsian_page(parsian))
    assert q["USD"].value == 221_060
    assert q["GOLD18K"].value == 23_518_800
    assert q["SEKE_EMAMI"].value == 234_010_000
    assert q["BTC"].value == 16_894_505_300
    assert q["ETH"].value == 523_990_140
    assert q["USDT"].value == 219_670
    assert q["SEKE_PRS100"].value == 2_105_000
    assert len(q) == 23


def test_payload_matches_bahabar_shape():
    home = (ROOT / "tests/fixtures/home-mini.html").read_text(encoding="utf-8")
    parsian = (ROOT / "tests/fixtures/parsian-mini.html").read_text(encoding="utf-8")
    q = crawler.parse_homepage(home)
    q.update(crawler.parse_parsian_page(parsian))
    state = crawler.update_state({"version": 1, "samples": {}}, q, 1_800_000_000_000)
    payload = crawler.build_payload(q, state, 1_800_000_000_000)
    assert payload["data"]["gold"]["GOLD18K"]["current"] == 23_518_800
    assert payload["data"]["currency"]["USD"]["current"] == 221_060
    assert payload["data"]["crypto"]["BTC"]["current"] == 16_894_505_300
    assert payload["market_count"] == 23


# Regression of the exact market cells extracted from the browser-saved TGJU
# page supplied on 2026-11-12. The data-price attributes are demonstrably old.
def test_real_20261112_snapshot_prefers_displayed_price():
    home = (ROOT / "tests/fixtures/tgju-20261112-visible-rows.html").read_text(encoding="utf-8")
    quotes = crawler.parse_homepage(home)
    assert len(quotes) == 34
    assert quotes["GOLD18K"].value == 25_178_700
    assert quotes["GOLD24K"].value == 33_571_200
    assert quotes["USD"].value == 264_070
    assert quotes["EUR"].value == 293_630
    assert quotes["SEKE_EMAMI"].value == 254_365_000
    assert quotes["SEKE_BAHAR"].value == 247_275_000
    assert quotes["OUNCE"].source_value == 3_986.62
    assert quotes["OUNCE"].value == 3_986.62 * 264_070
    assert quotes["BTC"].value == 19_712_096_400
    assert quotes["ETH"].value == 549_322_320
    assert quotes["USDT"].value == 264_479
    assert quotes["XRP"].value == 280_350
    assert quotes["USD"].observed_label == "۲۰ آبان"
    assert quotes["RUB"].value == 3_197  # The HTML also contains 3,122 in a commented old-day table.
    assert quotes["IQD100"].value == 16_840
    assert quotes["AMD100"].value == 73_300
    assert quotes["JPY100"].value == 165_478
    assert quotes["GOLD18K"].source_value != 249_310_000
    assert quotes["USD"].source_value != 2_599_000


def test_no_data_price_fallback_that_can_publish_old_values():
    html = '<tr data-market-row="price_dollar_rl" data-price="2599000"><th>دلار</th></tr>'
    soup = crawler.BeautifulSoup(html, "html.parser")
    assert crawler.visible_quote(soup, "price_dollar_rl") is None


def test_visible_table_beats_old_attribute_and_summary():
    html = """<div data-market-row="geram18"><div class="summary-widget-price">235,000,000</div></div>
    <tr data-market-row="geram18" data-price="249,310,000"><th>طلا ۱۸</th>
    <td class="nf">251,787,000</td><td>(0%) 0</td><td>249,328,000</td>
    <td>252,678,000</td><td>۲۰ آبان</td></tr>"""
    q = crawler.visible_quote(crawler.BeautifulSoup(html, "html.parser"), "geram18")
    assert q == (251_787_000, "IRR", "طلا ۱۸", "۲۰ آبان")


def test_crypto_usd_only_fallback_is_explicitly_converted():
    html = """<tr data-market-row="price_dollar_rl"><th>دلار</th><td>2,640,700</td></tr>
    <tr data-market-row="crypto-bitcoin" data-price="73500"><th>بیت کوین</th>
    <td class="market-price">74531.52</td><td>0%</td></tr>"""
    quotes = crawler.parse_homepage(html)
    assert quotes["BTC"].source_unit == "USD"
    assert quotes["BTC"].value == 74531.52 * 264_070


def test_refuse_two_inconsistent_visible_market_prices():
    html = """<tr data-market-row="price_dollar_rl"><th>دلار</th><td>2,640,700</td></tr>
    <tr data-market-row="price_dollar_rl"><th>دلار</th><td>3,640,700</td></tr>"""
    import pytest
    with pytest.raises(ValueError, match="Conflicting visible"):
        crawler.parse_homepage(html)


def test_provenance_marks_visible_price_basis():
    home = (ROOT / "tests/fixtures/tgju-20261112-visible-rows.html").read_text(encoding="utf-8")
    q = crawler.parse_homepage(home)
    state = crawler.update_state({"version": 1, "samples": {}}, q, 1_800_000_000_000)
    payload = crawler.build_payload(q, state, 1_800_000_000_000)
    assert payload["source"]["extractor_version"] == 2
    assert payload["source"]["unit"] == "TOMAN"
    assert payload["data"]["currency"]["USD"]["source"]["observed_label"] == "۲۰ آبان"
