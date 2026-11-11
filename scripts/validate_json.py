#!/usr/bin/env python3
"""Fail closed before publishing a TGJU snapshot with wrong units/old extraction."""
import json
import math
import sys
from datetime import datetime
from pathlib import Path

p = Path(sys.argv[1] if len(sys.argv) > 1 else "build/latest.json")
obj = json.loads(p.read_text(encoding="utf-8"))
assert obj.get("ok") is True
assert obj.get("schema") == "bahabar-market-v1"
source = obj["source"]
assert source.get("name") == "TGJU"
assert source.get("extractor_version") == 2, "Old TGJU extractor is unsafe"
assert source.get("price_basis") == "visible_market_price"
assert source.get("unit") == "TOMAN"
assert datetime.fromisoformat(obj["generated_at"].replace("Z", "+00:00")).tzinfo is not None

data = obj["data"]
required = {
    "gold": ["GOLD18K", "GOLD24K", "OUNCE", "MAZANEH", "SEKE_BAHAR", "SEKE_EMAMI", "SEKE_NIM", "SEKE_ROB", "SEKE_1G"],
    "currency": ["USD", "EUR", "GBP", "AED", "TRY"],
    "crypto": ["BTC", "ETH", "USDT", "XRP"],
}
found = {key for group in ("gold", "currency", "crypto") for key in data[group]}
assert len(found) == obj["market_count"], (len(found), obj["market_count"])
assert all(set(keys).issubset(data[group]) for group, keys in required.items())
usd = float(data["currency"]["USD"]["current"])
assert 10_000 < usd < 10_000_000, usd

for group in ("gold", "currency", "crypto"):
    for key, item in data[group].items():
        current = float(item["current"])
        low = float(item["min"]["1hour"])
        high = float(item["max"]["1hour"])
        assert all(math.isfinite(x) and x > 0 for x in (current, low, high)), key
        assert low <= current <= high, (key, low, current, high)
        raw = item["source"]
        assert raw["provider"] == "tgju.org"
        assert raw["price_basis"] == "visible_market_price", key
        assert raw["raw_unit"] in {"IRR", "USD"}
        raw_num = float(raw["raw_value"])
        assert math.isfinite(raw_num) and raw_num > 0
        # Compare ALL assets, including optional currencies with app conventions
        # per 100 units, against the untouched source value.
        multiplier = float(raw.get("app_unit_multiplier", 1.0))
        assert math.isfinite(multiplier) and multiplier > 0
        expected = (raw_num / 10 if raw["raw_unit"] == "IRR" else raw_num * usd) * multiplier
        assert abs(expected - current) <= max(0.01, expected * 1e-10), (key, raw_num, expected, current)
        if group == "currency" or key in {"GOLD18K", "GOLD24K", "MAZANEH", "SEKE_BAHAR", "SEKE_EMAMI", "SEKE_NIM", "SEKE_ROB", "SEKE_1G"}:
            assert raw["raw_unit"] == "IRR", key
        if key == "OUNCE":
            assert raw["raw_unit"] == "USD", key


ratio = lambda a, b: float(a) / float(b)
assert 0.5 <= ratio(data["crypto"]["USDT"]["current"], usd) <= 1.5
assert 1.15 <= ratio(data["gold"]["GOLD24K"]["current"], data["gold"]["GOLD18K"]["current"]) <= 1.50
assert 5 <= ratio(data["gold"]["SEKE_EMAMI"]["current"], data["gold"]["GOLD18K"]["current"]) <= 40
assert 100 <= ratio(data["gold"]["OUNCE"]["current"], usd) <= 20_000
assert 1_000 <= ratio(data["crypto"]["BTC"]["current"], usd) <= 1_000_000
print(f"VALIDATED: {len(found)} TGJU markets; visible prices, units, provenance and cross-ratios OK")
