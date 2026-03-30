const USER_TOKEN_KEY = "aegis_user_token";
const DEFAULT_USER_TOKEN = "dev-user-token";
const POLL_MS = 5000;

const tokenInput = document.getElementById("tokenInput");
const saveTokenBtn = document.getElementById("saveTokenBtn");
const refreshBtn = document.getElementById("refreshBtn");
const statusText = document.getElementById("statusText");
const profileBtn = document.getElementById("profileBtn");

const homeTodayRequests = document.getElementById("homeTodayRequests");
const homeTodaySuccess = document.getElementById("homeTodaySuccess");
const homeTodaySpend = document.getElementById("homeTodaySpend");
const homePendingCount = document.getElementById("homePendingCount");
const homeTotalBalance = document.getElementById("homeTotalBalance");
const homeProtectedBalance = document.getElementById("homeProtectedBalance");
const homeAvailableQuota = document.getElementById("homeAvailableQuota");
const homeBoundAgents = document.getElementById("homeBoundAgents");
const homeConnectorWaitingAgent = document.getElementById("homeConnectorWaitingAgent");
const homeConnectorWaitingUser = document.getElementById("homeConnectorWaitingUser");

const allocateAgentSelect = document.getElementById("allocateAgentSelect");
const reclaimAgentSelect = document.getElementById("reclaimAgentSelect");
const allocateAmountInput = document.getElementById("allocateAmountInput");
const reclaimAmountInput = document.getElementById("reclaimAmountInput");
const allocateBtn = document.getElementById("allocateBtn");
const reclaimBtn = document.getElementById("reclaimBtn");
const quotaMovementList = document.getElementById("quotaMovementList");

const installAgentNameInput = document.getElementById("installAgentNameInput");
const createInstallBtn = document.getElementById("createInstallBtn");
const installLinkBox = document.getElementById("installLinkBox");
const bindInstallIdInput = document.getElementById("bindInstallIdInput");
const bindAgentIdInput = document.getElementById("bindAgentIdInput");
const completeBindBtn = document.getElementById("completeBindBtn");
const confirmBindTokenInput = document.getElementById("confirmBindTokenInput");
const confirmBindBtn = document.getElementById("confirmBindBtn");

const agentList = document.getElementById("agentList");
const pendingList = document.getElementById("pendingList");
const consumptionList = document.getElementById("consumptionList");
const consumptionFilter = document.getElementById("consumptionFilter");
const auditList = document.getElementById("auditList");

const profileModal = document.getElementById("profileModal");
const profileCloseBtn = document.getElementById("profileCloseBtn");
const profileMobileBound = document.getElementById("profileMobileBound");
const profileMobileMasked = document.getElementById("profileMobileMasked");
const profileIdCardBound = document.getElementById("profileIdCardBound");
const profileIdCardMasked = document.getElementById("profileIdCardMasked");
const profileUpdatedAt = document.getElementById("profileUpdatedAt");

const agentModal = document.getElementById("agentModal");
const closeModalBtn = document.getElementById("closeModalBtn");
const modalAgentTitle = document.getElementById("modalAgentTitle");
const modalAgentBody = document.getElementById("modalAgentBody");

const tabButtons = [...document.querySelectorAll(".tab-btn[data-view]")];
const views = [...document.querySelectorAll(".view")];

let dashboard = null;
let signingInProgress = false;

const fmtZhTime = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const cny = (v) => `¥${Number(v || 0).toFixed(2)}`;
const zhTime = (value) => {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return fmtZhTime.format(d);
};

const escapeHtml = (text) =>
  String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");

const getToken = () => localStorage.getItem(USER_TOKEN_KEY) || DEFAULT_USER_TOKEN;
const setToken = (value) => localStorage.setItem(USER_TOKEN_KEY, value);

function setStatus(msg, isError = false) {
  statusText.textContent = msg;
  statusText.classList.toggle("error", isError);
}

async function api(url, opts = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-User-Token": getToken(),
    ...(opts.headers || {}),
  };
  const resp = await fetch(url, { ...opts, headers });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

function switchView(viewName) {
  tabButtons.forEach((b) => b.classList.toggle("active", b.dataset.view === viewName));
  views.forEach((v) => v.classList.toggle("active", v.id === `view-${viewName}`));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderSelectOptions(agents) {
  const current1 = allocateAgentSelect.value;
  const current2 = reclaimAgentSelect.value;
  const current3 = consumptionFilter.value;
  const options = agents.map((a) => `<option value="${escapeHtml(a.agent_id)}">${escapeHtml(a.name)} (${escapeHtml(a.agent_id)})</option>`).join("");
  allocateAgentSelect.innerHTML = options;
  reclaimAgentSelect.innerHTML = options;
  consumptionFilter.innerHTML = `<option value="">全部 Agent</option>${options}`;
  if ([...agents.map((a) => a.agent_id)].includes(current1)) allocateAgentSelect.value = current1;
  if ([...agents.map((a) => a.agent_id)].includes(current2)) reclaimAgentSelect.value = current2;
  if (["", ...agents.map((a) => a.agent_id)].includes(current3)) consumptionFilter.value = current3;
}

function renderHome(data) {
  const summary = data.summary || {};
  const quota = data.quota_summary || {};
  const conn = data.connector_status || {};
  const bind = data.binding_status || {};
  homeTodayRequests.textContent = String(summary.today_requests || 0);
  homeTodaySuccess.textContent = String(summary.today_success || 0);
  homeTodaySpend.textContent = cny(summary.today_spend || 0);
  homePendingCount.textContent = String((data.pending_requests || []).length);
  homeTotalBalance.textContent = cny(quota.total_balance || 0);
  homeProtectedBalance.textContent = cny(quota.protected_balance || 0);
  homeAvailableQuota.textContent = cny(quota.available_quota || 0);
  homeBoundAgents.textContent = String(bind.bound_agents_count || 0);
  homeConnectorWaitingAgent.textContent = String(conn.awaiting_agent_install || 0);
  homeConnectorWaitingUser.textContent = String(conn.awaiting_user_confirm || 0);
}

function renderQuotaMovements(list) {
  if (!list.length) {
    quotaMovementList.innerHTML = `<div class="muted">暂无额度变更记录</div>`;
    return;
  }
  quotaMovementList.innerHTML = list
    .map((m) => `
      <div class="table-row">
        <span>${zhTime(m.created_at)}</span>
        <span>${m.movement_type === "ALLOCATE" ? "分配" : "回收"} / ${escapeHtml(m.agent_id)}</span>
        <span>${cny(m.amount)}</span>
      </div>
    `)
    .join("");
}

function renderAgents(list) {
  if (!list.length) {
    agentList.innerHTML = `<div class="muted">暂无 Agent</div>`;
    return;
  }
  agentList.innerHTML = list
    .map((a) => `
      <article class="mini-card">
        <div class="row between">
          <strong>${escapeHtml(a.name)}</strong>
          <span class="badge">${a.bound ? "已绑定" : "未绑定"}</span>
        </div>
        <div class="muted">ID: ${escapeHtml(a.agent_id)}</div>
        <div class="muted">今日请求 ${a.today_requests}，成功 ${a.today_success}，成功率 ${a.today_success_rate}%</div>
        <div class="muted">可用额度 ${cny(a.available_quota)}，已消耗 ${cny(a.consumed_quota)}</div>
        <button class="btn small" data-agent-id="${escapeHtml(a.agent_id)}">查看详情</button>
      </article>
    `)
    .join("");
}

function renderPending(list) {
  if (!list.length) {
    pendingList.innerHTML = `<div class="muted">暂无待签请求</div>`;
    return;
  }
  pendingList.innerHTML = list
    .map((r) => `
      <article class="mini-card">
        <div class="row between"><strong>${escapeHtml(r.payee)}</strong><strong>${cny(r.amount)}</strong></div>
        <div class="muted">用途：${escapeHtml(r.purpose)}</div>
        <div class="muted">发起时间：${zhTime(r.created_at)}</div>
        <div class="mono">请求ID：${escapeHtml(r.request_id)}</div>
        <button class="btn" data-sign-id="${escapeHtml(r.request_id)}">确认签署</button>
      </article>
    `)
    .join("");
}

function filteredConsumptions() {
  if (!dashboard) return [];
  const selected = consumptionFilter.value;
  const list = dashboard.consumptions || [];
  return selected ? list.filter((x) => x.agent_id === selected) : list;
}

function renderConsumptions() {
  const list = filteredConsumptions();
  if (!list.length) {
    consumptionList.innerHTML = `<div class="muted">暂无消费记录</div>`;
    return;
  }
  consumptionList.innerHTML = list
    .map((c) => `
      <details class="table-row block">
        <summary><span>${zhTime(c.created_at)}</span><span>${escapeHtml(c.agent_id)}</span><span>${cny(c.amount)}</span></summary>
        <div><strong>收款方：</strong>${escapeHtml(c.payee)}</div>
        <div><strong>消费内容：</strong>${escapeHtml(c.purpose)}</div>
        <div class="mono wrap"><strong>交易哈希：</strong>${escapeHtml(c.tx_hash)}</div>
        <pre>${escapeHtml(JSON.stringify(c.tx_detail, null, 2))}</pre>
      </details>
    `)
    .join("");
}

function renderAudit(events) {
  if (!events.length) {
    auditList.innerHTML = `<div class="muted">暂无审计事件</div>`;
    return;
  }
  auditList.innerHTML = events
    .map((e) => {
      const detail = e.event_detail ? escapeHtml(JSON.stringify(e.event_detail)) : "-";
      return `<div class="table-row block"><div><strong>${escapeHtml(e.event_type)}</strong> · ${zhTime(e.created_at)}</div><div class="mono">request: ${escapeHtml(e.request_id)}</div><div class="wrap">${detail}</div></div>`;
    })
    .join("");
}

function renderProfile(data) {
  profileMobileBound.textContent = data.mobile_bound ? "已绑定" : "未绑定";
  profileMobileMasked.textContent = data.mobile_masked || "未绑定";
  profileIdCardBound.textContent = data.id_card_bound ? "已绑定" : "未绑定";
  profileIdCardMasked.textContent = data.id_card_masked || "未绑定";
  profileUpdatedAt.textContent = zhTime(data.updated_at);
}

async function loadDashboard(silent = false) {
  try {
    const data = await api("/api/dashboard");
    dashboard = data;
    renderHome(data);
    renderSelectOptions(data.agents || []);
    renderQuotaMovements(data.quota_movements || []);
    renderAgents(data.agents || []);
    renderPending(data.pending_requests || []);
    renderConsumptions();
    renderAudit(data.audit_events || []);
    if (!silent) setStatus("数据已刷新", false);
  } catch (err) {
    setStatus(`加载失败：${err.message}`, true);
  }
}

async function openProfileModal() {
  try {
    const data = await api("/api/user/profile");
    renderProfile(data);
    profileModal.classList.remove("hidden");
  } catch (err) {
    setStatus(`获取个人信息失败：${err.message}`, true);
  }
}

async function doAllocate() {
  try {
    const amount = Number(allocateAmountInput.value || 0);
    if (!(amount > 0)) throw new Error("请输入有效分配金额");
    await api("/api/quota/allocate", {
      method: "POST",
      body: JSON.stringify({ agent_id: allocateAgentSelect.value, amount }),
    });
    allocateAmountInput.value = "";
    await loadDashboard(true);
    setStatus("额度分配成功", false);
  } catch (err) {
    setStatus(`额度分配失败：${err.message}`, true);
  }
}

async function doReclaim() {
  try {
    const amount = Number(reclaimAmountInput.value || 0);
    if (!(amount > 0)) throw new Error("请输入有效回收金额");
    await api("/api/quota/reclaim", {
      method: "POST",
      body: JSON.stringify({ agent_id: reclaimAgentSelect.value, amount }),
    });
    reclaimAmountInput.value = "";
    await loadDashboard(true);
    setStatus("额度回收成功", false);
  } catch (err) {
    setStatus(`额度回收失败：${err.message}`, true);
  }
}

async function createInstallLink() {
  try {
    const agentName = installAgentNameInput.value.trim() || "未命名Agent";
    const data = await api("/api/connectors/install-link", {
      method: "POST",
      body: JSON.stringify({ agent_name: agentName }),
    });
    installLinkBox.textContent = `install_id: ${data.install_id}\ninstall_link: ${data.install_link}\nbind_token: ${data.bind_token}`;
    confirmBindTokenInput.value = data.bind_token;
    bindInstallIdInput.value = data.install_id;
    await loadDashboard(true);
    setStatus("安装链接已生成", false);
  } catch (err) {
    setStatus(`生成安装链接失败：${err.message}`, true);
  }
}

async function completeBind() {
  try {
    const installId = bindInstallIdInput.value.trim();
    const agentId = bindAgentIdInput.value.trim();
    if (!installId || !agentId) throw new Error("install_id 与 agent_id 不能为空");
    await api("/api/connectors/bind-complete", {
      method: "POST",
      headers: { "X-Agent-Token": "dev-agent-token" },
      body: JSON.stringify({ install_id: installId, agent_id: agentId, agent_name: agentId }),
    });
    await loadDashboard(true);
    setStatus("Agent 已完成安装回传", false);
  } catch (err) {
    setStatus(`bind-complete 失败：${err.message}`, true);
  }
}

async function confirmBinding() {
  try {
    const bindToken = confirmBindTokenInput.value.trim();
    if (!bindToken) throw new Error("bind_token 不能为空");
    await api("/api/connectors/confirm-binding", {
      method: "POST",
      body: JSON.stringify({ bind_token: bindToken }),
    });
    await loadDashboard(true);
    setStatus("用户确认绑定成功", false);
  } catch (err) {
    setStatus(`确认绑定失败：${err.message}`, true);
  }
}

async function signRequest(requestId) {
  try {
    signingInProgress = true;
    const buttons = pendingList.querySelectorAll("button[data-sign-id]");
    buttons.forEach((b) => (b.disabled = true));
    await api("/api/sign", {
      method: "POST",
      body: JSON.stringify({ request_id: requestId, approval: "user_approved", signed_by: "mobile_web_user", signature: "simulated_signature" }),
    });
    await loadDashboard(true);
    setStatus("签署成功", false);
  } catch (err) {
    setStatus(`签署失败：${err.message}`, true);
  } finally {
    signingInProgress = false;
  }
}

async function openAgentDetail(agentId) {
  try {
    const data = await api(`/api/agents/${encodeURIComponent(agentId)}`);
    modalAgentTitle.textContent = `${data.agent.name} (${data.agent.agent_id})`;
    modalAgentBody.innerHTML = `
      <div class="mini-card">
        <div class="muted">状态：${escapeHtml(data.agent.status)}</div>
        <div class="muted">可用额度：${cny(data.agent.available_quota)}</div>
        <div class="muted">已消耗：${cny(data.agent.consumed_quota)}</div>
        <div class="muted">今日请求：${data.agent.today_requests}，成功：${data.agent.today_success}</div>
      </div>
      <div class="mini-card">
        <strong>策略</strong>
        <div class="muted">单笔上限：${cny(data.policy.single_limit)}</div>
        <div class="muted">日累计上限：${cny(data.policy.daily_limit)}</div>
        <div class="muted">白名单：${data.policy.whitelist.length ? data.policy.whitelist.join("、") : "不限"}</div>
      </div>
    `;
    agentModal.classList.remove("hidden");
  } catch (err) {
    setStatus(`加载Agent详情失败：${err.message}`, true);
  }
}

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

saveTokenBtn.addEventListener("click", () => {
  const value = tokenInput.value.trim() || DEFAULT_USER_TOKEN;
  setToken(value);
  setStatus("令牌已保存", false);
  loadDashboard(true);
});

refreshBtn.addEventListener("click", () => loadDashboard());
profileBtn.addEventListener("click", openProfileModal);
profileCloseBtn.addEventListener("click", () => profileModal.classList.add("hidden"));
profileModal.addEventListener("click", (e) => {
  if (e.target === profileModal) profileModal.classList.add("hidden");
});

closeModalBtn.addEventListener("click", () => agentModal.classList.add("hidden"));
agentModal.addEventListener("click", (e) => {
  if (e.target === agentModal) agentModal.classList.add("hidden");
});

allocateBtn.addEventListener("click", doAllocate);
reclaimBtn.addEventListener("click", doReclaim);
createInstallBtn.addEventListener("click", createInstallLink);
completeBindBtn.addEventListener("click", completeBind);
confirmBindBtn.addEventListener("click", confirmBinding);

consumptionFilter.addEventListener("change", renderConsumptions);

pendingList.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-sign-id]");
  if (!btn || signingInProgress) return;
  signRequest(btn.dataset.signId);
});

agentList.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-agent-id]");
  if (!btn) return;
  openAgentDetail(btn.dataset.agentId);
});

tokenInput.value = getToken();
loadDashboard();
setInterval(() => loadDashboard(true), POLL_MS);
