import json
import urllib.request
import time

SOURCE_URL = f"https://fxhu.kripod.dev/api/v1/symbols/CNYHUF.json?t={int(time.time())}"

req = urllib.request.Request(
    SOURCE_URL,
    headers={
        "User-Agent": "Mozilla/5.0",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }
)

with urllib.request.urlopen(req) as response:
    raw = response.read().decode("utf-8")
    print("RAW RESPONSE:")
    print(raw[:1000])  # 先打印前1000个字符看看
    data = json.loads(raw)

dates = sorted(data.keys())
print("ALL DATES:")
print(dates)
print("LATEST DATE FROM ACTIONS:", dates[-1])

latest_date = dates[-1]
latest_value = data[latest_date]

result = {
    "date": latest_date,
    "value": latest_value
}

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"Updated data.json: {result}")
