#!/usr/bin/env python3
import json, math, sys
from pathlib import Path

p = Path(sys.argv[1] if len(sys.argv) > 1 else "build/latest.json")
obj = json.loads(p.read_text(encoding="utf-8"))
assert obj.get("ok") is True
assert obj.get("schema") == "bahabar-market-v1"
data = obj["data"]
required = {
    "gold": ["GOLD18K", "GOLD24K", "OUNCE", "MAZANEH", "SEKE_BAHAR", "SEKE_EMAMI", "SEKE_NIM", "SEKE_ROB", "SEKE_1G"],
    "currency": ["USD", "EUR", "GBP", "AED", "TRY"],
    "crypto": ["BTC", "ETH", "USDT", "XRP"],
}
for group, keys in required.items():
    for key in keys:
        item = data[group][key]
        current = float(item["current"])
        low = float(item["min"]["1hour"])
        high = float(item["max"]["1hour"])
        assert math.isfinite(current) and current > 0, (group, key, current)
        assert 0 < low <= current <= high, (group, key, low, current, high)
# Sanity relationships catch accidental Rial/Toman or USD-column parsing mistakes.
usd = float(data["currency"]["USD"]["current"])
gold = float(data["gold"]["GOLD18K"]["current"])
btc = float(data["crypto"]["BTC"]["current"])
usdt = float(data["crypto"]["USDT"]["current"])
assert 10_000 < usd < 10_000_000, usd
assert 1_000_000 < gold < 1_000_000_000, gold
assert btc > usd * 1_000, (btc, usd)
assert 0.5 * usd < usdt < 1.5 * usd, (usdt, usd)
print(f"VALID: {obj['market_count']} markets, generated {obj['generated_at']}")
