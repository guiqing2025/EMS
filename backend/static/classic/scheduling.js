(function () {
  const API = '/api/scheduling';
  let activeTab = 'smt';
  let meta = { material_statuses: {}, schedule_statuses: {}, tooling_statuses: {} };
  let rows = [];

  async function schedApi(path, opts = {}) {
    const res = await fetch(API + path, {
      ...opts,
      headers: { ...window.EMS.authHeaders(), 'Content-Type': 'application/json', ...(opts.headers || {}) },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    return res.json();
  }

  function kitLabel(s) {
    return meta.material_statuses[s] || { ready: '齐套', partial: '部分齐', shortage: '欠料', unknown: '未算', unbound: '未绑' }[s] || s;
  }

  function schedLabel(s) {
    return meta.schedule_statuses[s] || { planned: '待产', running: '生产中', done: '完工', hold: '暂停' }[s] || s;
  }

  function kitClass(s) {
    return `kit-badge kit-${s || 'unknown'}`;
  }

  function schedClass(s) {
    return `sched-badge sched-${s || 'planned'}`;
  }

  function statusOptions(type, selected) {
    const map = type === 'material' ? meta.material_statuses : meta.schedule_statuses;
    const fallback = type === 'material'
      ? { unknown: '未算', ready: '齐套', partial: '部分齐', shortage: '欠料' }
      : { planned: '待产', running: '生产中', done: '完工', hold: '暂停' };
    const src = Object.keys(map).length ? map : fallback;
    return Object.entries(src).map(([k, v]) => `<option value="${k}"${k === selected ? ' selected' : ''}>${v}</option>`).join('');
  }

  function toolingLabel(s) {
    return meta.tooling_statuses[s] || { ready: '工装齐全', partial: '工装部分', pending: '工装未登', unknown: '—' }[s] || s;
  }

  function toolingClass(s) {
    if (s === 'ready') return 'kit-badge kit-ready';
    if (s === 'partial') return 'kit-badge kit-partial';
    if (s === 'pending') return 'kit-badge kit-shortage';
    return 'kit-badge kit-unknown';
  }

  function rowHtml(r) {
    return `
      <tr data-id="${r.id}">
        <td><input class="sched-inline" data-field="line_name" value="${esc(r.line_name || '')}"></td>
        <td><input class="sched-inline" data-field="purchase_no" value="${esc(r.purchase_no || '')}"></td>
        <td><input class="sched-inline" data-field="model_code" value="${esc(r.model_code || '')}"></td>
        <td><input class="sched-inline" data-field="model_name" value="${esc(r.model_name || '')}"></td>
        <td><input class="sched-inline" data-field="process" value="${esc(r.process || '')}"></td>
        <td><input class="sched-inline sched-num" data-field="order_qty" type="number" min="0" step="1" value="${r.order_qty || 0}"></td>
        <td><input class="sched-inline" data-field="due_date" type="date" value="${esc(r.due_date || '')}"></td>
        <td><span class="${kitClass(r.material_status)}">${kitLabel(r.material_status)}</span></td>
        <td><span class="${toolingClass(r.tooling_status)}">${esc(r.tooling_status_label || toolingLabel(r.tooling_status))}</span></td>
        <td><input class="sched-inline" data-field="daily_plan" value="${esc(r.daily_plan || '')}"></td>
        <td>
          <select class="sched-select" data-field="schedule_status">${statusOptions('schedule', r.schedule_status)}</select>
        </td>
        <td><input class="sched-inline" data-field="remark" value="${esc(r.remark || '')}"></td>
        <td class="sched-actions">
          <button class="btn btn-xs btn-save-row" title="保存">保存</button>
          <button class="btn btn-xs btn-del-row" title="删除">删</button>
        </td>
      </tr>`;
  }

  function esc(v) {
    return String(v).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }

  function collectRow(tr) {
    const data = { line_type: activeTab, refresh_kitting: true };
    tr.querySelectorAll('[data-field]').forEach(el => {
      const key = el.dataset.field;
      if (el.type === 'number') data[key] = Number(el.value || 0);
      else data[key] = el.value;
    });
    return data;
  }

  async function loadMeta() {
    meta = await schedApi('/meta');
  }

  async function loadRows() {
    rows = await schedApi(`?line_type=${activeTab}`);
    const tbody = document.getElementById('sched-table-body');
    if (!tbody) return;
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="13" class="empty">暂无排产，点击「新增排产行」</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(rowHtml).join('');
    bindRowEvents();
  }

  function bindRowEvents() {
    document.querySelectorAll('#sched-table-body .btn-save-row').forEach(btn => {
      btn.addEventListener('click', async () => {
        const tr = btn.closest('tr');
        const id = Number(tr.dataset.id);
        try {
          await schedApi(`/${id}`, { method: 'PUT', body: JSON.stringify(collectRow(tr)) });
          window.EMS.showToast('已保存');
          await loadRows();
        } catch (e) {
          window.EMS.showToast(e.message, 'error');
        }
      });
    });
    document.querySelectorAll('#sched-table-body .btn-del-row').forEach(btn => {
      btn.addEventListener('click', async () => {
        const tr = btn.closest('tr');
        if (!confirm('确定删除此行？')) return;
        try {
          await schedApi(`/${tr.dataset.id}`, { method: 'DELETE' });
          await loadRows();
        } catch (e) {
          window.EMS.showToast(e.message, 'error');
        }
      });
    });
  }

  async function addRow() {
    try {
      await schedApi('', {
        method: 'POST',
        body: JSON.stringify({ line_type: activeTab, schedule_status: 'planned', process: activeTab.toUpperCase() }),
      });
      await loadRows();
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  async function refreshKitting() {
    try {
      const res = await schedApi(`/refresh-kitting?line_type=${activeTab}`, { method: 'POST' });
      window.EMS.showToast(res.message || '已刷新');
      await loadRows();
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  function switchTab(tab) {
    activeTab = tab;
    document.querySelectorAll('[data-sched-tab]').forEach(btn => btn.classList.toggle('active', btn.dataset.schedTab === tab));
    loadRows();
  }

  function customerKitCell(o) {
    if (o.customer_kit_status === 'na') return '—';
    const label = o.customer_kit_status_label || o.customer_kit_status;
    const sets = o.collected_sets_qty || 0;
    const qty = o.batch_pur_qty || o.output_qty || 0;
    return `<span class="kit-badge kit-cust-${o.customer_kit_status}">${label}</span> ${sets}/${qty}套`;
  }

  function toolingCell(o) {
    if (!o.tooling_status || o.tooling_status === 'unknown') return '—';
    return `<span class="${toolingClass(o.tooling_status)}">${o.tooling_status_label || toolingLabel(o.tooling_status)}</span>`;
  }

  function canImportOrder(o) {
    return o.customer_kit_status !== 'unkit';
  }

  async function searchOrders() {
    const kw = document.getElementById('sched-import-search')?.value?.trim() || '';
    const params = new URLSearchParams({ page_size: '30', completed: 'incomplete' });
    if (kw) params.set('keyword', kw);
    const list = await window.EMS.api('/orders?' + params.toString());
    const tbody = document.getElementById('sched-import-list');
    if (!list.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty">无匹配订单</td></tr>';
      return;
    }
    tbody.innerHTML = list.map(o => {
      const blocked = !canImportOrder(o);
      return `
      <tr class="${blocked ? 'kit-unkit' : ''}">
        <td>${o.customer_name || o.customer_id}</td>
        <td>${o.purchase_no}</td>
        <td>${o.product_goods_no || '—'}</td>
        <td>${o.batch_pur_qty || 0}</td>
        <td>${customerKitCell(o)}</td>
        <td>${toolingCell(o)}</td>
        <td>${o.expect_arrival_date || '—'}</td>
        <td>${blocked
          ? '<span class="kit-qty-hint">未齐套</span>'
          : `<button class="btn btn-xs btn-import-order" data-key="${o.line_key}" data-tooling-warn="${o.tooling_complete ? '0' : '1'}">导入</button>`}
        </td>
      </tr>`;
    }).join('');
    tbody.querySelectorAll('.btn-import-order').forEach(btn => {
      btn.addEventListener('click', async () => {
        try {
          await schedApi('/import-order', {
            method: 'POST',
            body: JSON.stringify({ line_key: btn.dataset.key, line_type: activeTab }),
          });
          document.getElementById('sched-import-modal')?.classList.add('hidden');
          const warn = btn.dataset.toolingWarn === '1';
          window.EMS.showToast(warn ? '已导入排产（工装未登齐，请到仓库→工装登记补全）' : '已导入排产', warn ? 'warning' : 'success');
          await loadRows();
        } catch (e) {
          window.EMS.showToast(e.message, 'error');
        }
      });
    });
  }

  function applySchedTabFromUrl() {
    const tab = new URLSearchParams(window.location.search).get('tab');
    if (tab !== 'dip' && tab !== 'smt') return;
    activeTab = tab;
    document.querySelectorAll('[data-sched-tab]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.schedTab === tab);
    });
  }

  async function load() {
    await loadMeta();
    applySchedTabFromUrl();
    await loadRows();
  }

  function bindEvents() {
    document.querySelectorAll('[data-sched-tab]').forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.schedTab));
    });
    document.getElementById('btn-sched-add')?.addEventListener('click', addRow);
    document.getElementById('btn-sched-refresh-kit')?.addEventListener('click', refreshKitting);
    document.getElementById('btn-sched-import-order')?.addEventListener('click', () => {
      document.getElementById('sched-import-modal')?.classList.remove('hidden');
    });
    document.getElementById('btn-sched-import-cancel')?.addEventListener('click', () => {
      document.getElementById('sched-import-modal')?.classList.add('hidden');
    });
    document.getElementById('btn-sched-import-search')?.addEventListener('click', searchOrders);
    document.getElementById('sched-import-search')?.addEventListener('keydown', e => { if (e.key === 'Enter') searchOrders(); });
  }

  bindEvents();
  window.SchedulingApp = { load, switchTab };
})();
