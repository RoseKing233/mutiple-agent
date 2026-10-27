# 上架 AI 营销辅助：交接文档

- 负责人：Xinyu Gu（2026-10-27）
- 分支：`feature/marketing-assist`，基于 `feature/inventory-management`（`a4c8a12`），两个都没有 push
- 同目录：`plan.md`、`dev-log.md`、`test-record.md`

## 1. 做了什么

对应 Stage 1 的 **UC3（生成宣传图）和 UC4（生成标题与文案）**，范围有缩小：经理在 `/inventory` →
**Warehouses & products** → **New product** 表单里，可以让 AI 生成：
- **3 版标题和文案**：每版包含标题、描述和 3 个卖点，角度各不相同；
- **2 张商品图**：只用文字生成，可以选风格（studio / lifestyle / minimal / festive）和背景。

经理点"Use this version"或"Use this image"，内容会填进表单，之后还能修改。点 **Save product** 时才真正写入商品，可以选择立即上架。生成失败时，表单内容保留，可以重试，也可以手动填写。

## 2. 怎么演示

1. 用经理账号登录，进入 `/inventory` → Warehouses & products → 展开 New product。
2. **先填基本信息**（带 * 的必填；空着离开输入框，或者点按钮时还没填，输入框会变红）：
   - Name *
   - Category *：下拉选择；没有合适的，选 "Other (add a new category)…" 再输入新类别
   - Brand（选填）
   - Price *
   - Description *：AI 生成文案时只能用这里写的数字，所以规格尽量写具体
3. 下方的 **AI 营销辅助**（全部选填）：
   - **文案**：卖点（Selling points，用逗号隔开）、目标人群（Audience）、语气（Tone），点 **Generate title & copy**，约 4 秒出 3 版，点 Use this version。
   - **图片**：风格（Image style）、画面描述（Image scene，写图片里要出现什么），点 **Generate images**，约 10 秒出 2 张，点 Use this image。
   - 没填 Name / Category 就点生成，会提示先填，并把这两个框标红。
4. 选一个仓库并填初始库存（选填），点 Save product。下方商品列表和顾客端都能看到新商品。

建议演示用的输入（已实测，效果好）：Aurora Ceramic Pour-Over Set / Home / Aurora / 49 /
"Hand-glazed ceramic dripper with a 600 ml glass server and 40 paper filters." / 卖点 slow coffee ritual, gift ready, dishwasher safe / 风格 lifestyle / 背景 sunlit kitchen counter。

## 3. 被问到时怎么讲

| 点 | 说明 |
|---|---|
| 多模态 / 不同能力的模型 | 文案用 gpt-4.1（文本），图片用 gpt-image-1-mini（文字生成图片），同一个流程里组合两种能力的模型，对应评分第 4 项的第 (5) 类。 |
| 不编造数据 | ① Structured Outputs：用 JSON Schema 约束输出格式。② 代码校验：文案里每个数字都必须来自经理的输入（价格、描述、关键词等），不然这一版就丢掉。商品名本身带的数字（例如 "Lamp 2"）不算，也不能用来放行别处的同一个数字。③ prompt 禁止编造规格、评分、保修和认证。 |
| Human-in-the-loop | 生成的只是候选，要经理选择、可以修改、保存后才上架，和 Stage 1 UC3/UC4 主流程里的"review and approve"对应。 |
| 服务不可用 | 返回 503，提示"表单没有变化"，对应 UC3/UC4 的 service unavailable 扩展流程。每次生成，成功或失败，都记在 `marketing_generations` 表里。 |
| 图片存储 | 图片以 webp 格式存在 PostgreSQL 里（每张约 55 KB），通过 `/api/media/{id}` 公开读取，经过前端已有的 `/api/*` 代理。不需要额外的 Docker 卷或对象存储，现场部署少一个出错点。 |

## 4. 代码和接口

| 位置 | 内容 |
|---|---|
| `docker/postgres/migrations/005_marketing_assist.sql` | `marketing_generations`、`generated_images` |
| `agents/python/shared/marketing.py` | 生成逻辑、校验、OpenAI 调用（writer 和 generator 可以注入） |
| `agents/python/orchestrator/routes/marketing.py` | 接口 |
| `web/src/components/manager/inventory.tsx` → `MarketingAssist` | 表单里的 AI 区 |
| `agents/python/tests/test_marketing_assist.py` | 9 项测试 |

| 方法 | 路径 | 权限 | 请求 → 返回 |
|---|---|---|---|
| POST | `/api/manager/marketing/copy` | store_manager / admin | `{name, category, brand?, price?, description?, keywords[], audience?, tone}` → `{generation_id, variants: [{angle, title, description, highlights}]}`；失败返回 503 |
| POST | `/api/manager/marketing/images` | store_manager / admin | `{name, category, description?, style, background?}` → `{generation_id, prompt, images: [{id, url}]}`；失败返回 503 |
| GET | `/api/media/{id}` | 公开 | 返回 `image/webp`，不存在时返回 404 |

配置（可选的环境变量）：
- `MARKETING_IMAGE_MODEL`：默认 `gpt-image-1-mini`
- `MARKETING_IMAGE_QUALITY`：默认 `low`；演示想要更好的效果可以改成 `medium`，会更慢、更贵

## 5. 给后面同学的说明

> **⚠ 迁移编号约定**：001–005 已经用掉（001–003 Jingtong，004 库存，005 本模块）。**新迁移从 `006_` 开始**，多人同时开发时先在组里约好编号。已经执行过的迁移文件不能修改。详见 `docs/inventory-management/README.md` 第 6 节。

- **Zihan（前端）**：`MarketingAssist` 组件的样式很简单，可以重写。保持"候选 → 使用 → 保存"这个流程就行。图片是普通的 `<img src="/api/media/...">`。
- **Zicong（商品介绍 / 数据填充）**：这里的文案只用于经理新建商品时；顾客端的推荐理由和评价总结是你那边负责。新商品没有写 `product_embeddings`，语义搜索搜不到（库存模块交接文档也提过）。
- **注意费用**：每次点生成都会实际调用 OpenAI。文案很便宜；图片 low 质量每张不到 1 美分。

## 6. 范围外 / 已知限制
- 不支持上传原图再编辑（`/v1/images/edits`），也没有做品牌规范（Stage 1 类图里的 BrandGuideline）。
- Chat 里没有营销工具，只能在页面上用。
- 图片生成只支持 `LLM_PROVIDER=openai`。
- 页面没有在浏览器里逐个点击验收，接口都经过真实环境测试。
