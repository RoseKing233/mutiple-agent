# Inventory and Sales Analysis：统一交接文档

维护位置：`docs/sales-analysis/README.md`。后续与本成员负责功能有关的字段、接口、预测及测试说明，继续更新此文件。
本文合并了原数据说明、数据字典、库存接入说明和验证记录，不再维护多份平行交接文本。

## 交付状态与范围

| 阶段 | 当前状态 |
|---|---|
| 数据结构、迁移、模拟销售和库存数据 | 已完成 |
| 经理角色、权限、分析服务 | 已完成 |
| 最小 Dashboard、经理商品列表与详情 | 已完成 |
| 注册 Inventory & Fulfillment Agent 分析 tools | 已完成，5 个工具，普通与 MCP 模式均注册 |
| 销量/库存预测、预测结果和商品表现分析结果保存 | 已完成，规则、模型比较、曲线、缺货风险、报告保存和重开 |
| 本成员范围内的系统联调与交接 | 数据库/API/tools/页面已联调；已使用配置模型完成针对性的真实英文 Chat 验收 |

历史分析已经实际查询数据库并计算指标、绘制图表，不是空页面。
历史统计、商品表现、预测及保存均已实现。LLM 通过 tools 调用同一计算服务，数字由代码和数据库产生。
按老师允许的范围，本实现可与 Ass1 细节不同：沿用模板 Agent 结构、使用单店经理角色，补货建议不执行采购或入库。

## 经理账号与权限

首次创建的演示经理：`manager.demo@gmail.com` / `manager123`，角色为 `store_manager`。
已有同邮箱经理时保留原密码；已有同邮箱其他角色时拒绝自动提权。

| 身份 | 行为 |
|---|---|
| customer | 原有购物、个人订单；无经理分析接口权限 |
| store_manager | 全店商品、销售、仓库库存和相关销售订单只读；无个人购物操作 |
| admin | 可查询经理分析接口，保留原有系统管理权限 |
| seller / power_user | 保留原行为，不自动获得全店经理权限 |

经理没有 Cart、Orders、购物首页入口，登录后进入 `/analysis`。
经理 Products 复用 `/products`、`/products/[id]`，显示经营信息并去掉加入购物车。
侧边栏、快捷搜索、顾客购物车自动加载均按角色处理。
经理直接访问购物地址会转回分析页；购物 API 和共享 cart tools 也拒绝经理操作。
普通注册接口始终创建 customer，不能通过提交 role 字段创建经理。

角色通过 JWT 和现有 Agent 身份传递机制传递；经理不是 admin，也不拥有审批、退款或库存编辑权限。
本轮没有更改其他组员负责的在线退货、取消回补、库存 CRUD 和补货建议执行逻辑。

> **2026-10-27 更新（Xinyu，库存管理模块）**：store_manager 现在有库存、仓库、商品（含上下架）的写权限，补货/积压建议在经理确认后可以执行。详见 `docs/inventory-management/README.md`。本文其余内容不变。

## 组员使用指南：启动、网页和 Chat

### 启动与退出

以下命令在仓库根目录执行。本机目录是 `C:\Users\12952\Documents\ELEC5620\ass2`；
其他组员替换成自己的克隆目录，并切换到包含这些新增功能的分支。

```powershell
cd C:\Users\12952\Documents\ELEC5620\ass2
# 仅首次且没有 .env 时复制模板；已有配置会保留。
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.minimal -Destination .env }
```

在本机 `.env` 中填写可用模型配置，例如模板中的 `OPENAI_API_KEY`。
经理历史分析、分类、图表、预测和报告保存不需要调用模型；Chat 自然语言路由与解释需要有效模型服务。
真实 key 只写入本地 `.env`，不要改进已跟踪的 `.env.example`、`.env.minimal` 或文档中。

1. 打开 Docker Desktop，等待 Docker 引擎就绪。
2. 执行下面的启动脚本，等待 `E-Commerce Agents is ready!`。
3. 打开 `http://localhost:3000/login`，使用 `manager.demo@gmail.com` / `manager123` 登录。
4. 经理默认进入 Analysis 页面；侧边栏 Products 和 Chat 分别用于经营商品查询和自然语言分析。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

该脚本从当前代码构建/启动服务，执行增量迁移，并在需要时初始化数据。已有演示数据默认保留。
正常退出可在仓库根目录执行：

```powershell
docker compose --profile agents --profile frontend down
```

该命令停止并移除容器，保留数据库卷。下次运行同一个 `dev.ps1` 启动命令即可。
普通启动/退出不要附加 `-Clean`、`-ResetData` 或 `down -v`；它们用于明确要清除/重建数据的操作。

### Dashboard 与 Products 的具体操作

1. 打开 `/analysis`，设置 **Start date (UTC)**、**End date (UTC)**、**Category**、**Product**，
   点击 **Apply filters**。例如 Books，2026-09-28 至 2026-10-25；该范围包含首尾两天。
2. 查看 **Sales units**、**Item sales amount**、**Sales orders**、**Current stock**，
   以及 **Daily sales** / **Inventory history** 曲线。当前库存是实时余额，历史库存为各日结束时余额；
   历史记录未知时曲线留空，不补成零。
3. 查看商品表现列表，区分 growing、declining、slow-moving、overstock、stockout-affected 和历史不足。
   分类依据与限制见本文“判断规则”；缺货影响不能直接解释成需求下降。
4. 在 **Sales & inventory forecast** 选择 **Forecast horizon**：7、14 或 28 天，
   点击 **Generate & save forecast**。这一步同时计算和保存一份报告，实际库存不变。
5. 在报告的 **Forecast product** 中选中商品，查看该商品的销量/库存曲线、所选模型、回测误差、
   缺货风险和经验高低情景；展开 **Saved performance, assumptions & reproducibility** 查看保存的规则和报告 ID。
6. 在 **Your saved analyses** 中打开已有报告，或者打开 `/analysis?run_id=<报告 UUID>`。
   读取保存的快照不会重新预测。只有创建者能读取自己的报告。
7. 打开 `/products` 查看经营商品列表，可按日期、类别、名称/品牌筛选；进入单品详情查看历史图、
   各仓当前库存和相关销售订单。经理账号在这些页面只读，不执行购买。

历史页面默认可能包含今天的部分日；预测与商品表现采用完整 UTC 日，截止日取所选结束日与 UTC 昨天中的较早者。
预测训练最多使用截止日前 180 天，页面历史图的开始日期不限制训练长度。
从链接打开的报告有自己的日期、范围和 horizon，应以报告内保存参数为准，不能把上方历史筛选误当成报告参数。

### Chat 的具体操作与英文验收示例

用经理账号打开 `/chat`，在输入框附近的模式选择器中选择 **Tool Router**。
每次等待回复完成、输入框恢复可用后再发送下一条。需要核对调用过程时，展开回复中的 **Agent activity**。
同一会话可追问“刚才的报告”；测试独立场景时用 **New chat** 新建对话。
Chat 通过可点击的报告链接进入 Dashboard，目前不自动跳转，也不自动填写页面全部历史筛选项。

下面日期对应本机截至 2026-10-25 的模拟批次。其他组员应按自己的数据覆盖范围调整日期，
不能把这里的销量或所选模型当成所有数据批次的固定答案。

**1. 查询真实历史与统计口径**

> Analyze actual sales for the Books category from 2026-09-28 through 2026-10-25 inclusive, in UTC. Report total sales units, distinct sales orders, item sales amount, historical closing inventory, current live inventory, and cancelled and returned units. Explain the counting rules.

预期调用 `get_sales_history`，明确未取消订单件数包含退货订单，取消件数另列；金额是商品小计，不能称为扣退款后的净收入。
本机这批数据的参考值为 518 件、331 单、USD 19,334.63，取消 26 件、退货订单 9 件，历史日终和实时库存均为 397。

**2. 查询增长、下降、滞销与积压**

> As of 2026-10-25, classify Books products into growing sales, declining sales, slow-moving and overstock. Use the system rules and list at most three products per group with evidence. Report stockout-affected products and insufficient history separately.

预期调用 `analyze_product_performance`，按实际标签列组。本机这批数据中 The Pragmatic Programmer 增长，
Atomic Habits 下降且积压，没有已确认滞销商品；Staff Engineer 和 The Manager's Path 应单列为缺货影响。
连续无销量天数不等于连续缺货天数。

**3. 生成并保存单品预测**

> Resolve the real product ID for Atomic Habits. As of 2026-10-25, forecast its next 14 days of sales, remaining inventory and stockout risk, and save the report. Include the chosen model and selection method, total forecast sales, starting and ending stock, reliability, limitations, report ID and dashboard link. Stay in Chat.

预期先解析真实商品 UUID，再调用 `forecast_sales_inventory`，新增报告并返回本站相对链接。
本机参考值为 tsb_0.1、预测销量 7.03、历史起始库存 38、期末库存约 30.97；这是滚动回测选出的模型，不能称为固定默认模型。
预测从 2026-10-26 开始，至 2026-11-08 结束，期内未预测到缺货；不表示以后永远不会缺货。

**4. 在同一会话读取刚才的报告**

> Read the report you just saved; do not generate another forecast. Repeat its report ID, product, cutoff date, horizon, expected sales and model. Explain whether this is retrieval or recomputation.

预期本轮实际调用 `get_saved_sales_analysis`，返回第 3 步相同的报告 ID，报告列表数量不增加。
读取依据是数据库保存快照，而不是只复述上一条回复。可点击报告链接核对保存内容。

**5. 跨会话列出并读取报告**

新建 Chat 后发送：

> List my three most recently saved sales analysis reports, newest first, including report ID, cutoff, horizon and scope. Then read the newest report and summarize its forecast and limitations. Do not create a new report.

预期先 `list_saved_sales_analyses` 再 `get_saved_sales_analysis`。范围仅限当前登录用户；不新增报告。
如果当前账号尚未保存报告，应说明列表为空。

**6. 核对预测不会修改实际库存**

> For Atomic Habits, query current actual inventory, generate and save a 7-day forecast as of 2026-10-25, then query current actual inventory again. Distinguish actual stock before, historical starting stock, projected ending stock and actual stock after. Only read stock and save analysis; do not create orders or inventory adjustments.

预期预测前后都实际调用 `check_stock`；当前库存标注查询时的 `observed_at`，不能标成历史预测截止日。
本机参考值是实际库存前后均为 38，7 天预测销量约 4.93，预测期末库存约 33.07，生成一份新报告。
在无人同时购买/修改库存时，前后余额应相同；预测不会触发真实出入库。

**7. 不支持的预测时长**

> Forecast Atomic Habits for 30 days as of 2026-10-25. If unsupported, state the supported horizons. Do not silently change the horizon or create a report for a different period.

预期说明只支持 7/14/28 天，不新增报告。工具可能正常执行后返回参数错误；工具步骤显示 success 不代表预测保存成功。

**8. 顾客权限检查**

退出经理账号，以演示顾客 `alice.johnson@gmail.com` / `customer123` 登录，新建 Chat 后发送：

> Give me store-wide Books sales, identify overstock products and list manager sales-analysis reports. I am signed in as a customer. Explain any manager-access restriction without disclosing internal data.

预期拒绝提供内部经营数据；经理 API 返回 403。完成后切回经理账号继续开发。

### 阅读结果时的注意事项

- 缺少历史、库存起点未知或严重缺货时，允许返回未知、暂停预测或低可靠性，不能强行输出零。
- 模型由代码与数据库计算，LLM 负责解释；以工具/保存报告中的参数、标签与数值为核对依据。
- 报告是不可变快照。后来数据变化不更新旧报告，重新计算会创建新报告。
- 修复代码并刷新页面后，应重新提问验证；历史 Chat 的旧回复不会被改写。
- 完整规则、算法、接口和接入边界继续见本文后续章节，新增使用说明不替代这些技术约定。

## 提交代码时保留本地数据库与 Chat

### 数据具体保存在哪里

| 内容 | 实际位置 | 是否应提交 Git |
|---|---|---|
| 商品、库存余额、订单、库存流水 | PostgreSQL，Docker 命名卷 `pgdata` | 否 |
| Chat 会话与回复 | PostgreSQL 的 `conversations`、`messages` 表 | 否 |
| 已保存预测报告 | PostgreSQL 的 `sales_analysis_runs` 表 | 否 |
| 账号与相关业务数据 | 本机 PostgreSQL 数据库 | 否 |
| 浏览器登录状态、部分界面设置 | 浏览器本地存储 | 否 |
| 私有 API key / 环境配置 | 本机 `.env` | 否 |
| SQL 结构迁移、seed 代码与生成规则 | `docker/postgres/migrations/`、`scripts/`、`agents/python/` | 是 |
| 前后端代码、测试、交接文档、Compose 配置 | 仓库源码文件 | 是 |

Git push 上传已经 commit 的 Git 对象，不会自动连接 PostgreSQL、导出 Docker 卷或读取浏览器存储。
因此不用清空数据库、删除 Chat 或停止 Docker，就可以提交代码。组员通过迁移和 seed 代码建立自己的本地数据库，
不会自动获得本机已有订单、测试对话或报告 UUID。

需要注意的是，手工导出的数据库/Chat 文件，以及包含这些内容的截图，属于普通文件；放进仓库再提交就可能上传。
本仓库 `.gitignore` 已覆盖私有 `.env.*`（保留模板）、虚拟环境、构建和测试产物、本地数据库文件及压缩备份。
手工导出请统一放在被忽略的 `/backups/`、`/exports/` 或 `/local-data/` 中。
本轮 `.claude/manager-*.png` 本地演示截图也被忽略。
不要笼统忽略所有 `.sql`、`.json` 或图片，否则会遗漏必要的迁移、配置与测试样本。

`.gitignore` 只影响尚未跟踪的文件；已经跟踪的模板或代码即使后来匹配忽略规则，修改仍可被提交。
目前实际 `.env` 没有被 Git 跟踪；`.env.example` 和 `.env.minimal` 是已跟踪模板，保持其中只有示例配置。

### 在当前功能分支提交和推送

下列命令由准备提交的人执行；更新交接文档本身不会自动执行 commit 或 push。
当前本机分支是 `feature/sales-analysis-forecast`，远程为 `origin`。

```powershell
cd C:\Users\12952\Documents\ELEC5620\ass2
git branch --show-current
git status --short
git check-ignore -v .env
```

确认分支正确、待提交内容都是计划交付的代码/文档后，再暂存并审阅：

```powershell
git add .
git diff --cached --name-only
git diff --cached --stat
git diff --cached
```

暂存列表中应包含新的源码目录、迁移 SQL、模拟数据生成逻辑、测试与本交接文档，
不应包含 `.env`、数据库备份、Chat 导出、虚拟环境或本地截图。
如果误暂存了某个文件，用 `git restore --staged -- <文件路径>` 取消该文件的暂存，保留本地文件。
不要用 `git add -f` 强行加入被忽略的数据文件。

审阅完成后提交到自己的分支：

```powershell
git commit -m "Implement inventory and sales analysis with forecasting and agent tools"
git push -u origin feature/sales-analysis-forecast
```

若当前分支并非上面的名称，先确认自己的目标分支，再替换命令中的分支名；不要直接推送到 main。
以后继续向同一已配置上游的分支提交，可使用 `git push`。
保留 SQL 迁移与 seed 代码，才能让组员重建兼容的数据结构和演示数据；它们不包含本机数据库的当前记录快照。

## 升级已有数据库并创建经理

从仓库根目录执行。以下操作保留业务数据，不生成替代销售历史：

```powershell
cd C:\Users\12952\Documents\ELEC5620\ass2
.\agents\python\.venv\Scripts\python.exe -X utf8 -m scripts.migrate
.\agents\python\.venv\Scripts\python.exe -X utf8 -m scripts.create_manager
```

脚本从当前进程的 `DATABASE_URL` 读取连接，未设置时连接模板默认的 localhost:5432 数据库。
`scripts/create_manager.py` 支持 `--email`、`--password`、`--name`，不会重设已有经理密码。
正常 seeder 也会补齐演示经理；已有用户和商品时不清空业务数据。
隔离代码测试不操作业务库；后续 Docker 启动排障已在本机现有业务库应用增量迁移，保留原数据。

如果旧库没有历史库存流水，迁移只建立当前库存起点，历史图中的未知区间是正确行为。
想查看完整模拟历史，可使用后文明确标注的 `--reset` 重建命令；它会替换业务演示数据。

### Windows Docker 启动与旧库排障

从根目录运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1`。
等待最后出现 `E-Commerce Agents is ready!`，再访问 `http://localhost:3000/login`。
仅出现镜像 Built、数据库/Redis ready 不代表前端已经启动。

Windows PowerShell 5.1 会将重定向的原生 stderr 包装成错误记录。Compose 的正常进度也写 stderr，
因此 `Invoke-Compose` 和探测函数局部使用 Continue，并明确检查进程退出码；真正的非零退出仍会中止启动。
数据库结构查询直接通过 stdin 传入 psql，避免额外 sh 层和嵌套引号；查询执行失败与字段缺失分开报告。
回归测试 `tests/test_dev_powershell.py` 覆盖正常 stderr、非零退出、显式允许失败三种情况。
本机验证：三个兼容性测试通过；使用 Windows PowerShell 5.1 完整运行启动脚本成功，
`/login` 返回 HTTP 200，orchestrator 与五个业务 Agent 的健康检查通过。已有业务数据保留。

若旧库确实缺少 `products.search_vector`，使用下列增量 SQL 保留数据修复；不要重跑整份 init.sql：

```powershell
$sql = @'
BEGIN;
ALTER TABLE public.products
ADD COLUMN IF NOT EXISTS search_vector tsvector
GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(brand, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(description, '')), 'C')
) STORED;
CREATE INDEX IF NOT EXISTS idx_products_search ON public.products USING GIN (search_vector);
COMMIT;
'@
$sql | docker compose exec -T db psql -U ecommerce -d ecommerce_agents -v ON_ERROR_STOP=1
```

补齐后再次运行启动脚本。`-Clean`、`-ResetData` 用于明确要删除/重建演示数据的场景，不是普通启动排障步骤。

### Chat 重复回复气泡排障

2026-10-26 排查：同一条分析请求在数据库只保存一条助手回复，但前端出现两个相同气泡。
工具/图节点事件在 setMessages 更新函数内修改 assistantCreated，React 尚未提交该状态时，
紧随其后的预览/正文事件仍认为消息未创建，重复插入同一 assistantId。
Chat 页面现统一按 assistantId 在待提交状态中更新或插入，并移除更新函数里的外部状态修改。
预览会被第一段最终正文替换，工具步骤和图事件保留在同一个气泡中。

验证：修复前回归测试复现重复，修复后 190 项前端测试、TypeScript、Docker 生产构建通过；
新增浏览器测试 `e2e/chat-stream-identity.spec.ts` 通过，验证一次请求和一条回复，不调用真实模型。
当前 Docker 前端已重建并更新，浏览器刷新加载修复。该问题没有产生重复持久化记录，因此无需删除聊天数据。

当时发现的另一个问题：实际模型回复曾把默认增长阈值 15% 和积压覆盖 60 天写成 20% 和 180 天。
容器的规则配置仍正确；气泡修复不解决模型复述失真。验收分类应核对实际工具返回的 rules/标签，
不能仅依赖自然语言说明。现有通用 grounding 校验不等于销售规则逐字段校验。

### 流式换行与分析回复复核

后续复核两次 Books 测试：历史查询的 518 件、331 单、USD 19,334.63、26 件取消、9 件退货、
397 件日终/实时库存均与真实只读分析结果相符。分类回复仍曾将“绝对销量差 ≥5 件”误述成“本期销量 ≥5 件”，
并把 stockout_affected 商品放入下降组，混合了滞销与积压。
`performance_report` 现增加由代码生成的 rule_descriptions、classification_groups 和 interpretation；
YAML 要求按工具标签和公式解释，不自行重新分类，缺货影响及历史不足单列。并禁止为类别销售汇总编造库存/物流卡。
这强化了工具与提示词契约，尚不能视为对真实 LLM 所有后续回复的逐字段保证，需要继续人工对话验收。

流式格式与重载格式不同的根因是 SSE 直接嵌入多行文本，却没有给每一行加 data: 前缀；
浏览器因此丢掉换行，数据库保存的原始正文仍正确。shared/sse.py 统一编码普通正文与 delta，
specialist→orchestrator 按完整事件拼接多行 data，而非逐行作为独立 token 转发。
纯换行 token、连续空行、缩进和 Markdown 围栏均保留，完成后的实时正文与保存正文一致。

另修正工具记录为空的问题：current_steps 在创建 asyncio 子任务前绑定共享列表，子任务内不再重置新列表；
所以父任务保存消息、agents_involved 和 usage steps 时能看到实际工具记录。
验证：59 项后端专项、6 项前端解析/消息测试、2 项无模型浏览器测试通过；
浏览器测试逐项比较即时显示和重新载入后 Markdown 结构。更新后的 orchestrator 和五个业务 Agent 镜像已应用。
此次只读复核不改写历史聊天内容，因此旧回复的语义错误需通过新一轮提问验证，不会被刷新自动纠正。

### 已保存报告读取与库存口径

报告读取不能只复述聊天历史。`shared/forecasting/chat_policy.py` 对经理/admin 的明确中英文
报告读取请求使用 MAF 原生 `tool_choice`：orchestrator 首先调用 specialist，库存 Agent 首先
调用读取工具；最新报告 ID 未知时先列出报告。MAF 执行首个工具后恢复正常工具选择。
历史上下文只用于定位 UUID，`get_saved_sales_analysis` 仍校验报告归属，不重新预测或新增报告。
该策略针对明确的读取/列出请求，不能替代工具权限检查，也不是任意语言意图的完整解析器。

`sales_analysis_tools.compact_report` 保留原有字段，并补充：

- `operation`：区分预测保存工具和已保存报告读取工具。
- 每商品 `starting_stock_at_cutoff`、`projected_ending_stock`、`forecast_start/forecast_end`。
- `model_selection`：滚动回测选择，或不足两折时的近期均值回退；不能描述成固定默认模型。
- `sales_definition/stock_definition`：未取消订单件数（含待履约和退货订单），以及历史日终库存口径。

报告地址为 `/analysis?run_id=<UUID>`，两层 Agent 提示词均要求原样传递。
Chat Markdown 还会将带有效报告 UUID 的 `/analysis` 链接规范为本站相对地址，避免模型添加占位域名。
其他链接继续使用原有 URL 清理规则。打开链接仍由后端校验报告所有者。

`check_stock` 增加 `inventory_basis=current_live` 与 UTC `observed_at`。
查询前后实际库存使用各自查询时间；预测起始库存使用截止日日终余额，两者不能共用日期标签。
经理混合对比的提示词要求用普通 Markdown 表格，分别列出查询前、历史起点、预测期末与查询后库存。

商品表现增加明确的 `consecutive_zero_sales_days`，原 `consecutive_zero_days` 作为兼容别名保留。
它表示连续无销量天数，不能作为连续缺货天数。
`recent_stockout_days` / `trend_stockout_days` 分别统计近期窗口 / 两个趋势窗口中观测到日内缺货的天数，
不表示连续天数。工具返回 `field_definitions` 说明这些含义；旧报告快照不会被改写。

流式 A2A 调用可能在工具已经提交后断开，orchestrator 随后回退到 `/message:send`。
因此同一次 A2A 调用携带固定的 `x-agent-request-id`，两个执行入口都绑定到
`current_agent_request_id`。预测工具从调用 ID 与完整预测参数派生保存 UUID，复用原有数据库锁和
owner/request 唯一约束；即使模型在重试时生成了不同的 request_id，同范围也只保存一次。
不同参数或新的 A2A 调用仍可生成新报告。无 A2A 上下文的直接工具调用保留原显式 request_id 行为。

## 仅测试分析页面，不需要模型 API key

真实 LLM 聊天仍需配置可用模型；经理登录、统计、分类、预测、图表和保存都不调用 LLM。
预测算法使用 Python 标准库实现，无新增 statsmodels/StatsForecast 依赖，也无需额外预测 API key。
在数据库已经运行并迁移完成后，可分别启动后端和前端：

```powershell
# 终端一：从仓库根目录进入 Python 后端
cd C:\Users\12952\Documents\ELEC5620\ass2\agents\python
.\.venv\Scripts\python.exe -X utf8 -m uvicorn orchestrator.main:app --host 127.0.0.1 --port 8080
```

```powershell
# 终端二：前端，使用现有 pnpm 依赖
cd C:\Users\12952\Documents\ELEC5620\ass2\web
$env:ORCHESTRATOR_URL = "http://127.0.0.1:8080"
pnpm dev
```

打开 `http://localhost:3000/login`，使用经理账号进入分析页。
如果使用完整 Docker Agent 栈，应从当前源码构建，并按原项目要求配置模型服务；上游预构建镜像不包含课程新增功能。

## 页面与统一统计服务

| 页面 | 内容 |
|---|---|
| `/products`，经理视图 | 类别、名称/品牌、日期筛选；当前库存、所选期销量、商品金额、订单数；20 条分页 |
| `/products/[id]`，经理视图 | 商品信息、指标、销量与库存图、各仓实时库存、相关订单；订单 10 条分页 |
| `/analysis` | 日期/类别/商品筛选、历史指标与曲线、商品表现、7/14/28 日预测、库存/缺货风险、模型比较、报告保存与重开 |

所有日期为 UTC，自定义起止日期包含首尾两天，默认最近 28 天且包含今天。
今天标记为未结束的部分日。起止倒置、未来日期、超过 730 天和非法 UUID/分页会拒绝。
筛选条件保存在 URL，支持刷新和页面间携带商品及日期。
当前库存是实时余额，不随历史日期改变；历史库存为当日结束前的最后余额。
请求切换会中止旧请求，不把旧图表标成新筛选结果。

统计逻辑在 `agents/python/shared/sales_analysis.py`，HTTP 路由只负责鉴权、参数与连接。
历史接口使用只读、一致快照事务。Agent tools 已复用该服务并严格校验角色；预测逻辑共用 `shared/forecasting/`。

## 管理接口

历史接口均为 GET，需要 Bearer 登录令牌，允许 store_manager/admin；预测保存接口见下节。

| 地址 | 参数/返回 |
|---|---|
| `/api/manager/catalog` | 商品选项、类别选项 |
| `/api/manager/products` | start_date/end_date、category、product_id、search、offset/limit；分页商品及经营指标 |
| `/api/manager/analysis` | start_date/end_date、category、product_id；summary、series、warehouses、coverage_start、口径及独立预测接口地址；不在此接口自动预测 |
| `/api/manager/products/{id}/orders` | start_date/end_date、offset/limit；该商品的相关订单及商品小计 |

无登录 401；非管理身份 403；参数不合法 422；不存在的具体商品 404。
相关订单不返回客户地址或其他客户个人信息，金额仅指该商品的明细小计。
订单数采用 COUNT DISTINCT，多商品同一订单在汇总时只算一笔。
未取消销售包含 returned 状态订单，退货件数另列；商品金额没有分摊整单优惠或扣除退款，不标为净收入。
库存历史分别延续每个仓库的余额，再跨仓汇总；任一已存在仓库缺少起点时，汇总保留未知。
没有销售的已知覆盖日期补零；商品上架前、记录覆盖前保留未知。

## 本轮新增/调整的代码

| 位置 | 用途 |
|---|---|
| `docker/postgres/migrations/002_manager_analysis.sql` | 经理角色说明、商品分析索引 |
| `docker/postgres/migrations/003_analysis_runs.sql` | 预测与商品表现结果表、状态历史查询索引 |
| `shared/forecasting/` | 参数/阈值、时点数据重建、模型、分类、汇总、保存 |
| `shared/tools/sales_analysis_tools.py` | 5 个带角色检查的分析 tools |
| `inventory_fulfillment/context.py` | 每次请求加载当前角色提示词 |
| `shared/manager_accounts.py`、`scripts/create_manager.py` | 无清库经理账号创建 |
| `shared/sales_analysis.py` | 共用历史统计和库存时间序列服务 |
| `orchestrator/routes/manager.py` | 管理 API 和权限 |
| `shared/auth.py`、`config/prompts/*` | 经理身份识别、角色提示词 |
| `shared/tools/cart_tools.py`、`orchestrator/routes/legacy.py` | 经理购物隔离 |
| `web/src/components/manager/` | 筛选、数据请求、商品视图、指标和图表 |
| `web/src/app/(app)/analysis/page.tsx` | 分析与预测页面入口 |
| `web/src/lib/manager*.ts`、`api.ts` | 角色、筛选、类型及请求 |
| 导航、登录、购物上下文及 Products 页面 | 按身份切换经营与购物视图 |

表中 shared/、orchestrator/、config/ 相对于 `agents/python/`。

## 早期阶段验证记录（历史）

日期：2026-10-26。数据全部使用临时 PostgreSQL/Redis，浏览器使用新的无头 Chrome 配置文件。
没有替换当前业务库、调用付费模型，或保持临时服务器运行。

- 数据、预测、经理权限、购买、Agent 工厂和提示词专项测试：86 项通过。
- 最后补充“历史缺货导致低可靠性”和“全部不可预测不显示零销量曲线”的边界检查后，11 项计算/角色测试再次通过。
- 前端单元测试：187 项通过；控件标签修正后的 7 项相关测试再次通过；TypeScript 检查及生产构建通过。
- ESLint：0 errors，64 warnings，警告主要为仓库已有用法。
- 真实浏览器：4 项全部通过，覆盖经理登录与导航、商品/订单查看、类别/日期筛选、错误提示、移动端、顾客加入购物车及越权拒绝，以及预测生成、单品曲线、保存和链接重开。
- 最近一次 Python 全量回归：865 passed、3 skipped、2 failed。两项失败仍为原有 `test_config_repo_root.py` 的 Windows/Linux 路径断言问题；随后请求级角色提示词修正及其新增测试已包含在 86 项专项回归中。
- 临时 180 天模拟数据（seed=42、截止 2026-10-25）：50 个商品中 42 个可预测，8 个暂停预测；默认规则得到增长 8、下降 10、滞销 2、积压 8。整店 14 日计算约 0.35 秒（本机单次测量，不是性能保证）。

```powershell
# 后端专项
cd C:\Users\12952\Documents\ELEC5620\ass2\agents\python
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_sales_forecasting.py tests/test_manager_analysis.py tests/test_sales_data.py tests/test_idempotency.py tests/test_agent_factories.py tests/test_prompt_loader.py -q
```

```powershell
# 前端与浏览器；浏览器需已运行、已初始化的 Python 后端和前端
cd C:\Users\12952\Documents\ELEC5620\ass2\web
pnpm test
pnpm exec tsc --noEmit
pnpm build
pnpm exec playwright test e2e/manager.spec.ts
```

Playwright 默认连接 localhost:3000，可用 E2E_BASE_URL 更改；此用例使用本机 Chrome。

## 商品表现、预测与结果保存（第三阶段）

### 页面操作与时间含义

1. 经理登录 `/analysis`，选择日期、类别或商品。历史图显示所选窗口，商品表现自动计算。
2. 预测截止日取筛选结束日与“UTC 昨天”中的较早者；不把今天的不完整销量当作完整一天。
3. 选择 7/14/28 天，点击 **Generate & save forecast**。使用截止日前最多 180 天训练，历史图的开始日不限制训练。
4. 报告显示销售及库存曲线、各商品预测和缺货风险。选择 Forecast product 查看单品模型、误差、限制与经验情景。
5. **Your saved analyses** 每页 20 条；Open saved report 读取原快照，不用当前数据重新计算。
6. Agent 返回的 `/analysis?run_id=<UUID>` 可直接重开该用户的报告。报告有自己的时间和范围，可能不同于页面上方的历史筛选。

**三个时间口径不能混用**：顶部 Current stock 是实时库存；历史图是所选日期的 UTC 日终库存；
预测起点是截止日的日终库存。今天已经发生的交易不包含在“昨天日终起点”的预测中，报告明确说明这一点。
查询历史截止日时不使用今天的库存倒推。若库存起点未知，仍可能显示销量预测，但库存曲线和缺货日期保留未知。

### 判断规则

默认阈值是课程项目的可配置规则，不宣称为零售行业统一标准。定义位于 `shared/forecasting/config.py::PerformanceRules`。

| 类型 | 默认判断 | 数据限制 |
|---|---|---|
| 增长 growing | 最近 28 日对前 28 日增长 ≥15%，且绝对增加 ≥5 件 | 两段完整数据，且库存已知、没有缺货影响 |
| 下降 declining | 同比窗口下降 ≥15%，且绝对减少 ≥5 件 | 同上；这里是相邻窗口比较，不是去年同期 |
| 稳定 stable | 不满足增长/下降阈值 | 前期为零、本期非零单列 new_sales，不计算无穷增长率 |
| 滞销 slow_moving | 最近 28 日 ≤3 件，或连续 14 日没有销售 | 观察期完整且期间有库存、没有缺货影响；否则为 null |
| 积压 overstock | 截止日库存 ≥5 件，且库存覆盖天数 >60 | 覆盖天数=截止日库存÷最近 28 日平均日销量；缺货/未知不强行分类 |

增长、下降是趋势；滞销、积压是独立标记，所以商品可以同时增长和积压。
最近完全无销售时，`days_of_cover=null`，`no_recent_sales=true`，不输出 Infinity。
`false` 表示有依据但不满足规则；`null` 表示缺少可靠判断依据。增长率和原始销量即使显示，也必须结合 trend/warnings 解读。
只拥有短历史的新商品不直接认定为滞销。结果保留窗口日期、销量、增长率、连续零销量天数、库存、覆盖天数和原因。

### 模型、验证和不确定性

代码：`shared/forecasting/models.py`。按 SKU 计算后再汇总；不会把某 SKU 多余库存用来抵消另一 SKU 的缺货。
不读取模拟器 profile、潜在需求或未来数据来选择“正确答案”。

| 候选 | 具体实现 |
|---|---|
| mean_28 | 最近最多 28 个已知完整日的平均值；短历史/回测不足时的基线 |
| seasonal_naive_7 | 预测同星期几，复用训练期最后一周 |
| holt_winters_* | 加性周季节性，周期 7；加性趋势，可阻尼。固定小网格 α∈{0.2,0.5}、β=0.1、γ=0.2、φ∈{0.9,1.0}，用回测选取 |
| tsb_* | TSB：每日更新需求发生概率，仅在正销量日更新需求规模；规模 α=0.2，概率 β∈{0.1,0.3}，适合间歇需求，也参加共同基线比较 |

实现采用可审阅的标准递推公式和有限参数网格，没有使用 statsmodels 的自动优化器；模型名称和参数编码在报告中。
公式参考：[Holt–Winters / 指数平滑](https://otexts.com/fpp3/exponential-smoothing.html)、
[TSB 方法说明](https://nixtlaverse.nixtla.io/statsforecast/docs/models/tsb.html)。

- 最多 3 个互不重叠的滚动验证窗口，各自至少 28 个训练日，验证长度等于预测长度。
- 按日 MAE 最小选择模型，整段累计销量绝对误差用于次级排序。至少 2 个有效窗口才选模型，否则退回近期均值并标为低可靠性。
- 每个验证起点重新构造当时可知的取消状态和缺货修正；不拿当前 cancelled 状态直接改写过去训练窗口。
- 订单采用发生时间语义：`order_status_history.timestamp` 表示业务事件时间。原表没有 recorded_at，因此**不声称**能还原“迟到修订写入前”的数据库版本。
- 订单缺少初始 placed/confirmed 记录，或已取消订单没有取消时间时，暂停该商品预测，提示状态历史不足。不能用当前状态伪造历史时间。
- 有销售覆盖的日子无订单才填零；上架前/覆盖前不填零。库存某日任一时点全仓合计归零，视为可能受缺货影响。
- 连续最多 3 日的短缺货仅用更早的同星期几估计，预测输入不低于已观测销量；较长缺口保留实际观测并明确提示可能低估需求，降低可靠性，不填造数据。
- 最近最多 28 日中缺货影响超过 20% 时暂停预测；验证窗口内有缺货的窗口不用于完整销量误差比较。库存历史未知会降低可靠性。
- 有 3 个窗口且至少 21 个残差时，给出日残差 p10/p90 的经验高低情景；**不是校准后的 80% 置信区间**。模型选择和残差使用同一批验证窗口，误差不是独立测试集精度。
- 不输出负销量。销量预测是期望值，可有小数。低可靠性/无法预测/零预测是不同状态。

### 库存与缺货

`预测剩余库存 = max(0, 截止日日终库存 − 累计预测销量)`。
未来采购入库、退货、取消释放、人工调整都默认 0；`restock_schedule` 不计入。
超过库存的预测需求单列 `shortfall`/`unmet_units`，不会写负库存。
累计需求第一次达到库存的日子为估计耗尽日（`stockout_date`）。
库存已经为零→`already_out_of_stock`；预测期内未耗尽→`not_within_horizon`，不是永不缺货；
起点未知→`unknown_stock`。若销量无法预测而库存已为零，仍说明当前缺货。
单品在全仓合计层面预测，未模拟地区需求/逐仓调拨和履约约束。
新交易发生后可重新生成报告；保存预测和补货建议都不会改变真实库存。

如果部分商品无法预测，`summary.complete=false`，全店 `series.units`/`stock` 为 null；
`available_product_units` 只显示可预测商品的小计，UI 明确标注 partial coverage，不能解释为全店总销量。

### 新接口与结果表

权限：store_manager/admin；报告列表和读取**仅限创建者本人**，包括 admin，不能通过猜 UUID 读取他人报告。

| 方法/地址 | 作用 |
|---|---|
| GET `/api/manager/performance` | as_of、category、product_id；默认规则下的商品表现，不写数据库 |
| POST `/api/manager/analysis-runs` | 服务端计算并保存商品表现和预测；返回完整报告和 id |
| GET `/api/manager/analysis-runs` | 本人报告列表，offset/limit，默认 20，上限 100 |
| GET `/api/manager/analysis-runs/{id}` | 原样读取保存的完整结果，不重新计算 |

POST 示例（Bearer token 使用正常登录获得的令牌）：

```json
{
  "as_of": "2026-10-25",
  "horizon": 14,
  "category": "Books",
  "product_id": null,
  "request_id": "7d21f4ad-18b4-4af6-867d-3d286e54004f",
  "rules": {"trend_percent": 15, "overstock_days": 60}
}
```

`as_of` 省略时为 UTC 昨天；必须是最近 730 日内的完整日。`horizon` 仅 7/14/28。
rules 可部分覆盖配置对象中的阈值，未给出的使用默认值；当前 UI 和 Agent 使用默认规则，API 可自定义。
报告保存实际采用的完整规则。单次最多 200 个商品，超出需缩小类别/商品范围。
同一用户和 request_id 的重试返回同一份报告；若参数不同返回 409。UI 网络失败重试保留 request_id。
POST 只接收参数，不允许客户端提交“算好的数字”冒充服务端结果。
新迁移 `003_analysis_runs.sql` 添加 `sales_analysis_runs`：

| 字段 | 含义 |
|---|---|
| id / owner_id / request_id | 报告 UUID、创建人、幂等键（用户+请求键唯一） |
| engine_version | `sales-forecast-v1`，修改算法含义时应升级 |
| as_of / horizon | 数据截止日与预测长度 |
| parameters JSONB | 范围、日期、完整规则 |
| result JSONB | 商品表现、逐日预测、库存、缺货、回测、限制、数据指纹、生成时间 |
| created_at | 数据库保存时间 |

计算和保存基于同一 repeatable-read 快照。HTTP 没有修改/删除报告接口；重新生成创建新报告。
数据指纹是模型输入历史的 SHA-256，用于识别输入是否一致；它不是历史数据库备份。
显式 `seed --reset` 重建演示数据时同时清空旧分析报告，普通 seed/migrate 保留。

### Agent tools 与对话验收

`shared/tools/sales_analysis_tools.py` 注册到 `inventory_fulfillment/agent.py`；MCP 模式下这 5 个工具仍在本地执行。

| Tool | 功能 |
|---|---|
| get_sales_history | 日期/类别/商品范围的实际销量与库存历史 |
| analyze_product_performance | 增长、下降、滞销、积压及证据 |
| forecast_sales_inventory | 计算并保存预测，返回摘要、报告 ID 和 Dashboard 链接 |
| list_saved_sales_analyses | 当前用户报告列表，offset 分页 |
| get_saved_sales_analysis | 当前用户报告摘要 |

每个工具入口都独立检查 ContextVars 中的认证身份和角色，即使通用 guardrails 关闭也不会给顾客经营数据。
Orchestrator 的经理提示词把这些意图转给 Inventory & Fulfillment；商品名称先由已有查询工具转换成真实 UUID。
工具返回数值/依据，LLM 负责解释，不能自行编造销量、模型误差、补货或缺货日期。
完整曲线保存在报告；工具返回较精简的商品摘要及所选模型的回测误差，避免把全部时间序列塞进对话。

联调发现 Inventory A2A 主程序复用启动时创建的 Agent。新增 `inventory_fulfillment/context.py::InventoryRoleProvider`
在每次 run 时加载当前角色的 YAML 指令，基础 prompt 不固化 customer 角色，避免经理请求仍沿用启动时顾客提示词。
此流程使用 MAF ContextProvider，不增加自定义 LLM 循环。

配置有效 LLM key 并启动 orchestrator + inventory-fulfillment 后，用经理账号在 Chat 人工验收：

- “分析最近 28 天 Books 中哪些商品增长、下降或积压，并给出依据。”
- “预测这个商品未来 14 天销量、库存和缺货风险，并保存结果。”
- “查看我刚保存的分析报告。”

第三阶段初次验证包含工具注册、真实数据库直接工具调用、HTTP/tools 结果一致、MAF 每次运行角色指令及浏览器流程，
当时没有调用付费 LLM。后续已按前文“组员使用指南”的场景完成针对性的真实英文 Chat 验收；
自然语言表述仍需与实际工具输出/报告核对，不能视为任意问题都经过逐字段保证。

### 后续组员接入边界

1. 库存 CRUD、取消回补、收到退货等使用下文 `change_inventory` 接口，在业务事务内维护库存和流水。
2. 订单状态改变时同事务追加 `order_status_history`，保留真实事件时间，不只覆盖 orders.status。取消后重新激活订单的工作流不在当前预测模型中，若新增需扩展状态重建规则。
3. 退货件数与回库数量分开处理。预测的默认未来回库仍为 0；有可信计划时另加显式情景，不能暗中改动默认假设。
4. 不覆盖已保存报告。改变规则、算法、时间口径时升级 engine_version 并更新此文档与测试。
5. 价格、促销、节假日、仓库地区需求未作为未来外生变量输入。若要支持这些，需要新的验证和情景参数；当前不宣称精准需求恢复。
6. 已有数据库可能缺失状态/库存历史；允许显示未知或暂停预测，不能为了演示把未知值强制改成 0。



## 数据基础与模拟数据运行说明

### 文件位置

| 位置 | 内容 |
|---|---|
| `docker/postgres/migrations/` | 增量 SQL；已执行文件不得修改，应新增版本 |
| `agents/python/shared/db_migrations.py` | 迁移锁、版本记录、文件校验和 |
| `scripts/migrate.py` | 保留业务数据的迁移命令 |
| `scripts/sales_data/config.py` | 历史长度、截止日、种子、生成版本 |
| `scripts/sales_data/generator.py` | 无数据库读写的模拟器 |
| `scripts/sales_data/writer.py` | 在调用方事务中批量写入 |
| `scripts/sales_data/validate.py` | 内存和数据库一致性校验 |
| `scripts/seed.py` | 初始化、显式重建、预览、校验入口 |
| `agents/python/shared/inventory_ledger.py` | 业务库存变更公共入口 |
| `agents/python/tests/test_sales_data.py` | 数据、迁移、流水测试 |


### 生成规则

- 保留原有 50 种商品、5 类、3 个仓库、演示账号和商品 UUID。
- 默认截至昨天的 180 个完整 UTC 日，支持 60～730 日；新商品只有最近 28 日记录。
- 商品覆盖 stable、growing、declining、weekly、intermittent、new、low_stock 场景。
- 每日需求结合基础值、趋势、周内周期、随机噪声；每 60 日中的第 38～42 日模拟九折和需求提升。
- 先生成需求，再检查实际库存；成交量受库存约束，缺货时不能继续生成无限销售。
- 每笔模拟订单暂为一种商品、1～3 件。商品小计与订单金额一致，使用当日历史单价。
- 顺序处理期初库存、历史到货、销售出库、取消释放和已完成历史退货的回库，得到当前库存。
- 正常商品有离线历史到货，低库存商品近期停止到货，以覆盖缺货场景。
- 取消样本约 4%；时间足够完成退货的样本约 2.5%，不是对真实运营比例的估计。
- 商品上架、下单、订单状态和退货处理时间相互协调，不出现未来已完成的状态。
- 当前商品价格对应最后一个历史日；客户累计消费按未取消、未退货订单重新汇总。
- 评论等辅助演示数据继续沿用模板规则。历史模拟折扣独立于当前网页的优惠券和活动规则。

同一生成版本、商品顺序、仓库/客户列表、种子、历史长度和截止日可重现销售业务数据。
密码盐、自增序号、实际写入时间不要求逐字节相同。
商品画像是模拟器配置，不能用于预测模型作弊；潜在未满足需求仅保存批次级诊断总量。
模拟器中的历史入库和退货不代表网页采购、在线退货已经实现。

### Windows 命令

从仓库根目录执行，以下路径使用项目已安装开发依赖的虚拟环境：

```powershell
cd C:\Users\12952\Documents\ELEC5620\ass2
```

仅内存预览，不连接数据库，也不需要 LLM API key：

```powershell
.\agents\python\.venv\Scripts\python.exe -m scripts.seed --preview --days 180 --seed 42 --end-date 2026-10-25
```

直接连接 PostgreSQL 前设置 `DATABASE_URL`；默认连接模板 localhost:5432 数据库。
只迁移结构，保留原有数据：

```powershell
.\agents\python\.venv\Scripts\python.exe -m scripts.migrate
```

初始化空库；已有用户或商品时迁移并保留原业务数据，同时补齐演示经理：

```powershell
.\agents\python\.venv\Scripts\python.exe -m scripts.seed
```

明确清空并重建业务演示数据：

```powershell
.\agents\python\.venv\Scripts\python.exe -m scripts.seed --reset --days 180 --seed 42
```

只读校验库存和订单金额：

```powershell
.\agents\python\.venv\Scripts\python.exe -m scripts.seed --check
```

### Docker

课程功能使用从当前源码构建的 **Python 后端**。上游预构建 Demo 镜像和 .NET 后端没有这里新增的
Checkout 行为；可以使用共享初始化脚本，但不能据此验证本阶段在线库存流水功能。

正常启动仍使用 `scripts/dev.ps1` 或 `scripts/dev.sh`，已有业务数据会保留。
凭据不匹配时退出，不再自动删除数据库卷。
显式重建使用 `-SeedOnly -ResetData`，Bash 对应 `--seed-only --reset-data`。
原有 `-Clean` / `--clean` 仍会明确删除 Docker 卷。

数据库已运行时，可以仅构建 seeder，再执行保留数据的迁移：

```powershell
docker compose --profile seed build seeder
docker compose --profile seed run --rm --no-deps seeder uv run --no-project python -m scripts.migrate
```

容器内校验或明确重建：

```powershell
docker compose --profile seed run --rm --no-deps seeder uv run --no-project python -m scripts.seed --check
docker compose --profile seed run --rm --no-deps seeder uv run --no-project python -m scripts.seed --reset --days 180
```

旧库迁移只记录迁移时刻的库存起点，此前库存历史未知。
要得到完整 180 日演示，应有意重建演示数据，不能将旧订单再次扣减当前库存。

### 分析服务与预测接入约定

- 第一版统一 UTC 业务日，时间以带时区时间存储；改时区要同步修改视图和生成器。
- 视图仅有事件日期。销量只能在已上架且记录覆盖的日期补零；库存静默日期延续此前余额。
- opening 之前的库存未知，不能补零；跨仓汇总之前先分别延续每个仓库余额。
- 缺货后的销量下降不等于需求下降，应结合库存历史标记受限时间段。
- `sales_daily` 使用当前订单状态，可能修订历史总量。回测应利用状态历史重建当时已知状态，
  不能把今天的取消/退货状态当作当时已知信息。
- 销售件数不等于订单笔数；商品明细金额不等于扣除优惠和退款后的净收入。
- `restock_schedule` 保留模板计划信息以兼容旧工具，不自动入库，默认库存预测也不计入。
- 补货建议只保存建议，查看、保存、接受建议都不调用库存写入函数。
  （2026-10-27 起由库存管理模块调整：经理**接受**补货建议时，会通过 `change_inventory` 记一笔 `restock_receipt`；生成、查看、拒绝建议仍然不改库存。预测本身依旧不计入未来入库。）

### 测试

测试使用 testcontainers 临时 PostgreSQL/Redis 容器，不使用业务数据库：

```powershell
cd C:\Users\12952\Documents\ELEC5620\ass2\agents\python
.\.venv\Scripts\python.exe -m pytest tests/test_sales_data.py tests/test_idempotency.py -q
```

覆盖生成规律、金额、时间、库存守恒、迁移幂等与校验和、普通初始化保留数据、显式重建、
库存事件重试、事务回滚，以及 Checkout 重复提交和并发库存保护。

## 数据字典与统计口径

### 原有业务表

| 表/字段 | 含义 |
|---|---|
| `products.id/category/seller_id/created_at` | 商品标识、类别、归属、上架时间 |
| `orders.created_at/status` | 下单时间、当前状态 |
| `orders.total/discount_amount` | 整单折扣后金额、折扣；关联多条明细后不能重复求和 |
| `order_items.quantity` | 明细商品件数 |
| `order_items.unit_price/subtotal` | 成交单价及未分摊整单优惠的商品小计 |
| `order_status_history.timestamp` | 状态发生时间，支持按截止时间回看 |
| `warehouse_inventory.quantity` | 商品在某仓库的当前库存 |
| `returns.status/resolved_at` | 退货处理状态、时间，不直接证明商品已经回库 |

原网页将订单标记 returned 的时点是申请退货，因此不能直接把该状态当成已收货入库。

### 新增 `inventory_movements`

| 字段 | 含义 |
|---|---|
| `id` | 自增序号，同一业务时间下按此排序 |
| `event_key` | 唯一业务事件标识，重复请求不得二次变动 |
| `product_id/warehouse_id` | 商品、仓库 |
| `movement_type` | opening、sale、historical_receipt、cancel_release、return_received，可扩展 |
| `quantity_delta` | 正数入库、负数出库；opening 允许零 |
| `balance_after` | 事件后的库存，不能为负 |
| `order_id/order_item_id/return_id` | 可选关联；目前 Checkout 关联到订单层级 |
| `dataset_run_id` | 模拟批次；在线业务事件为空 |
| `occurred_at` | 业务发生时间，用于历史分析 |
| `recorded_at` | 实际入库时间，不作为销售日期 |
| `notes` | 变动原因、旧库迁移起点等说明 |

每个商品/仓库只有一个 opening；`当前库存 = SUM(quantity_delta)`。
公共写入函数拒绝倒填会破坏余额顺序的事件，历史修复需要单独重算方案。

### 新增 `sales_dataset_runs`

字段为 `id`、`generator_version`、`random_seed`、`start_date/end_date`、`business_timezone`、
`config`、`summary`、`created_at`。
config 保存参数和商品画像；summary 保存订单、商品件数、流水、退货和未满足模拟需求总量。
生成画像和潜在需求诊断不是预测模型可以直接使用的未来数据。

### `sales_daily` 视图

粒度：UTC 下单日期 × 商品。无订单日期没有行。

| 字段 | 口径 |
|---|---|
| `order_count` | 涉及的不同订单数，包含全部状态 |
| `ordered_units` | 全部下单件数，包含后来取消、退货的订单 |
| `cancelled_units` | 当前 cancelled 订单件数 |
| `returned_order_units` | 当前 returned 订单件数，不等于实际回库件数 |
| `non_cancelled_units` | 未取消件数，包含退货单，不能标成扣退货后的净销量 |
| `ordered_item_amount` | 全部商品明细小计 |
| `non_cancelled_item_amount` | 未取消商品小计，不等于扣优惠、退款后的净收入 |

第一版分析服务可以采用 non_cancelled_units，同时分别显示取消和退货指标。
净销量/收入及退货影响归到下单日还是处理日，应在相应业务接入时明确。
品类订单数不能简单累加商品级 order_count，应重新 COUNT DISTINCT 订单。

### `inventory_daily_changes` 视图

粒度：UTC 事件日期 × 商品 × 仓库。
字段为 `net_change`、`outbound_units`、`returned_units`、`closing_quantity`。
closing_quantity 是当天最后一次事件的余额；无事件日期需要延续此前已知余额。
跨仓汇总日末库存前必须分别延续各仓余额，不能只相加当天有事件的仓库。

## 库存相关组员接入说明

### 已接通的路径

- Python Checkout 在同一事务中创建订单、扣库、写 sale 流水。
- Checkout 重试沿用原幂等机制；流水额外使用唯一 event_key。
- 网页/Agent/HITL 取消、网页/Agent 退货的库存回补留给对应组员完成。
- 模拟器的历史取消与退货是离线样本，不代表相应在线路径已经实现。

### 公共接口

复用 `shared.inventory_ledger.change_inventory`。ID 使用 uuid.UUID，数量为整数。
必须在业务事务中调用，业务授权、归属校验和退货数量判断由调用方完成。

```python
async with conn.transaction():
    # 先校验权限、归属、状态并锁定关联业务记录。
    await change_inventory(
        conn,
        product_id=product_id,
        warehouse_id=warehouse_id,
        quantity_delta=received_quantity,
        movement_type="return_received",
        event_key=f"return-received:{return_id}:{warehouse_id}:{product_id}",
        order_id=order_id,
        return_id=return_id,
        notes="Received and accepted for resale",
    )
    # 同一事务中更新退货业务状态。
```

函数负责行锁、防负库存、事件幂等及写入；同一个事件键携带不同业务参数会拒绝。
返回值为该事件执行后的余额，重复调用返回原事件余额，不是实时库存查询接口。
新商品先建立 quantity=0 的库存行，再记录首次入库；尚无流水时函数会创建当前余额起点。
多商品多仓库操作按商品 ID、仓库 ID 的统一顺序取得锁，避免交叉锁定。

### 业务时点

| 事件 | 库存约定 |
|---|---|
| 发起/同意退货 | 不增加库存 |
| 完成退款 | 单独判断是否回库，不自动增加库存 |
| 收到且可再次销售 | 记 return_received，回补实际接收数量 |
| 取消此前已扣库的订单 | 记 cancel_release，最多释放一次 |
| 人工调整实际库存 | 记录差值和原因，不能只 UPDATE quantity |
| 生成/保存/拒绝补货建议 | 不调用库存写入函数 |
| 接受补货建议（2026-10-27 新增） | 记 `restock_receipt`，event_key 为 `suggestion:<建议 ID>`，只执行一次 |
| 手工入库/出库/盘点（2026-10-27 新增） | 记 `manual_receipt` / `manual_issue` / `stock_count_adjustment`，必须填原因 |

取消可以通过订单 sale 流水确定实际扣减仓库，不要一律补到默认仓库。
如果以后支持分批验收，事件键还应包含验收批次标识，区分合法的不同批次与重复请求。
库存写入与对应业务状态更新必须共用事务，失败时整体回滚。
不需要开发网页采购、自动补货执行器。

### 接入后验证

执行 `python -m scripts.seed --check` 或 README 中对应容器命令。
绕过公共函数直接改库存，会造成余额与流水不一致；公共函数也会拒绝在不一致余额上继续写入。
可以新增流水类型和迁移，不得编辑已经执行过的 001 迁移。
旧库迁移前的库存历史未知，不能由现有订单反推出完整历史。

## 第一阶段历史验证记录

日期：2026-10-26。分支：`feature/sales-analysis-forecast`。

### 数据预览

```powershell
.\agents\python\.venv\Scripts\python.exe -m scripts.seed --preview --days 180 --seed 42 --end-date 2026-10-25
```

| 项目 | 结果 |
|---|---:|
| 历史范围 | 2026-04-29 ～ 2026-10-25 |
| 订单 / 明细 | 9,351 / 9,351 |
| 下单商品件数 | 13,929 |
| 库存流水 | 10,907 |
| 完成历史退货样本 | 239 |
| 未满足模拟需求件数 | 157 |

内存校验检查每一笔库存余额、订单金额、时间、出库与明细数量。
预览不会连接数据库；这些数字不是当前业务数据库的记录数量。

### 测试

本阶段测试：`tests/test_sales_data.py` 与 `tests/test_idempotency.py`，29 项通过。
数据库和 Redis 为 testcontainers 创建的临时容器。

覆盖旧库起点、不重复迁移、校验和保护、默认保留数据、显式重建可重现、每日视图、金额与库存对账、
错误事务回滚、事件键重试与冲突、并发 Checkout 防超卖和重复请求防二次扣库。

全仓库回归使用 UTF-8 模式（Windows 默认 GBK 无法读取部分已有 YAML 文件）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q --maxfail=3
```

结果：844 passed、3 skipped、2 failed。三项跳过因为没有 LLM 凭据。
两项失败位于未修改的 `tests/test_config_repo_root.py`，对 Linux 根路径的断言在 Windows 下出现盘符差异：
`/home/...` 与 `C:/home/...`，以及 `/app/shared` 与 `C:/app/shared`。
这是现有跨平台测试限制，不能把全仓库测试描述为全部通过。

PowerShell/Bash 启动脚本语法检查、三个 Compose 文件配置解析，以及新增 Python 模块 Ruff 检查通过。
仓库已有文件存在原有 lint 问题，不进行与本阶段无关的大规模重排。

### 数据边界

未对当前业务数据库执行迁移、初始化或重建；没有运行整个项目栈或调用付费 LLM。
第一阶段当时没有前端改动；第二阶段的浏览器验收结果见本文前半部分。
