(function () {
  const API = '/api/warehouse';
  let materials = [];
  let activeWhTab = 'materials';
  let activeDeptTab = 'pending';

  async function whApi(path, options = {}) {
    const res = await fetch(API + path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...window.EMS.authHeaders(),
        ...(options.headers || {}),
      },
    });
    if (res.status === 401) {
      location.reload();
      throw new Error('请重新登录');
    }
    if (!res.ok) {
      let msg = await res.text();
      try { msg = JSON.parse(msg).detail || msg; } catch (_) {}
      throw new Error(msg || '请求失败');
    }
    if (res.headers.get('content-type')?.includes('application/json')) return res.json();
    return res.blob();
  }

  function statusLabel(s) {
    return {
      pending_confirm: '待确认',
      confirmed: '已签收',
      rejected: '已拒收',
      pending_warehouse: '待仓库确认',
    }[s] || s;
  }

  function movementLabel(t) {
    return { stock_in: '手工来料', issue_out: '发料', return_in: '退料', excel_sync: '共享盘同步' }[t] || t;
  }

  function sourceLabel(s) {
    return { manual: '手工来料', excel_sync: '共享盘同步', return: '退料入库' }[s] || s;
  }

  async function loadCustomers() {
    const customers = await whApi('/customers');
    const sel = document.getElementById('wh-filter-customer');
    if (!sel) return;
    sel.innerHTML = '<option value="">全部客户</option>' +
      customers.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
  }

  function fmtQty(v) {
    if (v == null || v === '') return '-';
    const n = Number(v);
    if (Number.isNaN(n)) return '-';
    return n % 1 === 0 ? String(n) : n.toFixed(2).replace(/\.?0+$/, '');
  }

  async function loadMaterials() {
    const customerId = document.getElementById('wh-filter-customer')?.value || '';
    const keyword = document.getElementById('wh-search')?.value?.trim() || '';
    const qs = new URLSearchParams();
    if (customerId) qs.set('customer_id', customerId);
    if (keyword) qs.set('keyword', keyword);
    materials = await whApi('/materials?' + qs.toString());
    const tbody = document.getElementById('wh-materials-table');
    if (!materials.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty">暂无数据，请点击「从共享盘导入」初始化库存</td></tr>';
      return;
    }
    tbody.innerHTML = materials.map(m => {
      const alias = m.is_substitute_alias ? '<span class="cell-muted" title="客户替代料号">[替代] </span>' : '';
      const subs = (m.substitute_codes || []).length
        ? `<div class="cell-muted" title="关联料号（库存不合并）">关联 ${m.substitute_codes.join('、')}</div>` : '';
      const qtyClass = m.qty < 0 ? 'qty-negative' : '';
      return `
      <tr class="wh-row-click" data-material-id="${m.id}" title="点击查看进出账明细与关联订单">
        <td>${m.customer_name}</td>
        <td>${alias}${m.material_code}</td>
        <td>${m.material_name || '-'}</td>
        <td>${m.spec || '-'}</td>
        <td class="${qtyClass}">${fmtQty(m.qty)}</td>
        <td><strong>${fmtQty(m.available_qty)}</strong>${subs}</td>
        <td>${fmtQty(m.excel_in_qty)}</td>
        <td>${fmtQty(m.excel_demand_qty)}</td>
        <td>${m.excel_synced_at ? window.EMS.fmtDate(m.excel_synced_at) : '-'}</td>
      </tr>`;
    }).join('');
    tbody.querySelectorAll('.wh-row-click').forEach(tr => {
      tr.addEventListener('click', () => showMaterialDetail(tr.dataset.materialId));
    });
    fillMaterialSelects();
  }

  function fillMaterialSelects() {
    const opts = materials.map(m =>
      `<option value="${m.id}">${m.customer_name} | ${m.material_code} | 可用${m.available_qty}</option>`
    ).join('');
    ['wh-in-material', 'wh-issue-material', 'wh-op-material', 'dept-return-material'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = opts || '<option value="">暂无物料</option>';
    });
  }

  async function loadIssues() {
    const rows = await whApi('/issues');
    const tbody = document.getElementById('wh-issues-table');
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty">暂无发料单</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(r => `
      <tr>
        <td>${r.issue_no}</td>
        <td>${r.customer_name}</td>
        <td>${r.material_code}</td>
        <td>${r.qty}</td>
        <td>${r.department.toUpperCase()}</td>
        <td>${statusLabel(r.status)}</td>
        <td>${window.EMS.fmtDate(r.created_at)}</td>
      </tr>`).join('');
  }

  async function loadReturns() {
    const rows = await whApi('/returns');
    const tbody = document.getElementById('wh-returns-table');
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty">暂无退料单</td></tr>';
      return;
    }
    const user = window.EMS.getCurrentUser();
    const canConfirm = user?.role === 'warehouse' || user?.role === 'admin';
    tbody.innerHTML = rows.map(r => `
      <tr>
        <td>${r.return_no}</td>
        <td>${r.customer_name}</td>
        <td>${r.material_code}</td>
        <td>${r.qty}</td>
        <td>${r.department.toUpperCase()}</td>
        <td>${statusLabel(r.status)}</td>
        <td>${canConfirm && r.status === 'pending_warehouse'
          ? `<button class="btn btn-sm" data-confirm-return="${r.id}">确认入库</button>
             <button class="btn btn-sm" data-reject-return="${r.id}">驳回</button>`
          : '-'}</td>
      </tr>`).join('');
    tbody.querySelectorAll('[data-confirm-return]').forEach(btn => {
      btn.addEventListener('click', () => confirmReturn(btn.dataset.confirmReturn));
    });
    tbody.querySelectorAll('[data-reject-return]').forEach(btn => {
      btn.addEventListener('click', () => rejectReturn(btn.dataset.rejectReturn));
    });
  }

  let stockInMaterialFilter = null;

  async function loadStockIns(materialId) {
    const qs = new URLSearchParams();
    if (materialId) qs.set('material_id', materialId);
    const customerId = document.getElementById('wh-filter-customer')?.value || '';
    if (customerId) qs.set('customer_id', customerId);
    const rows = await whApi('/stock-ins?' + qs.toString());
    const tbody = document.getElementById('wh-stock-ins-table');
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty">暂无来料记录</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(r => `
      <tr>
        <td>${window.EMS.fmtDate(r.created_at)}</td>
        <td>${r.customer_name}</td>
        <td>${r.material_code}</td>
        <td>${r.material_name || '-'}</td>
        <td>${r.qty}</td>
        <td>${r.source_name || sourceLabel(r.source)}</td>
        <td>${r.operator || '-'}</td>
        <td>${r.receipt_no}</td>
        <td>${r.remark || '-'}</td>
      </tr>`).join('');
  }

  function stockStatusLabel(summary) {
    if (summary.stock_status === 'enough') return '<span class="text-ok">够用</span>';
    if (summary.stock_status === 'short') {
      const g = summary.stock_gap != null ? Math.abs(summary.stock_gap) : '';
      return `<span class="qty-negative">欠 ${fmtQty(g)}</span>`;
    }
    return '—';
  }

  async function showMaterialDetail(materialId) {
    const modal = document.getElementById('wh-material-detail-modal');
    const body = document.getElementById('wh-material-detail-body');
    if (!modal || !body) return;
    modal.classList.remove('hidden');
    body.innerHTML = '<p class="empty">加载中…</p>';
    try {
      const d = await whApi(`/materials/${materialId}/detail`);
      const m = d.material;
      const s = d.summary;
      body.innerHTML = `
        <div class="mat-detail-head">
          <div>
            <div class="mat-detail-code">${m.material_code}</div>
            <div>${m.material_name || '—'}</div>
            <div class="cell-muted">${m.spec || ''}</div>
          </div>
          <button class="btn btn-primary" id="wh-detail-operate" data-id="${m.id}">进出账操作</button>
        </div>
        <div class="mat-stats-row">
          <div class="mat-stat"><span>当前库存</span><strong class="${m.qty < 0 ? 'qty-negative' : ''}">${fmtQty(s.current_qty)}</strong></div>
          <div class="mat-stat"><span>盘点+来料</span><strong>${fmtQty((s.excel_count_qty||0)+(s.excel_in_qty||0))}</strong></div>
          <div class="mat-stat"><span>可用</span><strong>${fmtQty(s.available_qty)}</strong></div>
          <div class="mat-stat"><span>库存状态</span><strong>${stockStatusLabel(s)}</strong></div>
        </div>
        <p class="cell-muted">累计进 ${fmtQty(s.inbound_total)} · 累计出 ${fmtQty(s.outbound_total)} · 关联订单 ${s.order_count} 个</p>
        <h3>关联订单（${(d.orders||[]).length}）</h3>
        <div class="panel" style="max-height:200px;overflow:auto;margin-bottom:12px">
          <table><thead><tr><th>订单号</th><th>机型</th><th>已发</th><th>已退</th><th>最近</th></tr></thead><tbody>
          ${(d.orders||[]).length ? d.orders.map(o => `<tr><td>${o.order_no}</td><td>${o.product_model||'—'}</td><td>${fmtQty(o.issued_qty)}</td><td>${fmtQty(o.returned_qty)}</td><td>${o.last_date||'—'}</td></tr>`).join('') : '<tr><td colspan="5" class="empty">暂无</td></tr>'}
          </tbody></table>
        </div>
        <h3>进出账明细（${(d.movements||[]).length}）</h3>
        <div class="panel" style="max-height:240px;overflow:auto">
          <table><thead><tr><th>日期</th><th>类型</th><th>订单</th><th>数量</th><th>来源</th><th>备注</th></tr></thead><tbody>
          ${(d.movements||[]).length ? d.movements.map(r => `<tr><td>${r.doc_date||'—'}</td><td>${r.movement_type_name||excelMovementLabel(r.movement_type)}</td><td>${r.order_no||'—'}</td><td>${r.qty_delta>0?'+':''}${fmtQty(r.qty)}</td><td>${r.source==='system'?'系统':'共享盘'}</td><td>${r.remark||'—'}</td></tr>`).join('') : '<tr><td colspan="6" class="empty">暂无，请先同步共享盘或做账</td></tr>'}
          </tbody></table>
        </div>`;
      document.getElementById('wh-detail-operate')?.addEventListener('click', () => {
        modal.classList.add('hidden');
        fillMaterialSelects();
        const sel = document.getElementById('wh-op-material');
        if (sel) sel.value = String(m.id);
        document.getElementById('wh-operation-modal')?.classList.remove('hidden');
        toggleOpFields();
      });
    } catch (e) {
      body.innerHTML = `<p class="empty">${e.message}</p>`;
    }
  }

  function showMaterialStockIns(materialId) {
    stockInMaterialFilter = materialId;
    switchWhTab('stock-ins');
  }

  function excelMovementLabel(t) {
    return {
      inbound: '进账', issue: '发料', return: '退料', overissue: '超领',
      customer_return: '退客', smt_loss: 'SMT损耗', adjust: '盘亏超领',
    }[t] || t;
  }

  function toggleOpFields() {
    const type = document.getElementById('wh-op-type')?.value || 'inbound';
    const orderFields = document.getElementById('wh-op-order-fields');
    const processFields = document.getElementById('wh-op-process-fields');
    if (orderFields) orderFields.style.display = ['issue', 'return', 'overissue'].includes(type) ? 'block' : 'none';
    if (processFields) processFields.style.display = type === 'issue' ? 'block' : 'none';
  }

  async function saveOperation() {
    const material_id = Number(document.getElementById('wh-op-material').value);
    const movement_type = document.getElementById('wh-op-type').value;
    const qty = Number(document.getElementById('wh-op-qty').value);
    const payload = {
      material_id,
      movement_type,
      qty,
      order_no: document.getElementById('wh-op-order-no')?.value?.trim() || '',
      product_model: document.getElementById('wh-op-model')?.value?.trim() || '',
      order_qty: Number(document.getElementById('wh-op-order-qty')?.value) || undefined,
      process: document.getElementById('wh-op-process')?.value || undefined,
      department: document.getElementById('wh-op-dept')?.value || undefined,
      ref_no: document.getElementById('wh-op-ref-no')?.value?.trim() || '',
      remark: document.getElementById('wh-op-remark')?.value?.trim() || '',
    };
    try {
      await whApi('/operations', { method: 'POST', body: JSON.stringify(payload) });
      document.getElementById('wh-operation-modal').classList.add('hidden');
      window.EMS.showToast('进出账已提交，库存已更新');
      await loadMaterials();
      if (activeWhTab === 'movements') loadMovements();
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  async function loadMovements() {
    const qs = new URLSearchParams();
    const customerId = document.getElementById('wh-filter-customer')?.value || '';
    const keyword = document.getElementById('wh-search')?.value?.trim() || '';
    if (customerId) qs.set('customer_id', customerId);
    if (keyword) qs.set('keyword', keyword);
    const rows = await whApi('/movements?' + qs.toString());
    const tbody = document.getElementById('wh-movements-table');
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="13" class="empty">暂无进出账明细，请点击「从共享盘导入」</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(r => `
      <tr>
        <td>${r.doc_date || '-'}</td>
        <td>${r.movement_type_name || excelMovementLabel(r.movement_type)}</td>
        <td>${r.customer_name}</td>
        <td>${r.order_no || '-'}</td>
        <td>${r.product_model || '-'}</td>
        <td>${r.material_code}</td>
        <td>${r.material_name || '-'}</td>
        <td>${r.qty_delta > 0 ? '+' : ''}${fmtQty(r.qty)}</td>
        <td>${r.process ? r.process.toUpperCase() : '-'}</td>
        <td>${r.ref_no || '-'}</td>
        <td>${r.source === 'system' ? '系统' : '共享盘'}</td>
        <td>${r.operator || '-'}</td>
        <td>${r.remark || '-'}</td>
      </tr>`).join('');
  }

  let snapCache = { snapshotId: null, sheets: [] };

  async function loadSnapshotsList() {
    const rows = await whApi('/snapshots');
    const sel = document.getElementById('wh-snap-customer');
    if (!sel) return;
    sel.innerHTML = '<option value="">选择客户</option>' +
      rows.map(r => `<option value="${r.id}">${r.customer_name} · ${r.file_name} (${r.sheet_count}表)</option>`).join('');
    snapCache.list = rows;
  }

  async function onSnapCustomerChange() {
    const id = Number(document.getElementById('wh-snap-customer')?.value);
    const sheetSel = document.getElementById('wh-snap-sheet');
    if (!id || !sheetSel) return;
    const sheets = await whApi(`/snapshots/${id}/sheets`);
    snapCache.snapshotId = id;
    snapCache.sheets = sheets;
    sheetSel.innerHTML = '<option value="">选择工作表</option>' +
      sheets.map(s => `<option value="${encodeURIComponent(s.sheet_name)}">${s.sheet_name} (${s.row_count}×${s.col_count})</option>`).join('');
  }

  async function loadExcelRawSheet() {
    const snapshotId = snapCache.snapshotId || Number(document.getElementById('wh-snap-customer')?.value);
    const sheetEnc = document.getElementById('wh-snap-sheet')?.value;
    const info = document.getElementById('wh-snap-info');
    const table = document.getElementById('wh-excel-raw-table');
    if (!snapshotId || !sheetEnc) {
      window.EMS.showToast('请选择客户和工作表');
      return;
    }
    const sheetName = decodeURIComponent(sheetEnc);
    info.textContent = '加载中…';
    const data = await whApi(`/snapshots/${snapshotId}/sheets/${encodeURIComponent(sheetName)}/data?limit=2000`);
    info.textContent = `${sheetName}：共 ${data.row_count} 行 × ${data.col_count} 列（显示前 ${data.rows.length} 行，与 Excel 显示值一致）`;
    if (!data.rows.length) {
      table.innerHTML = '<tbody><tr><td class="empty">空表</td></tr></tbody>';
      return;
    }
    table.innerHTML = '<tbody>' + data.rows.map((row, i) =>
      `<tr><td class="cell-muted">${i + 1}</td>` + row.map(c => `<td>${c == null ? '' : String(c)}</td>`).join('') + '</tr>'
    ).join('') + '</tbody>';
  }

  async function loadLedger() {
    const rows = await whApi('/ledger');
    const tbody = document.getElementById('wh-ledger-table');
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty">暂无流水</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(r => `
      <tr>
        <td>${window.EMS.fmtDate(r.created_at)}</td>
        <td>${movementLabel(r.movement_type)}</td>
        <td>${r.material_code}</td>
        <td>${r.qty_delta > 0 ? '+' : ''}${r.qty_delta}</td>
        <td>${r.qty_after}</td>
        <td>${r.ref_no || '-'}</td>
        <td>${r.department ? r.department.toUpperCase() : '-'}</td>
        <td>${r.operator || '-'}</td>
      </tr>`).join('');
  }

  async function loadConfig() {
    const cfg = await whApi('/config');
    const el = document.getElementById('wh-path-info');
    if (el) {
      el.textContent = cfg.share_accessible
        ? `共享盘已连接：${cfg.share_resolved}`
        : `共享盘未挂载（配置路径：${cfg.share_path}），请先在 Mac 上挂载后再导入`;
    }
  }

  function switchWhTab(tab) {
    activeWhTab = tab;
    document.querySelectorAll('.wh-tab[data-wh-tab]').forEach(b => {
      b.classList.toggle('active', b.dataset.whTab === tab);
    });
    document.querySelectorAll('#page-warehouse .wh-panel').forEach(p => p.classList.add('hidden'));
    document.getElementById('wh-panel-' + tab)?.classList.remove('hidden');
    const mainFilter = document.getElementById('wh-main-filter');
    const headerActions = document.querySelector('#page-warehouse .wh-actions');
    const isTooling = tab === 'tooling';
    mainFilter?.classList.toggle('hidden', isTooling);
    headerActions?.classList.toggle('hidden', isTooling);
    if (tab === 'materials') loadMaterials();
    if (tab === 'stock-ins') loadStockIns(stockInMaterialFilter);
    if (tab === 'issues') loadIssues();
    if (tab === 'returns') loadReturns();
    if (tab === 'movements') loadMovements();
    if (tab === 'excel-raw') loadSnapshotsList();
    if (tab === 'ledger') loadLedger();
    if (tab === 'tooling') loadToolingCatalog();
  }

  async function load() {
    await loadConfig();
    await loadCustomers();
    switchWhTab(activeWhTab);
  }

  async function syncShare() {
    try {
      const res = await whApi('/sync-now', { method: 'POST' });
      const files = res.files || [];
      const ok = files.filter(f => f.status === 'success').length;
      window.EMS.showToast(res.message || `已同步 ${ok} 个客户`);
      await loadMaterials();
    } catch (e) {
      window.EMS.showToast(e.message, 'error', 6000);
    }
  }

  async function importExcel() {
    return syncShare();
  }

  async function downloadTemplate() {
    const blob = await whApi('/template');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '_模板.xlsx';
    a.click();
  }

  async function exportInventory() {
    const blob = await whApi('/export-inventory');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '库存导出.xlsx';
    a.click();
  }

  async function saveStockIn() {
    const material_id = Number(document.getElementById('wh-in-material').value);
    const qty = Number(document.getElementById('wh-in-qty').value);
    const remark = document.getElementById('wh-in-remark').value.trim();
    try {
      await whApi('/stock-in', {
        method: 'POST',
        body: JSON.stringify({ material_id, qty, remark }),
      });
      document.getElementById('wh-stock-in-modal').classList.add('hidden');
      window.EMS.showToast('来料入账成功');
      await loadMaterials();
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  async function saveIssue() {
    const material_id = Number(document.getElementById('wh-issue-material').value);
    const qty = Number(document.getElementById('wh-issue-qty').value);
    const department = document.getElementById('wh-issue-dept').value;
    const remark = document.getElementById('wh-issue-remark').value.trim();
    try {
      await whApi('/issues', {
        method: 'POST',
        body: JSON.stringify({ material_id, qty, department, remark }),
      });
      document.getElementById('wh-issue-modal').classList.add('hidden');
      window.EMS.showToast('发料单已提交，等待部门确认');
      switchWhTab('issues');
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  async function confirmReturn(id) {
    try {
      await whApi(`/returns/${id}/confirm`, { method: 'POST' });
      window.EMS.showToast('退料已入库');
      loadReturns();
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  async function rejectReturn(id) {
    const remark = prompt('驳回原因（可选）') || '';
    try {
      await whApi(`/returns/${id}/reject?remark=${encodeURIComponent(remark)}`, { method: 'POST' });
      window.EMS.showToast('已驳回');
      loadReturns();
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  // ---- 部门端 ----
  function switchDeptTab(tab) {
    activeDeptTab = tab;
    document.querySelectorAll('.wh-tab[data-dept-tab]').forEach(b => {
      b.classList.toggle('active', b.dataset.deptTab === tab);
    });
    document.getElementById('dept-pending-list').classList.toggle('hidden', tab !== 'pending');
    document.getElementById('dept-returns-list').classList.toggle('hidden', tab !== 'returns');
    document.getElementById('dept-apply-return').classList.toggle('hidden', tab !== 'apply-return');
    if (tab === 'pending') loadDeptPending();
    if (tab === 'returns') loadDeptReturns();
    if (tab === 'apply-return') loadMaterials().then(fillMaterialSelects);
  }

  async function loadDept() {
    const user = window.EMS.getCurrentUser();
    document.getElementById('dept-page-title').textContent =
      (user?.display_name || user?.department?.toUpperCase() || '部门') + ' · 领料确认';
    const summary = await whApi('/dept/summary');
    document.getElementById('dept-summary').innerHTML = `
      <div class="dept-stat"><span>待确认领料</span><strong>${summary.pending_issues}</strong></div>
      <div class="dept-stat"><span>退料处理中</span><strong>${summary.pending_returns}</strong></div>`;
    switchDeptTab(activeDeptTab);
  }

  async function loadDeptPending() {
    const rows = await whApi('/issues?status=pending_confirm');
    const box = document.getElementById('dept-pending-list');
    if (!rows.length) {
      box.innerHTML = '<p class="empty-card">暂无待确认领料</p>';
      return;
    }
    box.innerHTML = rows.map(r => `
      <div class="dept-card">
        <div class="dept-card-title">${r.material_code}</div>
        <div class="dept-card-meta">${r.customer_name} · ${r.material_name || ''}</div>
        <div class="dept-card-qty">数量 <strong>${r.qty}</strong></div>
        <div class="dept-card-meta">单号 ${r.issue_no}</div>
        <div class="dept-card-actions">
          <button class="btn btn-primary btn-block-mobile" data-confirm-issue="${r.id}">确认签收</button>
          <button class="btn btn-block-mobile" data-reject-issue="${r.id}">拒收</button>
        </div>
      </div>`).join('');
    box.querySelectorAll('[data-confirm-issue]').forEach(btn => {
      btn.addEventListener('click', () => deptConfirmIssue(btn.dataset.confirmIssue));
    });
    box.querySelectorAll('[data-reject-issue]').forEach(btn => {
      btn.addEventListener('click', () => deptRejectIssue(btn.dataset.rejectIssue));
    });
  }

  async function loadDeptReturns() {
    const rows = await whApi('/returns');
    const box = document.getElementById('dept-returns-list');
    if (!rows.length) {
      box.innerHTML = '<p class="empty-card">暂无退料记录</p>';
      return;
    }
    box.innerHTML = rows.map(r => `
      <div class="dept-card">
        <div class="dept-card-title">${r.return_no}</div>
        <div class="dept-card-meta">${r.material_code} · ${r.qty}</div>
        <div class="dept-card-meta">状态：${statusLabel(r.status)}</div>
      </div>`).join('');
  }

  async function deptConfirmIssue(id) {
    try {
      await whApi(`/issues/${id}/confirm`, { method: 'POST' });
      window.EMS.showToast('已确认签收');
      loadDept();
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  async function deptRejectIssue(id) {
    const remark = prompt('拒收原因（可选）') || '';
    try {
      await whApi(`/issues/${id}/reject?remark=${encodeURIComponent(remark)}`, { method: 'POST' });
      window.EMS.showToast('已拒收');
      loadDept();
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  async function submitDeptReturn() {
    const material_id = Number(document.getElementById('dept-return-material').value);
    const qty = Number(document.getElementById('dept-return-qty').value);
    const remark = document.getElementById('dept-return-remark').value.trim();
    try {
      await whApi('/returns', {
        method: 'POST',
        body: JSON.stringify({ material_id, qty, remark }),
      });
      window.EMS.showToast('退料申请已提交');
      switchDeptTab('returns');
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  let toolingCatalog = [];
  let toolingSelectedKey = null;
  const ENG_API = '/api/engineering';

  async function engApi(path, options = {}) {
    const res = await fetch(ENG_API + path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...window.EMS.authHeaders(),
        ...(options.headers || {}),
      },
    });
    if (res.status === 401) {
      location.reload();
      throw new Error('请重新登录');
    }
    if (!res.ok) {
      let msg = await res.text();
      try { msg = JSON.parse(msg).detail || msg; } catch (_) {}
      throw new Error(msg || '请求失败');
    }
    if (res.headers.get('content-type')?.includes('application/json')) return res.json();
    return res;
  }

  function toolingRowKey(row) {
    if (!row) return '';
    return `${row.internal_code}:${row.model_code}`;
  }

  function toolingRegBadge(registered) {
    return registered
      ? '<span class="kit-badge kit-ready">已登记</span>'
      : '<span class="kit-badge kit-partial">未登记</span>';
  }

  async function loadToolingCatalog() {
    const code = document.getElementById('wh-tooling-filter-code')?.value || '';
    const keyword = document.getElementById('wh-tooling-search')?.value?.trim() || '';
    const params = new URLSearchParams();
    if (code) params.set('internal_code', code);
    if (keyword) params.set('keyword', keyword);
    toolingCatalog = await engApi('/tooling/catalog?' + params.toString());
    const tbody = document.getElementById('wh-tooling-table');
    if (!tbody) return [];
    if (!toolingCatalog.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty">暂无在制订单机型</td></tr>';
      return [];
    }
    tbody.innerHTML = toolingCatalog.map(r => {
      const rowClass = toolingSelectedKey === toolingRowKey(r) ? ' selected' : '';
      const complete = r.tooling_complete ? ' eng-model-imported' : (r.registered_count ? ' eng-model-pending' : '');
      return `
      <tr class="wh-tooling-row${rowClass}${complete}" data-key="${toolingRowKey(r)}">
        <td>${r.internal_code}</td>
        <td><strong>${r.model_code}</strong></td>
        <td>${r.model_name || '—'}</td>
        <td>${toolingRegBadge(r.stencil_registered)}</td>
        <td>${toolingRegBadge(r.wave_fixture_registered)}</td>
        <td>${toolingRegBadge(r.ict_fct_fixture_registered)}</td>
      </tr>`;
    }).join('');
    tbody.querySelectorAll('.wh-tooling-row').forEach(tr => {
      tr.addEventListener('click', () => selectToolingModel(toolingCatalog.find(x => toolingRowKey(x) === tr.dataset.key)));
    });
    const el = document.getElementById('wh-tooling-meta');
    if (el) {
      const complete = toolingCatalog.filter(r => r.tooling_complete).length;
      el.textContent = `对照在制订单 ${toolingCatalog.length} 个机型 · 三类工装齐全 ${complete}`;
    }
    return toolingCatalog;
  }

  function renderToolingForm(entries) {
    const byType = {};
    (entries || []).forEach(e => { byType[e.tool_type] = e; });
    document.querySelectorAll('#wh-tooling-form-table tr[data-tool-type]').forEach(tr => {
      const toolType = tr.dataset.toolType;
      const data = byType[toolType] || {};
      tr.querySelector('[data-field="tool_code"]').value = data.tool_code || '';
      tr.querySelector('[data-field="version"]').value = data.version || '';
      tr.querySelector('[data-field="qty"]').value = data.qty ?? 1;
      tr.querySelector('[data-field="stored_at"]').value = (data.stored_at || '').slice(0, 10);
      tr.querySelector('[data-field="remark"]').value = data.remark || '';
    });
  }

  function readToolingForm() {
    const entries = [];
    document.querySelectorAll('#wh-tooling-form-table tr[data-tool-type]').forEach(tr => {
      entries.push({
        tool_type: tr.dataset.toolType,
        tool_code: tr.querySelector('[data-field="tool_code"]')?.value?.trim() || '',
        version: tr.querySelector('[data-field="version"]')?.value?.trim() || '',
        qty: Number(tr.querySelector('[data-field="qty"]')?.value || 1),
        stored_at: tr.querySelector('[data-field="stored_at"]')?.value || '',
        remark: tr.querySelector('[data-field="remark"]')?.value?.trim() || '',
      });
    });
    return entries;
  }

  async function selectToolingModel(row) {
    if (!row) return;
    toolingSelectedKey = toolingRowKey(row);
    document.querySelectorAll('.wh-tooling-row').forEach(tr => tr.classList.toggle('selected', tr.dataset.key === toolingSelectedKey));
    const title = document.getElementById('wh-tooling-title');
    const editor = document.getElementById('wh-tooling-editor');
    const empty = document.getElementById('wh-tooling-empty');
    const icSel = document.getElementById('wh-tooling-ic');
    const modelInput = document.getElementById('wh-tooling-model-code');
    if (icSel) icSel.value = row.internal_code;
    if (modelInput) modelInput.value = row.model_code;
    if (title) title.textContent = `${row.internal_code} · ${row.model_code} · ${row.model_name || '工装登记'}`;
    empty?.classList.add('hidden');
    editor?.classList.remove('hidden');
    try {
      const data = await engApi(`/tooling/lookup?internal_code=${encodeURIComponent(row.internal_code)}&model_code=${encodeURIComponent(row.model_code)}`);
      renderToolingForm(data.entries);
    } catch (e) {
      window.EMS.showToast('工装数据加载失败：' + e.message, 'error');
    }
  }

  async function saveTooling() {
    const ic = document.getElementById('wh-tooling-ic')?.value?.trim();
    const modelCode = document.getElementById('wh-tooling-model-code')?.value?.trim();
    if (!ic || !modelCode) {
      window.EMS.showToast('请先选择左侧机型', 'error');
      return;
    }
    const hit = toolingCatalog.find(r => toolingRowKey(r) === toolingSelectedKey);
    const body = {
      internal_code: ic,
      model_code: modelCode,
      model_name: hit?.model_name || null,
      entries: readToolingForm(),
    };
    try {
      const saved = await engApi('/tooling', { method: 'PUT', body: JSON.stringify(body) });
      window.EMS.showToast(saved.tooling_complete ? '工装登记已保存（三类齐全）' : '工装登记已保存');
      renderToolingForm(saved.entries);
      await loadToolingCatalog();
      document.querySelector(`.wh-tooling-row[data-key="${toolingRowKey({ internal_code: ic, model_code: modelCode })}"]`)?.classList.add('selected');
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  function init() {
    document.getElementById('btn-wh-search')?.addEventListener('click', () => {
      stockInMaterialFilter = null;
      loadMaterials();
    });
    document.querySelectorAll('.wh-tab[data-wh-tab]').forEach(btn => {
      btn.addEventListener('click', () => switchWhTab(btn.dataset.whTab));
    });
    document.querySelectorAll('.wh-tab[data-dept-tab]').forEach(btn => {
      btn.addEventListener('click', () => switchDeptTab(btn.dataset.deptTab));
    });
    document.getElementById('btn-wh-import')?.addEventListener('click', syncShare);
    document.getElementById('btn-wh-template')?.addEventListener('click', downloadTemplate);
    document.getElementById('btn-wh-export')?.addEventListener('click', exportInventory);
    document.getElementById('wh-snap-customer')?.addEventListener('change', onSnapCustomerChange);
    document.getElementById('btn-wh-snap-load')?.addEventListener('click', loadExcelRawSheet);
    document.getElementById('btn-wh-detail-close')?.addEventListener('click', () =>
      document.getElementById('wh-material-detail-modal')?.classList.add('hidden'));
    document.getElementById('btn-wh-operation')?.addEventListener('click', () => {
      fillMaterialSelects();
      document.getElementById('wh-op-qty').value = '1';
      toggleOpFields();
      document.getElementById('wh-operation-modal').classList.remove('hidden');
    });
    document.getElementById('wh-op-type')?.addEventListener('change', toggleOpFields);
    document.getElementById('btn-wh-op-cancel')?.addEventListener('click', () =>
      document.getElementById('wh-operation-modal').classList.add('hidden'));
    document.getElementById('btn-wh-op-save')?.addEventListener('click', saveOperation);
    document.getElementById('btn-wh-in-cancel')?.addEventListener('click', () =>
      document.getElementById('wh-stock-in-modal').classList.add('hidden'));
    document.getElementById('btn-wh-issue-cancel')?.addEventListener('click', () =>
      document.getElementById('wh-issue-modal').classList.add('hidden'));
    document.getElementById('btn-wh-in-save')?.addEventListener('click', saveStockIn);
    document.getElementById('btn-wh-issue-save')?.addEventListener('click', saveIssue);
    document.getElementById('btn-dept-submit-return')?.addEventListener('click', submitDeptReturn);
    document.getElementById('btn-wh-tooling-search')?.addEventListener('click', loadToolingCatalog);
    document.getElementById('wh-tooling-search')?.addEventListener('keydown', e => { if (e.key === 'Enter') loadToolingCatalog(); });
    document.getElementById('wh-tooling-filter-code')?.addEventListener('change', loadToolingCatalog);
    document.getElementById('btn-wh-tooling-save')?.addEventListener('click', saveTooling);
  }

  window.WarehouseApp = { init, load, loadDept, switchTab: switchWhTab };
})();
