# Aegis 模拟MVP（非托管审批层版）

本版本已从“冷/温钱包”重构为“保护余额 / 可用额度”模型。

## 核心能力
- Agent 发起结构化支付请求（含 `nonce` + `issued_at`）
- 网关执行规则校验、额度校验、预授权分流
- 用户签署后才执行（或命中预授权自动执行）
- 执行后扣减可用额度、记录消费哈希与审计事件
- 支持 Connector 安装链接、Agent 绑定回传、用户确认绑定

## 启动步骤

```powershell
cd "D:\agent wallet\simulation_mvp"
python -m pip install -r requirements.txt
python backend\app.py
```

可选：

```powershell
python agent\callback_server.py
python agent\agent_sim.py --mode balance --interval 5 --callback-url "http://127.0.0.1:7001/callback"
```

访问：
- 本机：`http://127.0.0.1:5000/`
- 局域网：`http://<你的电脑IP>:5000/`
- 默认用户令牌：`dev-user-token`

## 主要接口

兼容接口：
- `POST /api/pay-requests`
- `GET /api/pending-requests`
- `POST /api/sign`
- `GET /api/requests/<request_id>`
- `GET /api/agents`
- `GET /api/agents/<agent_id>`
- `GET /api/consumptions`
- `GET /api/dashboard`

新增接口：
- `GET /api/quota/summary`
- `POST /api/quota/allocate`
- `POST /api/quota/reclaim`
- `GET /api/policies`
- `POST /api/policies`
- `GET /api/preauths`
- `POST /api/preauths`
- `POST /api/connectors/install-link`
- `GET /api/connectors`
- `POST /api/connectors/bind-complete`
- `POST /api/connectors/confirm-binding`
- `GET /api/audit/events`
- `GET /api/user/profile`
- `POST /api/user/register`

兼容映射接口（渐进下线）：
- `GET /api/wallets`
- `POST /api/wallets/transfer`（映射到额度分配）
- `GET /api/wallet-transfers`

废弃兼容：
- `POST /api/wallets/external-topup`（返回 410）
- `GET /api/wallets/external-topups`（返回空列表）

## 测试

```powershell
python -m unittest tests\test_api.py -v
powershell -ExecutionPolicy Bypass -File tests\smoke_e2e.ps1
```
