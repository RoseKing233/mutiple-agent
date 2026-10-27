# 上架 AI 营销辅助：测试记录

- 日期：2026-10-27
- 分支：`feature/marketing-assist`
- 环境：与库存模块相同（见 `docs/inventory-management/test-record.md`）
- 原则：自动化测试用真实 PostgreSQL（testcontainers），文案 writer 和图片 generator 用假的，不调用真实 API；真实 API 只在第 3 节手动验收时调用。

## 1. 新增测试：`tests/test_marketing_assist.py`

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests\test_marketing_assist.py -q -W ignore
```

结果：**9 passed**（首轮有 1 项失败，是测出了真问题，见第 4 节）。

| 测试 | 验证内容 |
|---|---|
| `test_variant_numbers_must_come_from_the_input` | 4 版候选里只保留"$39.50 + 3 brightness levels"这一版（价格和 3 都来自输入）。编造的"4.9 stars / 10,000 buyers"、"2-year warranty"，以及空标题的那版都被丢弃 |
| `test_numbers_inside_product_name_are_not_claims` | 标题里出现商品名"LUMO DESK LAMP 2"（大小写不同）不算编造 |
| `test_copy_generation_logs_and_never_touches_products` | 3 版文案都返回；prompt 里有"不得编造"的约束；价格传给了模型；记录状态为 succeeded；**products 表仍是 0 行** |
| `test_copy_failure_is_503_logged_and_form_safe` ×3 | writer 抛异常、全部候选不合法、返回非 JSON 三种情况：都返回 503，提示里有"form is unchanged"，记录状态为 failed，products 表仍是 0 行 |
| `test_marketing_endpoints_require_manager` | 两个生成接口：未登录返回 401，customer 返回 403 |
| `test_images_are_stored_served_publicly_and_usable_as_product_image` | 生成 2 张图；prompt 里有商品名、"No text"和所选风格；`/api/media/{id}` **不登录**也能读回原字节，类型是 image/webp；生成时 products 表不变；用生成的图 URL 调 `POST /products` 保存后，`image_url` 正确 |
| `test_image_failure_is_503_and_unknown_media_is_404` | generator 抛异常时返回 503，记录为 failed，不存图片；不存在的图片 ID 返回 404 |

## 2. 回归

- 营销、库存和 Jingtong 的专项测试一起跑（`test_marketing_assist`、`test_inventory_management`、`test_sales_data`、`test_manager_analysis`、`test_sales_forecasting`、`test_idempotency`）：**90 passed**。
- 全量结果见第 5 节。
- 前端：`tsc --noEmit` 通过（exit 0），`eslint src/components/manager/inventory.tsx` 通过（exit 0）。
- ruff check 和 ruff format：新增和修改的 Python 文件都通过。

## 3. 真实环境验收（Docker 全栈、真实 OpenAI key）

先在已有的数据库上增量执行迁移 005（`scripts.migrate`，输出 `Applied: 005_marketing_assist.sql`），原有数据保留。验收脚本是本地临时脚本，没有放进仓库。

输入：Aurora Ceramic Pour-Over Set，Home，$49，描述 "Hand-glazed ceramic dripper with a 600 ml glass server and 40 paper filters."，关键词 slow coffee ritual / gift ready / dishwasher safe，人群 home coffee lovers，语气 premium。

| 检查 | 结果 |
|---|---|
| 文案（gpt-4.1，Structured Outputs） | 200，**4.0 秒**，3 版，角度分别是 Benefit-led、Story-led、Concise。数字只有 600 ml 和 40 filters，都来自输入；没有编造规格、评分或保修 |
| 图片（gpt-image-1-mini，low，webp） | 200，**9.5 秒**，2 张，大小 53 KB 和 58 KB |
| 通过前端代理读图（`localhost:3000/api/media/...`，不登录） | 200，image/webp |
| 图片内容（人工查看） | 蓝色手工釉面滴滤杯、玻璃分享壶、滤纸，背景是阳光照射的厨房台面，没有文字或水印，符合描述和所选风格 |
| 用第 1 版文案和第 1 张图保存商品 | 201，`image_url = /api/media/<id>` |
| 顾客端商品列表 | 能看到这个新商品 |

文案示例（Concise 版原文）：
> **Aurora Hand-Glazed Pour-Over Set: Ceramic & Glass** — Enjoy handcrafted coffee at home with Aurora's ceramic dripper, 600 ml glass server, and 40 filters. Designed for both everyday use and gifting, this set is also dishwasher safe for convenience.

## 4. 测试中发现的问题

- **数字校验的漏洞**：商品名里的数字会"放行"文案里其他位置的同一个数字，例如名字里的 2 让编造的 "2-year warranty" 通过了校验。已修复，允许的数字不再从商品名和品牌里取。由 `test_variant_numbers_must_come_from_the_input` 覆盖。
- **Jingtong 的迁移测试写死了列表**：每加一个迁移就要改一次，已改为和磁盘上的迁移文件比较，详见 `dev-log.md`。

## 5. 全量回归

- Python 全量：**940 passed、2 failed**。2 项失败是 `test_config_repo_root.py` 的 Windows 路径断言，Jingtong 已经记录过，和本模块无关。
  - 之前 3 项因为"no LLM credentials in .env"被跳过；这次本地 `.env` 里有 key，它们实际运行了，也通过了。
- 前端 vitest：**34 个文件、198 项全部通过**。

## 6. 没有覆盖到的
- 页面没有在浏览器里逐个点击，接口都经过真实环境测试，前端只做了类型检查和 lint。
- 没有测试 Azure provider（项目用的是 openai），图片生成也只支持 openai provider。
