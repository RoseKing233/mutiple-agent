# 智能客服订单支持（接力开发说明）

本文记录 `feature/order-refund-return` 分支的订单客服功能实现、行为约定和验证情况，供后续接力开发使用。

## 功能范围

- 智能客服可查询订单、退货资格和退货状态，并执行购物车操作；订单客服 Agent 已接入当前用户的记忆读取与保存工具。
- 用户可以在订单详情页申请退货、查看处理状态，并对已批准的退货标记寄回。
- 管理员可以在 Returns 页面审核退货、确认收货及完成演示退款。
- 用户可以取消处于 `placed` 或 `confirmed` 状态的订单。取消操作锁定订单行、写入状态历史，并通过库存账本回补能追溯到的结账销售流水。没有可追溯流水的旧订单不猜测库存分配。
- 下单仍通过商城 checkout 页面/API 完成；订单客服 Agent 没有聊天内直接创建订单的工具。

## 退货与退款规则

退货状态仅允许按以下方向转换：

```text
requested -> approved -> shipped_back -> received -> refunded
requested -> denied
```

- 退货仅适用于已送达订单，且必须在最近一次送达记录后的 30 天内申请。如果缺少送达记录，则保守地使用订单创建时间计算期限。
- 客服工具和网页入口都会检查退货资格；退货处理过程中会再次检查相关状态。
- 只有管理员确认收到寄回商品后，才能将退货标记为 `refunded`。
- `refunded` 仅代表演示流程完成。当前没有支付服务商集成，不会实际转账；取消订单也不会自动退款。
- 面单是演示 PDF，不含已购买的承运人邮资或取件服务。拒绝退货会撤销现有面单 URL；下载接口还会验证 token 与退货状态。
- 退款幂等层只缓存成功结果。可恢复的业务拒绝（例如商品尚未收货）不会被持久缓存，状态修正后可用同一请求重试。

## 主要实现位置

- `agents/python/shared/return_policy.py`：退货期限计算和状态转换表。
- `agents/python/shared/tools/return_tools.py`：Agent 退货资格、申请、状态查询和退款工具。
- `agents/python/shared/inventory_ledger.py`：按现有销售流水生成幂等的取消库存回补流水。
- `agents/python/shared/hitl.py`：高风险操作审批、取消库存回补和批准后的退款执行。
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

订单详情响应包含 `return_eligibility` 和 `return` 字段；前者说明是否可以发起退货，后者包含已存在退货的状态和面单信息。

## 数据库迁移约定

本功能没有新增或修改数据库迁移。后续如需变更 schema，应接着当前最大迁移编号新建迁移，不得修改已经执行过的迁移文件。

## 验证记录

在 `agents/python` 目录运行：

```powershell
uv run pytest tests\test_return_policy.py tests\test_agent_role_prompts.py -q
uv run pytest tests\test_idempotency.py -q
```

- 第一条命令：6 项通过。
- 第二条命令：25 项通过。新增退款状态变更后重试和拒绝退货后旧面单不可下载的数据库回归用例均通过。
- 修改后的 Python 模块通过 `compileall`，`orchestrator.routes.legacy` 成功导入并注册 44 条路由。
- Python 目标文件的 Ruff 检查在忽略既有 `E501`、`F841`、`F541` 风格问题后通过；全量检查仍会报告既有问题。新增及修正的幂等、退货策略模块和策略测试格式检查通过。
- `pnpm exec tsc --noEmit` 通过。修改前端文件的 ESLint 为 0 错误、19 条警告，警告涉及已有的 `any` 类型和 `<img>`。
- `git diff --check` 通过。
