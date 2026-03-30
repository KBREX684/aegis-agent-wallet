# Aegis MVP 验收手册

## 一、演示顺序（推荐）
1. 打开首页，确认“总余额/保护余额/可用额度”显示正常。
2. 在“额度”页执行一次分配，再执行一次回收，验证余额变化。
3. 在“Agent”页生成安装链接，完成 `bind-complete`，再执行用户确认绑定。
4. 用 Agent 脚本发起支付请求，在“请求”页签署。
5. 在“消费”页查看该交易的 `tx_hash` 与交易详情。
6. 在“审计”页确认 `REQUEST_CREATED -> REQUEST_APPROVED -> PAYMENT_EXECUTED` 事件链。

## 二、异常流演示
1. 额度不足：构造超额请求，系统应返回 `QUOTA_INSUFFICIENT`。
2. 规则拦截：构造不在白名单的 payee，系统应返回 `RULE_BLOCKED`。
3. nonce 重放：重复 nonce 发送不同请求，系统应返回 `REPLAY_DETECTED`。
4. 过期签署：请求过期后签署，应返回状态冲突。

## 三、回滚预案
1. 如果页面异常：刷新页面并重新输入 `X-User-Token`。
2. 如果隧道失效：重启 cloudflared 快速隧道。
3. 如果数据库状态混乱：删除 `backend/aegis_mvp.db` 后重启服务（仅演示环境）。
4. 如果 Agent 回调异常：单独重启 `agent/callback_server.py`。

## 四、通过标准
- 可完成 20 轮连续“请求 -> 签署 -> 执行 -> 记录”无阻断。
- 消费哈希可按规则复算一致。
- 前端六页签在手机与桌面均可完整操作。
- 关键异常流均返回明确原因码并产生审计事件。
