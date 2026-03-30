# Aegis MVP Optimization Roadmap

> 本文档基于当前代码库（14 commits, 模拟 MVP 阶段）制定，按阶段分组，每项改动标注作用与优先级。

---

## Phase 1: 缺陷修复 — 做对已有的功能（预计 1-2 天）

### 1.1 [BUG] 策略引擎 allowed_hours 未接入校验

- **位置**: `backend/app.py` → `create_pay_request()`
- **现状**: `policies` 表有 `allowed_hours_json` 字段，策略设置接口可以配置允许交易时段，但创建支付请求时的规则校验逻辑（约 L607-619）完全没有检查当前小时是否在该时段内
- **改动**: 在白名单检查和限额检查之后，增加 `datetime.now().hour not in policy["allowed_hours"]` 的校验，不满足则写入 `RULE_BLOCKED` 并返回 409
- **作用**: 这是一个已经开发但未接入的功能，修完后策略引擎四个维度（白名单、单笔限额、日限额、允许时段）才真正全部生效

### 1.2 [BUG] PENDING 请求不会自动过期

- **位置**: `backend/app.py` → `pending_requests()` 和 `sign()`
- **现状**: 请求有 `expires_at` 字段，但没有任何地方用它过滤或清理。过期的 PENDING 请求会永远出现在待签列表中
- **改动**:
  - 在 `pending_requests()` 查询时加条件 `WHERE status='PENDING' AND expires_at > current_timestamp`
  - 在 `sign()` 中检查请求是否已过期，过期则返回 409 并标记 `reason_code='EXPIRED'`
- **作用**: 保证待签列表的数据正确性，避免用户签署一笔已经过期的请求；这是支付审批产品的基本正确性要求

### 1.3 [BUG] 审计事件不完整 — 缺少 REQUEST_CREATED

- **位置**: `backend/app.py` → `create_pay_request()`
- **现状**: 只有执行成功（`PAYMENT_EXECUTED`）和失败（`PAYMENT_FAILED`）才会写审计事件，请求创建、被规则拦截、被预授权命中这些关键节点没有审计记录
- **改动**: 在请求创建成功后调用 `event(conn, request_id, "REQUEST_CREATED", {...})`，规则拦截时写 `REQUEST_REJECTED`，预授权命中时写 `PREAUTH_MATCHED`
- **作用**: 审计链从 `CREATED → APPROVED/REJECTED → EXECUTED` 变得完整，满足 `Aegis_Project_Framework.md` 第 4 条"全流程可审计"的原则定义

### 1.4 [BUG] Smoke 测试硬编码 Windows 路径

- **位置**: `tests/smoke_e2e.ps1` L3, L7, L10
- **现状**: 硬编码 `D:\agent wallet\simulation_mvp`，无法在其他环境运行
- **改动**: 改为 `$base = Split-Path -Parent $PSScriptRoot` 或使用脚本相对路径；额外新增一个 `tests/smoke_e2e.sh` bash 版本
- **作用**: 测试脚本可以在任意环境执行，CI/CD 和团队协作不再受路径限制

---

## Phase 2: 安全加固 — 堵住模拟阶段的风险点（预计 1-2 天）

### 2.1 SSRF 防护 — callback_url 校验加强

- **位置**: `backend/app.py` → `valid_callback()`
- **现状**: 只校验 URL 格式是否为 http/https，不检查目标地址。Agent 可以填写 `http://169.254.169.254/latest/meta-data/` 等内网地址，让 Aegis 网关主动发起请求
- **改动**: 增加一个简单的 IP/域名黑名单校验，拒绝 RFC 1918 私有地址、链路本地地址、localhost 等；或使用 `ipaddress` 模块解析目标 IP 后判断
- **作用**: 防止 Agent 利用 callback 机制发起 SSRF 攻击，这是 OWASP Top 10 中风险较高的漏洞类型

### 2.2 签署操作增加二次确认

- **位置**: `web/app.js` → `signRequest()`
- **现状**: 点击"确认签署"按钮直接调用 `/api/sign`，没有二次确认。作为支付审批产品，一次误触就可能批准一笔不该批准的支付
- **改动**: 在 `signRequest()` 中先弹出一个确认对话框，显示收款方、金额、用途，用户确认后才发送请求
- **作用**: 防止误操作导致的错误审批，这是金融/支付类产品的标准交互范式

### 2.3 API 响应中移除敏感信息泄露

- **位置**: `backend/app.py` → `user_profile()`
- **现状**: `user_profiles` 表中 `mobile` 和 `id_card_no` 是明文存储。虽然返回时做了脱敏（`138****8000`），但数据库层面没有保护
- **改动**: MVP 阶段至少在入库时对身份证号做单向哈希存储，手机号可以加密存储；展示时只返回脱敏值
- **作用**: 即使 SQLite 文件被泄露，攻击者也无法直接获取用户身份证和手机号明文

### 2.4 请求签名从模拟升级为可验证

- **位置**: `web/app.js:363` 和 `backend/app.py` → `sign()`
- **现状**: 签名是固定的 `"simulated_signature"` 字符串，服务端也不校验
- **改动**: MVP 阶段可以实现一个 HMAC-SHA256 方案 — 前端用 user_token 作为 key 对 request_id + timestamp 签名，后端验证。不需要真正的 PKI
- **作用**: 从"完全不可验证"升级为"模拟环境下可验证"，为后续接入真实签名（WebAuthn/SM2）铺路

---

## Phase 3: 体验优化 — 让演示更专业（预计 2-3 天）

### 3.1 Dashboard 轮询效率优化

- **位置**: `web/app.js:443` → `setInterval(() => loadDashboard(true), POLL_MS)`
- **现状**: 固定 5 秒轮询 `/api/dashboard`，即使页面在后台也会持续请求。该接口每次查询 7-8 张表
- **改动**:
  - 前端：监听 `document.visibilitychange`，页面不可见时暂停轮询
  - 后端：Dashboard 响应增加 `Last-Modified` 头，前端发 `If-Modified-Since`，无变化时返回 304
- **作用**: 减少不必要的数据库查询和网络传输，演示时浏览器标签页切走后不再浪费资源

### 3.2 前端数字变化动效

- **位置**: `web/app.js` → `renderHome()` 和各 render 函数
- **现状**: 额度分配/消费后，数字瞬间跳变，用户难以感知变化
- **改动**: 为金额类数字增加一个简单的计数动画（`requestAnimationFrame` + 线性插值），从旧值过渡到新值
- **作用**: 提升产品体感，让用户直观感受到"钱在流动"，这在路演和投资人演示时非常有价值

### 3.3 请求详情卡片优化

- **位置**: `web/app.js` → `renderPending()`
- **现状**: 待签请求只显示收款方、金额、用途、时间，缺少关键决策信息
- **改动**: 增加显示 Agent 名称（而非只有 ID）、该 Agent 今日已消费金额、该笔请求距离过期的倒计时
- **作用**: 用户签署时有更多上下文信息做决策，符合项目"人类在回路"的核心设计理念

### 3.4 移动端签署体验增强

- **位置**: `web/index.html` 和 `web/app.js`
- **现状**: 移动端签署按钮和卡片没有特殊的触控优化
- **改动**:
  - 签署按钮增加 `touch-action: manipulation` 防止双击缩放
  - 增加触觉反馈（`navigator.vibrate()`）或视觉反馈（按下态颜色变化）
  - 签署成功后增加一个简单的成功/失败状态展示
- **作用**: MVP 验收手册提到"前端六页签在手机与桌面均可完整操作"是验收标准之一，移动端体验直接影响演示效果

### 3.5 消费记录导出功能

- **位置**: 新增前端按钮 + 后端接口
- **现状**: 消费记录只能在页面上查看，无法导出
- **改动**: 后端新增 `GET /api/consumptions/export?format=csv` 接口，前端在消费页签加一个"导出 CSV"按钮
- **作用**: 演示时可以直接向观众展示可追溯的消费数据，也方便合规审计场景的展示

---

## Phase 4: 代码架构 — 为下一阶段铺路（预计 3-5 天）

### 4.1 后端 app.py 按职责拆分

- **位置**: `backend/app.py`（830 行）
- **现状**: 所有路由、业务逻辑、数据访问、工具函数都在一个文件中
- **改动**: 拆分为以下结构：
  ```
  backend/
    app.py              # Flask 工厂，注册蓝图
    auth.py             # ok_agent(), ok_user() 鉴权
    routes/
      pay.py            # 支付请求 + 签署 + 执行
      quota.py          # 额度分配/回收/查询
      policy.py         # 策略 CRUD
      preauth.py        # 预授权 CRUD
      connector.py      # Connector 安装/绑定
      dashboard.py      # 聚合数据接口
      legacy.py         # 兼容接口（wallets 系）
    services/
      policy_engine.py  # 策略校验逻辑
      executor.py       # 支付执行编排
      quota_manager.py  # 额度扣减/分配
    db.py               # 数据库连接、Schema、迁移
    helpers.py          # utcnow, iso, money, hash_tx 等
  ```
- **作用**: 降低单文件复杂度，多人协作时减少冲突，新功能有明确的归属位置。这是从 MVP 到成熟产品的必经之路

### 4.2 消除路由间的数据耦合

- **位置**: `backend/app.py:720-721`
- **现状**: `agent_detail()` 通过调用 `agents_get().json["agents"]` 获取数据 — 先执行另一个路由函数，再把 Flask Response 对象的 JSON 解出来
- **改动**: 把数据查询逻辑抽成纯函数（如 `get_agent_summary(conn, agent_id, token)`），两个路由都调用这个函数
- **作用**: 消除隐式依赖，路由函数之间不再互相调用，代码可读性和可测试性大幅提升

### 4.3 补充测试覆盖

- **位置**: `tests/test_api.py`（当前 5 个用例）
- **现状**: 只覆盖了额度初始化、创建+签署、白名单拦截、消费哈希
- **改动**: 新增以下测试场景：
  - nonce 重放 → 返回 `REPLAY_DETECTED`
  - 预授权窗口内自动执行（无需人工签署）
  - 预授权超出 remaining_amount 后回落到人工签署
  - Connector 绑定完整流（install-link → bind-complete → confirm-binding）
  - 额度回收边界（回收超过已分配的额度）
  - allowed_hours 时段拦截
  - 过期请求签署被拒绝
- **作用**: 每个业务规则都有测试守护，后续改动不怕引入回归。也符合 AUDIT_REPORT 中"核心功能可用"的验收标准

### 4.4 引入结构化日志

- **位置**: 全局
- **现状**: 只有 `agent/callback_server.py` 用 `print()` 输出，`app.py` 无任何运行日志
- **改动**: 引入 Python `logging` 模块，在关键节点记录结构化日志：
  - 请求创建（agent_id, amount, payee, request_id）
  - 规则拦截（reason_code）
  - 审批签署（signed_by, request_id）
  - 执行结果（tx_id, tx_hash）
  - 异常（callback 失败、数据库错误）
- **作用**: 演示时可以实时查看系统行为，排查问题时有据可查。这是从"能跑"到"可运维"的关键一步

---

## Phase 5: 演示增强 — 路演加分项（预计 2-3 天）

### 5.1 Docker 一键启动

- **位置**: 项目根目录新增文件
- **现状**: 需要 `pip install` + 手动启动多个进程
- **改动**: 新增 `Dockerfile` + `docker-compose.yml`，一条命令启动完整环境（backend + callback_server + agent_sim）
- **作用**: 路演时不再依赖本地环境配置，任何人 `docker compose up` 即可看到完整演示；也方便部署到云服务器

### 5.2 实时通知（WebSocket 或 SSE）

- **位置**: `backend/app.py` + `web/app.js`
- **现状**: 前端 5 秒轮询，新请求到达后最多延迟 5 秒才显示
- **改动**: 后端引入 Flask-SocketIO 或 SSE，在支付请求创建时主动推送通知到前端
- **作用**: 演示时 Agent 发起请求后 Dashboard 立刻刷新，而不是等 5 秒。这在"实时审批"场景的展示中效果差异很大

### 5.3 Agent 模拟器增强 — 多场景预设

- **位置**: `agent/agent_sim.py`
- **现状**: 只有单一请求模式（固定的 payee/amount/purpose）
- **改动**: 增加场景预设配置：
  - API 采购场景（小额高频，DeepSeek/OpenAI）
  - 云服务场景（中额低频，AWS/Azure）
  - 数据购买场景（不定额，各种数据供应商）
  - 异常场景（白名单外商户、超额请求、过期请求）
- **作用**: 演示时可以快速切换不同业务场景，展示策略引擎在不同场景下的拦截效果，远比单一场景有说服力

### 5.4 Dashboard 增加 "Live Demo Mode"

- **位置**: `web/index.html` + `web/app.js`
- **现状**: Dashboard 是被动展示，需要手动操作
- **改动**: 增加一个"演示模式"开关，开启后：
  - 自动启动 Agent 模拟发送请求
  - 自动审批（或延迟 3 秒后自动审批）
  - 实时展示完整的请求→审批→执行→记录流水线
  - 配合数字动效展示余额变化
- **作用**: 路演时一个按钮就能展示完整链路，不需要在多个终端窗口之间切换操作

---

## 改动总览

| Phase | 核心目标 | 改动数 | 预估工时 |
|-------|----------|--------|----------|
| **Phase 1** | 缺陷修复 | 4 项 | 1-2 天 |
| **Phase 2** | 安全加固 | 4 项 | 1-2 天 |
| **Phase 3** | 体验优化 | 5 项 | 2-3 天 |
| **Phase 4** | 架构重构 | 4 项 | 3-5 天 |
| **Phase 5** | 演示增强 | 4 项 | 2-3 天 |

### 推荐执行顺序

```
Phase 1 (修 bug) → Phase 3 (体验) → Phase 5 (演示增强) → Phase 2 (安全) → Phase 4 (架构)
```

理由：Phase 1 保证功能正确 → Phase 3 让演示效果好 → Phase 5 让路演有冲击力 → Phase 2 和 Phase 4 为进入下一阶段做准备。如果近期有路演安排，Phase 1+3+5 应该优先完成。

---

*最后更新: 2026-03-30*
