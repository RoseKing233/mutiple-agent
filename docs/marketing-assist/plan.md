# 上架 AI 营销辅助：开发计划

- 负责人：Xinyu Gu
- 开发日：2026-10-27（库存模块完成后，同一天第二阶段）
- 分支：`feature/marketing-assist`，基于 `feature/inventory-management`（提交 `a4c8a12`）
- 同目录：`dev-log.md`、`test-record.md`、`README.md`（交接）

## 1. 目标（对应 Stage 1 UC3 / UC4，范围缩小）

经理在 `/inventory` 的"新增商品"表单里：
1. 填好基本信息：名称、类别、品牌、价格、草稿描述、卖点关键词，还可以选目标人群和语气。
2. 点 **AI 生成标题与文案**：得到 3 版候选，每版包含标题、描述和 3 个卖点。点"使用"后填进表单，仍然可以修改。
3. 点 **AI 生成商品图**：只用文字生成图片（不上传原图），可以选风格和背景，得到 2 张候选图。点"使用"后设为商品图。
4. 两者都可以重新生成，也可以都不用、自己手写。最后点"保存"，走库存模块已有的 `POST /api/manager/products`，这时才真正写入商品。

和 Stage 1 的对应关系：
- UC4：多版本文案供选择，主流程第 5–9 步。
- UC3：生成宣传图，经理审核后采用，主流程第 6–9 步。
- 扩展流程 "Image Generation Service is unavailable"：返回 503 和提示，表单内容保留，可以重试或手动填写。
- "不把未确认的内容当成正式素材"：生成的内容在保存商品之前不会出现在顾客端。

## 2. 设计

| 点 | 做法 |
|---|---|
| 不编造数据（Stage 1 非功能要求） | 文案用 Structured Outputs（JSON Schema）。代码校验文案里出现的数字必须来自经理的输入（价格、名称、关键词、描述），不然这版就丢弃。一版都不剩时返回 503，提示重试。prompt 也禁止写没有提供的规格、价格、认证和评分。 |
| 图片存储 | 新表 `generated_images`，在 PostgreSQL 里存 webp 二进制，不另外挂 Docker 卷，现场部署少一个出错点。通过公开的 `GET /api/media/{id}` 读取，前端经已有的 `/api/*` 代理访问，`image_url` 存相对地址 `/api/media/<id>`。 |
| 记录生成请求 | 新表 `marketing_generations`，每次生成都记一行：请求参数、结果（或错误）、模型和耗时，方便审计。 |
| 模型 | 文案用项目已有配置的 `LLM_MODEL`（gpt-4.1）；图片用 `gpt-image-1-mini`，quality=low，1024×1024，webp。都可以用环境变量 `MARKETING_IMAGE_MODEL` / `MARKETING_IMAGE_QUALITY` 覆盖。 |
| 可测性 | 文案 writer 和图片 generator 都可以注入，测试里用假的，不调用真实 API。 |
| 权限 | 生成接口只允许 store_manager / admin；读图接口公开，因为商品图要给顾客看，图片 ID 是不可猜的 UUID。 |

## 3. 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/manager/marketing/copy` | 生成 3 版标题和文案，不写商品 |
| POST | `/api/manager/marketing/images` | 生成 2 张图并存库，返回 `[{id, url}]`，不写商品 |
| GET | `/api/media/{id}` | 公开，返回 `image/webp`，带长缓存头 |

## 4. 数据库：迁移 `005_marketing_assist.sql`
- `generated_images`：id、owner_id、generation_id、prompt、model、mime_type、data（bytea）、created_at
- `marketing_generations`：id、owner_id、kind（copy / image）、request（JSONB）、output（JSONB）、status（succeeded / failed）、error、model、duration_ms、created_at

## 5. 前端
- 在 `NewProductForm` 里加"营销辅助"区：关键词、目标人群、语气、图片风格，两个生成按钮，候选卡片和"使用"按钮，生成中显示加载状态，失败时显示错误提示并保留表单内容。
- 被选中的图片在表单里显示预览。

## 6. 测试计划
- 文案：
  - 假 writer 返回 3 版合法内容时，得到 3 版，记录状态为 succeeded。
  - 某一版出现编造的价格或数字时，这一版被丢弃。
  - 全部不合法，或 writer 抛异常时，返回 503，记录状态为 failed，**商品表不变**。
  - 非经理账号返回 403。
- 图片：
  - 假 generator 返回字节时，存进 `generated_images`；`/api/media/{id}` 不登录也能读回，类型是 image/webp。
  - generator 抛异常时返回 503。
  - 图片 ID 不存在时返回 404。
- 端到端：用生成的图和文案调 `POST /products` 保存，商品的 `image_url` 能访问到。
- 回归：库存模块和 Jingtong 的专项测试、前端 tsc 和 vitest。
- 真实 key：页面上各生成一次，记录耗时和效果。

## 7. 范围外
- 上传原图再编辑（`/v1/images/edits`）
- 品牌规范（Stage 1 类图里的 BrandGuideline）
- 发布到外部平台
- 营销 Chat 工具：这次只做页面，Chat 写商品走库存模块已有的工具。
