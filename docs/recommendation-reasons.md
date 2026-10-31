# 推荐理由生成：Zicong 的开发与演示说明

> 当前分支已统一为顾客、店铺经理、管理员三种业务身份；经理接管原商家职责并管理全店。经营接口仅限经理；管理员不继承经营和购物权限。迁移已到 007，后续从 008 开始。见[单店角色说明](single-store-management.md)。以下保留原交接阶段记录，角色和迁移编号以新说明为准。

这部分对应组内分工中的“推荐理由生成——总结文档、客户评价、商品介绍、数据库内容填充和接口”。实现位于 Python 后端和共用 Next.js 前端，开发分支为 `feature/zicong-recommendation-reasons`。保留原项目的 MAF、数据库查询、鉴权和限流方式。

## 小组接力开发

此分支已整合 `feature/marketing-assist` 的 `bfea1d3`，包含前两位同学的销量分析、预测、库存管理与营销辅助。推荐功能在这些功能之上继续开发。整合发生在个人分支，未合并到 `main`；下一位同学应从该个人分支创建自己的新分支，再继续开发。

```powershell
git fetch origin
git switch -c feature/your-next-task origin/feature/zicong-recommendation-reasons
```

`feature/your-next-task` 是示例名称，请换成自己的任务名称。已有未提交改动时先保存自己的工作。前两位同学的交接说明见 `docs/sales-analysis/README.md`、`docs/inventory-management/README.md` 和 `docs/marketing-assist/README.md`。

数据库迁移 `001`–`005` 保留同学原文件；推荐资料迁移调整为 `006_recommendation_evidence.sql`。当前下一份新增迁移从 `007` 起编号，开发前先检查远程分支是否已有新增编号。所有迁移统一通过 `shared.db_migrations.apply_migrations` 执行，不修改已经应用的文件。推荐导入器同样使用此入口。

## 实现内容

| 内容 | 实现 |
|---|---|
| 推荐依据 | 从数据库读取当前商品资料、最多 4 份文档、最多 8 条未被标记的评价及库存 |
| AI 生成 | 先直接回答用户要求能否满足，再生成商品/文档摘要、评价摘要、推荐理由和取舍 |
| 引用 | 每个观点带来源 ID；接口拒绝不存在的引用和来源类型错误的摘要 |
| 资料不足 | 显示缺少文档、没有评价、样本较少、库存未知或缺货等提示 |
| 数据填充 | 50 件原始演示商品的介绍，以及其中 8 件商品的购买参考和 16 条模拟评价 |
| 演示选项 | 50 件商品的补充属性：39 件的颜色、11 件的尺码、10 本书的语言，以及电路板外观说明；与原规格分开标记来源 |
| 页面 | 商品详情中的 **Is this product right for me?**，支持需求、预算、英文/中文输出及来源展开 |
| Agent 集成 | Product Discovery 增加读取依据和生成理由两个 MAF 工具；直接调用和 MCP 模式均注册 |
| 费用记录 | 返回 input/output token 数，并记录 `usage_logs`；浏览商品或查看资料不会触发 AI 生成 |

商品介绍由原有描述和规格整理而来；额外购买参考及评价为 AI 编写的课堂演示内容，明确标记为 synthetic。它们不是厂商文件或真实客户反馈。导入不会改写原商品描述，也不会删除已有评价。旧数据库中来源不明的评价不会被自动猜测为模拟评价，应由数据所有者核实其来源。

这不是完整的推荐系统重写：沿用已有搜索、筛选和比较功能；本次新增针对“为什么适合我”的解释。没有新增任意 PDF 上传、向量检索流水线或 .NET 同等接口。引用检查不能证明每句话的语义正确，仍须用真实模型测试内容质量。

## 在这台电脑上查看

项目路径：`C:\Users\13506\Desktop\5620\mutiple-agent`。

数据库已在独立的 Docker Compose 项目 `zicong-recommendation` 中初始化。日常重启只需要启动 Docker Desktop，然后在项目根目录运行：

```powershell
docker compose -p zicong-recommendation up -d db redis
```

打开第一个 PowerShell 窗口，启动后端：

```powershell
cd C:\Users\13506\Desktop\5620\mutiple-agent\agents\python
.\.venv\Scripts\python.exe -m uvicorn orchestrator.main:app --host 127.0.0.1 --port 8080
```

打开第二个 PowerShell 窗口，启动前端：

```powershell
cd C:\Users\13506\Desktop\5620\mutiple-agent\web
pnpm dev --hostname 127.0.0.1
```

浏览器访问 <http://127.0.0.1:3000/shop/products>，搜索 `Sony`，进入 **Sony WH-1000XM5** 商品详情，向下找到 **Is this product right for me?**。

1. 点击 **View product info & reviews**：无需 API key，读取数据库资料和来源。
2. 填写需求，例如 `I need noise cancelling for commuting and multipoint connection.`。
3. 预算填 `350`，语言选 English 或中文。
4. 点击 **Assess this product for me**：这一步才调用模型，消耗 API 额度。
5. 检查摘要、推荐理由和取舍，点击引用编号核对来源；再用低于商品价格的预算检验预算提示。

这一商品页面的功能只需要数据库、Redis、orchestrator 和 web。若要通过整个聊天机器人演示，还需要按原项目启动步骤运行 Product Discovery 等 specialist 服务并配置 `AGENT_REGISTRY`。已注册工具不等于已经完成真实模型的聊天联调。

聊天入口也属于搜索与推荐的验收范围。访问 `/shop/assistant`，输入 `I want to buy a earphone, my buget is 300`：当前演示库应能返回 $299.99 的 Sony WH-1000XM5，并说明这是相关的头戴式耳机，而非保证存在入耳式产品。原词查无结果时，系统会以相关的 `headphones` 用词补查，保留预算、分类、评分及在售条件；有精确匹配时不补查，明确要求 in-ear/earbuds 时也不会启用这一补查。该补查只覆盖这些英语耳机用词，不是通用的跨语言语义检索。

聊天页面已修复开发模式下重复追加文字和执行步骤的问题，并在 specialist → orchestrator → 浏览器之间保留流式文本的换行，使商品卡片和 Markdown 可以正常解析。旧页面里已经生成的重复文字不会自动清理，验收时打开新聊天或重新发送问题。没有匹配商品时仍应如实返回无结果，例如目前演示库没有女士连衣裙。

终端显示地址已占用时，通常是已有服务正在运行；直接打开页面即可，不要再重复启动。关闭前后端窗口中的服务使用 Ctrl+C。停止本次数据库可运行 `docker compose -p zicong-recommendation stop db redis`，数据仍保留。

## 配置自己的 OpenAI API

在 [OpenAI API keys](https://platform.openai.com/api-keys) 创建自己的 key，然后只在本机项目根目录的 `.env` 中填写：

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=在这里填写自己的密钥
LLM_MODEL=gpt-4.1
```

保留 `.env` 中原来的数据库地址和随机生成的本地鉴权配置。不要把密钥写进网页代码、截图、Jira、GitHub 或聊天消息。`.env` 已被 Git 忽略。修改后重启 Python 后端；无需重新构建前端。

模型沿用原项目的 `gpt-4.1`。实际可用性取决于自己的 API 项目；创建 key 不代表账户已具备可用额度。账户设置参见 [OpenAI 官方 Quickstart](https://developers.openai.com/api/docs/quickstart)。组内分摊时保留自己 API 项目的用量记录；应用记录的 token 供对照，模型失败、重试等情况不一定能返回完整用量，账单以服务商记录为准。

## 数据库迁移和填充

新建数据库先执行 `docker/postgres/init.sql`，再执行所有增量迁移。已有数据库也应执行完整迁移链，或运行下面的推荐导入器自动迁移：

```powershell
# 在项目根目录；默认只预览，不写入。
.\agents\python\.venv\Scripts\python.exe scripts\seed_recommendation_content.py

# 明确应用：增量迁移 + 演示资料。
.\agents\python\.venv\Scripts\python.exe scripts\seed_recommendation_content.py --apply
```

导入器通过固定 UUID 实现重复执行不重复插入，仅更新自己创建且标为模拟的数据。它要求商品目录已经存在；使用其他商品名称时会报告未匹配的 8 个演示配置，不会自动创建不属于项目的商品。介绍条数取决于当前有效商品数，50 是原始演示目录的数量。

整合后的 `scripts/seed.py` 默认应用迁移并保留已有业务数据；只有明确使用 `--reset` 才清空并重建。补充推荐资料使用这里的独立导入器即可，不需要重建。已有数据库不会自动获得同学新生成的 180 天历史销量；需要完整历史演示时，按销量分析文档在独立的新数据库初始化。

若只想更新表结构，不导入演示内容，在项目根目录运行 `.\agents\python\.venv\Scripts\python.exe -m scripts.migrate`。该命令从环境变量 `DATABASE_URL` 读取连接；未设置时使用文档中的本地默认库。迁移按顺序执行并记录校验和，重复运行不会重复应用。推荐迁移 `006` 只新增 `product_documents` 表和 `reviews.is_synthetic` 字段，不删除旧记录。

## 给组员的接口

### 读取依据，不调用 AI

`GET /api/products/{product_uuid}/recommendation-evidence`

返回 `product`、`sources`、`warnings`、`review_statistics`。评价总数与平均分按未被标记的真实数据库行计算，不相信商品表的缓存统计；摘要输入为分层采样的最多 8 条评价，包含不同评分档。

### 生成解释，需要服务端 API key

`POST /api/products/{product_uuid}/recommendation-reasons`

```json
{
  "preferences": "Noise cancelling for commuting and multipoint connection",
  "max_budget": 350,
  "language": "en"
}
```

`preferences` 必填，去除两端空格后 1–1500 字符。预算可不填或为 null，范围 0–1,000,000；0 不会被当作未填。语言为 `en` 或 `zh`。

返回 `product_summary`、`review_summary`、`reasons`、`cautions`（每项含 `text` 和 `source_ids`），以及 `product`、`budget_fit`、`sources`、`warnings`、`review_statistics`、`usage`。Agent 的商品卡片必须使用返回的 `product` 字段；不要从示例卡片抄评分、价格或图片地址。

返回值另含必填的 `needs_assessment`（`status`、`text`、`source_ids`），在界面 **Does it meet your needs?** 中优先展示。`status` 为 `meets_needs`、`does_not_meet` 或 `cannot_confirm`。提示词要求直接回答用户的具体需求；例如资料没有颜色时，应先说“无法确认红色款”，不能推断红色缺货，也不能用预算符合代替颜色符合。总库存不是颜色/尺码版本的库存证据。状态属于模型对资料的判断，引用校验只验证来源，不能证明判断语义正确。

每次生成的结构化输出 schema 将 `source_ids` 限定为本次查询所得的来源编号，避免模型抄错 UUID 导致整份回答被拒绝。商品摘要只允许商品/文档来源，评价摘要只允许评价来源；没有评价时强制评价摘要为空。服务端仍会校验返回结果，不替换、猜测或忽略无效引用。该约束不改变接口字段，也不保证每条陈述在语义上正确。

已知超预算或总库存为零时，输出 schema 只允许 `does_not_meet`，不能生成“符合”或“尚待确认”的状态。库存记录缺失与库存为零分别处理。提示词用具体例子区分：简单的已列出颜色偏好为 `meets_needs`；未列出的颜色/语言为 `cannot_confirm`；询问某种颜色或颜色尺码组合的库存时，没有对应库存证据就不能确认。总库存不能在任何摘要段落中解释为所有颜色都有货。

对可完整识别的单一颜色偏好（例如 `I want a Black one` 或“我想要一个黑色的”），服务端从结构化颜色列表和对应引用确定直接结论，并在输出 schema 中固定该结论。仅在总库存已知大于零且没有超预算时启用；回答同时说明该颜色的库存未单独记录。这不是通用的自然语言颜色识别：缺失颜色、否定、库存询问、尺码组合、其他要求或未匹配的句式仍按正常证据评估，不强行判定满足。

用户修改需求、预算或回复语言后，界面清除旧结论及对应警告；只有再次点击生成按钮才发起新的付费请求，避免旧预算结论被误认为新结果。

### 补充演示颜色和尺码

```powershell
# 预览，默认不写入数据库
.\agents\python\.venv\Scripts\python.exe scripts\seed_catalogue_options.py
# 备份后写入缺失的演示选项
.\agents\python\.venv\Scripts\python.exe scripts\seed_catalogue_options.py --apply
```

选项定义在 `scripts/data/catalogue_options.json`，写入 `products.specs.demo_options`，带 `is_synthetic` 和来源说明，不覆盖原有技术规格、价格、描述、评价或库存。若商品已有对应颜色/尺码字段或已有 `demo_options`，导入保留已有值。重复执行不会重复插入或覆盖后来修改的选项。备份保存于 `.claude/recommendation-checks/catalogue-options-backup-*.json`，含每个修改商品的 ID、原规格和新规格。

商品详情接口和 Product Discovery 的详情工具原本就返回 `specs`，因此能直接读取新选项。公开和登录后的商品页均展示 **Product options**。推荐依据将演示选项单独列为 `demo-options:{product_id}` 来源，保留原始数据的来源属性。

例如 Hydro Flask 的演示颜色是 Red、Black、White、Blue。前台按课程项目中的商店场景回答“商品资料列有红色”；问紫色时回答“商品资料未列紫色”。这不代表品牌真实销售范围。库存和购物车目前仍按商品管理，未实现颜色/尺码 SKU、组合库存或颜色选择下单，因此不能从总库存推断红色款数量。要演示精确颜色库存和履约，需要另行扩展库存与订单模型。

按项目要求，推荐窗口使用普通商城口吻，不在回答、警告或展开的资料中反复显示 demo/synthetic/test 字样。`recommendation-presentation.ts` 只投影本项目生成资料的显示文字，数据库和接口仍保留原始文本、`is_synthetic`、来源和引用 ID，便于审计或替换资料。库存未知、缺货、超预算、评价样本不足等事实提示仍展示。模型不得因调整语气而编造库存、认证或“已验证购买”。

不存在/已下架商品返回 404；参数错误返回 422；缺 key、模型失败、超时、无效引用或数据库不可用返回 503，不用虚构文本补结果。生成请求沿用聊天限流。客户端使用已有同源 `/api` 代理，API key 始终保留在 Python 服务端。

内部工具名称为 `get_recommendation_evidence` 和 `generate_recommendation_reasons`。单商品详细解释会额外启动一次受 45 秒超时约束的 MAF 调用；SDK 底层可能重试。多商品推荐提示词要求读取各商品依据后直接组织答案，减少重复生成。

## 验证与合并

2026-10-28 接力整合验证记录：

- 推荐、搜索、SSE、经理分析、库存和营销相关后端测试共 182 项通过；前端 218 项通过。
- 完整 Python 套件初次执行为 1005 项通过、5 项 Windows 兼容性失败，覆盖率 81.62%。已修复启动脚本的 PowerShell 5.1 字符编码问题，以及两项测试的绝对路径写法；这 5 项随后单独重跑全部通过。未将该结果描述为完整套件一次全部通过。
- 两个 MCP 包分别通过 16 项非集成冒烟测试，共 32 项。包内测试同名，需像 CI 一样分别运行。
- TypeScript、生产构建通过；完整前端 ESLint 为 0 错误、64 警告。整合涉及的 Python 文件 Ruff 通过；全库仍有原有 Ruff 问题，未进行无关的批量改写。
- 浏览器共 8 项通过：聊天单气泡/Markdown、桌面/手机推荐资料、经理登录/分析/筛选/购物限制，以及两项真实推荐生成（中文低预算、未列出的绿色）。两次真实只读购物聊天完成，搜索、推荐、比较的工具调用均成功。
- 本地数据库先执行完整备份，再应用 `001`–`006`；50 件商品、516 条评价、58 份资料、150 条仓库库存、200 笔订单及 505 条订单明细的内容校验值均未改变，第二次迁移为空操作。另使用同学的账户初始化器准备了本地经理演示账户，未重置已有用户。

本轮未调用付费营销生图，也未执行真实下单或付款；库存/营销写入逻辑在隔离测试库验证。销量历史保留本机原有数据，未清空并重新生成。

无需真实 key 的验证：

```powershell
cd agents\python
.\.venv\Scripts\python.exe -m pytest -q tests/test_recommendation_validation.py tests/test_recommendation_evidence.py

cd ..\..\web
pnpm test
pnpm exec tsc --noEmit
pnpm lint
pnpm build

# 前后端启动且数据库已填充时，验证电脑和手机页面；不会调用模型。
pnpm exec playwright test e2e/recommendation-evidence.spec.ts

# 只在手动验收时运行：当前包含九次真实生成请求，会消耗额度。
$env:RUN_LIVE_RECOMMENDATION = 'true'
pnpm exec playwright test e2e/recommendation-live.spec.ts
Remove-Item Env:RUN_LIVE_RECOMMENDATION
```

Python 集成测试使用独立的 testcontainers PostgreSQL，不操作本地演示数据库。证据页面的浏览器测试只读取本地数据；显式启用的 live 测试会调用 AI。两者均不创建订单。

真实模型验收至少检查：正常需求的引用是否支持结论；低预算是否明确提示不匹配；没有评价时不编评价；模型不可用时显示失败提示。聊天路径还需单独验证 Product Discovery 调用新工具及保留来源说明。

### 2026-10-28 推荐功能回归记录

- 本地 50 件在售商品的依据接口逐个通过，来源 ID 唯一，商品范围、评价数和抽样数量一致。
- 78 项后端测试通过，覆盖引用约束、预算/库存约束、实际 PostgreSQL 读取、搜索过滤与同义词回退、SSE 消息完整性。
- 196 项前端测试通过，覆盖错误恢复、重复点击、取消请求、输入修改后清除旧结果等；相关 ESLint、TypeScript 和生产构建通过。
- 11 项浏览器/API 集成检查通过：2 个免费证据页面检查（电脑/手机）及 9 次真实生成，包含已列出/未列出颜色、颜色库存、零预算、刚好达到商品价格的预算、颜色尺码组合、缺失语言版本、1500 字中文复合需求和低预算中文回答。颜色尺码的独立列表不能证明具体组合存在，另做了该措辞的定向复测。
- 额外在一次性 PostgreSQL 容器里验证无评价/无文档/无库存记录和零库存，调用真实模型，未修改本地商城商品；两种场景均通过，未编造评价。
- 主页聊天接口的预算内耳机搜索、Sony/AirPods 比较均完成，工具调用无错误，并返回对应商品卡片数据。

本轮修复了缺失颜色的状态判断、将总库存扩展到颜色库存的表述，以及修改条件后仍显示旧结论的问题；并对已知超预算和缺货的状态增加了 schema 约束。模型文字仍需依据核对：结构化输出限制格式和引用集合，不保证所有陈述都正确，见 [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)。本轮检查不覆盖下单、支付、所有聊天路由或 .NET 实现。

### 2026-10-28 最终交接复查

- 发现并修复：单一颜色偏好已与颜色列表匹配时，模型仍可能返回 `cannot_confirm`。现在上述窄范围请求使用固定的、有引用的目录结论；颜色库存仍不作承诺。提示词版本为 `1.5`。
- 修正浏览器测试的误报：允许“没有独立降噪测试数据”这类有意义的资料缺失说明，继续检查前台不反复出现演示目录或模拟评价措辞。
- 本次改动的推荐后端测试 64 项全部通过；Ruff、TypeScript 和修改文件的 ESLint 通过。
- 修正后完整重跑推荐浏览器检查，11 项全部通过（桌面/手机证据页面 2 项、真实 AI 生成 9 项），包含预算、列出/未列出颜色、颜色库存和尺码组合等边界。
- 接力整合基线 `40d6586` 的 GitHub 检查已完成：22 项成功，2 项按配置跳过。本次后续提交的检查状态以对应提交的 GitHub 页面为准。

开发代码先提交、推送到个人分支，再在 GitHub 创建 Pull Request，请组员检查改动和演示。等自动检查、真实 AI 验证及组员 review 完成后再合并。不要从本地直接把个人代码强制推送覆盖 `main`。
