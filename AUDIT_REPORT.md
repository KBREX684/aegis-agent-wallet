# Aegis Simulation MVP 代码审计报告

日期：2026-03-29  
范围：`simulation_mvp/` 全部源码

## 1. 审计目标

- 验证最小MVP是否满足“人类确认后才执行支付”
- 排查明显安全缺陷与状态机绕过风险
- 确认关键接口具备基础输入校验与审计留痕

## 2. 已审计项

1. 鉴权
- `POST /api/pay-requests` 需要 `X-Agent-Token`
- `GET /api/pending-requests`、`POST /api/sign`、`GET /api/requests/<id>` 需要 `X-User-Token`
- `POST /api/simulate-execute` 需要 `X-Internal-Token`

2. 请求校验
- `amount` 正数且有上限
- `payee/purpose` 长度限制
- `expires_at` 必须是带时区的ISO8601时间
- `callback_url` 限制为 `http/https`

3. 状态机一致性
- 创建请求默认 `PENDING`
- 仅允许 `PENDING -> APPROVED -> SUCCESS`
- 过期请求自动转 `EXPIRED`，不能签署

4. 幂等与重放控制
- `request_id` 唯一约束
- 同一 `request_id` 重放且载荷一致时返回幂等成功
- 同一 `request_id` 载荷不一致时拒绝（409）

5. 审计日志
- `REQUEST_CREATED` / `REQUEST_APPROVED` / `PAYMENT_EXECUTED` / `CALLBACK_ATTEMPTED` / `REQUEST_EXPIRED`
- 所有关键事件落库 `events` 表

## 3. 自动化测试结果

执行命令：

```powershell
python -m unittest tests\test_api.py -v
```

结果：5/5 通过  
覆盖点：
- 鉴权拦截
- 请求创建与查询
- 幂等重放
- 签署后执行成功
- 过期请求阻断

## 4. 端到端实用性测试

已执行 `tests/smoke_e2e.ps1` 所等价流程：
- 启动后端服务与回调服务
- 创建支付请求
- 拉取待签请求
- 发起签署
- 校验最终状态为 `SUCCESS`
- 校验回调被接收

结果：通过

## 5. 当前残余风险（MVP可接受）

1. 令牌为静态字符串
- 风险：泄露后可被重放调用
- 建议：下一阶段改为短期JWT + 设备绑定 + 轮换机制

2. 手机网页签署为“模拟签名”
- 风险：未使用真实系统生物识别与硬件密钥
- 建议：下一阶段接入 WebAuthn/Passkey 或原生 Biometric API

3. 单机SQLite与Flask开发服务
- 风险：并发能力和容灾有限
- 建议：试点阶段迁移到 PostgreSQL + Gunicorn/Uvicorn

4. 回调重试策略简单
- 风险：网络抖动下存在回调丢失
- 建议：加入指数退避重试和死信队列

## 6. 结论

该最小模拟MVP已满足演示目标：  
“Agent可发起请求，但必须经过人类确认后才执行支付，且全流程可审计。”

当前实现适合比赛演示、内部验证和早期试点，不可直接用于生产环境。
