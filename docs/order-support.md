# 智能客服订单支持（接力开发说明）

本文记录 `feature/order-refund-return` 分支的订单客服功能实现、行为约定和验证情况，供后续接力开发使用。

## 功能范围

- 商品追问由 Product Discovery Agent 处理；智能客服可查询订单、退货资格和退货状态，并执行购物车操作。订单客服 Agent 已接入当前用户的对话历史及记忆读取/保存工具。
- 订单、订单明细和状态历史已有数据库表及演示数据填充流程：`scripts/seed.py` 配合 `scripts/sales_data/writer.py` 写入订单模拟数据。
- 用户可以在订单详情页申请退货、下载演示面单，并将演示退货标记为已寄出。
- 符合条件的退货会自动批准；管理员在 Returns 页面模拟确认收货，系统随后自动将退款送入 Admin Approvals。
- 客服 AI 会先查询并核对订单归属和状态：明确取消请求且订单 UUID 已知时，系统强制调用取消工具；符合条件时可直接取消订单或提交退货申请，不再对这两类操作统一等待管理员审批。仅询问取消状态时不会触发新取消。
- 用户可以取消处于 `placed` 或 `confirmed` 状态的订单。取消操作锁定订单行、写入状态历史，并通过库存账本回补能追溯到的结账销售流水。没有可追溯流水的旧订单不猜测库存分配。
- 取消成功后的聊天回复只确认取消结果，并在工具返回回补数量时说明库存已释放；不主动提及演示结账、支付服务商或未处理付款，除非用户询问退款/支付。
- 下单仍通过商城 checkout 页面/API 完成；订单客服 Agent 没有聊天内直接创建订单的工具。

| 接力功能 | 当前状态 |
|----------|----------|
| 商品追问 | 已有 Product Discovery Agent 路由与商品查询能力 |
| 上下文记忆 | 对话历史会传给 specialist；订单客服 Agent 注册 `recall_memories` / `store_memory` |
| 加入购物车 | 聊天工具已支持加入、查看、移除及修改数量 |
| 聊天内生成订单 | 尚未实现；目前需使用 storefront checkout 页面/API |
| 订单 API 与演示数据 | 已有订单查询/取消/退货 API，订单与明细由 seed 流程填充 |
| 取消/退货/退款 | AI 会执行合格取消和退货申请；模拟收货后自动创建退款审批，管理员批准后完成演示退款 |

## 退货与退款规则

退货状态仅允许按以下方向转换：

```text
approved -> shipped_back -> received -> refunded
requested -> approved -> shipped_back -> received -> refunded  (legacy requests)
requested -> denied  (legacy requests)
```

- 退货仅适用于已送达订单，且必须在最近一次送达记录后的 30 天内申请。如果缺少送达记录，则保守地使用订单创建时间计算期限。
- 客服工具和网页入口都会检查退货资格；退货处理过程中会再次检查相关状态。
- 符合条件的退货申请会立即自动批准并生成演示面单，用户不需要等待第二次退货审批。客户可在申请时选择退款偏好（默认原支付方式）。
- 本项目没有真实承运人集成：客户点击“模拟退货寄出”，管理员在 Returns 页面点击“模拟承运人收货”，退货状态从 `shipped_back` 变为 `received`。原订单状态保持 `returned`，不会伪装成订单重新送达。
- 退货状态变为 `received` 时，系统在同一数据库事务内自动创建 `process_refund` 待审批记录。客户不需要再发起退款申请；管理员只能在 Admin Approvals 批准或拒绝。
- 订单详情和客服状态查询会区分退款审批中的 `pending`、已拒绝的 `denied` 与已完成的 `executed`，避免退货已收货但退款审批被拒绝时仍显示“等待审批”。
- 退款必须对应已收到的退货，不存在仅退款流程，也没有单独的退款时限或按近期退款次数拒绝的规则。30 天期限从订单送达起计算，限制退货申请。
- 管理员批准后，系统将退货标记为 `refunded`。当前没有支付服务商集成；系统会记录退款完成状态，但不会实际转账。取消订单也不会自动退款。
- 面单是演示 PDF，不含已购买的承运人邮资或取件服务。拒绝退货会撤销现有面单 URL；下载接口还会验证 token 与退货状态。
- 退款状态只会在管理员批准审批记录后变为 `refunded`；退款执行由幂等层保护。

## 退货与退款演示步骤

演示前准备一笔符合退货资格的客户订单：订单状态为已送达，且送达时间在最近 30 天内。若没有符合条件的订单，应先准备/填充演示订单数据；不要用未送达或超过退货期限的订单验证成功流程。

1. **客户申请退货**：登录客户账号，进入订单详情，提交退货原因并选择退款偏好（原支付方式或 store credit）。符合条件时退货会立即自动批准，页面显示 `approved` 并提供演示面单。
2. **客户模拟寄回**：下载面单（可选），点击“模拟退货寄出”。退货状态变为 `shipped_back`，等待管理员模拟收货。
3. **管理员模拟收货**：使用管理员账号进入 Admin → Returns，在对应退货上点击“模拟承运人收货”。退货变为 `received`，并自动产生一条退款审批；订单状态保持 `returned`。
4. **管理员审批退款**：进入 Admin → Approvals，批准该退款后，退货状态变为 `refunded`，页面显示退款已完成。若拒绝，退货仍为 `received`，但订单详情和客服状态会明确显示退款审批已拒绝，而不是仍在等待审批。
5. **客户核对状态**：回到订单详情，或在客服聊天中询问退货状态，确认显示与管理员操作一致。

此流程中的物流状态由人工推进，没有承运人回调或真实邮资。管理员批准退款后，系统记录 `refunded` 状态；当前没有支付服务商集成，因此不会实际转账。用户只提交一次退货申请；收到退货后退款审批自动创建，无需再次申请退款。

## 主要实现位置

- `agents/python/shared/return_policy.py`：30 天退货申请期限计算和状态转换表。
- `agents/python/shared/tools/return_tools.py`：Agent 退货资格、申请、状态查询和退款工具。
- `agents/python/shared/inventory_ledger.py`：按现有销售流水生成幂等的取消库存回补流水。
- `agents/python/shared/hitl.py`：管理员审批队列、批准后的退款执行和库存回补。
- `agents/python/shared/idempotency.py`：幂等预留、成功结果缓存与失败重试。
- `agents/python/orchestrator/routes/legacy.py`：订单取消、网页退货、管理员退货处理及面单下载 API。
- `agents/python/order_management/agent.py`、`agents/python/order_management/tools.py`：订单客服 Agent 的工具注册与行为。
- `agents/python/config/prompts/order-management.yaml`：订单客服流程提示词和支付边界。
- `web/src/app/(app)/orders/[id]/page.tsx`：客户订单详情和退货流程。
- `web/src/app/(app)/admin/returns/page.tsx`：管理员退货队列。
- `web/src/lib/api.ts`、`web/src/lib/nav.ts`、`web/src/lib/toast.ts`：前端 API、导航和提示。

## 新增 API

以下路由由 orchestrator 提供，受用户或管理员 JWT 鉴权（面单下载使用不可预测的 token）：

| 方法 | 路由 | 用途 |
|------|------|------|
| `POST` | `/api/orders/{order_id}/cancel` | 取消允许取消的订单 |
| `POST` | `/api/orders/{order_id}/return` | 为符合条件的订单申请退货 |
| `POST` | `/api/orders/{order_id}/return/shipped` | 将已批准的退货标记为已寄回 |
| `GET` | `/api/admin/returns` | 管理员查看退货队列 |
| `POST` | `/api/admin/returns/{return_id}/status` | 管理员推进退货状态 |
| `GET` | `/api/returns/{label_token}/label` | 下载有效退货流程的演示面单 |

订单详情响应包含 `return_eligibility` 和 `return` 字段；前者说明是否可以发起退货，后者包含已存在退货的状态、面单信息及 `refund_approval_status`。退款审批状态为 `pending`/`processing` 时表示等待管理员处理，`denied` 表示被拒绝，`executed` 表示管理员已批准并将退款记录为完成。

## 数据库迁移约定

本功能没有新增或修改数据库迁移。后续如需变更 schema，应接着当前最大迁移编号新建迁移，不得修改已经执行过的迁移文件。

## 验证记录

在 `agents/python` 目录运行：

```powershell
uv run --active pytest tests\test_return_policy.py tests\test_tool_input_validation.py tests\test_prompt_loader.py tests\test_idempotency.py tests\test_return_replace_workflow.py -q
uv run --active ruff check --ignore E501,F841,F541 shared/return_policy.py shared/tool_inputs.py shared/tools/return_tools.py shared/hitl.py orchestrator/routes/legacy.py tests/test_return_policy.py tests/test_tool_input_validation.py tests/test_idempotency.py tests/test_prompt_loader.py tests/test_return_replace_workflow.py
uv run --active ruff format --check shared/return_policy.py shared/tool_inputs.py shared/tools/return_tools.py tests/test_return_policy.py tests/test_tool_input_validation.py tests/test_prompt_loader.py tests/test_return_replace_workflow.py
pnpm exec tsc --noEmit
pnpm exec eslint "src/app/(app)/admin/returns/page.tsx" "src/app/(app)/orders/[id]/page.tsx" src/components/chat/return-card.tsx src/lib/api.ts src/lib/toast.ts
git diff --check
```

- 上一轮 Python 退货/退款回归测试有 85 项通过；本次将退货申请期限调整为 30 天，并补充订单历史按退货/退款状态展示。
- Ruff 检查在忽略既有 `E501`、`F841`、`F541` 风格问题后通过；选定 Python 文件的格式检查通过。
- `pnpm exec tsc --noEmit` 通过。前端 ESLint 为 0 错误、19 条既有警告（`any` 和 `<img>`）。
- `git diff --check` 通过。
