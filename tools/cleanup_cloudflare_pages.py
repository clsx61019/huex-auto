"""一次性工具：删除 Cloudflare Pages 项目（先清空全部部署，再删项目）。

部署太多时 Cloudflare 控制台不允许直接删项目，所以先逐个删部署。

环境变量：
  CF_API_TOKEN   Cloudflare API Token，权限 Account → Cloudflare Pages → Edit
  CF_ACCOUNT_ID  Cloudflare 账户 ID
  CF_PROJECTS    要删除的项目名，逗号分隔，例如 "huex-auto,huex"
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"


def cf(method, path):
    req = urllib.request.Request(
        f"{API}{path}",
        method=method,
        headers={"Authorization": f"Bearer {os.environ['CF_API_TOKEN']}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {"errors": [{"message": body.decode("utf-8", "replace")[:300]}]}


def errors(resp):
    return "; ".join(f"{e.get('code')}: {e.get('message')}" for e in resp.get("errors", [])) or "未知错误"


def delete_project(account, name):
    base = f"/accounts/{account}/pages/projects/{name}"
    status, resp = cf("GET", base)
    if status == 404:
        print(f"[{name}] 项目不存在，跳过")
        return True
    if status != 200:
        print(f"[{name}] 读取项目失败（HTTP {status}）：{errors(resp)}")
        return False

    ids, page = [], 1
    while True:
        status, resp = cf("GET", f"{base}/deployments?per_page=25&page={page}")
        if status != 200:
            print(f"[{name}] 读取部署列表失败（HTTP {status}）：{errors(resp)}")
            return False
        batch = resp.get("result") or []
        ids += [d["id"] for d in batch]
        info = resp.get("result_info") or {}
        if not batch or page >= info.get("total_pages", page):
            break
        page += 1
    print(f"[{name}] 共 {len(ids)} 个部署，开始删除")

    failed = 0
    for i, dep_id in enumerate(ids, 1):
        status, resp = cf("DELETE", f"{base}/deployments/{dep_id}?force=true")
        if status != 200:
            failed += 1
            print(f"[{name}]   部署 {dep_id} 删除失败（HTTP {status}）：{errors(resp)}")
        if i % 25 == 0:
            print(f"[{name}]   已处理 {i}/{len(ids)}")
        time.sleep(0.2)
    print(f"[{name}] 部署删除完成，失败 {failed} 个（当前线上部署删不掉属正常，会随项目一起删除）")

    status, resp = cf("DELETE", base)
    if status != 200:
        print(f"[{name}] 删除项目失败（HTTP {status}）：{errors(resp)}")
        return False
    print(f"[{name}] 项目已删除")
    return True


def main():
    account = os.environ["CF_ACCOUNT_ID"]
    projects = [p.strip() for p in os.environ["CF_PROJECTS"].split(",") if p.strip()]
    results = [delete_project(account, p) for p in projects]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
