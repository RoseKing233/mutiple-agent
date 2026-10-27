# 库存建议与库存管理：交接文档

- 负责人：Xinyu Gu（接力开发第 2 天，2026-10-27）
- 分支：`feature/inventory-management`，基于 Jingtong 的 `feature/sales-analysis-forecast`，两个都还没合并到 main
- 同目录其他文档：`plan.md`（计划和设计取舍）、`dev-log.md`（开发过程和决策）、`test-record.md`（测试结果）

## 1. 做了什么（一句话版）

经理可以：
- 让系统根据**实时库存 + Jingtong 的销量预测**算出"缺货要补多少 / 哪些积压了"，AI 用自然语言解释原因，经理确认后才执行；
- 对库存、仓库、商品做增删改查，包括商品上下架；
- 在 **Chat 里让 AI 直接改库存**：AI 先给预览，经理回复"确认"之后才执行，是否同意由服务端判断，不靠 AI 自觉。

## 2. 怎么跑起来、怎么演示

启动方式和 Jingtong 文档一致（`scripts/dev.ps1`，从源码构建）。新迁移 `004_inventory_management.sql` 会自动执行，不需要重置数据。

> 如果本机 5432 端口被占用（比如装了 Windows 版 PostgreSQL），在仓库根目录建一个**不提交**的 `docker-compose.override.yml`：
> ```yaml
> services:
>   db:
>     ports: !override ["5435:5432"]
> ```

用经理账号 `manager.demo@gmail.com` / `manager123` 登录。

### 页面演示：`/inventory`（侧边栏 Inventory）
1. **Suggestions 标签**：点 **Generate suggestions**，大约 12 秒后出现按优先级排好的建议卡片。每张卡片有类型（Restock / Overstock）、优先级、建议数量和仓库、AI 写的理由，以及依据（实时库存、预测销量、耗尽日期）。
   - 补货卡片可以先改数量和仓库，再点 **Accept & receive stock**，库存会立刻增加并记一笔流水。
   - **Reject** 只记录原因，不改库存。积压卡片点 Accept 也只记录决定，不改库存。
2. **Stock 标签**：库存表（低库存排在前面，可以只看低库存）。点 **Manage** 可以做入库、出库、盘点（必须填原因），改补货阈值，删除空的库存行，下面能看到最近的流水。右上角可以给商品在某个仓库新建库存行。
3. **Warehouses & products 标签**：仓库的新增、停用和重新启用（有货的仓库不能停用）；新增商品（可以带初始库存、选择是否立即上架）；商品的上架和下架。

### Chat 演示（经理账号，模式选 Tool Router）
已经实测通过的英文提示词：
1. `Which products are at risk of running out or are overstocked? Generate inventory suggestions and show me the top 5.`
2. `Receive 10 units of Atomic Habits into the Central Warehouse. Reason: supplier delivery.` → AI 给出预览（当前 13 → 23），此时**库存没有变化** → 回复 `确认`（或 `confirm`）→ 执行
3. `Issue 3 units of Atomic Habits from the Central Warehouse because they were damaged.` → 回复 `No, cancel that.` → 取消，库存不变

演示时可以强调：AI 在同一轮里自己确认是执行不了的，`test-record.md` 4.3 记录了真实发生过的一次。

## 3. 设计要点（被问到时这样讲）

| 点 | 说明 |
|---|---|
| 数字从哪来 | 建议数量、优先级、依据全部由代码算：`shared/inventory_suggestions.py::compute_suggestions`，是纯函数。LLM 只负责写理由。 |
| 怎么防止 AI 编数字 | ① Structured Outputs：用 JSON Schema 约束 LLM 的输出格式。② `grounded()`：理由里出现的每个数字和日期都必须能在这条建议的依据里找到，不然就改用规则模板。LLM 出错时同样降级，建议照常保存。 |
| Human-in-the-loop | 页面上必须点接受。Chat 里是两步确认，服务端会读数据库里这个对话中用户**最新一条消息**：必须比预览晚，必须是明确同意（确认 / 同意 / yes / confirm…），而且不含否定词，才会执行。 |
| 库存可追溯 | 所有改动都走 Jingtong 的 `change_inventory`，写进 `inventory_movements` 流水。手工改动必须填原因，备注里记录操作人。 |
| 幂等 | 手工调整带 `request_id`，接受建议的流水 key 是 `suggestion:<id>`，重复提交不会重复入账。 |
| 不物理删除 | 商品和仓库都只是停用或下架，因为订单和流水还引用着它们。库存行只能在库存为 0 时删除，流水保留。 |
| 下架的效果 | 顾客端商品列表里看不到，加入购物车和结算都会被拒；它待处理的建议会被清掉。直接打开商品详情链接仍然能看（原项目的设计，历史订单需要能链接到商品）。 |

### 建议规则（默认值可以通过 `SuggestionRules` 调整）
- **补货**：已缺货、预测期（默认 14 天）内会耗尽，或者实时库存不高于补货阈值。
  - 数量 = ceil(预测销量 + 安全库存（各仓阈值之和）− 实时库存)。
  - 没有预测时，补到阈值的 2 倍，并标为低置信。
  - 优先级：已缺货或 7 天内耗尽为 high，预测期内耗尽为 medium，其他为 low。
  - 补到哪个仓库：库存相对阈值最紧张的那个启用仓库。
- **积压**：沿用 Jingtong 的 overstock / slow_moving 标记，超出"30 天销量"的部分就是积压量；动作是促销和暂停补货。
- 新一批建议生成时，同一商品、同一类型的旧 pending 建议标成 `superseded`。

## 4. 代码在哪

| 位置 | 内容 |
|---|---|
| `docker/postgres/migrations/004_inventory_management.sql` | `warehouses.is_active`，`inventory_suggestions` 表，`inventory_action_requests` 表 |
| `agents/python/shared/inventory_management.py` | 库存、仓库、商品的服务层（页面和 Chat 共用），`resolve_warehouse` |
| `agents/python/shared/inventory_suggestions.py` | 规则、AI 解释和数字校验、生成、列表、接受/拒绝 |
| `agents/python/shared/inventory_actions.py` | Chat 两步确认：`propose` / `confirm` / `cancel`，同意判断 `is_explicit_consent` |
| `agents/python/shared/tools/inventory_management_tools.py` | 8 个 Agent tools（已注册到 `inventory_fulfillment/agent.py`） |
| `agents/python/orchestrator/routes/inventory.py` | HTTP 接口 |
| `agents/python/config/prompts/orchestrator.yaml`、`inventory-fulfillment.yaml` | 经理路由和两步确认的提示词 |
| `agents/python/tests/test_inventory_management.py` | 28 项测试 |
| `web/src/app/(app)/inventory/page.tsx`、`web/src/components/manager/inventory.tsx` | 简易页面 |
| `web/src/lib/api.ts`（`api.inventory`）、`web/src/lib/nav.ts` | 通用请求方法、侧边栏入口 |

## 5. 接口（都在 `/api/manager` 下，只允许 store_manager / admin，未登录 401，无权限 403）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/inventory` | `search`、`category`、`warehouse_id`、`low_stock_only`、`include_inactive`、`offset/limit` |
| POST | `/inventory` | `{product_id, warehouse_id, reorder_threshold?, initial_quantity?, request_id?}`；已存在返回 409 |
| PATCH | `/inventory/{pid}/{wid}` | `{reorder_threshold}` |
| POST | `/inventory/{pid}/{wid}/adjustments` | `{kind: manual_receipt / manual_issue / stock_count_adjustment, quantity, reason（≥3 个字）, request_id?}`；盘点时 `quantity` 是盘点得到的总数；库存不够返回 422 |
| DELETE | `/inventory/{pid}/{wid}` | 库存为 0 才能删 |
| GET | `/inventory/{pid}/{wid}/movements` | 流水，最新的在前 |
| GET / POST | `/warehouses` | 列表带总库存 / `{name, location, region}` |
| PATCH / DELETE | `/warehouses/{id}` | 修改（含 `is_active`）/ 停用（有货返回 422） |
| POST | `/products` | `{name, description, category, brand?, price, original_price?, image_url?, specs?, is_active?, stock: [{warehouse_id, initial_quantity, reorder_threshold}]}` |
| GET | `/products/{id}/detail` | 商品信息和各仓库存 |
| PATCH | `/products/{id}` | 部分字段更新 |
| PATCH | `/products/{id}/status` | `{is_active}`：上架或下架 |
| POST | `/inventory-suggestions/generate` | `{as_of?, category?, product_id?, rules?, use_ai?}` |
| GET | `/inventory-suggestions` | `status`（默认 pending，可以传 all）、`suggestion_type`、`product_id` |
| POST | `/inventory-suggestions/{id}/decision` | `{decision: accept/reject, quantity?, warehouse_id?, note?}`；已经处理过的返回 409 |

新增流水类型：`manual_receipt`（正数）、`manual_issue`（负数）、`stock_count_adjustment`（正负都行）、`restock_receipt`（接受建议，正数）。

## 6. 给后面同学的接入说明

> **⚠ 迁移编号约定（所有人）**：`docker/postgres/migrations/` 下已经用掉 001–005：
> - 001–003：Jingtong，销量分析
> - 004：本模块，`004_inventory_management.sql`
> - 005：营销辅助，`005_marketing_assist.sql`
>
> **新迁移请从 `006_` 开始编号**，文件名要写清楚用途，例如 `006_order_cancellation.sql`。如果有两个人同时在不同分支上加迁移，请先在组里约好各自用哪个号，不然合并时会撞号，或者执行顺序出错。
>
> - 已经执行过的迁移文件**不能修改**：迁移器会校验文件内容，改了就报 "Applied migration changed"。要改表结构，请新建一个迁移。
> - 迁移测试 `test_sales_data.py::test_migration_baselines_...` 现在直接和磁盘上的迁移文件比较，新增迁移不需要再改这个测试。

- **Siqi（周四，取消/退款/退货）**：库存回补请继续用 `change_inventory`，类型是 `cancel_release` / `return_received`，跟本模块的类型不冲突。如果在 Chat 里做退款类写操作，也可以复用 `shared/inventory_actions.py` 的两步确认思路：服务端核对用户最新消息。原项目的 `shared/hitl.py` 是**管理员**审批队列，是另一种机制。
- **Zihan（周五，前端）**：`/inventory` 页面的样式很简单，可以直接重写。接口都走 `api.inventory(path, method, body)`。注意 422 时 FastAPI 的 `detail` 可能是数组，现有 `api.request` 会显示成 `[object Object]`，统一前端时建议处理一下。
- **Zicong（周三）**：通过本模块 `POST /products` 新增的商品**没有写 `product_embeddings`**，所以语义搜索搜不到新商品，普通关键词搜索可以搜到。如果你做数据填充，可以在这里补上 embedding。
- **改规则时**：改 `SuggestionRules` 的默认值或 `compute_suggestions` 后，同步更新本文第 3 节和 `test_rule_*` 测试。

## 7. 已知限制

- 页面没有在浏览器里逐个点击验收，只做了类型检查、确认生产构建能访问（200），接口都经过真实环境测试。交接前建议有人点一遍。
- 同意判断是规则（关键词加否定词），比如"好的但先别动"这种会判为否定，不执行，是偏保守的设计。只接受 60 个字以内的短回复。
- 补货不区分地区需求和仓库间调拨，全部补到一个仓库。积压建议只给出建议动作，不会自动改价格（价格属于 pricing 模块）。
- Chat 写操作的预览 15 分钟后过期，过期了需要重新发起。

## 8. 推荐组里接着做的（Advanced Technologies 加分项）

| 推荐 | 理由 | 估计工作量 |
|---|---|---|
| ~~上架时的 AI 营销辅助~~ | **已完成**，在分支 `feature/marketing-assist`，见 `docs/marketing-assist/README.md` | — |
| **客服的语音和图片输入**（Stage 1 p.5、UC1，原本是 Zihan 的需求） | 报告里写了支持语音和图片，现在都没实现。语音可以用浏览器 Web Speech API 纯前端实现；图片可以用 GPT-4.1 视觉能力识别商品。属于评分第 (5) 类"不同能力的 AI 模型"。 | 语音约半天（纯前端） |
| **GitHub Actions CI** | 仓库里已经有 `.github/workflows/tests.yml`，改成适配我们的分支后，PR 时自动跑测试。属于评分第 (4) 类，也能给 Agile 分（反馈循环）加分。需要仓库管理员开 Actions。 | 约 1–2 小时 |
