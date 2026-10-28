"""把匈牙利央行（MNB）公布的 CNY→HUF 官方汇率同步到简道云「辅助：历史汇率」表。

每次运行都会：
  1. 从 MNB 官网接口取 START_DATE 至今的全部汇率（失败时改用 fxhu 镜像）；
  2. 读出简道云表里已有的全部日期；
  3. 把缺的日期补进去（所以哪天没跑成功，下一次运行会自动补上）；
  4. 再读一遍简道云核对，仍有缺失则让任务失败（GitHub 会发邮件提醒）；
  5. 把最新一天写进 data.json。

环境变量：
  JDY_API_KEY   简道云开放平台 API Key（必填，DRY_RUN 时可不填）
  JDY_APP_ID    应用 ID，默认「签证管理」
  JDY_ENTRY_ID  表单 ID，默认「辅助：历史汇率」
  START_DATE    从哪天开始核对，默认 2025-01-01
  DRY_RUN       设为 1 时只打印要补的数据，不写简道云
"""

import datetime as dt
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

JDY_API = "https://api.jiandaoyun.com/api/v5/app/entry/data"
JDY_APP_ID = os.environ.get("JDY_APP_ID") or "67501067fec27368c50bdf57"
JDY_ENTRY_ID = os.environ.get("JDY_ENTRY_ID") or "69cd0a2a40748297894ff83a"
FIELD_DATE = "_widget_1775045148282"
FIELD_RATE = "_widget_1775045148283"
# 简道云里已有的日期都按 UTC+2 的零点存储（例如 2026-10-27 存成 2026-10-26T22:00:00Z），保持一致
JDY_TZ = dt.timezone(dt.timedelta(hours=2))

START_DATE = os.environ.get("START_DATE") or "2025-01-01"
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
# 最新官方汇率超过这么多天没更新，就认为数据源出了问题
MAX_STALE_DAYS = 10

MNB_URL = "http://www.mnb.hu/arfolyamok.asmx"
FXHU_URL = "https://fxhu.kripod.dev/api/v1/symbols/CNYHUF.json"


def http(url, body=None, headers=None, attempts=4, timeout=60):
    """带重试的 HTTP 请求，返回响应文本。4xx（429 除外）不重试。"""
    data = body.encode("utf-8") if isinstance(body, str) else body
    for i in range(attempts):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            if (400 <= e.code < 500 and e.code != 429) or i == attempts - 1:
                raise RuntimeError(f"HTTP {e.code} {url}: {detail}") from e
            print(f"  HTTP {e.code}，{2 ** (i + 1)} 秒后重试：{detail}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if i == attempts - 1:
                raise RuntimeError(f"请求失败 {url}: {e}") from e
            print(f"  网络错误，{2 ** (i + 1)} 秒后重试：{e}")
        time.sleep(2 ** (i + 1))


def fetch_mnb(start, end):
    """MNB 官方 SOAP 接口，返回 {"YYYY-MM-DD": 每 1 CNY 的 HUF}。"""
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
        '<GetExchangeRates xmlns="http://www.mnb.hu/webservices/">'
        f"<startDate>{start}</startDate><endDate>{end}</endDate>"
        "<currencyNames>CNY</currencyNames>"
        "</GetExchangeRates></soap:Body></soap:Envelope>"
    )
    raw = http(
        MNB_URL,
        envelope,
        {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"http://www.mnb.hu/webservices/MNBArfolyamServiceSoap/GetExchangeRates"',
        },
    )
    result = ET.fromstring(raw).find(".//{http://www.mnb.hu/webservices/}GetExchangeRatesResult")
    if result is None or not result.text:
        raise RuntimeError(f"MNB 返回内容无法解析：{raw[:300]}")
    rates = {}
    for day in ET.fromstring(html.unescape(result.text)).iter("Day"):
        for rate in day.iter("Rate"):
            if rate.get("curr") == "CNY" and rate.text:
                unit = int(rate.get("unit") or 1)
                rates[day.get("date")] = round(float(rate.text.replace(",", ".")) / unit, 6)
    return rates


def fetch_fxhu(start):
    """备用数据源：fxhu.kripod.dev（MNB 数据的镜像）。"""
    data = json.loads(http(FXHU_URL, headers={"User-Agent": "huex-auto"}))
    return {d: float(v) for d, v in data.items() if d >= start}


def fetch_official_rates(start, end):
    try:
        rates = fetch_mnb(start, end)
        if rates:
            print(f"MNB 官网：取到 {len(rates)} 天汇率")
            return rates
        print("MNB 官网返回空数据，改用 fxhu 镜像")
    except Exception as e:  # noqa: BLE001 - 任何错误都切换到备用源
        print(f"MNB 官网获取失败（{e}），改用 fxhu 镜像")
    rates = fetch_fxhu(start)
    print(f"fxhu 镜像：取到 {len(rates)} 天汇率")
    return rates


def jdy_post(path, payload):
    key = os.environ.get("JDY_API_KEY")
    if not key:
        raise RuntimeError("缺少环境变量 JDY_API_KEY")
    raw = http(
        f"{JDY_API}/{path}",
        json.dumps(payload),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    return json.loads(raw)


def to_jdy_datetime(day):
    local = dt.datetime.fromisoformat(day).replace(tzinfo=JDY_TZ)
    return local.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def from_jdy_datetime(value):
    utc = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return utc.astimezone(JDY_TZ).date().isoformat()


def list_jdy_records():
    """读出表里全部记录，返回 {日期: [(data_id, 汇率), ...]}。"""
    records, cursor = {}, None
    while True:
        payload = {
            "app_id": JDY_APP_ID,
            "entry_id": JDY_ENTRY_ID,
            "fields": [FIELD_DATE, FIELD_RATE],
            "limit": 100,
        }
        if cursor:
            payload["data_id"] = cursor
        page = jdy_post("list", payload).get("data", [])
        for row in page:
            if row.get(FIELD_DATE):
                day = from_jdy_datetime(row[FIELD_DATE])
                records.setdefault(day, []).append((row["_id"], row.get(FIELD_RATE)))
        if len(page) < 100:
            return records
        cursor = page[-1]["_id"]


def create_jdy_records(rows):
    for i in range(0, len(rows), 100):
        chunk = rows[i : i + 100]
        resp = jdy_post(
            "batch_create",
            {
                "app_id": JDY_APP_ID,
                "entry_id": JDY_ENTRY_ID,
                "data_list": [
                    {FIELD_DATE: {"value": to_jdy_datetime(d)}, FIELD_RATE: {"value": v}}
                    for d, v in chunk
                ],
            },
        )
        print(f"  已写入 {resp.get('success_count', '?')}/{len(chunk)} 条")


def write_summary(lines):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def main():
    today = dt.datetime.now(JDY_TZ).date()
    rates = fetch_official_rates(START_DATE, today.isoformat())
    if not rates:
        raise RuntimeError("两个数据源都没有取到汇率")

    latest = max(rates)
    stale_days = (today - dt.date.fromisoformat(latest)).days
    print(f"官方最新汇率：{latest} = {rates[latest]}")

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump({"date": latest, "value": rates[latest]}, f, ensure_ascii=False, indent=2)
        f.write("\n")

    if DRY_RUN and not os.environ.get("JDY_API_KEY"):
        print("DRY_RUN 且没有 JDY_API_KEY，跳过简道云核对")
        return

    existing = list_jdy_records()
    print(f"简道云已有 {sum(len(v) for v in existing.values())} 条记录，覆盖 {len(existing)} 天")

    missing = sorted(d for d in rates if d not in existing)
    duplicates = sorted(d for d, rows in existing.items() if len(rows) > 1)
    mismatched = sorted(
        d for d in rates if d in existing
        if any(v is None or abs(v - rates[d]) > 1e-9 for _, v in existing[d])
    )

    summary = [
        "## 汇率同步结果",
        f"- 官方最新：**{latest} = {rates[latest]}**",
        f"- 简道云缺失并已补上：{len(missing)} 天" + (f"（{', '.join(missing)}）" if missing else ""),
    ]
    if duplicates:
        print(f"警告：简道云有重复日期 {duplicates}")
        summary.append(f"- ⚠️ 重复日期：{', '.join(duplicates)}")
    if mismatched:
        print(f"警告：简道云与官方数值不一致的日期 {mismatched}")
        summary.append(f"- ⚠️ 数值与官方不一致：{', '.join(mismatched)}")

    if missing:
        print(f"需要补 {len(missing)} 天：{missing}")
        if DRY_RUN:
            print("DRY_RUN：不写入")
        else:
            create_jdy_records([(d, rates[d]) for d in missing])
            still_missing = sorted(set(rates) - set(list_jdy_records()))
            if still_missing:
                raise RuntimeError(f"写入后仍缺少：{still_missing}")
            print("核对通过，简道云已完整")
    else:
        print("简道云数据完整，无需补录")

    write_summary(summary)

    if stale_days > MAX_STALE_DAYS:
        raise RuntimeError(f"官方最新汇率停留在 {latest}，已 {stale_days} 天未更新，请检查数据源")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"失败：{e}", file=sys.stderr)
        write_summary([f"## ❌ 汇率同步失败", f"```\n{e}\n```"])
        sys.exit(1)
