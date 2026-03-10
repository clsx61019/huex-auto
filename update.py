import json
import urllib.request

SOURCE_URL = "https://fxhu.kripod.dev/api/v1/symbols/CNYHUF.json"

with urllib.request.urlopen(SOURCE_URL) as response:
    data = json.load(response)

latest_date = sorted(data.keys())[-1]
latest_value = data[latest_date]

result = {
    "date": latest_date,
    "value": latest_value
}

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"Updated data.json: {result}")
