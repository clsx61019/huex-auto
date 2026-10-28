# huex-auto

自动把匈牙利央行（MNB）公布的 **人民币 → 福林** 官方汇率同步到简道云「签证管理 / 辅助：历史汇率」表。

## 工作方式

GitHub Actions 每天运行 4 次（UTC 11:23 / 14:23 / 17:23 / 21:23），每次运行时：

1. 从 MNB 官网接口取 2025-01-01 至今的全部 CNY 汇率（官网不可用时改用 fxhu.kripod.dev 镜像）；
2. 读出简道云表里已有的全部日期；
3. **缺哪天补哪天**。某次没跑成功也没关系，下一次运行会自动补齐；
4. 补完后再核对一遍，仍有缺失就让任务失败，GitHub 会发邮件提醒；
5. 把最新一天写入 `data.json`。

## 配置

在仓库 **Settings → Secrets and variables → Actions** 里添加：

| 名称 | 内容 |
|---|---|
| `JDY_API_KEY` | 简道云开放平台的 API Key，需要有「签证管理」应用的数据读写权限 |

## 手动运行

Actions → **Sync CNY/HUF rates** → Run workflow。勾选 “只检查不写入简道云” 时，只打印需要补录的日期，不会写入数据。

## 本地运行

```bash
JDY_API_KEY=xxx python3 sync_rates.py          # 同步
DRY_RUN=1 JDY_API_KEY=xxx python3 sync_rates.py # 只检查
```
