# 上架 AI 营销辅助：开发记录

## 2026-10-27

### 准备
- 库存模块已提交（`a4c8a12`，没有 push），从它切出 `feature/marketing-assist`。
- 已实测 OpenAI key 可以调用 `gpt-image-1-mini`：1024×1024、low 质量一张约 9 秒。
- 查了前端怎么访问后端：`web/src/app/api/[...path]/route.ts` 把浏览器发出的所有 `/api/*` 请求原样转发给 orchestrator，二进制响应也直接透传。所以图片可以存进数据库，用相对地址 `/api/media/<id>` 访问，不用挂 Docker 卷，也不用配 CORS。
- 写好 `plan.md`。

### 实现
| 文件 | 内容 |
|---|---|
| `docker/postgres/migrations/005_marketing_assist.sql` | `marketing_generations`（每次生成的记录）、`generated_images`（图片二进制） |
| `agents/python/shared/marketing.py` | 请求模型、文案 prompt 和 JSON Schema、数字校验 `valid_variants`、图片 prompt 模板、OpenAI 调用、生成和记录、读图 |
| `agents/python/orchestrator/routes/marketing.py` | `POST /api/manager/marketing/copy`、`POST /api/manager/marketing/images`、公开的 `GET /api/media/{id}`（带长缓存头） |
| `web/src/components/manager/inventory.tsx` | 新增商品表单里的 `MarketingAssist` 区：卖点、人群、语气、图片风格、背景；候选卡片，点"使用"就填进表单；选中的图片显示预览 |
| `agents/python/tests/test_marketing_assist.py` | 9 项测试 |

实现时的几个细节：
- **生成出错一律返回 503**：provider 抛异常、返回的 JSON 不合法、全部候选都没通过校验，都返回 503，提示"表单没有变化，请重试或手动填写"，对应 UC3/UC4 的 service unavailable 扩展流程。失败也会记进 `marketing_generations`（status=failed）。
- **writer / generator 默认值用 None**：真实客户端在调用时才取，测试直接用 monkeypatch 替换模块里的属性，不用去改函数的默认参数。
- **异常类名**：仓库的 ruff 规则 N818 要求异常类以 Error 结尾，所以叫 `MarketingUnavailableError`。
- **image_url 存相对地址** `/api/media/<id>`：浏览器经过 Next 的 `/api/*` 代理访问，不受部署地址影响。

### 测试中发现：数字校验的漏洞
- 首次运行时，`test_variant_numbers_must_come_from_the_input` 失败了：编造的 "2-year warranty" 没有被拦下。原因是商品名 "Lumo Desk Lamp **2**" 里的 2 被算进了"允许出现的数字"。
- 修复：允许的数字只从类别、描述、人群、关键词和价格里取。商品名和品牌在校验前已经从文案里去掉了，所以它们的数字不能再用来放行文案里其他位置的同一个数字。

### 让 Jingtong 的迁移测试不再写死列表
- `test_sales_data.py::test_migration_baselines_...` 原本写死了迁移列表。库存模块加 004 时我改过一次，这次加 005 又失败了。之后 Siqi 他们加迁移还会再碰到同样的问题。
- 改为和磁盘上实际的迁移文件比较（`migration_directory()`），同时保留"前三个是 Jingtong 的 001–003"这个断言。测试原来要检查的东西（每个迁移按顺序只执行一次）没有变。

### 真实环境
- 重新构建 seeder、orchestrator、frontend，用 `scripts.migrate` 在原有数据库上增量执行了 005，数据保留。
- 用真实 key 测试，结果见 `test-record.md`：文案 4 秒，图片 9.5 秒，生成的图片质量可以直接用作商品图。

### 用户试用后的表单改进（10-27）
用户实际点页面后反馈："不知道哪些必填、各个框该填什么"。改动只涉及 `web/src/components/manager/inventory.tsx` 的 `NewProductForm` / `MarketingAssist`：
- **顺序**：基本信息 → AI 营销辅助 → 图片和库存 → 保存。先填好信息，再让 AI 生成。
- **必填提示**：Name、Category、Price、Description 的标签加 `*`。必填项空着离开输入框，或点保存时还没填，输入框会变红（用 `aria-invalid`，复用 Input 组件自带的红色样式），并提示 "Please fill in the fields marked in red"。生成按钮不再是灰色不可点：没填 Name / Category 就点生成，会把这两个框标红并说明原因。
- **灰色示例文字**（placeholder，输入时消失）：每个框都给了例子，比如 Audience 写 "e.g. home coffee lovers"，卖点提示"用逗号隔开"，图片的 Background 改名为 "Image scene"，并说明是"图片里要出现什么"。
- **Category 改成下拉框**：选项来自 Jingtong 已有的 `/api/manager/catalog`，即现有商品的类别，另外加一项 "Other (add a new category)…"，选了之后可以输入新类别。后端本来就接受任意类别名，所以不用改后端。
- 验证：`tsc` 和 `eslint` 通过，前端容器已重新构建。交互效果还需要用户在浏览器里确认。
- **选中反馈**（用户第二轮反馈）：点"Use this version"后，这张卡片会加粗主色外框、加阴影和浅色底，右上角显示"In use"标记，按钮变为"Selected (filled into the form)"；重新生成文案后，选中状态会清空。生成的图片也用同样的样式，选中的图片按表单当前的 image_url 判断。`tsc` 和 `eslint` 通过，前端容器已重新构建。
