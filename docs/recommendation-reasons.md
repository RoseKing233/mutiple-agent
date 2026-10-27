# 推荐理由生成：Zicong 的开发与演示说明

这部分对应组内分工中的“推荐理由生成——总结文档、客户评价、商品介绍、数据库内容填充和接口”。实现位于 Python 后端和共用 Next.js 前端，开发分支为 `feature/zicong-recommendation-reasons`。保留原项目的 MAF、数据库查询、鉴权和限流方式。

## 实现内容

| 内容 | 实现 |
|---|---|
| 推荐依据 | 从数据库读取当前商品资料、最多 4 份文档、最多 8 条未被标记的评价及库存 |
| AI 生成 | 根据用户需求和预算，生成商品/文档摘要、评价摘要、推荐理由和取舍 |
| 引用 | 每个观点带来源 ID；接口拒绝不存在的引用和来源类型错误的摘要 |
| 资料不足 | 显示缺少文档、没有评价、样本较少、库存未知或缺货等提示 |
| 数据填充 | 50 件原始演示商品的介绍，以及其中 8 件商品的购买参考和 16 条模拟评价 |
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

新建数据库会从 `docker/postgres/init.sql` 得到新表和字段。已有数据库需执行增量迁移，或运行下面的导入器自动迁移：

```powershell
# 在项目根目录；默认只预览，不写入。
.\agents\python\.venv\Scripts\python.exe scripts\seed_recommendation_content.py

# 明确应用：增量迁移 + 演示资料。
.\agents\python\.venv\Scripts\python.exe scripts\seed_recommendation_content.py --apply
```

导入器通过固定 UUID 实现重复执行不重复插入，仅更新自己创建且标为模拟的数据。它要求商品目录已经存在；使用其他商品名称时会报告未匹配的 8 个演示配置，不会自动创建不属于项目的商品。介绍条数取决于当前有效商品数，50 是原始演示目录的数量。

**不要对已有数据库重新运行原项目的 `scripts/seed.py` 来更新本功能。该脚本会清空并重建演示数据。** 本机已初始化，不需要再运行它。只有确认全新且空的演示库时，才使用原项目初始化步骤。

若只想添加表结构，不要演示内容，在 PostgreSQL 中执行 `docker/postgres/migrations/005_recommendation_evidence.sql`。迁移只新增 `product_documents` 表和 `reviews.is_synthetic` 字段，不删除旧记录。

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

不存在/已下架商品返回 404；参数错误返回 422；缺 key、模型失败、超时、无效引用或数据库不可用返回 503，不用虚构文本补结果。生成请求沿用聊天限流。客户端使用已有同源 `/api` 代理，API key 始终保留在 Python 服务端。

内部工具名称为 `get_recommendation_evidence` 和 `generate_recommendation_reasons`。单商品详细解释会额外启动一次受 45 秒超时约束的 MAF 调用；SDK 底层可能重试。多商品推荐提示词要求读取各商品依据后直接组织答案，减少重复生成。

## 验证与合并

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

# 只在手动验收时运行：这一条会产生一次真实生成请求并消耗额度。
$env:RUN_LIVE_RECOMMENDATION = 'true'
pnpm exec playwright test e2e/recommendation-live.spec.ts
Remove-Item Env:RUN_LIVE_RECOMMENDATION
```

Python 集成测试使用独立的 testcontainers PostgreSQL，不操作本地演示数据库。浏览器测试读取本地演示数据，不创建订单或调用 AI。

真实模型验收至少检查：正常需求的引用是否支持结论；低预算是否明确提示不匹配；没有评价时不编评价；模型不可用时显示失败提示。聊天路径还需单独验证 Product Discovery 调用新工具及保留来源说明。

开发代码先提交、推送到个人分支，再在 GitHub 创建 Pull Request，请组员检查改动和演示。等自动检查、真实 AI 验证及组员 review 完成后再合并。不要从本地直接把个人代码强制推送覆盖 `main`。
