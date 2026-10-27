# 库存建议与库存管理：开发计划

- 负责人：Xinyu Gu
- 开发日：2026-10-27（周二，接力开发第 2 天）
- 分支：`feature/inventory-management`，基于 Jingtong 的 `feature/sales-analysis-forecast`
- 相关文档：同目录下 `dev-log.md`（开发记录）、`test-record.md`（测试记录）、`README.md`（交接文档）

## 1. 目标

1. **库存建议**：根据现有库存和销量预测，给出两类建议：
   - **缺货（restock）**：已经缺货、预测期内会耗尽，或低于补货阈值。
   - **积压（overstock）**：库存覆盖天数过长，或者滞销。
2. **库存管理增删改查**：
   - 仓库库存：查看、入库、出库、盘点调整，建立和删除库存行，修改补货阈值。
   - 仓库：增删改查。
   - 商品：新增、修改、上架、下架。
3. Chat 里的 Agent 能生成和查询建议，并用自然语言解释原因。
4. 做一个简易管理页，保证能演示。周五 Zihan 统一做前端时再美化。
5. **上架时的 AI 营销辅助**：对应 Stage 1 的 UC3 / UC4，范围缩小。
   - 经理在"新增商品"表单里填好基本信息，点按钮就能让 AI 生成多版标题和文案、生成商品图。
   - 经理选择要或不要；选中的内容自动填进表单，仍然可以修改；点"保存"才真正写入商品。
   - 图片只做纯文字生成图片，不做"上传商品图再编辑"。

## 2. 设计原则

延续 Stage 1 的非功能要求和 Jingtong 的交接约定：

| 原则 | 落实方式 |
|---|---|
| 数字不编造 | 建议数量、优先级、证据全部由代码根据数据库和预测结果计算。LLM 只写解释文字（rationale）。 |
| Human-in-the-loop | 建议生成后是 `pending` 状态，必须经理同意才执行：可以在页面上点"接受/拒绝"，也可以在 Chat 里由 AI 预览，经理回复确认后由 AI 执行（见第 6 节）。<br>**接受**：按建议数量执行，接受前可以修改数量和仓库。<br>**拒绝**：只记录决定和原因，不改库存。<br>不管有没有建议，经理随时都可以用手工入库、出库、盘点调整修改库存，两条路径都写流水。 |
| 外部服务不可用时降级 | LLM 调用失败时，用规则模板生成解释（`rationale_source='rule'`），建议照常保存。 |
| 库存变动可追溯 | 所有库存数量变化都走 `shared.inventory_ledger.change_inventory`，在业务事务里写 `inventory_movements` 流水，不直接 UPDATE quantity。 |
| 不物理删除有历史的数据 | 商品、仓库都是停用或下架（`is_active=false`）。库存行只允许在数量为 0 时删除，流水保留。 |

**和 Jingtong 文档不同的地方**：他写的是"补货建议只保存、接受也不改库存"。按本次组内决定，**接受补货建议会记一笔 `restock_receipt` 入库**，用来模拟"已到货"（本项目没有采购模块）。接受积压建议仍然只记录决定，不改库存。`docs/sales-analysis/README.md` 里对应的说明会同步修改。

## 3. 数据库：迁移 `004_inventory_management.sql`

- `warehouses`：新增 `is_active`、`created_at`。
- 新表 `inventory_suggestions`，字段如下：
  - 关联：批次 `batch_id`、创建人 `owner_id`、商品、建议仓库
  - 建议内容：类型、优先级、建议数量、`as_of` / `horizon`
  - 依据：`evidence` JSONB、AI 或规则写的 `rationale`
  - 状态：`pending` / `accepted` / `rejected` / `superseded`
  - 决策记录：决策人、时间、备注、实际执行数量和仓库、流水 `event_key`
- 新表 `generated_images`，用来存 AI 生成的商品图：
  - 字段：id、创建人、prompt、模型、MIME 类型、图片二进制（webp）、创建时间。
  - 图片直接存在数据库里，不另外挂 Docker 卷，现场部署少一个出错点。
  - 通过 `GET /api/media/{id}` 公开读取。被采用的图把这个地址写进 `products.image_url`，顾客端页面能直接显示。
- 新的流水类型，代码里校验符号：
  - `manual_receipt`：手工入库，正数
  - `manual_issue`：手工出库（报损等），负数
  - `stock_count_adjustment`：盘点调整，正负都可以
  - `restock_receipt`：接受补货建议后入库，正数

## 4. 建议规则（初版，阈值可配置）

复用 Jingtong 的 `forecast_report`（商品表现加预测），默认 horizon 为 14 天，截止日为 UTC 昨天。

**缺货 restock**，满足任意一条：
- `stockout_status` 为 `already_out_of_stock` 或 `within_horizon`
- 当前实时总库存 ≤ 各仓 `reorder_threshold` 之和

建议数量 = ceil(预测期销量 + 安全库存 − 当前实时库存)，最小为 0，安全库存取补货阈值之和。预测不可用时，按补货阈值的 2 倍补到位，并标为低置信。

优先级：
- high：已缺货，或 7 天内耗尽
- medium：预测期内耗尽
- low：只是低于阈值

建议仓库：该商品库存相对阈值最低的启用仓库。

**积压 overstock**，满足任意一条：
- `performance.overstock` 为 true
- `performance.slow_moving` 为 true

建议数量是超出"目标覆盖天数 30 天"的那部分库存。动作建议写成促销或暂停补货。

另外：
- 新一批建议生成时，同一商品、同一类型的旧 `pending` 建议改为 `superseded`。
- 下架商品不生成建议。

## 5. 接口（`/api/manager/...`，只允许 store_manager 和 admin）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/inventory` | 库存列表：商品 × 仓库，支持搜索、类别、低库存筛选、分页 |
| POST | `/inventory` | 给商品在某个仓库建库存行，可以带初始入库数量 |
| PATCH | `/inventory/{product_id}/{warehouse_id}` | 修改补货阈值 |
| POST | `/inventory/{product_id}/{warehouse_id}/adjustments` | 入库、出库、盘点调整，带幂等键和原因 |
| DELETE | `/inventory/{product_id}/{warehouse_id}` | 删除库存行，库存为 0 才允许 |
| GET | `/inventory/{product_id}/{warehouse_id}/movements` | 该库存行的流水 |
| GET / POST | `/warehouses` | 仓库列表 / 新建仓库 |
| PATCH / DELETE | `/warehouses/{id}` | 修改仓库 / 停用仓库（仓内总库存为 0 才允许） |
| POST | `/products` | 新增商品，可以同时建各仓库存行 |
| PATCH | `/products/{id}` | 修改商品信息 |
| PATCH | `/products/{id}/status` | 上架 / 下架 |
| POST | `/inventory-suggestions/generate` | 计算并保存一批建议，附带 AI 解释 |
| GET | `/inventory-suggestions` | 建议列表，按状态和类型筛选 |
| POST | `/inventory-suggestions/{id}/decision` | 接受或拒绝，可以修改数量和仓库 |

营销辅助接口（只生成候选内容，不写商品，商品由上面的 POST/PATCH `/products` 保存）：

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/api/manager/marketing/copy` | 根据表单信息生成 3 版标题和文案（Structured Outputs，JSON Schema 约束） |
| POST | `/api/manager/marketing/images` | 根据描述和风格要求生成 2 张图（`gpt-image-1-mini`，webp），存进 `generated_images`，返回地址 |
| GET | `/api/media/{id}` | 公开读取生成的图片 |

生成服务不可用时返回 503 和提示，表单内容保留，经理可以重试或者手动填写，对应 UC3 / UC4 的 "service unavailable" 扩展流程。

权限上的变化：Jingtong 设计的经理角色是只读，现在 store_manager 新增库存和商品的写权限，Chat 购物隔离不变。

## 6. Agent tools（注册到 Inventory & Fulfillment Agent）

**只读和建议类：**
- `generate_inventory_suggestions`：生成并保存建议，返回证据和 ID
- `list_inventory_suggestions`：查询建议
- `list_low_stock_inventory`：低库存和缺货清单

**写操作：用户在 Chat 里同意后，由 AI 执行（2026-10-27 组内决定）**

采用两步确认：
1. AI 调用 `propose_*` 工具，在新表 `inventory_action_requests` 里记一条 `pending` 操作并返回预览，这一步不改任何数据。
   - `propose_stock_adjustment`：入库、出库或盘点
   - `propose_suggestion_decision`：接受或拒绝某条建议，可以带修改后的数量和仓库
   - `propose_product_status`：上架或下架
2. AI 把预览展示给用户，请用户回复"确认 / confirm"。
3. 用户同意后，AI 调用 `confirm_inventory_action(action_id)`。服务端校验通过才执行，否则拒绝：
   - 这条操作属于当前用户和当前对话（`conversation_id`），状态是 `pending`，没有过期（15 分钟）。
   - 从数据库读出这个对话里**用户最新的一条消息**：必须是在预览之后发的，内容是明确的同意（确认 / 同意 / 执行 / yes / confirm 等），而且不包含"不 / 取消 / no / cancel"之类的否定词。
   - 所以即使 LLM 自己调用了 confirm，用户没有同意就执行不了。同意由服务端判断，不靠 LLM 自觉。
4. `cancel_inventory_action(action_id)`：用户说不要时取消。
   - 真实环境验收后的调整：confirm / cancel 可以不带 `action_id`，这时取本对话最新一条 pending 操作，因为 orchestrator 转述时可能把 ID 丢掉；`propose_*` 也接受仓库名，由服务端解析。见 `test-record.md` 4.3。
5. 执行时调用的服务函数和页面接口是同一套，所以流水、校验、幂等的行为完全一致。

页面上的按钮本身就是用户的明确操作，直接调 REST 接口，不需要两步确认。

## 7. 前端（简易）

- 新增 `/inventory` 页面，只有经理能看到，三个标签页：
  - 建议：生成、列表、接受/拒绝
  - 库存：表格、调整弹窗、流水
  - 仓库与商品：仓库增删改，商品新增和上下架
- 侧边栏加 Inventory 入口。
- 新增商品表单（营销辅助）：
  - 先填基本信息：名称、类别、品牌、价格、简单描述、卖点关键词。
  - "AI 生成标题与文案"：展示 3 张候选卡片，点"使用"就填进标题和描述。
  - "AI 生成商品图"：展示 2 张候选图，点"使用"就设为商品图。
  - 都可以"重新生成"，不选也能手动填写。最后点"保存"，可以选上架或者先存为下架状态。

## 8. 测试计划

测试都用真实 PostgreSQL（testcontainers），不 mock 数据库，也不调用真实 LLM。

- 权限：未登录返回 401，customer 返回 403，经理可以访问。
- 库存调整写流水、余额一致；出库超量被拒；幂等键重复提交不重复入账。
- 删除非零库存行、停用有库存的仓库都被拒绝。
- 商品新增、修改、上下架；下架后不可购买，原有校验仍然生效。
- 建议规则：
  - 缺货、即将缺货、低于阈值、积压、滞销各一个用例
  - 旧建议被 superseded
- AI 解释：用 fake client 返回 JSON 时 `rationale_source='ai'`；client 抛异常时降级为 `rule`，建议照常保存。
- 接受补货后库存增加，流水里是 `restock_receipt`；重复接受被拒；接受积压后库存不变。
- 营销辅助：
  - 用 fake client 返回合法 JSON 时得到 3 版文案。
  - 返回不合法 JSON，或 client 抛异常时，接口返回 503，数据库不写入。
  - 图片生成用 fake 图片 client，`generated_images` 写入后能通过 `/api/media/{id}` 读回。
  - 生成接口不会改动 `products`。
  - 用真实 key 手动测一次，结果记录进测试文档。
- 运行 Jingtong 的专项回归，确认没有破坏原有功能。
- 前端：`tsc`、`pnpm test`，并在浏览器里手动走一遍。

## 9. 时间安排

**10-27（周二）先做库存，这是今天的交付：**
1. 写计划（本文）
2. 迁移和库存服务层
3. 接口，其中包括商品增删改和上下架
4. 建议规则和 AI 解释
5. Agent tools 和提示词
6. 测试
7. 简易页面
8. 测试记录
9. 交接文档
10. 提交分支（push 前先跟用户确认）

**营销辅助是第二阶段：** 今天有时间就接着做，否则放到周六（10-31）。用的都是新文件，只在新增商品表单上挂按钮，和别人的接力冲突很小。

2026-10-27 已实测：OpenAI key 可以调用 `gpt-image-1-mini`，低质量 1024×1024 一张约 9 秒，花费不到 1 美分。

## 10. Advanced Technologies（评分第 4 项，5 分）

- **本模块做**：AI 图片生成（gpt-image，纯文字生成图片），属于评分第 (5) 类"不同能力的 AI 模型"，对应 Stage 1 UC3。
- **本模块做**：Structured Outputs。LLM 按 JSON Schema 返回解释，代码校验后才保存，校验失败就降级为规则模板。这样和 Human-in-the-loop 一起体现"AI 负责解释，人做决定"。
- **不做**：本地模型降级（Ollama），2026-10-27 决定。
- **写进交接文档，推荐组里做**：
  - 语音和图片输入：Stage 1 p.5 / UC1 的需求
  - GitHub Actions CI

## 11. 风险和待确认

- 接受补货会改库存，这与 Jingtong 原文档的约定不同，已经在本文第 2 节说明。交接时要提醒全组。
- Siqi 周四做取消和退货回补，会用到 `cancel_release` / `return_received`，与本模块的流水类型不冲突。
- 新商品不写 `product_embeddings`，语义搜索暂时搜不到新商品，留给 Zicong（周三，商品介绍和数据填充）评估。
