# 库存建议与库存管理：开发记录

按时间顺序记录做了什么、为什么这样做、遇到的问题。

## 2026-10-27

### 准备
- 克隆小组仓库 `RoseKing233/mutiple-agent` 到 `D:\elec5620\mutiple-agent`，从 `feature/sales-analysis-forecast` 切出 `feature/inventory-management`。
- github.com 凭据是个人账号 `sunny20010115`，仓库里的 git user 也是这个。
- 阅读 `docs/sales-analysis/README.md` 和相关代码：
  - `shared/inventory_ledger.py`：统一库存流水入口
  - `shared/forecasting/`：商品表现和预测
  - `shared/tools/sales_analysis_tools.py`：tool 的权限检查写法
  - `orchestrator/routes/manager.py`：经理接口
- 现有代码里和库存相关的事实：
  - 商品和仓库被 `orders` / `order_items` / `inventory_movements` 外键引用，不能物理删除，所以只做停用和下架。
  - Checkout 从 `quantity > 0` 的任意仓库扣减库存。规定停用仓库时总库存必须为 0，并禁止往停用仓库入库，Checkout 就不用改。
  - `inventory_movements` 的 CHECK 只约束已列出的类型，新类型的正负号在代码里校验。
- 写好 `plan.md`。

### 迁移
- 新增 `docker/postgres/migrations/004_inventory_management.sql`：`warehouses.is_active` / `created_at`，以及 `inventory_suggestions` 表。
- 已执行过的 001–003 不修改，迁移器会按校验和保护。

### 决策：建议的确认方式（与用户确认）
- 接受建议：经理可以先修改数量和仓库，确认后执行（补货记 `restock_receipt`）。
- 拒绝建议：只记录决定和原因，不改库存。
- 手工修改：不依赖建议，经理随时可以入库、出库、盘点调整。
- 已同步到 `plan.md` 第 2 节。

### 决策：Advanced Technologies 范围（与用户确认）
- 对照评分标准和 Stage 1 报告确认：多模态在 Stage 1 里出现在三处，分别是客服的语音和图片输入（p.5、UC1）和 UC3 宣传图生成。"拍照上架"在报告里没有依据，不做。
- 本模块做 Structured Outputs，不做本地模型降级。
- 语音/图片输入和 GitHub Actions CI 写进交接文档，推荐组里做。
- 已同步到 `plan.md` 第 10 节。

### 决策：营销辅助加入范围（与用户确认）
- 实测 OpenAI key：`/v1/models` 能看到 gpt-image-1 / 1-mini / 1.5 / 2 等模型。用 `gpt-image-1-mini`、quality=low 生成一张 1024×1024 图片成功，耗时 9 秒，用了 295 token。没有测 `/v1/images/edits`，因为决定只做纯文字生成图片。
- 形态：新增商品表单里加"AI 生成标题与文案"和"AI 生成商品图"两个按钮。经理选择是否使用，选中的内容自动填进表单，保存时才写入商品。
- 排期：库存模块先做完，营销是第二阶段。
- 已同步到 `plan.md` 第 1、3、5、7、8、9、10 节。
- 和 Zicong 周三"商品介绍 AI 填充"的重叠，用户已在组里同步。

### 决策：Chat 里经用户同意由 AI 直接执行（组内决定）
- 组里认为让用户在 Chat 里同意后由 AI 直接执行更完整，所以推翻了原来"Chat 只读"的设计。
- 调研了现有机制：
  - `shared/hitl.py` 是**管理员**审批队列（`HITL_ENABLED`，默认关闭），拦截取消订单、退款等工具，由 admin 在 `/admin/approvals` 审批，不是"当事用户自己同意"。
  - Chat 里的 `ApprovalCard` 只服务于 return-replace workflow 的 checkpoint 恢复，也不通用。
  - 专家 Agent 能通过 `x-session-id` 拿到 `current_session_id`（就是 conversation_id）。用户消息在 Agent 运行**之前**就写进了 `messages` 表（`chat.py` 的 304 / 449 行）。
- 所以采用"两步确认 + 服务端核对用户最新消息"，设计见 `plan.md` 第 6 节。这个做法不依赖前端组件，也不用改 Siqi 那边的 HITL。
- 迁移 004 里加了 `inventory_action_requests` 表。`created_at` 用 `clock_timestamp()` 而不是 `NOW()`：`NOW()` 取的是事务开始时间，和用户消息的时间比较时可能不准。

### 后端实现
| 文件 | 内容 |
|---|---|
| `shared/inventory_management.py` | 库存行、手工调整（入库/出库/盘点）、流水查询、仓库、商品的增删改查和上下架。页面接口和 Chat 工具共用。 |
| `shared/inventory_suggestions.py` | 建议规则 `compute_suggestions`（纯函数，好测）、规则模板解释、LLM 解释（JSON Schema 结构化输出 + 数字校验）、生成/列表/决策。 |
| `shared/inventory_actions.py` | Chat 两步确认：`propose` / `confirm` / `cancel`、同意判断 `is_explicit_consent`。 |
| `shared/tools/inventory_management_tools.py` | 8 个 Agent tools，注册到 Inventory & Fulfillment Agent（普通模式和 MCP 模式都注册）。 |
| `orchestrator/routes/inventory.py` | `/api/manager/...` 下的接口，权限复用 `manager.py` 的 `require_manager`。 |
| `config/prompts/*.yaml` | Orchestrator 路由加了库存写操作和"确认/取消"回复。库存 Agent 的经理提示词：原来写的是"只读"，改成两步确认流程；补货相关的句子也改成"只有确认的操作才会增加库存"。 |

实现时的几个细节：
- **盘点调整**：用户输入盘点得到的数量，服务端在锁住库存行后再算差值，所以并发出库不会算错。重复提交（同一个 `request_id`）直接返回第一次的结果，不会因为库存已经变了而重新算差值。
- **建议用实时库存算**：Jingtong 的预测起点是"截止日日终库存"，补货要用"现在有多少"，所以耗尽日期是用实时库存和预测日销量重新累计出来的。
- **AI 解释的数字校验** `grounded()`：解释里出现的每个数字和日期都必须出现在这条建议的 evidence 里（允许四舍五入），不然这条就改用规则模板。LLM 调用异常、返回的 JSON 不合法，也都降级到规则模板，建议照常保存。
- **LLM 客户端**：项目里 MAF 的 `get_chat_client()` 不方便直接传 `response_format`，所以用 `shared.factory.get_embeddings_client()` 拿到原生 OpenAI / Azure SDK 客户端。这个函数名虽然带 embeddings，返回的其实是通用客户端。replay 模式下不支持，会直接降级到规则模板。
- **下架商品时**，把它待处理（pending）的建议标成 `superseded`，避免旧建议又把下架商品补进库存。
- **仓库停用**要求仓内总库存为 0，并且禁止往停用仓库入库。这样 Checkout 原有的"从有货的仓库扣减"逻辑不用改。
- `ruff check` 和 `ruff format` 都通过。

### 测试
- 新增 `tests/test_inventory_management.py`，共 26 项，用 testcontainers 起真实 PostgreSQL，LLM 用假函数代替。结果见 `test-record.md`。
- 首轮 25 项通过，1 项失败。原因是我对原项目的假设不对：公开的商品详情接口 `/api/products/{id}` 对下架商品仍然返回 200。这是原项目的设计，历史订单的页面要能链接到商品。真正拦截下架商品的是商品列表的过滤、加入购物车（返回 400 "Product is no longer available"）和 Checkout。所以把测试改成检查这三处，而不去改原有接口。

### 前端（简易）
- 新增 `web/src/app/(app)/inventory/page.tsx` 和 `web/src/components/manager/inventory.tsx`。页面分三个标签页：建议、库存、仓库与商品。
- `web/src/lib/api.ts` 加了一个通用方法 `api.inventory(path, method, body)`，统一调用 `/api/manager/...`。
- `web/src/lib/nav.ts` 加了 Inventory 入口，只有经理和 admin 能看到。
- 样式很简单，周五 Zihan 统一美化。新增商品表单里留了注释位置，第二阶段的 AI 营销按钮加在那里。

### 回归和真实环境验收
- Python 全量测试：925 passed，3 failed。其中 2 项是已知的 Windows 路径问题；另 1 项是 Jingtong 的测试写死了迁移列表，已把 004 加进去。之后专项 114 passed。前端 tsc 通过，vitest 198 passed。
- 启动 Docker 全栈时：
  - `scripts/dev.ps1` 需要 `-ExecutionPolicy Bypass` 才能运行，被本机的权限策略拦截，所以改为手动执行脚本里那几条 `docker compose` 命令：build → up db/redis/aspire → 运行 seeder → up agents/frontend。
  - 本机 5432 端口被占用，用一个本地 override 文件把数据库改到 5435，这个文件不提交。
- 真实环境发现 3 个问题，都已修复并补了测试，详见 `test-record.md` 4.3：
  1. 商品名里的数字被数字校验误判为编造
  2. Agent 拿不到仓库 UUID，改为接受仓库名
  3. orchestrator 转述时丢了 action_id，改为 confirm/cancel 可以不带 ID，取本对话最新的 pending 操作
- 收获：用假 LLM 的测试只能验证"规则是否正确"，"真实模型会怎么写、怎么转述"只有接上真实环境才能暴露出来。

### 换行符和迁移校验和（排查结论：没问题）
- 提交时 git 提示 LF 会被转成 CRLF（本机 `core.autocrlf=true`，`.gitattributes` 没有约束 `*.sql`）。我担心迁移校验和是按原始字节算的，换行符一变就会报 "Applied migration changed"。
- 实测：`shared/db_migrations.py` 用 `Path.read_text()` 读文件，它会把 CRLF 统一转成 LF，所以不管在哪个系统、用哪种换行符检出，校验和都一样。不需要改代码。

### 同步 Jingtong 的文档
- `docs/sales-analysis/README.md` 里有三处说法被本模块改变了：经理没有库存编辑权限、接受建议不改库存、业务时点表。在这三处**追加**了更新说明并指向本目录，没有删改他的原文。

### 用户试用后的补充（10-27 下午）
用户问：上架新品和库存是不是联动的？查了代码，只有选了初始仓库才会建库存行；选 "No initial stock" 时新品不出现在库存页，之后也没法直接入库。按用户的要求改了两处：
1. **新品默认建库存行**：`create_product` 没收到 stock 时，自动在第一个启用中的仓库（按名称排序，和页面下拉框顺序一致）建一条 0 件的库存行，并记流水。这个逻辑放在后端，接口和页面的行为一致。前端那个选项改名为 "Default: first warehouse, 0 units"。
2. **调仓接口** `POST /api/manager/inventory/transfers`（`transfer_stock`）：
   - 同一个事务里先补建目标库存行，再按仓库 ID 的固定顺序锁两行，避免两个方向相反的调仓互相死锁，然后记 `transfer_in` / `transfer_out` 两笔流水。
   - **两笔流水用同一个时间，先记调入**：Jingtong 的预测把"全店合计库存在某个时刻为 0"当成缺货。如果先调出，把一个仓库的货全部移走时，合计会在一瞬间变成 0，被误判成缺货。
   - 用 `request_id` 做幂等。
   - 页面：Stock → Manage 加了调仓区。"有库存行但数量是 0，之后来货"的情况，用原来的 Receive 就能处理，不需要新接口。
- Chat 里暂时**不加**调仓工具：要改 `inventory_action_requests` 的 action_type 约束，就得新建迁移，会占用刚通知全组从 006 开始的编号。以后需要的话可以用 006 来加。
- 新增 3 项测试，营销和库存一共 40 项通过；用真实环境调仓 2 件（Central 23→21，East 12→14），重复请求返回 replayed，库存不变。
