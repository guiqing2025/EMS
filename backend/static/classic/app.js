const API = '/api';
let currentPage = 1;
const pageSize = 20;
let authToken = localStorage.getItem('ems_auth_token') || '';
let lastNotifiedLogId = 0;
let notifyTimer = null;
let pendingNotifyCount = 0;
let shipTarget = null;
let scanTarget = null;
const NOTIFY_STORAGE_KEY = 'ems_last_notified_sync_log_id';
const TOKEN_KEY = 'ems_auth_token';
const USER_KEY = 'ems_current_user';

let currentUser = null;

function setCurrentUser(user) {
  currentUser = user || null;
  if (currentUser) localStorage.setItem(USER_KEY, JSON.stringify(currentUser));
  else localStorage.removeItem(USER_KEY);
}

function loadStoredUser() {
  try {
    const raw = localStorage.getItem(USER_KEY);
    currentUser = raw ? JSON.parse(raw) : null;
  } catch {
    currentUser = null;
  }
}

function applyEmbedEngTab() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('embed') !== '1') return;
  const page = params.get('page');
  const tab = params.get('tab');
  if (!page || !tab) return;
  if (page === 'engineering' && window.EngineeringApp?.switchTab) {
    window.EngineeringApp.switchTab(tab);
  } else if (page === 'warehouse' && window.WarehouseApp?.switchTab) {
    window.WarehouseApp.switchTab(tab);
  } else if (page === 'scheduling' && window.SchedulingApp?.switchTab) {
    window.SchedulingApp.switchTab(tab);
  }
}

function switchPage(pageId) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const page = document.getElementById('page-' + pageId);
  const nav = document.querySelector(`[data-page="${pageId}"]`);
  if (page) page.classList.add('active');
  if (nav) nav.classList.add('active');
  if (pageId === 'warehouse' && window.WarehouseApp) {
    void Promise.resolve(window.WarehouseApp.load()).then(() => applyEmbedEngTab());
  }
  if (pageId === 'dept' && window.WarehouseApp) window.WarehouseApp.loadDept();
  if (pageId === 'engineering' && window.EngineeringApp) {
    // 等 load 完成后再切 tab（load 的 finally 也会 applyEngTabFromUrl），避免未加载客户时卡在「加载客户列表…」
    void Promise.resolve(window.EngineeringApp.load()).then(() => applyEmbedEngTab());
  }
  if (pageId === 'scheduling' && window.SchedulingApp) {
    void Promise.resolve(window.SchedulingApp.load()).then(() => applyEmbedEngTab());
  }
}

function applyRoleUI() {
  loadStoredUser();
  const role = currentUser?.role || 'admin';
  const navOrders = document.getElementById('nav-orders');
  const navWarehouse = document.getElementById('nav-warehouse');
  const navEngineering = document.getElementById('nav-engineering');
  const navScheduling = document.getElementById('nav-scheduling');
  const navDept = document.getElementById('nav-dept');
  const badge = document.getElementById('user-badge');
  if (badge && currentUser) {
    badge.textContent = currentUser.display_name || currentUser.username;
    badge.classList.remove('hidden');
  }
  const isDept = role === 'dept';
  const isAdmin = role === 'admin';
  const isWarehouse = role === 'warehouse' || isAdmin || role === 'pmc' || role === 'eng_auditor';
  const isPlanner = role === 'planner' || isAdmin;
  const isEngineering = role === 'engineering';
  const isEngAuditor = role === 'eng_auditor';
  const isPmc = role === 'pmc';
  const canManageOrders = isAdmin || role === 'planner';
  navOrders?.classList.toggle('hidden', isDept || isEngineering);
  navWarehouse?.classList.toggle('hidden', !isWarehouse);
  navEngineering?.classList.toggle('hidden', !isPlanner && !isEngineering && !isEngAuditor);
  navScheduling?.classList.toggle('hidden', !isPlanner);
  navDept?.classList.toggle('hidden', !isDept);
  document.getElementById('btn-sync-now')?.classList.toggle('hidden', !canManageOrders);
  document.getElementById('btn-manual-order')?.classList.toggle('hidden', !canManageOrders);
  document.body.classList.toggle('role-pmc', isPmc);
  document.body.classList.toggle('eng-import-only', isEngineering);
  document.body.classList.toggle('eng-audit-only', isEngAuditor);
  if (document.body.classList.contains('embed-mode')) return;
  if (isDept) switchPage('dept');
  else if (isEngineering || isEngAuditor) switchPage('engineering');
  else if (isPmc) switchPage('orders');
  else if (role === 'planner') switchPage('scheduling');
  else if (role === 'warehouse') switchPage('warehouse');
}

window.EMS = { api, showToast, fmtDate, authHeaders, switchPage, getCurrentUser: () => currentUser };

function setAuthToken(token) {
  authToken = token || '';
  if (authToken) localStorage.setItem(TOKEN_KEY, authToken);
  else localStorage.removeItem(TOKEN_KEY);
}

function clearAuth() {
  authToken = '';
  currentUser = null;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

function authHeaders() {
  return authToken ? { 'X-Auth-Token': authToken } : {};
}

function showLogin(show) {
  document.getElementById('system-login').classList.toggle('hidden', !show);
  document.getElementById('app-main').classList.toggle('hidden', show);
}

function showChangePassword(show) {
  document.getElementById('change-password-modal')?.classList.toggle('hidden', !show);
  document.getElementById('system-login')?.classList.add('hidden');
  document.getElementById('app-main')?.classList.add('hidden');
  if (show) {
    const hint = document.getElementById('change-password-hint');
    if (hint && currentUser) {
      hint.textContent = `${currentUser.display_name || currentUser.username}，首次登录请设置新密码`;
    }
  }
}

function mustChangePassword() {
  return !!currentUser?.must_change_password;
}

async function submitChangePassword() {
  const oldPwd = document.getElementById('change-old-password')?.value || '';
  const newPwd = document.getElementById('change-new-password')?.value || '';
  const newPwd2 = document.getElementById('change-new-password2')?.value || '';
  const errEl = document.getElementById('change-password-error');
  errEl.classList.add('hidden');
  if (!oldPwd || !newPwd || !newPwd2) {
    errEl.textContent = '请填写完整信息';
    errEl.classList.remove('hidden');
    return;
  }
  if (newPwd.length < 6) {
    errEl.textContent = '新密码至少 6 位';
    errEl.classList.remove('hidden');
    return;
  }
  if (newPwd !== newPwd2) {
    errEl.textContent = '两次输入的新密码不一致';
    errEl.classList.remove('hidden');
    return;
  }
  try {
    const res = await fetch(API + '/auth/change-password', {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ old_password: oldPwd, new_password: newPwd }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || '修改失败');
    setAuthToken(data.token);
    setCurrentUser({
      username: data.username,
      role: data.role,
      department: data.department,
      display_name: data.display_name,
      must_change_password: false,
    });
    document.getElementById('change-old-password').value = '';
    document.getElementById('change-new-password').value = '';
    document.getElementById('change-new-password2').value = '';
    showChangePassword(false);
    showLogin(false);
    applyRoleUI();
    await bootApp();
    showToast('密码已修改', 'success');
  } catch (e) {
    errEl.textContent = e.message || '修改失败';
    errEl.classList.remove('hidden');
  }
}

function logout() {
  try {
    sessionStorage.removeItem('eng_todo_auto_opened_v1');
    sessionStorage.removeItem('eng_todo_auto_nav_v1');
  } catch (_) { /* ignore */ }
  clearAuth();
  stopNotifyPolling();
  showLogin(true);
  document.getElementById('login-password').value = '';
}

async function checkAuth() {
  if (!authToken) return false;
  const res = await fetch(API + '/auth/status', {
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
  });
  if (!res.ok) return false;
  const status = await res.json();
  if (!status.authenticated) return false;
  setCurrentUser({
    username: status.username,
    role: status.role || 'admin',
    department: status.department,
    display_name: status.display_name,
    must_change_password: status.must_change_password,
  });
  return true;
}

async function loginSystem() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const errEl = document.getElementById('login-error');
  errEl.classList.add('hidden');
  if (!username || !password) {
    errEl.textContent = '请输入账号和密码';
    errEl.classList.remove('hidden');
    return;
  }
  try {
    const res = await fetch(API + '/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const msg = res.status === 401 ? '账号或密码错误' : await res.text();
      throw new Error(msg);
    }
    const data = await res.json();
    setAuthToken(data.token);
    setCurrentUser({
      username: data.username,
      role: data.role,
      department: data.department,
      display_name: data.display_name,
      must_change_password: data.must_change_password,
    });
    document.getElementById('login-password').value = '';
    if (data.must_change_password) {
      showToast(data.message || '请先修改初始密码', 'warning', 5000);
      showChangePassword(true);
      return;
    }
    showLogin(false);
    applyRoleUI();
    await bootApp();
  } catch (e) {
    const raw = e.message || '';
    const msg = raw === 'Load failed' || raw === 'Failed to fetch' || e.name === 'TypeError'
      ? '无法连接服务器，请确认后台服务已启动'
      : (raw || '登录失败');
    errEl.textContent = msg;
    errEl.classList.remove('hidden');
  }
}

async function bootApp() {
  applyRoleUI();
  const role = currentUser?.role || 'admin';
  if (role !== 'dept') {
    await loadCustomers();
    loadStatusOptions();
    loadOrders();
    await initNotifyCursor();
    await requestNotifyPermission();
    startNotifyPolling();
  }
  if (window.WarehouseApp) window.WarehouseApp.init();
}

function fmtMoney(n) {
  return '¥' + Number(n || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtDate(s) {
  if (!s) return '-';
  return s.replace('T', ' ').slice(0, 19);
}

function lineNo(o) {
  if (!o.purchase_seq || o.purchase_seq === '0') return '-';
  return `${o.purchase_seq}-${o.purchase_phase_seq || '1'}`;
}

function showToast(msg, type = 'success', duration = 3000) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast show ${type}`;
  setTimeout(() => el.classList.remove('show'), duration);
}

function updateNotifyBadge(count) {
  pendingNotifyCount = count;
  const badge = document.getElementById('notify-badge');
  if (!badge) return;
  if (count > 0) {
    badge.textContent = count > 99 ? '99+' : String(count);
    badge.classList.remove('hidden');
    document.title = `(${count}) 新订单 · EMS 订单中心`;
  } else {
    badge.classList.add('hidden');
    document.title = '深圳鼎雄电子科技有限公司 · EMS 订单中心';
  }
}


function formatNewOrderSummary(orders, total) {
  const preview = (orders || []).slice(0, 3).map(o => {
    const goods = o.product_goods_no || o.product_goods_name || '';
    return `${o.customer_name || ''} ${o.purchase_no}${goods ? ` / ${goods}` : ''}`.trim();
  }).filter(Boolean);
  const head = preview.join('；');
  if (total > preview.length) {
    return `${head} 等 ${total} 条新订单`;
  }
  return head || `${total} 条新订单`;
}

function customerKitBadge(o) {
  if (o.customer_kit_status === 'na') return '—';
  const label = o.customer_kit_status_label || o.customer_kit_status;
  const cls = `kit-badge kit-cust-${o.customer_kit_status}`;
  const sets = o.collected_sets_qty || 0;
  const qty = o.batch_pur_qty || o.output_qty || 0;
  return `<span class="${cls}">${label}</span><span class="kit-qty-hint">${sets}/${qty}套</span>`;
}

function formatKittingAlertSummary(alerts, total) {
  const preview = (alerts || []).slice(0, 3).map(a => {
    const goods = a.product_goods_no || a.product_goods_name || '';
    return `${a.customer_name || ''} ${a.purchase_no}${goods ? ` / ${goods}` : ''}`.trim();
  }).filter(Boolean);
  const head = preview.join('；');
  if (total > preview.length) {
    return `${head} 等 ${total} 单客户已齐套`;
  }
  return head || `${total} 单客户已齐套`;
}

function notifyKittingAlerts(item) {
  const total = item.kitting_alert_count || 0;
  if (!total) return;
  const summary = formatKittingAlertSummary(item.kitting_alerts, total);
  showToast(`客户齐套提醒：${summary}`, 'info', 8000);
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification('EMS 客户齐套提醒', {
      body: summary,
      tag: `ems-kitting-${item.sync_log_id}`,
    });
  }
}

function notifySyncItem(item) {
  notifyNewOrders(item);
  notifyKittingAlerts(item);
}

function notifyNewOrders(item) {
  const total = item.new_orders_count || 0;
  if (!total) return;
  const summary = formatNewOrderSummary(item.orders, total);
  showToast(`新订单提醒：${summary}`, 'info', 8000);
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification('EMS 新订单提醒', {
      body: summary,
      tag: `ems-new-orders-${item.sync_log_id}`,
    });
  }
  openNewOrdersModal(`；本次同步新增 ${total} 条`);
}

async function requestNotifyPermission() {
  if (!('Notification' in window)) return;
  if (Notification.permission === 'default') {
    try {
      await Notification.requestPermission();
    } catch (_) {}
  }
}

async function initNotifyCursor() {
  const stored = parseInt(localStorage.getItem(NOTIFY_STORAGE_KEY) || '0', 10);
  try {
    const status = await api('/sync/status');
    const latestId = status?.last_log?.id || 0;
    lastNotifiedLogId = stored > 0 ? stored : latestId;
    if (stored <= 0 && latestId > 0) {
      localStorage.setItem(NOTIFY_STORAGE_KEY, String(latestId));
    }
  } catch (_) {
    lastNotifiedLogId = stored;
  }
}

async function pollNewOrderNotifications() {
  try {
    const data = await api(`/sync/notifications?after_log_id=${lastNotifiedLogId}`);
    const items = data.items || [];
    if (items.length) {
      let maxId = lastNotifiedLogId;
      for (const item of items) {
        notifySyncItem(item);
        maxId = Math.max(maxId, item.sync_log_id || 0);
      }
      lastNotifiedLogId = maxId;
      localStorage.setItem(NOTIFY_STORAGE_KEY, String(lastNotifiedLogId));
      loadOrders();
    }
    await refreshNewOrderBadge();
  } catch (_) {}
}

function startNotifyPolling() {
  if (notifyTimer) clearInterval(notifyTimer);
  pollNewOrderNotifications();
  notifyTimer = setInterval(pollNewOrderNotifications, 30000);
}

function stopNotifyPolling() {
  if (notifyTimer) {
    clearInterval(notifyTimer);
    notifyTimer = null;
  }
  updateNotifyBadge(0);
}

async function api(path, options = {}) {
  const isPublicAuth = path.startsWith('/auth/login') || path.startsWith('/auth/status');
  const headers = {
    'Content-Type': 'application/json',
    ...(!isPublicAuth ? authHeaders() : {}),
    ...(options.headers || {}),
  };
  const res = await fetch(API + path, { ...options, headers });
  if (res.status === 401) {
    const text = await res.text();
    let detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch (_) {}
    logout();
    throw new Error(detail || '登录已过期，请重新登录');
  }
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function statusBadge(completed, srmStatusName) {
  const label = srmStatusName || (completed ? '已结案' : '进行中');
  return completed
    ? `<span class="badge badge-success">${label}</span>`
    : `<span class="badge badge-warning">${label}</span>`;
}

function fmtQty(n, completed) {
  if (completed && (n === 0 || n === null || n === undefined)) return '—';
  return n ?? 0;
}

let customersCache = [];

async function loadCustomers() {
  const [syncCustomers, manualCustomers] = await Promise.all([
    api('/sync/customers'),
    api('/orders/manual-customers').catch(() => []),
  ]);
  const merged = [...syncCustomers];
  const seen = new Set(syncCustomers.map(c => c.id));
  for (const c of manualCustomers) {
    if (!seen.has(c.id)) {
      merged.push({ id: c.id, name: `${c.name}（手动）` });
      seen.add(c.id);
    }
  }
  customersCache = merged;
  const options = '<option value="">全部客户</option>' +
    merged.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
  const filterSel = document.getElementById('filter-customer');
  const filterCurrent = filterSel?.value || '';
  if (filterSel) {
    filterSel.innerHTML = options;
    filterSel.value = filterCurrent;
  }
}

function openManualOrderModal() {
  document.getElementById('manual-customer-name').value = '';
  document.getElementById('manual-purchase-no').value = '';
  document.getElementById('manual-purchase-seq').value = '1';
  document.getElementById('manual-batch-qty').value = '1';
  document.getElementById('manual-goods-no').value = '';
  document.getElementById('manual-goods-name').value = '';
  document.getElementById('manual-spec').value = '';
  document.getElementById('manual-purchase-date').value = new Date().toISOString().slice(0, 10);
  document.getElementById('manual-expect-date').value = '';
  document.getElementById('manual-remark').value = '';
  document.getElementById('manual-order-modal').classList.remove('hidden');
  document.getElementById('manual-customer-name').focus();
}

function closeManualOrderModal() {
  document.getElementById('manual-order-modal').classList.add('hidden');
}

async function saveManualOrder() {
  try {
    await api('/orders/manual', {
      method: 'POST',
      body: JSON.stringify({
        customer_name: document.getElementById('manual-customer-name').value.trim(),
        purchase_no: document.getElementById('manual-purchase-no').value.trim(),
        purchase_seq: document.getElementById('manual-purchase-seq').value.trim() || '1',
        product_goods_no: document.getElementById('manual-goods-no').value.trim(),
        product_goods_name: document.getElementById('manual-goods-name').value.trim(),
        product_spec: document.getElementById('manual-spec').value.trim(),
        batch_pur_qty: Number(document.getElementById('manual-batch-qty').value || 0),
        purchase_date: document.getElementById('manual-purchase-date').value,
        expect_arrival_date: document.getElementById('manual-expect-date').value,
        remark: document.getElementById('manual-remark').value.trim(),
      }),
    });
    closeManualOrderModal();
    showToast('手动录单成功', 'success');
    await loadCustomers();
    currentPage = 1;
    loadOrders();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function orderRow(o) {
  const qty = o.batch_pur_qty || o.output_qty;
  const pending = o.pending_ship_qty || 0;
  const shippedLocal = o.shipped_local_qty || 0;
  const hideOps = window.EMS.getCurrentUser()?.role === 'pmc';
  const classes = [];
  if (o.customer_kit_status === 'unkit') classes.push('kit-unkit');
  if (o.is_new_order) classes.push('row-new-order');
  const newTag = o.is_new_order ? ' <span class="new-order-tag">新</span>' : '';
  return `<tr class="${classes.join(' ')}">
    <td>${o.customer_name || '-'}</td>
    <td>${o.purchase_no}${newTag}</td>
    <td>${lineNo(o)}</td>
    <td>${o.product_goods_no || '-'}</td>
    <td>${o.product_goods_name || '-'}</td>
    <td class="cell-wrap">${o.product_spec || '—'}</td>
    <td>${qty}</td>
    <td>${customerKitBadge(o)}</td>
    <td>${fmtQty(o.delivery_qty, o.is_completed && !o.delivery_qty)}</td>
    <td>${fmtQty(o.receive_qty, o.is_completed && !o.receive_qty)}</td>
    <td>${o.is_completed ? fmtQty(0, true) : (o.un_receive_qty ?? 0)}</td>
    <td><strong>${pending}</strong></td>
    <td>${shippedLocal}</td>
    <td>${o.purchase_date || '-'}</td>
    <td>${o.expect_arrival_date || '-'}</td>
    <td>${statusBadge(o.is_completed, o.srm_status_name)}</td>
    <td>${o.is_completed ? '是' : '否'}</td>
    <td class="order-remark-cell"><input type="text" class="order-remark-input" data-line-key="${encodeURIComponent(o.line_key)}" data-saved="${(o.remark || '').replace(/"/g, '&quot;')}" value="${(o.remark || '').replace(/"/g, '&quot;')}" placeholder="尾数状态等"></td>
    ${hideOps ? '' : `<td>
      <button class="btn btn-mini" data-scan-line="${encodeURIComponent(o.line_key)}" data-scan-pending="${pending}" data-scan-shipped="${shippedLocal}" data-scan-qty="${qty}" data-scan-no="${o.purchase_no}" ${o.is_completed ? 'disabled' : ''}>扫码</button>
    </td>`}
  </tr>`;
}

async function loadStatusOptions() {
  const customerId = document.getElementById('filter-customer')?.value || '';
  const q = customerId ? `?customer_id=${encodeURIComponent(customerId)}` : '';
  const opts = await api('/orders/status-options' + q);
  const sel = document.getElementById('filter-srm-status');
  const current = sel.value;
  sel.innerHTML = '<option value="">全部 SRM 状态</option>' +
    opts.map(o => `<option value="${o.name}">${o.name} (${o.count})</option>`).join('');
  sel.value = current;
}

function getFilterParams() {
  const newOnly = document.getElementById('filter-new-only')?.value || 'all';
  const params = {
    customer_id: document.getElementById('filter-customer')?.value || '',
    keyword: document.getElementById('search-keyword').value.trim(),
    completed: document.getElementById('filter-completed').value,
    srm_status: document.getElementById('filter-srm-status').value,
    receive_filter: document.getElementById('filter-receive').value,
    date_from: document.getElementById('filter-date-from').value,
    date_to: document.getElementById('filter-date-to').value,
  };
  if (newOnly === 'yes') params.new_only = 'true';
  return params;
}

function resetFilters() {
  document.getElementById('filter-customer').value = '';
  document.getElementById('search-keyword').value = '';
  document.getElementById('filter-completed').value = 'all';
  const newOnly = document.getElementById('filter-new-only');
  if (newOnly) newOnly.value = 'all';
  document.getElementById('filter-srm-status').value = '';
  document.getElementById('filter-receive').value = 'all';
  document.getElementById('filter-date-from').value = '';
  document.getElementById('filter-date-to').value = '';
  currentPage = 1;
  loadOrders();
}

async function refreshNewOrderBadge() {
  try {
    const data = await api('/orders/new-orders?limit=1');
    updateNotifyBadge(data.count || 0);
  } catch (_) {}
}

async function openNewOrdersModal(syncHint) {
  const modal = document.getElementById('new-orders-modal');
  const tbody = document.getElementById('new-orders-tbody');
  const hint = document.getElementById('new-orders-hint');
  if (!modal || !tbody) return;
  tbody.innerHTML = '<tr><td colspan="7">加载中…</td></tr>';
  modal.classList.remove('hidden');
  try {
    const data = await api('/orders/new-orders?limit=200');
    const items = data.items || [];
    updateNotifyBadge(data.count || 0);
    if (hint) {
      hint.textContent = `客户下单日期在近 ${data.days || 3} 个自然日内（自 ${data.date_from || '—'} 起）视为新订单${syncHint || ''}；共 ${data.count || 0} 条`;
    }
    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="7">暂无近3天新订单</td></tr>';
      return;
    }
    tbody.innerHTML = items.map((o) => {
      const qty = o.batch_pur_qty || o.output_qty || 0;
      return `<tr>
        <td>${o.customer_name || '-'}</td>
        <td>${o.purchase_no || '-'}</td>
        <td>${o.product_goods_no || '-'}</td>
        <td>${o.product_goods_name || '-'}</td>
        <td>${qty}</td>
        <td>${o.purchase_date || '-'}</td>
        <td>${o.expect_arrival_date || '-'}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7">${e.message || '加载失败'}</td></tr>`;
  }
}

function closeNewOrdersModal() {
  document.getElementById('new-orders-modal')?.classList.add('hidden');
}

function exportOrders() {
  const f = getFilterParams();
  const params = new URLSearchParams(f);
  fetch(API + '/orders/export?' + params.toString(), { headers: authHeaders() })
    .then(res => {
      if (!res.ok) throw new Error('导出失败');
      const disposition = res.headers.get('Content-Disposition') || '';
      const match = disposition.match(/filename="?([^"]+)"?/);
      const filename = match ? decodeURIComponent(match[1]) : 'orders.xlsx';
      return res.blob().then(blob => ({ blob, filename }));
    })
    .then(({ blob, filename }) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    })
    .catch(e => showToast(e.message, 'error'));
}

async function loadOrders() {
  const f = getFilterParams();
  const params = new URLSearchParams({
    page: currentPage, page_size: pageSize, ...f,
  });
  const countParams = new URLSearchParams(f);
  const [orders, countRes] = await Promise.all([
    api('/orders?' + params),
    api('/orders/count?' + countParams),
  ]);
  const total = countRes.total;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  document.getElementById('page-info').textContent = `第 ${currentPage} / ${totalPages} 页（共 ${total} 行）`;

  const tbody = document.getElementById('orders-table');
  if (!orders.length) {
    tbody.innerHTML = '<tr><td colspan="19" class="empty">暂无数据</td></tr>';
  } else {
    tbody.innerHTML = orders.map(orderRow).join('');
    tbody.querySelectorAll('[data-scan-line]').forEach(btn => {
      btn.addEventListener('click', () => openScanModal(btn.dataset));
    });
    tbody.querySelectorAll('.order-remark-input').forEach(input => {
      input.addEventListener('blur', () => saveOrderRemark(input));
      input.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
      });
    });
  }
  refreshNewOrderBadge();
}

async function saveOrderRemark(input) {
  const lineKey = decodeURIComponent(input.dataset.lineKey || '');
  const remark = input.value.trim();
  const prev = input.dataset.saved || '';
  if (remark === prev) return;
  try {
    await api(`/orders/${encodeURIComponent(lineKey)}/remark`, {
      method: 'PATCH',
      body: JSON.stringify({ remark }),
    });
    input.dataset.saved = remark;
    showToast('备注已保存', 'success');
  } catch (e) {
    input.value = prev;
    showToast(e.message, 'error');
  }
}

function openScanModal(dataset) {
  scanTarget = decodeURIComponent(dataset.scanLine || '');
  document.getElementById('scan-order-brief').textContent =
    `订单：${dataset.scanNo || scanTarget}`;
  document.getElementById('scan-order-qty').textContent = dataset.scanQty || 0;
  document.getElementById('scan-pending-qty').textContent = dataset.scanPending || 0;
  document.getElementById('scan-shipped-qty').textContent = dataset.scanShipped || 0;
  document.getElementById('scan-operator').value = localStorage.getItem('ems_scan_operator') || '';
  document.getElementById('scan-barcode-input').value = '';
  document.getElementById('scan-modal').classList.remove('hidden');
  loadScanRecent();
  setTimeout(() => document.getElementById('scan-barcode-input').focus(), 100);
}

function closeScanModal() {
  scanTarget = null;
  document.getElementById('scan-modal').classList.add('hidden');
}

async function loadScanRecent() {
  if (!scanTarget) return;
  const ul = document.getElementById('scan-recent-list');
  try {
    const rows = await api(`/packing/scans/${encodeURIComponent(scanTarget)}?status=pending&limit=15`);
    if (!rows.length) {
      ul.innerHTML = '<li class="muted">暂无扫码记录</li>';
      return;
    }
    ul.innerHTML = rows.map(r => `<li>${r.barcode}</li>`).join('');
  } catch (_) {
    ul.innerHTML = '<li class="muted">加载失败</li>';
  }
}

async function submitScanBarcode(barcode) {
  if (!scanTarget) return;
  const code = (barcode || '').trim();
  if (!code) return;
  const operator = document.getElementById('scan-operator').value.trim();
  if (operator) localStorage.setItem('ems_scan_operator', operator);
  try {
    const res = await api('/packing/scan', {
      method: 'POST',
      body: JSON.stringify({
        line_key: scanTarget,
        barcode: code,
        operator,
      }),
    });
    document.getElementById('scan-pending-qty').textContent = res.pending_ship_qty;
    document.getElementById('scan-shipped-qty').textContent = res.shipped_local_qty;
    showToast(`入库成功 ${res.pending_ship_qty}/${res.order_qty}`, 'success');
    document.getElementById('scan-barcode-input').value = '';
    document.getElementById('scan-barcode-input').focus();
    await loadScanRecent();
    loadOrders();
  } catch (e) {
    showToast(e.message, 'error');
    document.getElementById('scan-barcode-input').value = '';
    document.getElementById('scan-barcode-input').focus();
  }
}

function openShipModal(lineKey, pendingQty) {
  shipTarget = decodeURIComponent(lineKey);
  document.getElementById('ship-pending-qty').value = pendingQty;
  document.getElementById('ship-date').value = new Date().toISOString().slice(0, 10);
  document.getElementById('ship-box-count').value = '1';
  document.getElementById('ship-logistics').value = '';
  document.getElementById('ship-remark').value = '';
  document.getElementById('ship-operator').value = localStorage.getItem('ems_scan_operator') || '';
  document.getElementById('ship-order-brief').textContent = `订单行：${shipTarget}`;
  document.getElementById('ship-modal').classList.remove('hidden');
}

function closeShipModal() {
  shipTarget = null;
  document.getElementById('ship-modal').classList.add('hidden');
}

async function confirmShip() {
  if (!shipTarget) return;
  try {
    const res = await api('/packing/ship', {
      method: 'POST',
      body: JSON.stringify({
        line_key: shipTarget,
        ship_date: document.getElementById('ship-date').value,
        box_count: Number(document.getElementById('ship-box-count').value || 1),
        logistics: document.getElementById('ship-logistics').value.trim(),
        remark: document.getElementById('ship-remark').value.trim(),
        operator: document.getElementById('ship-operator').value.trim(),
      }),
    });
    const op = document.getElementById('ship-operator').value.trim();
    if (op) localStorage.setItem('ems_scan_operator', op);
    closeShipModal();
    showToast(`发货成功：${res.shipment_no}，共 ${res.qty} 片`, 'success');
    window.open(`/static/ship_print.html?id=${res.id}`, '_blank');
    loadOrders();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

async function runSync(btn) {
  const label = document.getElementById('btn-sync-label');
  btn.disabled = true;
  if (label) label.textContent = '同步中...';
  try {
    const res = await api('/sync/run', { method: 'POST' });
    if (res.status === 'failed') {
      showToast('同步失败: ' + (res.message || '未知错误'), 'error');
    } else if (res.status === 'running') {
      showToast(res.message || '同步正在进行中', 'error');
    } else if (res.status === 'partial') {
      showToast(res.message || '部分同步成功', 'error');
    } else {
      showToast(res.message || '同步完成', 'success');
    }
    if ((res.new_orders_count > 0 || res.kitting_alert_count > 0) && res.sync_log_id) {
      notifySyncItem({
        sync_log_id: res.sync_log_id,
        new_orders_count: res.new_orders_count || 0,
        orders: res.new_orders || [],
        kitting_alert_count: res.kitting_alert_count || 0,
        kitting_alerts: res.kitting_alerts || [],
      });
      lastNotifiedLogId = Math.max(lastNotifiedLogId, res.sync_log_id);
      localStorage.setItem(NOTIFY_STORAGE_KEY, String(lastNotifiedLogId));
    }
    await loadOrders();
    await refreshNewOrderBadge();
  } catch (e) {
    showToast('同步失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    if (label) label.textContent = '立即同步';
    if (pendingNotifyCount > 0) updateNotifyBadge(pendingNotifyCount);
  }
}

document.getElementById('btn-system-login').addEventListener('click', loginSystem);
document.getElementById('btn-change-password')?.addEventListener('click', submitChangePassword);
document.getElementById('change-new-password2')?.addEventListener('keydown', e => {
  if (e.key === 'Enter') submitChangePassword();
});
document.getElementById('login-password').addEventListener('keydown', e => {
  if (e.key === 'Enter') loginSystem();
});
document.getElementById('login-username').addEventListener('keydown', e => {
  if (e.key === 'Enter') loginSystem();
});
document.getElementById('btn-logout').addEventListener('click', logout);

document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => switchPage(btn.dataset.page));
});

document.getElementById('btn-sync-now').addEventListener('click', e => runSync(e.currentTarget));
document.getElementById('btn-new-orders')?.addEventListener('click', () => openNewOrdersModal());
document.getElementById('btn-new-orders-close')?.addEventListener('click', closeNewOrdersModal);
document.getElementById('btn-new-orders-filter')?.addEventListener('click', () => {
  const sel = document.getElementById('filter-new-only');
  if (sel) sel.value = 'yes';
  closeNewOrdersModal();
  currentPage = 1;
  loadOrders();
});
document.getElementById('filter-new-only')?.addEventListener('change', () => {
  currentPage = 1;
  loadOrders();
});
document.getElementById('btn-search').addEventListener('click', () => { currentPage = 1; loadOrders(); });
document.getElementById('btn-reset').addEventListener('click', resetFilters);
document.getElementById('btn-export').addEventListener('click', exportOrders);
document.getElementById('search-keyword').addEventListener('keydown', e => {
  if (e.key === 'Enter') { currentPage = 1; loadOrders(); }
});
document.getElementById('btn-prev').addEventListener('click', () => { if (currentPage > 1) { currentPage--; loadOrders(); } });
document.getElementById('btn-next').addEventListener('click', () => { currentPage++; loadOrders(); });

document.getElementById('filter-customer').addEventListener('change', () => {
  currentPage = 1;
  loadStatusOptions();
  loadOrders();
});

document.getElementById('btn-manual-order').addEventListener('click', openManualOrderModal);
document.getElementById('btn-manual-cancel').addEventListener('click', closeManualOrderModal);
document.getElementById('btn-manual-save').addEventListener('click', saveManualOrder);
document.getElementById('btn-ship-cancel').addEventListener('click', closeShipModal);
document.getElementById('btn-ship-confirm').addEventListener('click', confirmShip);
document.getElementById('btn-scan-cancel').addEventListener('click', closeScanModal);
document.getElementById('scan-barcode-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') submitScanBarcode(e.target.value);
});

function applyEmbedMode() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('embed') !== '1') return false;
  document.body.classList.add('embed-mode');
  const page = params.get('page');
  if (page) switchPage(page);
  return true;
}

window.addEventListener('message', (event) => {
  if (event.origin !== window.location.origin) return;
  const data = event.data;
  if (!data || data.type !== 'ems-embed-tab') return;
  if (data.page === 'engineering' && window.EngineeringApp?.switchTab) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-engineering')?.classList.add('active');
    const go = async () => {
      if (data.customer && window.EngineeringApp.ensureCustomer) {
        await window.EngineeringApp.ensureCustomer(data.customer);
      }
      if (data.tab) window.EngineeringApp.switchTab(data.tab);
      if (data.todo === '1' && window.EngineeringApp.openTodo) {
        window.EngineeringApp.refreshTodo?.();
        window.EngineeringApp.openTodo();
      }
    };
    go();
  } else if (data.page === 'warehouse' && window.WarehouseApp?.switchTab) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-warehouse')?.classList.add('active');
    window.WarehouseApp.switchTab(data.tab);
  } else if (data.page === 'scheduling' && window.SchedulingApp?.switchTab) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-scheduling')?.classList.add('active');
    window.SchedulingApp.switchTab(data.tab);
  }
});

(async function init() {
  const embedded = applyEmbedMode();
  loadStoredUser();
  if (authToken) {
    const ok = await checkAuth();
    if (ok) {
      if (mustChangePassword()) {
        showChangePassword(true);
        return;
      }
      showLogin(false);
      applyRoleUI();
      if (embedded) {
        const page = new URLSearchParams(window.location.search).get('page');
        if (page) switchPage(page);
      }
      await bootApp();
      return;
    }
    clearAuth();
  }
  if (embedded) return;
  showLogin(true);
})();
