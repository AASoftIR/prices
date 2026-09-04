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
