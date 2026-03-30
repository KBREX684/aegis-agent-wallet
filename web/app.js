/* ═══════════════════════════════════════════════════════
   Aegis Agent Wallet — Refined Frontend Logic
   ═══════════════════════════════════════════════════════ */

const USER_TOKEN_KEY = "aegis_user_token";
const DEFAULT_USER_TOKEN = "dev-user-token";
const POLL_MS = 5000;

/* ── DOM Refs ──────────────────────────────────────── */
const $ = (id) => document.getElementById(id);

const tokenInput          = $("tokenInput");
const saveTokenBtn        = $("saveTokenBtn");
const refreshBtn          = $("refreshBtn");
const statusText          = $("statusText");
const profileBtn          = $("profileBtn");

const homeTodayRequests   = $("homeTodayRequests");
const homeTodaySuccess    = $("homeTodaySuccess");
const homeTodaySpend      = $("homeTodaySpend");
const homePendingCount    = $("homePendingCount");
const homeTotalBalance    = $("homeTotalBalance");
const homeProtectedBalance= $("homeProtectedBalance");
const homeAvailableQuota  = $("homeAvailableQuota");
const homeBoundAgents     = $("homeBoundAgents");
const homeWaitingAgent    = $("homeConnectorWaitingAgent");
const homeWaitingUser     = $("homeConnectorWaitingUser");

const allocateAgentSelect = $("allocateAgentSelect");
const reclaimAgentSelect  = $("reclaimAgentSelect");
const allocateAmountInput = $("allocateAmountInput");
const reclaimAmountInput  = $("reclaimAmountInput");
const allocateBtn         = $("allocateBtn");
const reclaimBtn          = $("reclaimBtn");
const quotaMovementList   = $("quotaMovementList");

const installAgentNameInput = $("installAgentNameInput");
const createInstallBtn      = $("createInstallBtn");
const installLinkBox        = $("installLinkBox");
const bindInstallIdInput    = $("bindInstallIdInput");
const bindAgentIdInput      = $("bindAgentIdInput");
const completeBindBtn       = $("completeBindBtn");
const confirmBindTokenInput = $("confirmBindTokenInput");
const confirmBindBtn        = $("confirmBindBtn");

const agentList            = $("agentList");
const pendingList          = $("pendingList");
const consumptionList      = $("consumptionList");
const consumptionFilter    = $("consumptionFilter");
const auditList            = $("auditList");

const profileModal         = $("profileModal");
const profileCloseBtn      = $("profileCloseBtn");
const profileMobileBound   = $("profileMobileBound");
const profileMobileMasked  = $("profileMobileMasked");
const profileIdCardBound   = $("profileIdCardBound");
const profileIdCardMasked  = $("profileIdCardMasked");
const profileUpdatedAt     = $("profileUpdatedAt");

const agentModal           = $("agentModal");
const closeModalBtn        = $("closeModalBtn");
const modalAgentTitle      = $("modalAgentTitle");
const modalAgentBody       = $("modalAgentBody");

const confirmModal         = $("confirmModal");
const confirmPayee         = $("confirmPayee");
const confirmAmount        = $("confirmAmount");
const confirmPurpose       = $("confirmPurpose");
const confirmRequestId     = $("confirmRequestId");
const confirmRejectBtn     = $("confirmRejectBtn");
const confirmApproveBtn    = $("confirmApproveBtn");

const toastContainer       = $("toastContainer");

const tabButtons = [...document.querySelectorAll(".tab-btn[data-view]")];
const views      = [...document.querySelectorAll(".view")];

/* ── State ─────────────────────────────────────────── */
let dashboard = null;
let signingInProgress = false;
let pollTimerId = null;
let confirmResolve = null;

/* ── Utilities ─────────────────────────────────────── */
const getToken = () => localStorage.getItem(USER_TOKEN_KEY) || DEFAULT_USER_TOKEN;
const setToken = (v) => localStorage.setItem(USER_TOKEN_KEY, v);

const esc = (t) =>
  String(t ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

const cny = (v) => `¥${Number(v || 0).toFixed(2)}`;

const fmtZhTime = new Intl.DateTimeFormat("zh-CN", {
  year:"numeric", month:"2-digit", day:"2-digit",
  hour:"2-digit", minute:"2-digit", second:"2-digit", hour12:false,
});
const zhTime = (v) => {
  if (!v) return "-";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : fmtZhTime.format(d);
};

function setStatus(msg, isError = false) {
  statusText.textContent = msg;
  statusText.classList.toggle("error", isError);
}

/* ── Toast System ──────────────────────────────────── */
function showToast(message, type = "info", duration = 3200) {
  const icons = { success: "✓", error: "✕", info: "i" };
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span class="toast-icon">${icons[type] || "i"}</span><span>${esc(message)}</span>`;
  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("removing");
    toast.addEventListener("animationend", () => toast.remove());
  }, duration);
}

/* ── Number Animation ──────────────────────────────── */
function animateValue(el, newText) {
  const old = el.textContent;
  if (old === String(newText)) return;
  el.style.opacity = "0.3";
  el.style.transform = "translateY(2px)";
  setTimeout(() => {
    el.textContent = newText;
    el.style.opacity = "1";
    el.style.transform = "translateY(0)";
  }, 140);
}

/* ── API Helper ────────────────────────────────────── */
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

/* ── Navigation ────────────────────────────────────── */
function switchView(name) {
  tabButtons.forEach(b => b.classList.toggle("active", b.dataset.view === name));
  views.forEach(v => {
    if (v.id === `view-${name}`) {
      v.style.display = "flex";
      requestAnimationFrame(() => v.classList.add("active"));
    } else {
      v.classList.remove("active");
      setTimeout(() => { if (!v.classList.contains("active")) v.style.display = "none"; }, 300);
    }
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ── Renderers ─────────────────────────────────────── */

function renderSelectOptions(agents) {
  const c1 = allocateAgentSelect.value;
  const c2 = reclaimAgentSelect.value;
  const c3 = consumptionFilter.value;
  const opts = agents.map(a => `<option value="${esc(a.agent_id)}">${esc(a.name)}</option>`).join("");
  allocateAgentSelect.innerHTML = opts;
  reclaimAgentSelect.innerHTML = opts;
  consumptionFilter.innerHTML = `<option value="">全部 Agent</option>` + opts;
  const ids = agents.map(a => a.agent_id);
  if (ids.includes(c1)) allocateAgentSelect.value = c1;
  if (ids.includes(c2)) reclaimAgentSelect.value = c2;
  if (["", ...ids].includes(c3)) consumptionFilter.value = c3;
}

function renderHome(data) {
  const s = data.summary || {};
  const q = data.quota_summary || {};
  const cs = data.connector_status || {};
  const bs = data.binding_status || {};
  animateValue(homeTodayRequests, s.today_requests || 0);
  animateValue(homeTodaySuccess, s.today_success || 0);
  animateValue(homeTodaySpend, cny(s.today_spend));
  animateValue(homePendingCount, (data.pending_requests || []).length);
  animateValue(homeTotalBalance, cny(q.total_balance));
  animateValue(homeProtectedBalance, cny(q.protected_balance));
  animateValue(homeAvailableQuota, cny(q.available_quota));
  animateValue(homeBoundAgents, bs.bound_agents_count || 0);
  animateValue(homeWaitingAgent, cs.awaiting_agent_install || 0);
  animateValue(homeWaitingUser, cs.awaiting_user_confirm || 0);
}

function renderQuotaMovements(list) {
  if (!list.length) {
    quotaMovementList.innerHTML = `<div class="empty-state"><div class="empty-icon">↔</div><div class="empty-text">暂无额度变更记录</div></div>`;
    return;
  }
  quotaMovementList.innerHTML = list.map(m => `
    <div class="table-row">
      <span>${zhTime(m.created_at)}</span>
      <span>${m.movement_type === "ALLOCATE" ? "分配" : "回收"} / ${esc(m.agent_id)}</span>
      <strong style="color:${m.movement_type === "ALLOCATE" ? "var(--success)" : "var(--accent)"}">${m.movement_type === "ALLOCATE" ? "+" : "-"}${cny(m.amount)}</strong>
    </div>
  `).join("");
}

function renderAgents(list) {
  if (!list.length) {
    agentList.innerHTML = `<div class="empty-state"><div class="empty-icon">🤖</div><div class="empty-text">暂无 Agent，创建安装链接开始接入</div></div>`;
    return;
  }
  agentList.innerHTML = list.map(a => {
    const pct = a.allocated_quota > 0 ? Math.round(a.consumed_quota / a.allocated_quota * 100) : 0;
    const barColor = pct > 85 ? "var(--danger)" : pct > 60 ? "var(--accent)" : "var(--primary)";
    return `
    <div class="mini-card">
      <div class="row between">
        <strong>${esc(a.name)}</strong>
        <span class="badge ${a.bound ? "badge-success" : "badge-neutral"}">${a.bound ? "已绑定" : "未绑定"}</span>
      </div>
      <div class="muted" style="font-size:0.78rem;margin-top:4px">ID: ${esc(a.agent_id)}</div>
      <div style="margin:8px 0 4px;display:flex;justify-content:space-between;font-size:0.78rem;color:var(--ink-tertiary)">
        <span>可用 ${cny(a.available_quota)}</span><span>已消耗 ${cny(a.consumed_quota)}</span>
      </div>
      <div style="height:4px;border-radius:2px;background:var(--border-light);overflow:hidden">
        <div style="height:100%;width:${pct}%;background:${barColor};border-radius:2px;transition:width 0.5s var(--ease-out)"></div>
      </div>
      <div class="muted" style="margin-top:6px;font-size:0.78rem">今日 ${a.today_requests} 请求 · ${a.today_success} 成功 · ${a.today_success_rate}%</div>
      <button class="btn secondary small" style="margin-top:8px" data-agent-id="${esc(a.agent_id)}">查看详情 →</button>
    </div>`;
  }).join("");
}

function renderPending(list) {
  if (!list.length) {
    pendingList.innerHTML = `<div class="empty-state"><div class="empty-icon">☕</div><div class="empty-text">暂无待签署请求</div></div>`;
    return;
  }
  pendingList.innerHTML = list.map(r => `
    <article class="pending-card">
      <div class="pending-header">
        <span class="pending-payee">${esc(r.payee)}</span>
        <span class="pending-amount">${cny(r.amount)}</span>
      </div>
      <div class="pending-purpose">${esc(r.purpose)}</div>
      <div class="pending-meta">
        <span class="pending-chip">⏱ ${zhTime(r.created_at)}</span>
        <span class="pending-chip">请求 ${esc(r.request_id).slice(0,16)}…</span>
      </div>
      <div class="pending-actions">
        <button class="btn btn-danger small" data-reject-id="${esc(r.request_id)}">拒绝</button>
        <button class="btn small" data-sign-id="${esc(r.request_id)}">确认签署</button>
      </div>
    </article>
  `).join("");
}

function filteredConsumptions() {
  if (!dashboard) return [];
  const sel = consumptionFilter.value;
  const list = dashboard.consumptions || [];
  return sel ? list.filter(x => x.agent_id === sel) : list;
}

function renderConsumptions() {
  const list = filteredConsumptions();
  if (!list.length) {
    consumptionList.innerHTML = `<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">暂无消费记录</div></div>`;
    return;
  }
  consumptionList.innerHTML = list.map(c => `
    <details class="table-row block">
      <summary>
        <span>${zhTime(c.created_at)}</span>
        <span>${esc(c.agent_id)}</span>
        <strong>${cny(c.amount)}</strong>
      </summary>
      <div style="margin-top:8px;display:flex;flex-direction:column;gap:4px;font-size:0.84rem">
        <div><span class="muted">收款方：</span>${esc(c.payee)}</div>
        <div><span class="muted">消费内容：</span>${esc(c.purpose)}</div>
        <div class="mono wrap" style="font-size:0.74rem"><span class="muted">交易哈希：</span>${esc(c.tx_hash)}</div>
        <pre>${esc(JSON.stringify(c.tx_detail, null, 2))}</pre>
      </div>
    </details>
  `).join("");
}

function renderAudit(events) {
  if (!events.length) {
    auditList.innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div><div class="empty-text">暂无审计事件</div></div>`;
    return;
  }
  const typeClass = (t) => {
    if (t.includes("EXECUTED") || t.includes("SUCCESS") || t.includes("APPROVED") || t.includes("BOUND")) return "event-success";
    if (t.includes("REJECTED") || t.includes("FAILED") || t.includes("EXPIRED")) return "event-danger";
    if (t.includes("PREAUTH") || t.includes("CALLBACK") || t.includes("CREATED")) return "event-warning";
    return "";
  };
  auditList.innerHTML = events.map(e => {
    const detail = e.event_detail ? esc(JSON.stringify(e.event_detail)) : "";
    return `<div class="audit-event ${typeClass(e.event_type)}">
      <div class="audit-event-type">${esc(e.event_type)}</div>
      <div class="audit-event-time">${zhTime(e.created_at)} · <span class="mono">${esc(e.request_id)}</span></div>
      ${detail ? `<div class="audit-event-detail wrap">${detail}</div>` : ""}
    </div>`;
  }).join("");
}

function renderProfile(data) {
  profileMobileBound.textContent = data.mobile_bound ? "已绑定" : "未绑定";
  profileMobileMasked.textContent = data.mobile_masked || "未绑定";
  profileIdCardBound.textContent = data.id_card_bound ? "已绑定" : "未绑定";
  profileIdCardMasked.textContent = data.id_card_masked || "未绑定";
  profileUpdatedAt.textContent = zhTime(data.updated_at);
}

/* ── Data Loading ──────────────────────────────────── */
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
    if (!silent) showToast("数据已刷新", "success");
  } catch (err) {
    setStatus(`加载失败：${err.message}`, true);
  }
}

/* ── Confirmation Modal ────────────────────────────── */
function showConfirmModal(req) {
  confirmPayee.textContent = req.payee;
  confirmAmount.textContent = cny(req.amount);
  confirmPurpose.textContent = req.purpose;
  confirmRequestId.textContent = req.request_id;
  confirmModal.classList.remove("hidden");
  return new Promise(resolve => { confirmResolve = resolve; });
}

function closeConfirmModal(result) {
  confirmModal.classList.add("hidden");
  if (confirmResolve) { confirmResolve(result); confirmResolve = null; }
}

/* ── Actions ───────────────────────────────────────── */

async function openProfileModal() {
  try {
    const data = await api("/api/user/profile");
    renderProfile(data);
    profileModal.classList.remove("hidden");
  } catch (err) {
    showToast(`获取信息失败：${err.message}`, "error");
  }
}

async function doAllocate() {
  try {
    const amount = Number(allocateAmountInput.value || 0);
    if (!(amount > 0)) throw new Error("请输入有效金额");
    await api("/api/quota/allocate", {
      method: "POST",
      body: JSON.stringify({ agent_id: allocateAgentSelect.value, amount }),
    });
    allocateAmountInput.value = "";
    await loadDashboard(true);
    showToast("额度分配成功", "success");
  } catch (err) {
    showToast(`分配失败：${err.message}`, "error");
  }
}

async function doReclaim() {
  try {
    const amount = Number(reclaimAmountInput.value || 0);
    if (!(amount > 0)) throw new Error("请输入有效金额");
    await api("/api/quota/reclaim", {
      method: "POST",
      body: JSON.stringify({ agent_id: reclaimAgentSelect.value, amount }),
    });
    reclaimAmountInput.value = "";
    await loadDashboard(true);
    showToast("额度回收成功", "success");
  } catch (err) {
    showToast(`回收失败：${err.message}`, "error");
  }
}

async function createInstallLink() {
  try {
    const name = installAgentNameInput.value.trim() || "未命名Agent";
    const data = await api("/api/connectors/install-link", {
      method: "POST",
      body: JSON.stringify({ agent_name: name }),
    });
    installLinkBox.textContent = `install_id: ${data.install_id}\ninstall_link: ${data.install_link}\nbind_token: ${data.bind_token}`;
    confirmBindTokenInput.value = data.bind_token;
    bindInstallIdInput.value = data.install_id;
    await loadDashboard(true);
    showToast("安装链接已生成", "success");
  } catch (err) {
    showToast(`生成失败：${err.message}`, "error");
  }
}

async function completeBind() {
  try {
    const iid = bindInstallIdInput.value.trim();
    const aid = bindAgentIdInput.value.trim();
    if (!iid || !aid) throw new Error("install_id 与 agent_id 不能为空");
    await api("/api/connectors/bind-complete", {
      method: "POST",
      headers: { "X-Agent-Token": "dev-agent-token" },
      body: JSON.stringify({ install_id: iid, agent_id: aid, agent_name: aid }),
    });
    await loadDashboard(true);
    showToast("Agent 已完成安装回传", "success");
  } catch (err) {
    showToast(`bind-complete 失败：${err.message}`, "error");
  }
}

async function confirmBinding() {
  try {
    const bt = confirmBindTokenInput.value.trim();
    if (!bt) throw new Error("bind_token 不能为空");
    await api("/api/connectors/confirm-binding", {
      method: "POST",
      body: JSON.stringify({ bind_token: bt }),
    });
    await loadDashboard(true);
    showToast("用户确认绑定成功", "success");
  } catch (err) {
    showToast(`确认绑定失败：${err.message}`, "error");
  }
}

async function signRequest(requestId) {
  const list = (dashboard && dashboard.pending_requests) || [];
  const req = list.find(r => r.request_id === requestId);
  if (!req) { showToast("请求未找到", "error"); return; }

  const approved = await showConfirmModal(req);
  if (!approved) { showToast("已取消签署", "info"); return; }

  try {
    signingInProgress = true;
    const buttons = pendingList.querySelectorAll("button[data-sign-id]");
    buttons.forEach(b => b.disabled = true);
    await api("/api/sign", {
      method: "POST",
      body: JSON.stringify({
        request_id: requestId, approval: "user_approved",
        signed_by: "mobile_web_user", signature: "simulated_signature",
      }),
    });
    await loadDashboard(true);
    showToast("签署成功", "success");
  } catch (err) {
    showToast(`签署失败：${err.message}`, "error");
  } finally {
    signingInProgress = false;
  }
}

function rejectRequest(requestId) {
  showToast("已拒绝（模拟）", "info");
}

async function openAgentDetail(agentId) {
  try {
    const data = await api(`/api/agents/${encodeURIComponent(agentId)}`);
    modalAgentTitle.textContent = `${data.agent.name} (${data.agent.agent_id})`;
    const pct = data.agent.allocated_quota > 0 ? Math.round(data.agent.consumed_quota / data.agent.allocated_quota * 100) : 0;
    modalAgentBody.innerHTML = `
      <div class="mini-card">
        <div class="kv-list">
          <div class="kv-row"><span>状态</span><strong>${esc(data.agent.status)}</strong></div>
          <div class="kv-row"><span>可用额度</span><strong>${cny(data.agent.available_quota)}</strong></div>
          <div class="kv-row"><span>已消耗</span><strong>${cny(data.agent.consumed_quota)}</strong></div>
          <div class="kv-row"><span>额度使用率</span><strong>${pct}%</strong></div>
          <div class="kv-row"><span>今日请求</span><strong>${data.agent.today_requests} · 成功 ${data.agent.today_success}</strong></div>
        </div>
      </div>
      <div class="mini-card">
        <h3>策略规则</h3>
        <div class="kv-list">
          <div class="kv-row"><span>单笔上限</span><strong>${cny(data.policy.single_limit)}</strong></div>
          <div class="kv-row"><span>日累计上限</span><strong>${cny(data.policy.daily_limit)}</strong></div>
          <div class="kv-row"><span>白名单</span><strong>${data.policy.whitelist.length ? data.policy.whitelist.map(esc).join("、") : "不限"}</strong></div>
        </div>
      </div>`;
    agentModal.classList.remove("hidden");
  } catch (err) {
    showToast(`加载失败：${err.message}`, "error");
  }
}

/* ── Polling ───────────────────────────────────────── */
function startPolling() {
  if (pollTimerId !== null) return;
  pollTimerId = setInterval(() => loadDashboard(true), POLL_MS);
}

function stopPolling() {
  if (pollTimerId === null) return;
  clearInterval(pollTimerId);
  pollTimerId = null;
}

function handleVisibility() {
  if (document.visibilityState === "hidden") { stopPolling(); return; }
  loadDashboard(true);
  startPolling();
}

/* ── Event Binding ─────────────────────────────────── */
tabButtons.forEach(btn => btn.addEventListener("click", () => switchView(btn.dataset.view)));

saveTokenBtn.addEventListener("click", () => {
  setToken(tokenInput.value.trim() || DEFAULT_USER_TOKEN);
  showToast("令牌已保存", "success");
  loadDashboard(true);
});

refreshBtn.addEventListener("click", () => loadDashboard());
profileBtn.addEventListener("click", openProfileModal);
profileCloseBtn.addEventListener("click", () => profileModal.classList.add("hidden"));
profileModal.addEventListener("click", e => { if (e.target === profileModal) profileModal.classList.add("hidden"); });

closeModalBtn.addEventListener("click", () => agentModal.classList.add("hidden"));
agentModal.addEventListener("click", e => { if (e.target === agentModal) agentModal.classList.add("hidden"); });

confirmRejectBtn.addEventListener("click", () => closeConfirmModal(false));
confirmApproveBtn.addEventListener("click", () => closeConfirmModal(true));
confirmModal.addEventListener("click", e => { if (e.target === confirmModal) closeConfirmModal(false); });

allocateBtn.addEventListener("click", doAllocate);
reclaimBtn.addEventListener("click", doReclaim);
createInstallBtn.addEventListener("click", createInstallLink);
completeBindBtn.addEventListener("click", completeBind);
confirmBindBtn.addEventListener("click", confirmBinding);

consumptionFilter.addEventListener("change", renderConsumptions);

pendingList.addEventListener("click", e => {
  const signBtn = e.target.closest("button[data-sign-id]");
  const rejectBtn = e.target.closest("button[data-reject-id]");
  if (signBtn && !signingInProgress) signRequest(signBtn.dataset.signId);
  if (rejectBtn) rejectRequest(rejectBtn.dataset.rejectId);
});

agentList.addEventListener("click", e => {
  const btn = e.target.closest("button[data-agent-id]");
  if (btn) openAgentDetail(btn.dataset.agentId);
});

/* ── Init ──────────────────────────────────────────── */
tokenInput.value = getToken();
loadDashboard();
startPolling();
document.addEventListener("visibilitychange", handleVisibility);
