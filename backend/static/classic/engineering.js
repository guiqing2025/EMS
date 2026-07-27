(function () {
  const API = '/api/engineering';
  const ENG_CUSTOMER_STORAGE = 'eng_active_customer_v1';
  let selectedModelId = null;
  let selectedModelKey = null;
  let selectedModel = null;
  let lastKitExport = null;
  let lastKitLines = [];
  let lastReviewDossier = null;
  let kitMountFilter = 'no-type';
  let activeEngTab = 'bom';
  let subPage = 1;
  let subImportRows = [];
  let subImportSourceType = 'xlsx';
  let subImportSourceFile = '';
  let procSelectedId = null;
  let procStepDefs = [];
  let procCurrentRoute = null;
  let procIsNew = false;
  let placeSelectedId = null;
  let placeSelectedKey = null;
  let placeFiles = [];
  let gerberSelectedId = null;
  let gerberSelectedKey = null;
  let gerberPackages = [];
  let customerAssets = [];
  let assetsSelectedKey = null;
  let assetsSelectedRow = null;
  let engCustomers = [];
  let activeEngCustomer = null;
  let engConfigCache = null;

  const PROC_STATUS_LABEL = { configured: '已配置', pending: '待填报' };
  const PROC_SOURCE_LABEL = { excel: '工艺明细', manual: '手工', system: '系统' };
  const PROCESS_OPTIONS = [
    { value: '', label: '—' },
    { value: '贴片', label: '贴片' },
    { value: '插件', label: '插件' },
    { value: 'SMT', label: 'SMT' },
    { value: 'DIP', label: 'DIP' },
  ];
  const PROFILE_LABELS = {
    dip_only: '纯插件',
    smt_only: '纯贴片',
    mixed: '混贴',
    unknown: '未识别',
  };

  function getActiveInternalCode() {
    return (activeEngCustomer?.internal_code || '').trim().toUpperCase();
  }

  function appendBomScopeToForm(form) {
    const bomId = selectedModelId || selectedModel?.id || selectedModel?.bom_model_id;
    const pn = (selectedModel?.purchase_no || '').trim();
    if (bomId) form.append('bom_model_id', String(bomId));
    if (pn) form.append('purchase_no', pn);
  }

  function readStoredCustomer() {
    try {
      const raw = sessionStorage.getItem(ENG_CUSTOMER_STORAGE);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function writeStoredCustomer(cust) {
    if (!cust?.internal_code) {
      sessionStorage.removeItem(ENG_CUSTOMER_STORAGE);
      return;
    }
    sessionStorage.setItem(ENG_CUSTOMER_STORAGE, JSON.stringify({
      internal_code: cust.internal_code,
      customer_id: cust.customer_id || '',
      name: cust.name || '',
    }));
  }

  function resolveCustomerFromList(code) {
    const ic = (code || '').trim().toUpperCase();
    return engCustomers.find((c) => (c.internal_code || '').toUpperCase() === ic) || null;
  }

  function fillCustomerSelects(selectedCode) {
    const code = (selectedCode || getActiveInternalCode() || '').toUpperCase();
    const opts = engCustomers.map((c) => {
      const ic = c.internal_code || '';
      const label = `${ic}${c.name ? ` ${c.name}` : ''}`;
      return `<option value="${escapeHtml(ic)}">${escapeHtml(label)}</option>`;
    }).join('');
    ['eng-filter-code', 'eng-proc-filter-code', 'eng-proc-ic', 'eng-place-import-ic', 'eng-gerber-import-ic'].forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      const keepEmpty = id.includes('filter');
      el.innerHTML = (keepEmpty ? '<option value="">全部</option>' : '') + opts;
      if (code) el.value = code;
      else if (!keepEmpty && engCustomers[0]) el.value = engCustomers[0].internal_code;
    });
    fillSubCustomerSelect();
  }

  function renderCustomerRulesSummary() {
    const box = document.getElementById('eng-rules-summary');
    if (!box || !activeEngCustomer) {
      if (box) box.innerHTML = '';
      return;
    }
    const rules = activeEngCustomer.rules || {};
    const checklist = rules.checklist || {};
    const required = [];
    if (checklist.bom !== false) required.push('BOM');
    if (checklist.placement !== false) required.push('坐标');
    if (checklist.gerber) required.push('Gerber');
    if (checklist.refmap) required.push('位号图');
    if (checklist.mount_resolved !== false) required.push('贴装识别');
    const profile = rules.bom_parse_profile || 'auto';
    const scope = (rules.assets_scope || 'model') === 'order' ? '资料按订单隔离' : '资料按机型共用';
    box.innerHTML = `本客户规则：<strong>${escapeHtml(scope)}</strong> · 解析 <strong>${escapeHtml(String(profile))}</strong> · 必交 <strong>${escapeHtml(required.join(' / ') || '—')}</strong> · 录入 <strong>人工导入</strong>`;
  }

  function updatePickerChrome() {
    const h1 = document.querySelector('#eng-customer-picker .page-title');
    const p = document.querySelector('#eng-customer-picker .page-subtitle');
    if (activeEngTab === 'substitution') {
      if (h1) h1.textContent = '替代料';
      if (p) p.textContent = '请选择客户后查看或维护替代/投产料规则';
    } else if (activeEngTab === 'process') {
      if (h1) h1.textContent = '工序对照';
      if (p) p.textContent = '请选择客户后维护机型工序对照';
    } else {
      if (h1) h1.textContent = '工程资料';
      if (p) p.textContent = '请选择客户模块进入工作台；各客户资料与规则相互隔离';
    }
  }

  function updateWorkspaceChrome() {
    const title = document.getElementById('eng-workspace-title');
    const sub = document.getElementById('eng-workspace-subtitle');
    const chipCode = document.getElementById('eng-customer-chip-code');
    const chipName = document.getElementById('eng-customer-chip-name');
    const custLabel = activeEngCustomer
      ? (activeEngCustomer.name || activeEngCustomer.internal_code)
      : '';
    if (activeEngTab === 'substitution') {
      if (title) title.textContent = custLabel ? `替代料 · ${custLabel}` : '替代料';
      if (sub) sub.textContent = '按客户查询与维护替代/投产料规则';
    } else if (activeEngTab === 'process') {
      const filterCode = (document.getElementById('eng-proc-filter-code')?.value || '').trim().toUpperCase();
      const filterCust = filterCode ? resolveCustomerFromList(filterCode) : null;
      const procLabel = filterCust
        ? (filterCust.name || filterCust.internal_code)
        : (filterCode ? filterCode : '');
      if (title) title.textContent = procLabel ? `工序对照 · ${procLabel}` : '工序对照';
      if (sub) {
        sub.textContent = filterCust
          ? `${filterCust.internal_code} · 机型工序对照`
          : (filterCode ? '机型工序对照' : '全部客户 · 机型工序对照');
      }
    } else if (activeEngCustomer) {
      if (title) title.textContent = `工程资料 · ${custLabel}`;
      if (sub) sub.textContent = `${activeEngCustomer.internal_code} · BOM · 坐标 · Gerber/位号图 · 贴装审核（人工导入）`;
    }
    if (chipCode) chipCode.textContent = activeEngCustomer?.internal_code || '—';
    if (chipName) chipName.textContent = activeEngCustomer?.name || '';
    const importBtn = document.getElementById('btn-eng-import-manual');
    if (importBtn) {
      importBtn.textContent = '导入 BOM';
    }
    document.body.classList.toggle('eng-tab-sub', activeEngTab === 'substitution');
    document.body.classList.toggle('eng-tab-process', activeEngTab === 'process');
    if (activeEngTab === 'bom') renderCustomerRulesSummary();
    else {
      const box = document.getElementById('eng-rules-summary');
      if (box) box.innerHTML = '';
    }
  }

  function showCustomerPicker() {
    document.getElementById('eng-customer-picker')?.classList.remove('hidden');
    document.getElementById('eng-workspace')?.classList.add('hidden');
    updatePickerChrome();
  }

  function showCustomerWorkspace() {
    document.getElementById('eng-customer-picker')?.classList.add('hidden');
    document.getElementById('eng-workspace')?.classList.remove('hidden');
    updateWorkspaceChrome();
  }

  /** 替代料/工序对照自带客户筛选，直接进工作台，跳过「工程资料」选客户页 */
  function showDirectEngWorkspace() {
    document.getElementById('eng-customer-picker')?.classList.add('hidden');
    document.getElementById('eng-workspace')?.classList.remove('hidden');
    updateWorkspaceChrome();
  }

  function showSubstitutionWorkspace() {
    showDirectEngWorkspace();
  }

  function showProcessWorkspace() {
    showDirectEngWorkspace();
    const filterEl = document.getElementById('eng-proc-filter-code');
    if (filterEl) {
      filterEl.classList.remove('hidden');
      filterEl.removeAttribute('aria-hidden');
      filterEl.title = '客户平台';
    }
  }

  function bindProcFilterCustomer() {
    const filterEl = document.getElementById('eng-proc-filter-code');
    if (!filterEl || filterEl.dataset.boundCustomer === '1') return;
    filterEl.dataset.boundCustomer = '1';
    filterEl.addEventListener('change', () => {
      const code = (filterEl.value || '').trim().toUpperCase();
      const hit = code ? resolveCustomerFromList(code) : null;
      if (hit) {
        activeEngCustomer = hit;
        writeStoredCustomer(hit);
      }
      updateWorkspaceChrome();
      if (activeEngTab === 'process') loadProcModels();
    });
  }

  function renderCustomerCards(todoCounts) {
    const box = document.getElementById('eng-customer-cards');
    if (!box) return;
    if (!engCustomers.length) {
      box.innerHTML = '<p class="empty">未配置工程客户，请在 srm_config.json 的 engineering_customers 中登记</p>';
      return;
    }
    const counts = todoCounts || {};
    box.innerHTML = engCustomers.map((c) => {
      const ic = c.internal_code || '';
      const n = Number(counts[ic] || 0);
      const badge = n > 0 ? `<span class="eng-todo-badge">${n}</span>` : '';
      const folder = c.bom_folder ? `<div class="eng-customer-card-meta">目录 ${escapeHtml(c.bom_folder)}</div>` : '';
      return `<button type="button" class="eng-customer-card" data-code="${escapeHtml(ic)}">
        <div class="eng-customer-card-top">
          <strong>${escapeHtml(ic)}</strong>
          ${badge}
        </div>
        <div class="eng-customer-card-name">${escapeHtml(c.name || '')}</div>
        ${folder}
        <div class="eng-customer-card-action">进入工作台 →</div>
      </button>`;
    }).join('');
    box.querySelectorAll('.eng-customer-card').forEach((btn) => {
      btn.addEventListener('click', () => {
        const hit = resolveCustomerFromList(btn.dataset.code);
        if (hit) enterCustomerWorkspace(hit);
      });
    });
  }

  async function loadCustomerTodoCounts() {
    const counts = {};
    await Promise.all(engCustomers.map(async (c) => {
      const ic = c.internal_code || '';
      try {
        const data = await engApi(`/todos?internal_code=${encodeURIComponent(ic)}`);
        counts[ic] = Number(data?.count || 0);
      } catch (_) {
        counts[ic] = 0;
      }
    }));
    return counts;
  }

  async function enterCustomerWorkspace(cust, { silent } = {}) {
    activeEngCustomer = cust;
    writeStoredCustomer(cust);
    fillCustomerSelects(cust.internal_code);
    showCustomerWorkspace();
    if (!silent) window.EMS.showToast(`已进入 ${cust.name || cust.internal_code} 工作台`);
    selectedModel = null;
    selectedModelId = null;
    selectedModelKey = null;
    await loadCoverage();
    await loadModels();
    startReviewTodoPolling();
  }

  function leaveCustomerWorkspace() {
    activeEngCustomer = null;
    writeStoredCustomer(null);
    showCustomerPicker();
    if (reviewTodoTimer) {
      clearInterval(reviewTodoTimer);
      reviewTodoTimer = null;
    }
    loadCustomerTodoCounts().then(renderCustomerCards);
  }

  async function engApi(path, opts = {}) {
    const res = await fetch(API + path, {
      ...opts,
      headers: { ...window.EMS.authHeaders(), 'Content-Type': 'application/json', ...(opts.headers || {}) },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(formatApiDetail(err.detail, res.statusText));
    }
    if (res.headers.get('content-type')?.includes('application/json')) return res.json();
    return res;
  }

  function formatApiDetail(detail, fallback = '请求失败') {
    if (detail == null || detail === '') return fallback;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      const parts = detail.map((d) => {
        if (typeof d === 'string') return d;
        if (!d || typeof d !== 'object') return '';
        const loc = Array.isArray(d.loc)
          ? d.loc.filter((x) => typeof x === 'string' && x !== 'body').join('.')
          : '';
        const msg = d.msg || d.message || '';
        return loc ? `${loc}: ${msg}` : msg;
      }).filter(Boolean);
      return parts.join('；') || fallback;
    }
    if (typeof detail === 'object') {
      if (typeof detail.msg === 'string') return detail.msg;
      if (typeof detail.message === 'string') return detail.message;
      try {
        return JSON.stringify(detail);
      } catch (_) {
        return fallback;
      }
    }
    return String(detail);
  }

  function kitLabel(status) {
    return { ready: '齐套', partial: '部分齐', shortage: '欠料', unbound: '未绑BOM', unknown: '未算' }[status] || status;
  }

  function kitClass(status) {
    return `kit-badge kit-${status || 'unknown'}`;
  }

  function fmtTime(v) {
    if (!v) return '—';
    return window.EMS.fmtDate ? window.EMS.fmtDate(v) : String(v).slice(0, 16).replace('T', ' ');
  }

  async function loadConfig() {
    engConfigCache = await engApi('/config');
    engCustomers = Array.isArray(engConfigCache?.customers) ? engConfigCache.customers : [];
    const pathInfo = document.getElementById('eng-path-info');
    if (pathInfo) {
      pathInfo.textContent = 'BOM / 坐标 / Gerber：人工导入（不从本地共享盘同步）';
    }
    fillCustomerSelects(getActiveInternalCode());
    return engConfigCache;
  }

  function engUsername() {
    return String(window.EMS.getCurrentUser()?.username || '').trim().toLowerCase();
  }

  /** 邱梦林 dxgc / engineering：资料导入与退回处理（dxgc 虽是 admin 也按资料员） */
  function isEngImportOnly() {
    const name = engUsername();
    const role = window.EMS.getCurrentUser()?.role;
    return name === 'dxgc' || role === 'engineering';
  }

  /** 黄星 dxsmt001 / 王总 dx003 / eng_auditor */
  function isEngAuditOnly() {
    const name = engUsername();
    const role = window.EMS.getCurrentUser()?.role;
    return name === 'dxsmt001' || name === 'dx003' || role === 'eng_auditor';
  }

  function canEngAudit() {
    // 资料员不显示审核通过/退回（即使帐号角色是 admin）
    if (isEngImportOnly()) return false;
    const role = window.EMS.getCurrentUser()?.role;
    return isEngAuditOnly() || role === 'admin' || role === 'planner' || engUsername() === 'wgq';
  }

  function applyEngImportOnlyUI() {
    document.body.classList.toggle('eng-import-only', isEngImportOnly());
    document.body.classList.toggle('eng-audit-only', isEngAuditOnly());
    const hint = document.getElementById('eng-review-hint');
    if (hint) {
      if (isEngAuditOnly()) {
        hint.textContent = '审核员（黄星/王总）：点「待审核资料」打开推送 →「去处理」核对贴装 →「审核通过」或「退回」。审完可继续下一条。';
      } else if (isEngImportOnly()) {
        hint.textContent = '资料员邱梦林：导入 BOM / 坐标 / Gerber 后自动送审；被退回后按醒目原因修正再重新导入。';
      } else {
        hint.textContent = '先点「BOM 资料审核」核对贴装，再点「审核通过」。资料员导入后会自动进入待审。';
      }
    }
  }

  function switchEngTab(tab) {
    if (tab === 'customer-assets' || tab === 'files' || tab === 'docs') tab = 'bom';
    // 审核员仅 BOM；资料员可进替代料（菜单入口），仍不可进工序对照
    if (isEngAuditOnly() && tab !== 'bom') {
      tab = 'bom';
    } else if (isEngImportOnly() && tab !== 'bom' && tab !== 'substitution') {
      tab = 'bom';
    }
    activeEngTab = tab;
    document.querySelectorAll('[data-eng-tab]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.engTab === tab);
    });
    document.getElementById('eng-panel-bom')?.classList.toggle('hidden', tab !== 'bom');
    document.getElementById('eng-panel-substitution')?.classList.toggle('hidden', tab !== 'substitution');
    document.getElementById('eng-panel-process')?.classList.toggle('hidden', tab !== 'process');
    if (tab === 'substitution') {
      showSubstitutionWorkspace();
      fillSubCustomerSelect();
      loadSubstitutionMeta().then(() => loadSubstitutions());
      return;
    }
    if (tab === 'process') {
      showProcessWorkspace();
      bindProcFilterCustomer();
      fillCustomerSelects(getActiveInternalCode());
      loadProcMeta().then(() => loadProcStepDefs().then(() => loadProcModels()));
      return;
    }
    // bom
    if (!activeEngCustomer) showCustomerPicker();
    else showCustomerWorkspace();
  }

  function getActiveCustomerId() {
    return (activeEngCustomer?.customer_id || '').trim();
  }

  function fillSubCustomerSelect() {
    const el = document.getElementById('eng-sub-customer');
    if (!el) return;
    const cur = getActiveCustomerId();
    el.innerHTML = engCustomers.map((c) => {
      const id = c.customer_id || '';
      const label = `${c.internal_code || ''} ${c.name || id}`.trim();
      return `<option value="${escapeHtml(id)}">${escapeHtml(label)}</option>`;
    }).join('');
    if (cur && [...el.options].some((o) => o.value === cur)) el.value = cur;
    else if (el.options.length) el.value = el.options[0].value;
  }

  function currentSubCustomerId() {
    const el = document.getElementById('eng-sub-customer');
    return (el?.value || getActiveCustomerId() || '').trim();
  }

    async function loadSubstitutionMeta() {
    const cid = currentSubCustomerId();
    const el = document.getElementById('eng-sub-meta');
    if (!cid) {
      if (el) el.textContent = '请先选择客户平台';
      return;
    }
    const meta = await engApi('/substitutions/meta?customer_id=' + encodeURIComponent(cid));
    if (el) {
      el.textContent = meta.row_count
        ? `${meta.customer_name || cid} · 规则 ${meta.row_count} 条 · 更新 ${fmtTime(meta.synced_at)}`
        : `${meta.customer_name || cid} · 暂无规则（可下载模板后导入 XLSX）`;
    }
    document.body.classList.toggle('eng-sub-yonglian', cid === 'yonglian');
    syncSubCustomerMode(cid);
  }

  const YL_BOARD_TAGS = ['D1', 'U1', 'U2', 'U3', 'M1', '结构'];

  function syncSubCustomerMode(cid) {
    const isYl = cid === 'yonglian';
    const thead = document.getElementById('eng-sub-thead');
    if (thead) {
      if (isYl) {
        thead.innerHTML = `<tr>
          <th>序号</th>
          <th class="eng-sub-col-comp">子项物料编码</th>
          <th class="eng-sub-col-sub">投产物料编码</th>
          <th>物料名称</th><th>规格型号</th><th>单位</th>
          <th>D1</th><th>U1</th><th>U2</th><th>U3</th><th>M1</th><th>结构</th>
          <th>合并需求</th><th>机型绑定</th><th>操作</th>
        </tr>`;
      } else {
        thead.innerHTML = `<tr>
          <th class="eng-sub-col-comp">元件品号</th><th>元件品名</th><th>元件规格</th><th>单位</th>
          <th class="eng-sub-parent-col">主件品号</th><th class="eng-sub-parent-col">主件品名</th>
          <th>关系</th><th class="eng-sub-col-sub">替代料号</th><th>替代品名</th><th>替代规格</th>
          <th>顺序</th><th>生效</th><th>失效</th><th>数量</th><th>备注</th><th>来源</th><th>操作</th>
        </tr>`;
      }
    }
    document.querySelectorAll('#eng-sub-import-modal .eng-sub-col-comp').forEach((el) => {
      el.textContent = isYl ? '子项物料编码' : '元件品号';
    });
    document.querySelectorAll('#eng-sub-import-modal .eng-sub-col-sub').forEach((el) => {
      el.textContent = isYl ? '投产物料编码' : '替代料号';
    });
  }

  function subTableColspan() {
    return currentSubCustomerId() === 'yonglian' ? 15 : 17;
  }

  function ylBoardTagFromRule(r) {
    const rem = String(r.remark || '');
    const m = rem.match(/板别(D1|U1|U2|U3|M1|结构)/);
    if (m) return m[1];
    const name = `${r.parent_name || ''}${r.parent_spec || ''}`;
    if (name.includes('结构')) return '结构';
    const hit = name.match(/(?:CZ|S)?(D1|U[123]|M1)(?:板|_?PCBA|-PCBA|$)/i);
    if (hit) return hit[1].toUpperCase();
    return '';
  }

  function ylMergeNeedFromRemark(remark) {
    const m = String(remark || '').match(/合并需求\s*([0-9.]+)/);
    return m ? Number(m[1]) : null;
  }

  function pivotYonglianSubRows(rows) {
    const map = new Map();
    (rows || []).forEach((r) => {
      const key = `${String(r.comp_code || '').toUpperCase()}||${String(r.sub_code || '').toUpperCase()}`;
      let g = map.get(key);
      if (!g) {
        g = {
          ids: [],
          seq: r.sub_order || '',
          comp_code: r.comp_code,
          sub_code: r.sub_code,
          name: r.comp_name || r.sub_name || '',
          spec: r.comp_spec || r.sub_spec || '',
          unit: r.comp_unit || r.sub_unit || '',
          boards: Object.fromEntries(YL_BOARD_TAGS.map((t) => [t, null])),
          parents: [],
          merge: null,
        };
        map.set(key, g);
      }
      g.ids.push(r.id);
      if (!g.seq && r.sub_order) g.seq = r.sub_order;
      if (!g.name) g.name = r.comp_name || r.sub_name || '';
      if (!g.spec) g.spec = r.comp_spec || r.sub_spec || '';
      const tag = ylBoardTagFromRule(r);
      if (tag && YL_BOARD_TAGS.includes(tag) && r.qty != null) g.boards[tag] = r.qty;
      if (r.parent_code) {
        const label = r.parent_name ? `${r.parent_code}（${r.parent_name}）` : r.parent_code;
        if (!g.parents.includes(label)) g.parents.push(label);
      }
      const merge = ylMergeNeedFromRemark(r.remark);
      if (merge != null) g.merge = merge;
    });
    const list = [...map.values()];
    list.sort((a, b) => {
      const na = Number(a.seq);
      const nb = Number(b.seq);
      if (Number.isFinite(na) && Number.isFinite(nb) && a.seq && b.seq) return na - nb;
      return String(a.comp_code).localeCompare(String(b.comp_code), 'zh-CN', { numeric: true });
    });
    return list;
  }

  function renderYonglianSubPivot(pivoted) {
    const tbody = document.getElementById('eng-sub-table');
    if (!tbody) return;
    if (!pivoted.length) {
      tbody.innerHTML = `<tr><td colspan="15" class="empty">该客户暂无替代料规则，请导入含 D1/U1/U2/U3/M1 列的 XLSX</td></tr>`;
      return;
    }
    tbody.innerHTML = pivoted.map((g, idx) => {
      const boardCells = YL_BOARD_TAGS.map((t) => {
        const v = g.boards[t];
        return `<td class="eng-yl-board-qty">${v != null ? v : ''}</td>`;
      }).join('');
      const merge = g.merge != null
        ? g.merge
        : YL_BOARD_TAGS.reduce((s, t) => s + (Number(g.boards[t]) || 0), 0) || '—';
      return `<tr data-ids="${g.ids.join(',')}">
        <td>${escapeHtml(g.seq || String(idx + 1))}</td>
        <td>${escapeHtml(g.comp_code)}</td>
        <td><strong>${escapeHtml(g.sub_code)}</strong></td>
        <td>${escapeHtml(g.name || '—')}</td>
        <td class="cell-wrap">${escapeHtml(g.spec || '—')}</td>
        <td>${escapeHtml(g.unit || '—')}</td>
        ${boardCells}
        <td>${merge}</td>
        <td class="cell-wrap" title="${escapeHtml(g.parents.join('；'))}">${escapeHtml(g.parents.length ? g.parents.join('；') : '—')}</td>
        <td><button type="button" class="btn btn-sm btn-eng-sub-del-group" data-ids="${g.ids.join(',')}">删除</button></td>
      </tr>`;
    }).join('');
    tbody.querySelectorAll('.btn-eng-sub-del-group').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const ids = String(btn.dataset.ids || '').split(',').map((x) => Number(x)).filter(Boolean);
        if (!ids.length || !confirm(`确认删除该替代关系（共 ${ids.length} 条分板规则）？`)) return;
        try {
          for (const id of ids) await engApi('/substitutions/' + id, { method: 'DELETE' });
          window.EMS.showToast('已删除', 'success');
          await loadSubstitutionMeta();
          await loadSubstitutions(1);
        } catch (e) {
          window.EMS.showToast(e.message, 'error');
        }
      });
    });
  }

  async function loadSubstitutions(page = subPage) {
    subPage = page;
    const cid = currentSubCustomerId();
    const tbody = document.getElementById('eng-sub-table');
    if (!tbody) return;
    const cols = subTableColspan();
    if (!cid) {
      tbody.innerHTML = `<tr><td colspan="${cols}" class="empty">请选择客户平台</td></tr>`;
      return;
    }
    const keyword = document.getElementById('eng-sub-search')?.value?.trim() || '';
    // 永联：拉全量后按子项/投产透视成 D1/U1…列（对齐客户 Excel）
    if (cid === 'yonglian') {
      const params = new URLSearchParams({ page: '1', page_size: '500', customer_id: cid });
      if (keyword) params.set('keyword', keyword);
      const rows = await engApi('/substitutions?' + params.toString());
      const pivoted = pivotYonglianSubRows(rows);
      const pageSize = 50;
      const start = (page - 1) * pageSize;
      const slice = pivoted.slice(start, start + pageSize);
      renderYonglianSubPivot(slice);
      const info = document.getElementById('eng-sub-page-info');
      if (info) {
        const pages = Math.max(1, Math.ceil(pivoted.length / pageSize) || 1);
        info.textContent = `第 ${page} / ${pages} 页 · 共 ${pivoted.length} 组（分板规则 ${rows.length} 条）`;
      }
      return;
    }
    const params = new URLSearchParams({ page: String(page), page_size: '50', customer_id: cid });
    if (keyword) params.set('keyword', keyword);
    const rows = await engApi('/substitutions?' + params.toString());
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="${cols}" class="empty">该客户暂无替代料规则，请导入 XLSX 或手工新增</td></tr>`;
    } else {
      tbody.innerHTML = rows.map(r => `
        <tr data-id="${r.id}">
          <td>${escapeHtml(r.comp_code)}</td><td>${escapeHtml(r.comp_name || '—')}</td><td class="cell-wrap">${escapeHtml(r.comp_spec || '—')}</td>
          <td>${escapeHtml(r.comp_unit || '—')}</td>
          <td class="eng-sub-parent-col">${escapeHtml(r.parent_code || '—')}</td><td class="eng-sub-parent-col">${escapeHtml(r.parent_name || '—')}</td>
          <td>${escapeHtml(r.relation_type || '—')}</td><td><strong>${escapeHtml(r.sub_code)}</strong></td>
          <td>${escapeHtml(r.sub_name || '—')}</td><td class="cell-wrap">${escapeHtml(r.sub_spec || '—')}</td>
          <td>${escapeHtml(r.sub_order || '—')}</td><td>${escapeHtml(r.effective_date || '—')}</td><td>${escapeHtml(r.expiry_date || '—')}</td>
          <td>${r.qty ?? '—'}</td><td class="cell-wrap">${escapeHtml(r.remark || '—')}</td>
          <td class="cell-muted">${escapeHtml(r.source_type || '—')}</td>
          <td><button type="button" class="btn btn-sm btn-eng-sub-del" data-id="${r.id}">删除</button></td>
        </tr>`).join('');
      tbody.querySelectorAll('.btn-eng-sub-del').forEach((btn) => {
        btn.addEventListener('click', () => deleteSubstitution(Number(btn.dataset.id)));
      });
    }
    const info = document.getElementById('eng-sub-page-info');
    if (info) info.textContent = `第 ${page} 页`;
  }

  async function deleteSubstitution(id) {
    if (!id || !confirm('确认删除该替代料规则？')) return;
    try {
      await engApi('/substitutions/' + id, { method: 'DELETE' });
      window.EMS.showToast('已删除', 'success');
      await loadSubstitutionMeta();
      await loadSubstitutions(subPage);
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  function openSubImportModal(title, rows, sourceType, sourceFile, message) {
    subImportRows = rows || [];
    subImportSourceType = sourceType || 'xlsx';
    subImportSourceFile = sourceFile || '';
    document.getElementById('eng-sub-import-title').textContent = title || '导入预览';
    document.getElementById('eng-sub-import-msg').textContent = message || `共 ${subImportRows.length} 行，请确认后写入`;
    const tb = document.getElementById('eng-sub-import-tbody');
    const thead = document.querySelector('#eng-sub-import-modal .eng-sub-table thead');
    const isYl = currentSubCustomerId() === 'yonglian'
      || subImportRows.some((r) => /板别(D1|U1|U2|U3|M1|结构)/.test(r.remark || '') || r.board_tag);
    if (isYl) {
      if (thead) {
        thead.innerHTML = `<tr>
          <th>子项</th><th>投产</th><th>名称</th>
          <th>D1</th><th>U1</th><th>U2</th><th>U3</th><th>M1</th><th>结构</th>
          <th>机型</th>
        </tr>`;
      }
      const pivoted = pivotYonglianSubRows(subImportRows);
      tb.innerHTML = pivoted.length
        ? pivoted.map((g) => `<tr>
            <td>${escapeHtml(g.comp_code || '')}</td>
            <td>${escapeHtml(g.sub_code || '')}</td>
            <td>${escapeHtml(g.name || '')}</td>
            ${YL_BOARD_TAGS.map((t) => `<td>${g.boards[t] != null ? g.boards[t] : ''}</td>`).join('')}
            <td class="cell-muted">${escapeHtml(g.parents.join('；') || '—')}</td>
          </tr>`).join('')
        : '<tr><td colspan="10" class="empty">无有效行</td></tr>';
    } else {
      if (thead) {
        thead.innerHTML = `<tr>
          <th class="eng-sub-col-comp">元件品号</th><th class="eng-sub-col-sub">替代料号</th>
          <th class="eng-sub-parent-col">主件品号</th><th>元件品名</th><th>替代品名</th><th>备注</th>
        </tr>`;
      }
      tb.innerHTML = subImportRows.length
        ? subImportRows.map((r) => `<tr>
            <td>${escapeHtml(r.comp_code || '')}</td>
            <td>${escapeHtml(r.sub_code || '')}</td>
            <td class="eng-sub-parent-col">${escapeHtml(r.parent_code || '')}</td>
            <td>${escapeHtml(r.comp_name || '')}</td>
            <td>${escapeHtml(r.sub_name || '')}</td>
            <td class="cell-wrap" title="${escapeHtml(r.remark || '')}">${escapeHtml(r.remark || '—')}</td>
          </tr>`).join('')
        : `<tr><td colspan="6" class="empty">无有效行</td></tr>`;
    }
    document.getElementById('eng-sub-import-modal')?.classList.remove('hidden');
  }

  function closeSubImportModal() {
    document.getElementById('eng-sub-import-modal')?.classList.add('hidden');
    subImportRows = [];
  }

  async function confirmSubImport() {
    const cid = currentSubCustomerId();
    if (!cid) {
      window.EMS.showToast('请先选择客户', 'error');
      return;
    }
    if (!subImportRows.length) {
      window.EMS.showToast('没有可导入的行', 'error');
      return;
    }
    const mode = document.getElementById('eng-sub-import-mode')?.value || 'append';
    try {
      const res = await engApi('/substitutions/import-confirm', {
        method: 'POST',
        body: JSON.stringify({
          customer_id: cid,
          mode,
          source_type: subImportSourceType,
          source_file: subImportSourceFile,
          rows: subImportRows,
        }),
      });
      window.EMS.showToast(res.message || '导入完成', 'success', 6000);
      closeSubImportModal();
      await loadSubstitutionMeta();
      await loadSubstitutions(1);
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  async function parseSubXlsx(file) {
    const cid = currentSubCustomerId();
    if (!cid) {
      window.EMS.showToast('请先选择客户', 'error');
      return;
    }
    const form = new FormData();
    form.append('file', file);
    form.append('customer_id', cid);
    const res = await fetch(API + '/substitutions/parse-xlsx', {
      method: 'POST',
      headers: window.EMS.authHeaders(),
      body: form,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(formatApiDetail(data.detail, res.statusText));
    openSubImportModal('XLSX 导入预览', data.rows || [], 'xlsx', file.name, data.message || '');
  }

  async function addSubstitutionManual() {
    const cid = currentSubCustomerId();
    if (!cid) {
      window.EMS.showToast('请先选择客户', 'error');
      return;
    }
    const isYl = cid === 'yonglian';
    const comp = prompt(isYl ? '子项物料编码（BOM 原料）' : '元件品号（主料号）');
    if (!comp) return;
    const sub = prompt(isYl ? '投产物料编码（实际发料/替代）' : '替代料号');
    if (!sub) return;
    const parent = isYl ? '' : (prompt('主件/机型品号（可留空）') || '');
    try {
      await engApi('/substitutions', {
        method: 'POST',
        body: JSON.stringify({
          customer_id: cid,
          comp_code: comp.trim(),
          sub_code: sub.trim(),
          parent_code: parent.trim(),
          relation_type: '替代料件',
        }),
      });
      window.EMS.showToast('已新增', 'success');
      await loadSubstitutionMeta();
      await loadSubstitutions(1);
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  function downloadSubTemplate() {
    const cid = currentSubCustomerId();
    const a = document.createElement('a');
    const qs = cid ? `?customer_id=${encodeURIComponent(cid)}` : '';
    a.href = API + '/substitutions/template.xlsx' + qs;
    a.download = cid === 'yonglian' ? 'yonglian_substitution_template.xlsx' : 'substitution_template.xlsx';
    // 带鉴权：用 fetch blob
    fetch(a.href, { headers: window.EMS.authHeaders() })
      .then(async (res) => {
        if (!res.ok) throw new Error('下载失败');
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        a.href = url;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((e) => window.EMS.showToast(e.message || '下载失败', 'error'));
  }

  async function loadProcMeta() {
    const meta = await engApi('/process-routes/meta');
    const el = document.getElementById('eng-proc-meta');
    if (el) {
      const pending = meta.pending_count ? ` · 待填报 ${meta.pending_count}` : '';
      el.textContent = meta.row_count
        ? `已加载 ${meta.row_count} 条${pending} · 同步 ${fmtTime(meta.synced_at)}`
        : (meta.source_accessible ? '尚未同步工艺明细' : '工艺明细文件未找到');
    }
  }

  async function loadProcStepDefs() {
    if (procStepDefs.length) return;
    procStepDefs = await engApi('/process-routes/steps-def');
  }

  function procStatusBadge(status) {
    const cls = status === 'configured' ? 'kit-ready' : 'kit-partial';
    return `<span class="kit-badge ${cls}">${PROC_STATUS_LABEL[status] || status}</span>`;
  }

  function readProcStepsFromForm() {
    const steps = {
      laser_label: false,
      smt: false,
      insert: false,
      test: false,
      conformal: { enabled: false, type: '普通三防' },
      potting: false,
    };
    document.querySelectorAll('#eng-proc-steps input[data-step]').forEach(inp => {
      const key = inp.dataset.step;
      if (key === 'conformal') {
        steps.conformal.enabled = inp.checked;
      } else {
        steps[key] = inp.checked;
      }
    });
    const confType = document.querySelector('#eng-proc-steps input[name="conformal-type"]:checked');
    if (confType) steps.conformal.type = confType.value;
    return steps;
  }

  function stepsToPayload(steps) {
    return {
      laser_label: !!steps.laser_label,
      smt: !!steps.smt,
      insert: !!steps.insert,
      test: !!steps.test,
      conformal_enabled: !!steps.conformal?.enabled,
      conformal_type: steps.conformal?.type || '普通三防',
      potting: !!steps.potting,
    };
  }

  function buildRoutePreview(steps) {
    const parts = [];
    if (steps.laser_label) parts.push('镭雕/贴码');
    if (steps.smt) parts.push('SMT');
    if (steps.insert) parts.push('插件');
    if (steps.test) parts.push('测试');
    if (steps.conformal?.enabled) {
      const t = steps.conformal.type || '普通三防';
      parts.push(t === '普通三防' ? '三防' : `三防(${t})`);
    }
    if (steps.potting) parts.push('灌胶');
    return parts.join('-') || '—';
  }

  function updateProcPreview() {
    const steps = readProcStepsFromForm();
    const preview = document.getElementById('eng-proc-route-preview');
    if (preview) preview.textContent = buildRoutePreview(steps);
    const confWrap = document.getElementById('eng-proc-conformal-options');
    const confChecked = document.querySelector('#eng-proc-steps input[data-step="conformal"]')?.checked;
    confWrap?.classList.toggle('hidden', !confChecked);
  }

  function renderProcStepForm(steps) {
    const wrap = document.getElementById('eng-proc-steps');
    if (!wrap) return;
    const s = steps || {
      laser_label: false, smt: false, insert: false, test: false,
      conformal: { enabled: false, type: '普通三防' }, potting: false,
    };
    wrap.innerHTML = procStepDefs.map(def => {
      if (def.key === 'conformal') {
        const enabled = !!s.conformal?.enabled;
        const ctype = s.conformal?.type || '普通三防';
        const opts = (def.sub_options || ['普通三防', 'UV胶']).map(opt => `
          <label class="eng-proc-radio">
            <input type="radio" name="conformal-type" value="${opt}" ${ctype === opt ? 'checked' : ''}>
            ${opt}
          </label>`).join('');
        return `
          <div class="eng-proc-step-row">
            <label class="eng-proc-check">
              <input type="checkbox" data-step="conformal" ${enabled ? 'checked' : ''}> ${def.label}
            </label>
            <div id="eng-proc-conformal-options" class="eng-proc-sub-options${enabled ? '' : ' hidden'}">${opts}</div>
          </div>`;
      }
      return `
        <label class="eng-proc-check">
          <input type="checkbox" data-step="${def.key}" ${s[def.key] ? 'checked' : ''}> ${def.label}
        </label>`;
    }).join('');
    wrap.querySelectorAll('input').forEach(inp => {
      inp.addEventListener('change', updateProcPreview);
    });
    updateProcPreview();
  }

  function showProcEditor(route, isNew) {
    procCurrentRoute = route;
    procIsNew = !!isNew;
    document.getElementById('eng-proc-empty')?.classList.add('hidden');
    document.getElementById('eng-proc-editor')?.classList.remove('hidden');
    const ic = document.getElementById('eng-proc-ic');
    const code = document.getElementById('eng-proc-model-code');
    const name = document.getElementById('eng-proc-model-name');
    const remark = document.getElementById('eng-proc-remark');
    if (ic) { ic.value = route.internal_code || 'A123'; ic.disabled = !isNew && route.id > 0; }
    if (code) { code.value = route.model_code || ''; code.disabled = !isNew && route.id > 0; }
    if (name) name.value = route.model_name || '';
    if (remark) remark.value = route.remark || '';
    const title = document.getElementById('eng-proc-title');
    if (title) {
      const src = PROC_SOURCE_LABEL[route.source] || route.source;
      title.textContent = `${route.internal_code} · ${route.model_code}${route.model_name ? ' · ' + route.model_name : ''}（${src}）`;
    }
    const rawEl = document.getElementById('eng-proc-raw-process');
    if (rawEl) {
      rawEl.textContent = route.raw_process ? `工艺明细原文：${route.raw_process}` : '';
      rawEl.classList.toggle('hidden', !route.raw_process);
    }
    renderProcStepForm(route.steps);
  }

  function hideProcEditor() {
    procCurrentRoute = null;
    procIsNew = false;
    document.getElementById('eng-proc-editor')?.classList.add('hidden');
    document.getElementById('eng-proc-empty')?.classList.remove('hidden');
    const title = document.getElementById('eng-proc-title');
    if (title) title.textContent = '选择或新建机型配置工序';
  }

  async function loadProcModels() {
    const filterEl = document.getElementById('eng-proc-filter-code');
    // 以下拉当前值为准，禁止用 activeEngCustomer 回写覆盖用户选择
    const code = String(filterEl?.value || '').trim().toUpperCase();
    const keyword = document.getElementById('eng-proc-search')?.value?.trim() || '';
    const params = new URLSearchParams();
    if (code) params.set('internal_code', code);
    if (keyword) params.set('keyword', keyword);
    const rows = await engApi('/process-routes?' + params.toString());
    const tbody = document.getElementById('eng-proc-models-table');
    if (!tbody) return;
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty">无匹配记录，可同步工艺明细或新建机型</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(r => `
      <tr class="eng-proc-row${procSelectedId === r.id ? ' selected' : ''}" data-id="${r.id}">
        <td>${r.internal_code}</td>
        <td><strong>${r.model_code}</strong></td>
        <td>${r.route_display || '—'}</td>
        <td>${procStatusBadge(r.status)}</td>
      </tr>`).join('');
    tbody.querySelectorAll('.eng-proc-row').forEach(tr => {
      tr.addEventListener('click', () => selectProcRoute(Number(tr.dataset.id), rows.find(x => x.id === Number(tr.dataset.id))));
    });
  }

  async function selectProcRoute(id, route) {
    procSelectedId = id;
    document.querySelectorAll('.eng-proc-row').forEach(tr => tr.classList.toggle('selected', Number(tr.dataset.id) === id));
    showProcEditor(route, false);
  }

  function newProcModel() {
    procSelectedId = null;
    document.querySelectorAll('.eng-proc-row').forEach(tr => tr.classList.remove('selected'));
    const filterCode = document.getElementById('eng-proc-filter-code')?.value || getActiveInternalCode() || 'A123';
    showProcEditor({
      id: 0,
      internal_code: filterCode || 'A123',
      model_code: '',
      model_name: '',
      source: 'manual',
      steps: {
        laser_label: false, smt: false, insert: false, test: false,
        conformal: { enabled: false, type: '普通三防' }, potting: false,
      },
      raw_process: null,
      remark: '',
    }, true);
  }

  async function saveProcRoute() {
    const ic = document.getElementById('eng-proc-ic')?.value?.trim();
    const modelCode = document.getElementById('eng-proc-model-code')?.value?.trim();
    if (!ic || !modelCode) {
      window.EMS.showToast('请填写内部代码和机型料号', 'error');
      return;
    }
    const steps = readProcStepsFromForm();
    const body = {
      internal_code: ic,
      model_code: modelCode,
      model_name: document.getElementById('eng-proc-model-name')?.value?.trim() || null,
      remark: document.getElementById('eng-proc-remark')?.value?.trim() || null,
      steps: stepsToPayload(steps),
    };
    try {
      const saved = await engApi('/process-routes', { method: 'PUT', body: JSON.stringify(body) });
      window.EMS.showToast('工序对照已保存');
      procSelectedId = saved.id;
      await loadProcMeta();
      await loadProcModels();
      showProcEditor(saved, false);
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  async function syncProcessRoutes() {
    try {
      const res = await engApi('/process-routes/sync-now', { method: 'POST' });
      window.EMS.showToast(res.message || '同步完成', res.status === 'error' ? 'error' : 'success', 6000);
      await loadProcMeta();
      await loadProcModels();
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  function resolveAssetStatus(row) {
    if (!row) return 'pending';
    if (row.asset_status) return row.asset_status;
    if (row.id && (row.line_count > 0 || row.file_count > 0)) return 'imported';
    return 'pending';
  }

  function assetStatusBadge(status) {
    if (status === 'imported') return '<span class="kit-badge kit-ready">已导入</span>';
    if (status === 'failed') return '<span class="kit-badge kit-shortage">审核未通过</span>';
    return '<span class="kit-badge kit-partial">未导入</span>';
  }

  async function refreshSelectedCustomerAsset() {
    if (selectedModel?.internal_code && selectedModel?.model_code) {
      await syncAssetsForSelectedModel();
      return;
    }
    if (!assetsSelectedKey) return;
    await loadCustomerAssets();
    const row = customerAssets.find(x => customerAssetRowKey(x) === assetsSelectedKey);
    if (row) await selectCustomerAsset(row);
    else {
      assetsSelectedRow = null;
      placeSelectedId = null;
      gerberSelectedId = null;
    }
  }

  function updateAssetDeleteButtons(row) {
    const placeBtn = document.getElementById('btn-eng-place-delete');
    const gerberBtn = document.getElementById('btn-eng-gerber-delete');
    const refmapBtn = document.getElementById('btn-eng-refmap-delete');
    const hasPlace = !!(row?.placement_file_id && row?.placement_line_count);
    const hasGerber = !!(row?.gerber_package_id && row?.gerber_file_count);
    const hasRefmap = !!(row?.refmap_file_id && row?.refmap_file_name);
    placeBtn?.classList.toggle('hidden', !hasPlace);
    gerberBtn?.classList.toggle('hidden', !hasGerber);
    refmapBtn?.classList.toggle('hidden', !hasRefmap);
  }

  async function deleteCustomerAsset(kind) {
    const row = assetsSelectedRow;
    if (!row) {
      window.EMS.showToast('请先在左侧选择订单', 'error');
      return;
    }
    const labels = { placement: '贴片坐标', gerber: 'Gerber 制板资料', refmap: '位号图' };
    const ids = {
      placement: row.placement_file_id,
      gerber: row.gerber_package_id,
      refmap: row.refmap_file_id,
    };
    const id = ids[kind];
    if (!id) return;
    if (!confirm(`确定清除本机型的${labels[kind]}？清除后可重新导入正确文件。`)) return;
    try {
      await engApi(`/${kind === 'placement' ? 'placements' : kind === 'gerber' ? 'gerbers' : 'refmaps'}/${id}`, { method: 'DELETE' });
      window.EMS.showToast(`已清除${labels[kind]}`, 'success');
      await refreshSelectedCustomerAsset();
      if (kind === 'placement' && selectedModelId) await loadMountReadiness({ silent: true });
    } catch (e) {
      window.EMS.showToast(e.message || '清除失败', 'error');
    }
  }

  let refmapPreviewUrl = '';
  let refmapPreviewFileId = null;
  let refmapPreviewPage = 1;
  let refmapPreviewPages = 1;

  function refmapContentUrl(fileId) {
    const token = localStorage.getItem('ems_auth_token') || '';
    const q = token ? `?access_token=${encodeURIComponent(token)}` : '';
    return `${API}/refmaps/${fileId}/content${q}`;
  }

  function refmapPreviewImageUrl(fileId, page) {
    const token = localStorage.getItem('ems_auth_token') || '';
    const params = new URLSearchParams({ page: String(page) });
    if (token) params.set('access_token', token);
    return `${API}/refmaps/${fileId}/preview?${params.toString()}`;
  }

  function updateRefmapPageLabel() {
    const label = document.getElementById('eng-refmap-page-label');
    if (label) label.textContent = `${refmapPreviewPage} / ${refmapPreviewPages}`;
    const prev = document.getElementById('btn-eng-refmap-prev');
    const next = document.getElementById('btn-eng-refmap-next');
    if (prev) prev.disabled = refmapPreviewPage <= 1;
    if (next) next.disabled = refmapPreviewPage >= refmapPreviewPages;
  }

  function formatFileSize(bytes) {
    const size = Number(bytes) || 0;
    if (size <= 0) return '—';
    if (size < 1024) return `${size} B`;
    return `${Math.round(size / 1024)} KB`;
  }

  function clearRefmapPreview() {
    const wrap = document.getElementById('eng-refmap-preview-wrap');
    const empty = document.getElementById('eng-refmap-preview-empty');
    const img = document.getElementById('eng-refmap-preview-img');
    refmapPreviewUrl = '';
    refmapPreviewFileId = null;
    refmapPreviewPage = 1;
    refmapPreviewPages = 1;
    if (img) img.removeAttribute('src');
    wrap?.classList.add('hidden');
    empty?.classList.add('hidden');
    if (empty) empty.textContent = '';
    updateRefmapPageLabel();
  }

  function loadRefmapPreview(fileId, pageCount) {
    const wrap = document.getElementById('eng-refmap-preview-wrap');
    const empty = document.getElementById('eng-refmap-preview-empty');
    const img = document.getElementById('eng-refmap-preview-img');
    if (!fileId) {
      clearRefmapPreview();
      return;
    }
    refmapPreviewFileId = fileId;
    refmapPreviewPages = Math.max(1, Number(pageCount) || 1);
    refmapPreviewPage = 1;
    refmapPreviewUrl = refmapContentUrl(fileId);
    if (img) {
      img.onerror = () => {
        wrap?.classList.add('hidden');
        if (empty) {
          empty.textContent = '位号图预览加载失败，请点「新窗口打开 PDF」';
          empty.classList.remove('hidden');
        }
      };
      img.onload = () => empty?.classList.add('hidden');
      img.src = refmapPreviewImageUrl(fileId, refmapPreviewPage);
    }
    updateRefmapPageLabel();
    wrap?.classList.remove('hidden');
  }

  function stepRefmapPreview(delta) {
    if (!refmapPreviewFileId) return;
    const next = refmapPreviewPage + delta;
    if (next < 1 || next > refmapPreviewPages) return;
    refmapPreviewPage = next;
    const img = document.getElementById('eng-refmap-preview-img');
    if (img) img.src = refmapPreviewImageUrl(refmapPreviewFileId, refmapPreviewPage);
    updateRefmapPageLabel();
  }

  function escapeHtml(text) {
    return String(text ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function renderGerberFilesTable(files, packageId) {
    const tbody = document.getElementById('eng-gerber-files-table');
    const gerberHint = document.getElementById('eng-gerber-audit-hint');
    if (!tbody) return;
    tbody.innerHTML = files.length
      ? files.map(f => {
        const delBtn = f.valid === false
          ? `<button type="button" class="btn btn-xs btn-danger-outline eng-gerber-file-del" data-name="${escapeHtml(f.name)}">删除</button>`
          : '—';
        return `<tr class="${f.valid === false ? 'eng-file-invalid' : ''}" title="${escapeHtml(f.message || '')}">
            <td>${escapeHtml(f.name)}</td><td>${escapeHtml(f.ext || '—')}</td>
            <td>${f.valid === false ? '不合规' : escapeHtml(f.kind || 'Gerber')}</td>
            <td>${f.size ? Math.round(f.size / 1024) + ' KB' : '—'}</td>
            <td class="cell-muted">${escapeHtml(f.message || '—')}</td>
            <td>${delBtn}</td>
          </tr>`;
      }).join('')
      : '<tr><td colspan="6" class="empty">无文件列表</td></tr>';

    tbody.querySelectorAll('.eng-gerber-file-del').forEach(btn => {
      btn.addEventListener('click', async e => {
        e.stopPropagation();
        const name = btn.dataset.name;
        if (!name || !packageId) return;
        if (!confirm(`从资料包中删除不合规文件？\n${name}`)) return;
        try {
          const result = await engApi(`/gerbers/${packageId}/files?name=${encodeURIComponent(name)}`, { method: 'DELETE' });
          window.EMS.showToast(`已删除：${name}`, 'success');
          if (gerberHint && result.audit_message) {
            gerberHint.textContent = result.audit_message;
            gerberHint.className = `eng-gerber-audit-hint audit-${result.audit_status || 'pending'}`;
          }
          if (result.deleted_package || !result.file_count) {
            await refreshSelectedCustomerAsset();
          } else {
            await renderGerberFilesTable(result.files || [], packageId);
            await loadCustomerAssets();
          }
        } catch (err) {
          window.EMS.showToast(err.message || '删除失败', 'error');
        }
      });
    });
  }

  function bindAssetSectionToggles() {
    const storageKey = 'eng-asset-section-collapsed';
    let collapsed = {};
    try {
      collapsed = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
    } catch (_) {
      collapsed = {};
    }

    document.querySelectorAll('.eng-asset-section[data-asset-section]').forEach(section => {
      const key = section.dataset.assetSection;
      const toggle = section.querySelector('.eng-asset-toggle');
      if (!toggle) return;

      const apply = expanded => {
        section.classList.toggle('collapsed', !expanded);
        toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      };

      apply(collapsed[key] !== true);

      toggle.addEventListener('click', () => {
        const expanded = section.classList.contains('collapsed');
        apply(expanded);
        collapsed[key] = !expanded;
        sessionStorage.setItem(storageKey, JSON.stringify(collapsed));
      });
    });
  }

  function gerberAuditBadge(status) {
    if (status === 'passed') return '<span class="kit-badge kit-ready">审核通过</span>';
    if (status === 'warning') return '<span class="kit-badge kit-partial">审核警告</span>';
    if (status === 'failed') return '<span class="kit-badge kit-shortage">审核未通过</span>';
    return '<span class="kit-badge kit-unknown">待审核</span>';
  }

  function placeRowKey(row) {
    if (!row) return '';
    return row.id ? `place:${row.id}` : `place-pending:${row.internal_code}:${row.model_code}`;
  }

  function gerberRowKey(row) {
    if (!row) return '';
    return row.id ? `gerber:${row.id}` : `gerber-pending:${row.internal_code}:${row.model_code}`;
  }

  const PLACE_SOURCE_LABEL = { share: '共享盘', manual: '手工导入', pending: '待导入' };

  function placeSourceLabel(source) {
    return PLACE_SOURCE_LABEL[source] || source || '—';
  }

  function shortPath(path) {
    if (!path) return '—';
    if (path.startsWith('upload:')) return path.replace('upload:', '');
    const parts = path.split('/');
    return parts.length > 2 ? parts.slice(-2).join('/') : path;
  }

  function customerAssetRowKey(row) {
    if (!row) return '';
    const pn = (row.purchase_no || '').trim();
    const bomId = row.bom_model_id || row.id || '';
    if (pn || bomId) return `${row.internal_code}:${row.model_code}:${pn || bomId}`;
    return `${row.internal_code}:${row.model_code}`;
  }

  function customerFileStatusBadge(row, kind) {
    if (!row) return '<span class="kit-badge kit-partial">未导入</span>';
    const hasFile = kind === 'placement'
      ? !!(row.placement_file_id && row.placement_line_count)
      : kind === 'gerber'
        ? !!(row.gerber_package_id && row.gerber_file_count)
        : !!(row.refmap_file_id && row.refmap_file_name);
    if (!hasFile) return '<span class="kit-badge kit-partial">未导入</span>';
    const audit = ({
      placement: row.placement_audit_status,
      gerber: row.gerber_audit_status,
      refmap: row.refmap_audit_status,
    })[kind];
    if (audit === 'passed') return '<span class="kit-badge kit-ready">审核通过</span>';
    if (audit === 'warning') return '<span class="kit-badge kit-partial">审核警告</span>';
    if (audit === 'failed') return '<span class="kit-badge kit-shortage">审核未通过</span>';
    return '<span class="kit-badge kit-ready">已导入</span>';
  }

  function setFileStatusBadges(row) {
    const placeHtml = customerFileStatusBadge(row, 'placement');
    const gerberHtml = customerFileStatusBadge(row, 'gerber');
    const refmapHtml = customerFileStatusBadge(row, 'refmap');
    const fill = (id, html) => {
      const el = document.getElementById(id);
      if (!el) return;
      const tmp = document.createElement('div');
      tmp.innerHTML = html;
      const badge = tmp.firstElementChild;
      if (!badge) return;
      el.className = badge.className;
      el.textContent = badge.textContent;
    };
    fill('eng-place-status-badge', placeHtml);
    fill('eng-gerber-status-badge', gerberHtml);
    fill('eng-refmap-status-badge', refmapHtml);
    fill('eng-place-head-badge', placeHtml);
    fill('eng-gerber-head-badge', gerberHtml);
    fill('eng-refmap-head-badge', refmapHtml);
  }

  function modelToCustomerAsset(m) {
    return {
      internal_code: m.internal_code,
      model_code: m.model_code,
      model_name: m.model_name,
      purchase_no: m.purchase_no || '',
      bom_model_id: m.id || m.bom_model_id,
      bom_status: m.bom_status,
      order_count: m.order_count || 0,
      placement_file_id: null,
      placement_line_count: 0,
      placement_audit_status: 'pending',
      placement_asset_status: 'pending',
      gerber_package_id: null,
      gerber_file_count: 0,
      gerber_audit_status: 'pending',
      gerber_asset_status: 'pending',
      refmap_file_id: null,
      refmap_audit_status: 'pending',
      refmap_asset_status: 'pending',
    };
  }

  async function loadCustomerAssets(opts = {}) {
    const code = opts.internal_code
      || selectedModel?.internal_code
      || getActiveInternalCode()
      || document.getElementById('eng-filter-code')?.value
      || '';
    const keyword = opts.keyword || '';
    const params = new URLSearchParams();
    if (code) params.set('internal_code', code);
    if (keyword) params.set('keyword', keyword);
    try {
      customerAssets = await engApi('/customer-assets?' + params.toString());
    } catch (e) {
      try {
        const models = await engApi('/models?' + params.toString());
        customerAssets = models.map(modelToCustomerAsset);
      } catch (_) {
        window.EMS.showToast('客户资料加载失败：' + e.message, 'error', 6000);
        customerAssets = [];
        return [];
      }
    }
    return customerAssets;
  }

  async function syncAssetsForSelectedModel() {
    if (!selectedModel?.internal_code || !selectedModel?.model_code) {
      clearAssetPanels();
      return null;
    }
    const bomId = selectedModelId || selectedModel.id || selectedModel.bom_model_id;
    let hit = null;
    // 优先按当前订单 BOM 直查，避免同机型多订单串单/折叠
    if (bomId) {
      try {
        hit = await engApi(`/models/${bomId}/assets`);
      } catch (_) {
        hit = null;
      }
    }
    if (!hit) {
      const rows = await loadCustomerAssets({
        internal_code: selectedModel.internal_code,
        keyword: selectedModel.purchase_no || selectedModel.model_code,
      });
      const pn = (selectedModel.purchase_no || '').trim();
      hit = rows.find((r) => bomId && Number(r.bom_model_id) === Number(bomId))
        || rows.find((r) => pn && (r.purchase_no || '') === pn && r.model_code === selectedModel.model_code)
        || rows.find((r) => r.internal_code === selectedModel.internal_code && r.model_code === selectedModel.model_code)
        || modelToCustomerAsset(selectedModel);
    }
    await selectCustomerAsset(hit);
    return hit;
  }

  function clearAssetPanels() {
    assetsSelectedRow = null;
    assetsSelectedKey = null;
    placeSelectedId = null;
    gerberSelectedId = null;
    const title = document.getElementById('eng-assets-title');
    if (title) title.textContent = '分工序分面：BOM + 坐标（须含面别）。Gerber / 位号图为可选归档。';
    clearMountReadinessPanel();
    document.getElementById('eng-place-lines-wrap')?.classList.add('hidden');
    document.getElementById('eng-gerber-files-wrap')?.classList.add('hidden');
    document.getElementById('eng-refmap-detail-wrap')?.classList.add('hidden');
    document.getElementById('eng-place-empty')?.classList.remove('hidden');
    document.getElementById('eng-gerber-empty')?.classList.remove('hidden');
    document.getElementById('eng-refmap-empty')?.classList.remove('hidden');
    if (typeof clearRefmapPreview === 'function') clearRefmapPreview();
    updateAssetDeleteButtons(null);
    setFileStatusBadges(null);
  }

  async function selectCustomerAsset(row) {
    if (!row) return;
    assetsSelectedRow = row;
    assetsSelectedKey = customerAssetRowKey(row);
    placeSelectedId = row.placement_file_id || null;
    gerberSelectedId = row.gerber_package_id || null;
    document.querySelectorAll('.eng-assets-row').forEach(tr => tr.classList.toggle('selected', tr.dataset.key === assetsSelectedKey));

    const title = document.getElementById('eng-assets-title');
    const placeIc = document.getElementById('eng-place-import-ic');
    const placeModel = document.getElementById('eng-place-import-model');
    const gerberIc = document.getElementById('eng-gerber-import-ic');
    const gerberModel = document.getElementById('eng-gerber-import-model');
    if (placeIc) placeIc.value = row.internal_code;
    if (placeModel) placeModel.value = row.model_code;
    if (gerberIc) gerberIc.value = row.internal_code;
    if (gerberModel) gerberModel.value = row.model_code;
    if (title) title.textContent = `${row.internal_code} · ${row.model_code} · ${row.model_name || '客户资料'}`;
    updateAssetDeleteButtons(row);
    setFileStatusBadges(row);

    const placeHint = document.getElementById('eng-place-audit-hint');
    const placeEmpty = document.getElementById('eng-place-empty');
    const placeWrap = document.getElementById('eng-place-lines-wrap');
    if (!row.placement_file_id || !row.placement_line_count) {
      placeWrap?.classList.add('hidden');
      placeEmpty?.classList.remove('hidden');
      if (placeHint) { placeHint.textContent = ''; placeHint.className = 'eng-gerber-audit-hint'; }
      if (placeEmpty) placeEmpty.textContent = '尚未导入坐标（须含位号与 TOP/BOT；支持 Altium/AIS/简易 place/ASC；无需 Gerber）';
    } else {
      placeEmpty?.classList.add('hidden');
      placeWrap?.classList.remove('hidden');
      if (placeHint) {
        placeHint.textContent = row.placement_audit_message || '';
        placeHint.className = `eng-gerber-audit-hint audit-${row.placement_audit_status || 'pending'}`;
      }
      await loadPlaceLines();
    }

    const gerberHint = document.getElementById('eng-gerber-audit-hint');
    const gerberEmpty = document.getElementById('eng-gerber-empty');
    const gerberWrap = document.getElementById('eng-gerber-files-wrap');
    if (!row.gerber_package_id || !row.gerber_file_count) {
      gerberWrap?.classList.add('hidden');
      gerberEmpty?.classList.remove('hidden');
      if (gerberHint) { gerberHint.textContent = ''; gerberHint.className = 'eng-gerber-audit-hint'; }
      if (gerberEmpty) gerberEmpty.textContent = '尚未导入 Gerber（可选归档；zip/7z/rar）。不参与工序/面别自动判定。';
    } else {
      gerberEmpty?.classList.add('hidden');
      gerberWrap?.classList.remove('hidden');
      if (gerberHint) {
        gerberHint.textContent = row.gerber_audit_message || '';
        gerberHint.className = `eng-gerber-audit-hint audit-${row.gerber_audit_status || 'pending'}`;
      }
      const files = await engApi(`/gerbers/${row.gerber_package_id}/files`);
      await renderGerberFilesTable(files, row.gerber_package_id);
    }

    const refmapHint = document.getElementById('eng-refmap-audit-hint');
    const refmapEmpty = document.getElementById('eng-refmap-empty');
    const refmapWrap = document.getElementById('eng-refmap-detail-wrap');
    const refmapTable = document.getElementById('eng-refmap-detail-table');
    if (!row.refmap_file_id || !row.refmap_file_name) {
      refmapWrap?.classList.add('hidden');
      refmapEmpty?.classList.remove('hidden');
      clearRefmapPreview();
      if (refmapHint) { refmapHint.textContent = ''; refmapHint.className = 'eng-gerber-audit-hint'; }
      if (refmapEmpty) refmapEmpty.textContent = '尚未导入位号图（PDF，文件名建议含 位号图/丝印图/ASM 等关键字）';
    } else {
      refmapEmpty?.classList.add('hidden');
      refmapWrap?.classList.remove('hidden');
      if (refmapHint) {
        refmapHint.textContent = row.refmap_audit_message || '';
        refmapHint.className = `eng-gerber-audit-hint audit-${row.refmap_audit_status || 'pending'}`;
      }
      try {
        const meta = await engApi(`/refmaps/${row.refmap_file_id}/reaudit`, { method: 'POST' });
        if (refmapHint && meta.audit_message) {
          refmapHint.textContent = meta.audit_message;
          refmapHint.className = `eng-gerber-audit-hint audit-${meta.audit_status || 'pending'}`;
        }
      } catch (_) { /* 使用列表中的审核信息 */ }
      if (refmapTable) {
        refmapTable.innerHTML = `
          <tr><th>文件名</th><td>${escapeHtml(row.refmap_file_name)}</td></tr>
          <tr><th>页数</th><td>${row.refmap_page_count || '—'}</td></tr>
          <tr><th>大小</th><td>${formatFileSize(row.refmap_file_size)}</td></tr>`;
      }
      loadRefmapPreview(row.refmap_file_id, row.refmap_page_count);
    }
  }

  async function importRefmap() {
    const ic = selectedModel?.internal_code
      || document.getElementById('eng-place-import-ic')?.value?.trim();
    const modelCode = selectedModel?.model_code
      || document.getElementById('eng-place-import-model')?.value?.trim();
    const fileInput = document.getElementById('eng-refmap-import-file');
    if (!ic || !modelCode) {
      window.EMS.showToast('请先在左侧选择订单', 'error');
      return;
    }
    if (!fileInput) return;
    fileInput.value = '';
    fileInput.onchange = async () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      const form = new FormData();
      form.append('file', file);
      form.append('internal_code', ic);
      form.append('model_code', modelCode);
      appendBomScopeToForm(form);
      try {
        const res = await fetch(API + '/refmaps/import', {
          method: 'POST',
          headers: window.EMS.authHeaders(),
          body: form,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(formatApiDetail(data.detail, res.statusText));
        if (data.status === 'failed') throw new Error(data.message || data.audit_message || '位号图审核未通过');
        const toastType = data.audit_status === 'warning' ? 'warning' : 'success';
        window.EMS.showToast(data.message || `已导入位号图 ${data.file || ''}`, toastType);
        await syncAssetsForSelectedModel();
      } catch (e) {
        window.EMS.showToast(e.message, 'error');
      } finally {
        fileInput.value = '';
      }
    };
    fileInput.click();
  }

  async function loadPlaceFiles() {
    return loadCustomerAssets();
  }

  async function selectPlaceFile(file) {
    const hit = customerAssets.find(r => r.model_code === file?.model_code && r.internal_code === file?.internal_code);
    if (hit) await selectCustomerAsset(hit);
  }

  async function loadGerberPackages() {
    return loadCustomerAssets();
  }

  async function selectGerberPackage(pkg) {
    const hit = customerAssets.find(r => r.model_code === pkg?.model_code && r.internal_code === pkg?.internal_code);
    if (hit) await selectCustomerAsset(hit);
  }

  async function loadPlaceLines() {
    if (!placeSelectedId) return;
    const keyword = document.getElementById('eng-place-line-search')?.value?.trim() || '';
    const params = new URLSearchParams();
    if (keyword) params.set('keyword', keyword);
    const lines = await engApi(`/placements/${placeSelectedId}/lines?` + params.toString());
    const tbody = document.getElementById('eng-place-lines-table');
    if (!tbody) return;
    if (!lines.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty">无匹配位号</td></tr>';
      return;
    }
    tbody.innerHTML = lines.map(l => `
      <tr>
        <td><strong>${l.refdes}</strong></td>
        <td>${l.comment || l.material_hint || '—'}</td>
        <td class="cell-muted">${l.footprint || '—'}</td>
        <td>${l.layer || '—'}</td>
        <td>${l.mid_x ?? '—'}</td>
        <td>${l.mid_y ?? '—'}</td>
        <td>${l.rotation ?? '—'}</td>
        <td>${l.skip ? '是' : '—'}</td>
      </tr>`).join('');
  }

  let lastMountReadiness = null;

  function clearMountReadinessPanel() {
    lastMountReadiness = null;
    const badge = document.getElementById('eng-mount-ready-badge');
    const hint = document.getElementById('eng-mount-ready-hint');
    const issues = document.getElementById('eng-mount-ready-issues');
    const rowsWrap = document.getElementById('eng-mount-ready-rows-wrap');
    const empty = document.getElementById('eng-mount-ready-empty');
    const copyBtn = document.getElementById('btn-eng-mount-ready-copy');
    if (badge) {
      badge.textContent = '未检查';
      badge.className = 'kit-badge kit-partial';
    }
    if (hint) { hint.textContent = ''; hint.className = 'eng-gerber-audit-hint'; }
    if (issues) issues.innerHTML = '';
    rowsWrap?.classList.add('hidden');
    empty?.classList.remove('hidden');
    if (empty) empty.textContent = '选择已导入 BOM 的订单后，点击「检查」';
    copyBtn?.classList.add('hidden');
  }

  function renderMountReadiness(data) {
    lastMountReadiness = data;
    const badge = document.getElementById('eng-mount-ready-badge');
    const hint = document.getElementById('eng-mount-ready-hint');
    const issuesEl = document.getElementById('eng-mount-ready-issues');
    const rowsWrap = document.getElementById('eng-mount-ready-rows-wrap');
    const rowsEl = document.getElementById('eng-mount-ready-rows');
    const empty = document.getElementById('eng-mount-ready-empty');
    const copyBtn = document.getElementById('btn-eng-mount-ready-copy');
    empty?.classList.add('hidden');
    if (badge) {
      badge.textContent = data.ready ? '达标' : '不达标';
      badge.className = data.ready ? 'kit-badge kit-ok' : 'kit-badge kit-bad';
    }
    if (hint) {
      const extra = data.ais_skip_repaired
        ? `（已自动修正 AIS 镜像误标跳过 ${data.ais_skip_repaired} 行）`
        : '';
      hint.textContent = (data.message || '') + extra;
      hint.className = `eng-gerber-audit-hint audit-${data.ready ? 'passed' : 'failed'}`;
    }
    if (issuesEl) {
      const items = data.issues || [];
      issuesEl.innerHTML = items.length
        ? items.map((it) => {
            const samples = (it.samples || []).slice(0, 5).join('、');
            const sampleHint = samples ? ` <span class="muted">例：${escapeHtml(samples)}</span>` : '';
            return `<li class="eng-mount-ready-issue sev-${escapeHtml(it.severity || 'block')}">` +
              `<strong>${escapeHtml(it.title || it.code)}</strong>×${it.count || 0}${sampleHint}` +
              `<div class="muted">${escapeHtml(it.advice || '')}</div></li>`;
          }).join('')
        : (data.ready ? '<li class="muted">无缺项</li>' : '');
    }
    const badRows = data.rows || [];
    if (rowsEl && rowsWrap) {
      if (!badRows.length) {
        rowsWrap.classList.add('hidden');
        rowsEl.innerHTML = '';
      } else {
        rowsWrap.classList.remove('hidden');
        rowsEl.innerHTML = badRows.map((r) => `
          <tr>
            <td>${escapeHtml(r.material_code || '')}</td>
            <td class="eng-kit-pos">${escapeHtml(r.position || '')}</td>
            <td>${escapeHtml(r.mount_type || '—')}</td>
            <td>${escapeHtml(r.mount_side || '—')}</td>
            <td>${escapeHtml(r.note || '')}</td>
          </tr>`).join('');
      }
    }
    copyBtn?.classList.toggle('hidden', !(data.reject_text || '').trim());
  }

  async function loadMountReadiness(opts = {}) {
    const silent = !!opts.silent;
    if (!selectedModelId) {
      clearMountReadinessPanel();
      if (!silent) window.EMS.showToast('请先选择已导入 BOM 的订单', 'error');
      return;
    }
    try {
      const data = await engApi(`/models/${selectedModelId}/mount-readiness`);
      renderMountReadiness(data);
      if (!silent) {
        window.EMS.showToast(data.ready ? '工序·面别已达标' : '尚未达标，请查看缺项', data.ready ? 'success' : 'warning');
      }
    } catch (e) {
      clearMountReadinessPanel();
      if (!silent) window.EMS.showToast(e.message || '完备性检查失败', 'error');
    }
  }

  async function copyMountReadinessAdvice() {
    const text = lastMountReadiness?.reject_text || lastMountReadiness?.message || '';
    if (!text) {
      window.EMS.showToast('暂无可复制内容', 'error');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      window.EMS.showToast('已复制缺项说明');
    } catch (e) {
      window.EMS.showToast('复制失败：' + (e.message || ''), 'error');
    }
  }

  async function importPlacement() {
    const ic = selectedModel?.internal_code
      || document.getElementById('eng-place-import-ic')?.value?.trim();
    const modelCode = selectedModel?.model_code
      || document.getElementById('eng-place-import-model')?.value?.trim();
    const fileInput = document.getElementById('eng-place-import-file');
    if (!ic || !modelCode) {
      window.EMS.showToast('请先在左侧选择订单', 'error');
      return;
    }
    const placeIc = document.getElementById('eng-place-import-ic');
    const placeModel = document.getElementById('eng-place-import-model');
    if (placeIc) placeIc.value = ic;
    if (placeModel) placeModel.value = modelCode;
    if (!fileInput) return;
    fileInput.value = '';
    fileInput.onchange = async () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      const form = new FormData();
      form.append('file', file);
      form.append('internal_code', ic);
      form.append('model_code', modelCode);
      appendBomScopeToForm(form);
      try {
        const res = await fetch(API + '/placements/import', {
          method: 'POST',
          headers: window.EMS.authHeaders(),
          body: form,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(formatApiDetail(data.detail, res.statusText));
        if (data.status === 'failed') throw new Error(data.message || data.audit_message || '坐标审核未通过');
        const toastType = data.audit_status === 'warning' ? 'warning' : 'success';
        window.EMS.showToast(data.message || `已导入 ${data.lines} 个位号`, toastType);
        placeSelectedId = data.placement_file_id || placeSelectedId;
        await syncAssetsForSelectedModel();
        if (selectedModelId) await loadMountReadiness({ silent: true });
      } catch (e) {
        window.EMS.showToast(e.message, 'error');
      } finally {
        fileInput.value = '';
      }
    };
    fileInput.click();
  }

  async function loadCoverage() {
    const el = document.getElementById('eng-coverage-info');
    if (!el) return;
    try {
      const data = await engApi('/coverage');
      const miss = data.missing_bom_count || 0;
      const mismatch = data.code_mismatch_count || 0;
      if (!miss && !mismatch) {
        el.classList.add('hidden');
        return;
      }
      el.classList.remove('hidden');
      el.textContent = `资料覆盖检查：${miss} 项有 Gerber/坐标但缺 BOM，${mismatch} 项资料夹料号与 BOM 料号不一致（请手工导入 BOM 并核对料号）`;
    } catch (_) {
      el.classList.add('hidden');
    }
  }

  function modelRowKey(row) {
    if (!row) return '';
    const pn = (row.purchase_no || '').trim();
    if (pn) return `order:${row.internal_code}:${pn}:${row.model_code || ''}`;
    return row.id ? String(row.id) : `pending:${row.internal_code}:${row.model_code}`;
  }

  function resolveBomStatus(row) {
    if (!row) return 'pending';
    if (row.bom_confirmed || row.bom_status === 'imported') return 'imported';
    if (row.id && row.line_count > 0) return 'imported';
    return 'pending';
  }

  function modelFolderSubtitle(row) {
    const folder = (row?.folder_name || '').trim();
    if (folder) {
      const label = shortPath(folder);
      return `<div class="muted" style="font-size:11px" title="${escapeHtml(folder)}">导入：${escapeHtml(label)}</div>`;
    }
    if (row?.remark) {
      return `<div class="muted" style="font-size:11px">${escapeHtml(row.remark)}</div>`;
    }
    return '';
  }

  function bomStatusBadge(status) {
    if (status === 'imported') return '<span class="kit-badge kit-ready">已确认</span>';
    return '<span class="kit-badge kit-partial">待导入</span>';
  }

  async function loadModels() {
    const code = getActiveInternalCode() || document.getElementById('eng-filter-code')?.value || '';
    if (!code) {
      const tbody = document.getElementById('eng-models-table');
      if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="empty">请先选择客户模块</td></tr>';
      return [];
    }
    const filterEl = document.getElementById('eng-filter-code');
    if (filterEl) filterEl.value = code;
    const keyword = document.getElementById('eng-search')?.value?.trim() || '';
    const params = new URLSearchParams();
    params.set('internal_code', code);
    if (keyword) params.set('keyword', keyword);
    const rows = await engApi('/models?' + params.toString());
    const tbody = document.getElementById('eng-models-table');
    if (!tbody) return [];
    const pendingCount = rows.filter(r => resolveBomStatus(r) === 'pending').length;
    const importedCount = rows.length - pendingCount;
    const meta = document.getElementById('eng-path-info');
    if (meta) {
      meta.textContent = `${code} 在制 ${rows.length} 笔 · BOM 已确认 ${importedCount} · 待导入 ${pendingCount} · 资料人工导入`;
    }
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty">暂无在制订单</td></tr>';
      return [];
    }
    tbody.innerHTML = rows.map(r => {
      const status = resolveBomStatus(r);
      const rev = effectiveReviewStatus(r);
      return `
      <tr class="eng-model-row${selectedModelKey === modelRowKey(r) ? ' selected' : ''}${status === 'pending' ? ' eng-model-pending' : ' eng-model-imported'}${rev === 'pending_review' ? ' eng-model-pending-review' : ''}" data-key="${modelRowKey(r)}" data-id="${r.id || ''}" data-purchase="${escapeHtml(r.purchase_no || '')}">
        <td>${r.internal_code}</td>
        <td>${r.customer_name || r.customer_id}</td>
        <td><strong>${r.model_code}</strong>${modelFolderSubtitle(r)}${(r.has_substitution || r.substitution_rule_count > 0) ? ` <span class="kit-badge kit-partial" title="已绑定替代料规则 ${r.substitution_rule_count || 0} 条">替×${r.substitution_rule_count || ''}</span>` : ''}</td>
        <td><strong>${r.purchase_no || '—'}</strong></td>
        <td>${r.model_name || '—'}</td>
        <td>${bomStatusBadge(status)}${status === 'imported' ? ` <span class="muted">${r.line_count}</span>` : ''}</td>
        <td><span class="kit-badge ${reviewStatusClass(rev)}" title="资料审核状态（不是按钮）">${status === 'imported' ? reviewStatusLabel(rev) : '—'}</span></td>
        <td>${r.order_qty != null ? r.order_qty : '—'}</td>
      </tr>`;
    }).join('');
    tbody.querySelectorAll('.eng-model-row').forEach(tr => {
      tr.addEventListener('click', () => selectModel(rows.find(x => modelRowKey(x) === tr.dataset.key)));
    });
    // 仅一条结果时自动选中，便于按订单号搜索后直接导入
    if (rows.length === 1) {
      await selectModel(rows[0]);
    }
    return rows;
  }

  function normalizeLinesPayload(payload) {
    if (Array.isArray(payload)) {
      return {
        lines: payload,
        mount_profile_override: '',
        detected_profile: '',
        profile_confidence: '',
        profile_source: '',
        eng_review_status: '',
        eng_review_message: '',
      };
    }
    return {
      lines: payload?.lines || [],
      mount_profile_override: payload?.mount_profile_override || '',
      detected_profile: payload?.detected_profile || '',
      profile_confidence: payload?.profile_confidence || '',
      profile_source: payload?.profile_source || '',
      eng_review_status: payload?.eng_review_status || '',
      eng_review_message: payload?.eng_review_message || '',
    };
  }

  function processSelect(current) {
    const cur = current || '';
    return `<select class="sched-inline eng-process-select" data-field="process">${
      PROCESS_OPTIONS.map(o => `<option value="${o.value}"${o.value === cur ? ' selected' : ''}>${o.label}</option>`).join('')
    }</select>`;
  }

  function updateDetailTitle(model, lines, meta) {
    const title = document.getElementById('eng-detail-title');
    if (!title || !model) return;
    const orderPart = model.purchase_no ? ` · 订单 ${model.purchase_no}` : '';
    const base = `${model.internal_code} · ${model.model_code}${orderPart} · ${model.model_name || ''}`;
    const hasPlacement = (lines || []).some(l => l.mount_source === 'placement');
    const hasRule = (lines || []).some(l => l.mount_source === 'rule' && l.mount_type);
    if (hasPlacement) {
      title.textContent = `${base}（贴装/面别由坐标判定）`;
    } else if (hasRule) {
      title.textContent = `${base}（无坐标，贴装/面别由规则判定）`;
    } else {
      title.textContent = `${base}（请补工艺列或指定贴装画像）`;
    }
    applyMountProfileBar(meta);
  }

  function applyMountProfileBar(meta) {
    const bar = document.getElementById('eng-mount-profile-bar');
    const sel = document.getElementById('eng-mount-profile');
    const hint = document.getElementById('eng-mount-profile-hint');
    if (!bar || !sel || !hint) return;
    bar.classList.remove('hidden');
    const override = meta?.mount_profile_override || '';
    sel.value = override;
    const detected = meta?.detected_profile || 'unknown';
    if (override) {
      hint.textContent = `当前：手工指定「${PROFILE_LABELS[override] || override}」`;
    } else if (detected && detected !== 'unknown') {
      const conf = meta?.profile_confidence ? ` / ${meta.profile_confidence}` : '';
      hint.textContent = `自动识别：${PROFILE_LABELS[detected] || detected}${conf}`;
    } else {
      hint.textContent = '自动识别未得出明确结论，可手工指定或补工艺列';
    }
  }

  function isImportOnly() {
    return isEngImportOnly();
  }

  function isAuditOnly() {
    return isEngAuditOnly();
  }

  function reviewStatusLabel(status) {
    return {
      pending_import: '待导入',
      pending_review: '待审核',
      approved: '已通过',
      rejected: '已退回',
    }[status] || status || '—';
  }

  function reviewStatusClass(status) {
    return {
      pending_import: 'kit-unknown',
      pending_review: 'kit-partial',
      approved: 'kit-ready',
      rejected: 'kit-shortage',
    }[status] || 'kit-unknown';
  }

  /** BOM 已导入但尚未写入审核流时，按「待审核」处理，避免误显示「待导入」 */
  function effectiveReviewStatus(model, meta) {
    const raw = (meta?.eng_review_status || model?.eng_review_status || '').trim();
    const bomOk = resolveBomStatus(model) === 'imported' || Number(model?.line_count || 0) > 0;
    if (bomOk && (!raw || raw === 'pending_import')) return 'pending_review';
    return raw;
  }

  function mountReasonCell(line) {
    const reason = line.mount_reason || '';
    if (!line.mount_type) {
      return `<span class="mount-reason mount-reason-warn" title="${escapeHtml(reason)}">${escapeHtml(reason || '未识别')}</span>`;
    }
    if (line.mount_type === 'ASSY' || line.mount_type === 'N/A') {
      return `<span class="mount-reason" title="${escapeHtml(reason)}">${escapeHtml(reason || line.mount_type)}</span>`;
    }
    return reason
      ? `<span class="mount-reason muted" title="${escapeHtml(reason)}">${escapeHtml(reason)}</span>`
      : '<span class="muted">—</span>';
  }

  function renderBomLines(lines, meta) {
    const tbody = document.getElementById('eng-lines-table');
    if (!tbody) return;
    const active = (lines || []).filter((l) => l.is_active !== false);
    if (!active.length) {
      tbody.innerHTML = '<tr><td colspan="11" class="empty">无明细行</td></tr>';
      return;
    }
    tbody.innerHTML = active.map(l => {
      const ctrlMark = (l.source === 'control' || l.control_id)
        ? ' <span class="kit-badge kit-partial" title="管制变更料">变更</span>'
        : '';
      return `
      <tr data-line-id="${l.id}" class="${l.source === 'control' ? 'eng-line-control' : ''}" title="${mountSourceHint(l.mount_source)}">
        <td>${l.seq || '—'}</td>
        <td>${l.material_code}${ctrlMark}</td>
        <td>${l.material_name || '—'}</td>
        <td>${mountTypeSelect(l)}</td>
        <td>${mountSideSelect(l)}</td>
        <td>${mountReasonCell(l)}</td>
        <td class="cell-wrap">${escapeHtml(l.spec || '—')}</td>
        <td>${isImportOnly() || isAuditOnly() ? (l.qty_per ?? '—') : `<input class="sched-inline" data-field="qty_per" type="number" min="0" step="0.0001" value="${l.qty_per}">`}</td>
        <td>${l.unit}</td>
        <td class="eng-kit-pos">${escapeHtml(l.position || '—')}</td>
        <td>${isImportOnly() || isAuditOnly() ? (l.process || '—') : processSelect(l.process)}</td>
      </tr>`;
    }).join('');
    if (!isImportOnly() && !isAuditOnly()) {
      tbody.querySelectorAll('input[data-field="qty_per"]').forEach(inp => {
        inp.addEventListener('change', () => saveLine(Number(inp.closest('tr').dataset.lineId), { qty_per: Number(inp.value) }));
      });
      tbody.querySelectorAll('select[data-field="process"]').forEach(sel => {
        sel.addEventListener('change', () => saveLine(Number(sel.closest('tr').dataset.lineId), { process: sel.value }));
      });
    }
    bindMountEditors(tbody);
    if (meta) applyMountProfileBar(meta);
    updateReviewBar(meta);
  }

  function updateReviewBar(meta) {
    const badge = document.getElementById('eng-review-status-badge');
    const approveBtn = document.getElementById('btn-eng-review-approve');
    const rejectBtn = document.getElementById('btn-eng-review-reject');
    const printBtn = document.getElementById('btn-eng-print-issue');
    if (selectedModel && meta?.eng_review_status) {
      selectedModel.eng_review_status = meta.eng_review_status;
    }
    const status = effectiveReviewStatus(selectedModel, meta);
    if (badge) {
      badge.textContent = reviewStatusLabel(status);
      badge.className = `kit-badge ${reviewStatusClass(status)}`;
      badge.title = '资料审核状态（不是按钮）';
    }
    const canAudit = canEngAudit();
    const pending = status === 'pending_review';
    approveBtn?.classList.toggle('hidden', !(canAudit && pending && selectedModelId));
    rejectBtn?.classList.toggle('hidden', !(canAudit && pending && selectedModelId));
    printBtn?.classList.toggle('eng-print-disabled', status !== 'approved');
    if (printBtn) {
      printBtn.title = status === 'approved' ? '打印本订单发料单' : '资料未审核，审核通过后可打印';
    }
    syncKitApproveButton(status, canAudit);
  }

  function dossierBlockingItems(dossier) {
    return (dossier?.checklist || []).filter((c) => !c.optional && !c.ready);
  }

  function applyApproveGate(dossier) {
    const blockers = dossierBlockingItems(dossier);
    const blocked = blockers.length > 0;
    const tip = blocked
      ? `齐套未完成，暂不可通过：${blockers.map((c) => c.label).join('、')}`
      : '资料齐套已满足，可审核通过';
    ['btn-eng-kit-approve', 'btn-eng-review-approve'].forEach((id) => {
      const btn = document.getElementById(id);
      if (!btn) return;
      btn.disabled = blocked;
      btn.title = tip;
      btn.classList.toggle('eng-approve-blocked', blocked);
    });
    const gate = document.getElementById('eng-kit-approve-gate');
    if (gate) {
      if (blocked) {
        gate.classList.remove('hidden');
        gate.textContent = tip;
      } else {
        gate.classList.add('hidden');
        gate.textContent = '';
      }
    }
  }

  function syncKitApproveButton(status, canAudit) {
    const kitApprove = document.getElementById('btn-eng-kit-approve');
    const kitReject = document.getElementById('btn-eng-kit-reject');
    const pending = (status || effectiveReviewStatus(selectedModel)) === 'pending_review';
    const allow = canAudit != null ? canAudit : canEngAudit();
    kitApprove?.classList.toggle('hidden', !(allow && pending && selectedModelId));
    kitReject?.classList.toggle('hidden', !(allow && pending && selectedModelId));
  }

  function renderReviewDossier(dossier) {
    const box = document.getElementById('eng-kit-dossier');
    const badge = document.getElementById('eng-kit-status-badge');
    const title = document.getElementById('eng-kit-modal-title');
    if (!box) return;
    if (!dossier) {
      box.innerHTML = '';
      box.classList.add('hidden');
      if (badge) badge.textContent = '';
      if (title) title.textContent = 'BOM 资料审核';
      applyApproveGate(null);
      return;
    }
    box.classList.remove('hidden');
    if (title) title.textContent = '工程资料审核工作台';
    const st = dossier.eng_review_status || 'pending_review';
    if (badge) {
      badge.textContent = reviewStatusLabel(st);
      badge.className = `kit-badge ${reviewStatusClass(st)}`;
    }
    const checks = (dossier.checklist || []).map((c) => {
      const cls = c.ready ? 'ok' : (c.optional ? 'opt' : 'miss');
      const mark = c.ready ? '✓' : (c.optional ? '○' : '!');
      return `<div class="eng-check-item eng-check-${cls}" title="${escapeHtml(c.detail || '')}">
        <span class="eng-check-mark">${mark}</span>
        <div>
          <div class="eng-check-label">${escapeHtml(c.label)}</div>
          <div class="eng-check-detail">${escapeHtml(c.detail || '')}</div>
        </div>
      </div>`;
    }).join('');
    const steps = (dossier.workflow || []).map((s) => `
      <div class="eng-flow-step ${s.done ? 'done' : ''}">
        <span class="eng-flow-num">${s.step}</span>
        <span>${escapeHtml(s.title)}</span>
      </div>
    `).join('<span class="eng-flow-sep">→</span>');
    const rules = dossier.customer_rules || {};
    const scope = (rules.assets_scope || activeEngCustomer?.rules?.assets_scope || 'model') === 'order'
      ? '资料按订单隔离'
      : '资料按机型共用';
    const allowNoMount = !!(rules.workflow && rules.workflow.allow_approve_without_mount);
    const stats = dossier.mount_stats || {};
    const reviewMeta = (dossier.eng_reviewed_by || dossier.eng_reviewed_at)
      ? `<div><span class="k">最近审核</span><span>${escapeHtml(dossier.eng_reviewed_by || '—')} · ${formatReviewTodoTime(dossier.eng_reviewed_at)}</span></div>`
      : '';
    const rejectBanner = st === 'rejected'
      ? `<div class="eng-dossier-reject" role="alert">
          <div class="eng-dossier-reject-title">⚠ 审核已退回 — 请按下列原因修正后重新导入/送审</div>
          <div class="eng-dossier-reject-body">${escapeHtml(dossier.eng_review_message || '（未填写原因）')}</div>
        </div>`
      : '';
    box.innerHTML = `
      ${rejectBanner}
      <div class="eng-dossier-meta">
        <div class="eng-dossier-grid">
          <div><span class="k">采购订单</span><strong>${escapeHtml(dossier.purchase_no || '—')}</strong></div>
          <div><span class="k">机型料号</span><strong>${escapeHtml(dossier.model_code || '—')}</strong></div>
          <div><span class="k">品名</span><span>${escapeHtml(dossier.model_name || '—')}</span></div>
          <div><span class="k">客户代码</span><span>${escapeHtml(dossier.internal_code || '—')}${dossier.customer_name ? ` · ${escapeHtml(dossier.customer_name)}` : ''}</span></div>
          <div><span class="k">提交人</span><span>${escapeHtml(dossier.eng_submitter || '—')}</span></div>
          <div><span class="k">送审时间</span><span>${formatReviewTodoTime(dossier.eng_submitted_at)}</span></div>
          ${reviewMeta}
          <div><span class="k">客户规则</span><span>${escapeHtml(scope)}${allowNoMount ? ' · 允许贴装未全识别通过' : ''}</span></div>
          <div><span class="k">贴装统计</span><span>SMT ${stats.smt || 0} · DIP ${stats.dip || 0} · 装配 ${stats.assy || 0} · 待确认 ${stats.unresolved || 0}</span></div>
          ${st !== 'rejected' ? `<div class="eng-dossier-span"><span class="k">资料摘要</span><span>${escapeHtml(dossier.eng_review_message || '—')}</span></div>` : ''}
        </div>
      </div>
      <div class="eng-dossier-flow">${steps}</div>
      <div class="eng-dossier-checks">${checks}</div>
    `;
    applyApproveGate(dossier);
  }

  async function loadReviewDossier(bomModelId) {
    if (!bomModelId) {
      renderReviewDossier(null);
      lastReviewDossier = null;
      return null;
    }
    try {
      const dossier = await engApi(`/models/${bomModelId}/review-dossier`);
      lastReviewDossier = dossier;
      renderReviewDossier(dossier);
      return dossier;
    } catch (_) {
      lastReviewDossier = null;
      renderReviewDossier(null);
      return null;
    }
  }

  async function approveEngReview() {
    if (!selectedModelId) return;
    const kitOpen = !document.getElementById('eng-kit-modal')?.classList.contains('hidden');
    if (!kitOpen) {
      await showKitting();
      window.EMS.showToast('请先在审核工作台核对齐套与贴装明细，再点「审核通过」', 'warning', 5000);
      return;
    }
    const dossier = lastReviewDossier || await loadReviewDossier(selectedModelId);
    const blockers = dossierBlockingItems(dossier);
    if (blockers.length) {
      window.EMS.showToast(`齐套未完成：${blockers.map((c) => c.label).join('、')}`, 'error', 6000);
      applyApproveGate(dossier);
      return;
    }
    if (!window.confirm('确认审核通过本订单资料？通过后可用于发料打印。')) return;
    await engApi(`/models/${selectedModelId}/review/approve`, {
      method: 'POST',
      body: JSON.stringify({ message: '审核通过' }),
    });
    window.EMS.showToast('已审核通过，资料信息已更新');
    document.getElementById('eng-kit-modal')?.classList.add('hidden');
    renderReviewDossier(null);
    await loadModels();
    await loadReviewInbox({ silent: true });
    const next = (reviewTodoItems || []).find((it) => {
      const kind = it.todo_type || reviewTodoMeta.todo_kind;
      return kind === 'review' || (!kind && reviewTodoMeta.todo_kind !== 'import');
    });
    if (next && canEngAudit()) {
      if (window.confirm('还有待审核事项，是否继续处理下一条？')) {
        await openReviewTodoItem(next);
        return;
      }
    }
    if (selectedModel) await selectModel(selectedModel);
  }

  function defaultRejectReason() {
    const blockers = dossierBlockingItems(lastReviewDossier);
    if (blockers.length) {
      return `请补齐：${blockers.map((c) => `${c.label}${c.detail ? `（${c.detail}）` : ''}`).join('；')}`;
    }
    const n = (lastKitLines || []).filter(kitLineNeedsAttention).length;
    if (n > 0) return `请修正贴装/面别，仍有 ${n} 行待确认`;
    return lastMountReadiness?.reject_text || '';
  }

  function openRejectModal() {
    if (!selectedModelId) return;
    const modal = document.getElementById('eng-reject-modal');
    const input = document.getElementById('eng-reject-reason');
    if (input) input.value = defaultRejectReason();
    modal?.classList.remove('hidden');
    input?.focus();
  }

  async function submitRejectModal() {
    if (!selectedModelId) return;
    const input = document.getElementById('eng-reject-reason');
    const reason = (input?.value || '').trim();
    if (!reason) {
      window.EMS.showToast('请填写退回原因', 'error');
      return;
    }
    await engApi(`/models/${selectedModelId}/review/reject`, {
      method: 'POST',
      body: JSON.stringify({ message: reason }),
    });
    document.getElementById('eng-reject-modal')?.classList.add('hidden');
    window.EMS.showToast('已退回给导入员');
    document.getElementById('eng-kit-modal')?.classList.add('hidden');
    renderReviewDossier(null);
    await loadModels();
    if (selectedModel) await selectModel(selectedModel);
    await loadReviewInbox({ silent: true });
    const next = (reviewTodoItems || []).find((it) => {
      const kind = it.todo_type || reviewTodoMeta.todo_kind;
      return kind === 'review' || (!kind && reviewTodoMeta.todo_kind !== 'import');
    });
    if (next && canEngAudit()) {
      if (window.confirm('还有待审核事项，是否继续处理下一条？')) {
        await openReviewTodoItem(next);
      }
    }
  }

  async function printIssueSlip() {
    if (!selectedModel) {
      window.EMS.showToast('请先选择左侧订单', 'error');
      return;
    }
    const status = effectiveReviewStatus(selectedModel);
    if (status !== 'approved') {
      window.EMS.showToast('资料未审核，请联系管理员审核', 'error');
      return;
    }
    if (!selectedModelId) {
      window.EMS.showToast('请先导入并审核本订单 BOM', 'error');
      return;
    }
    document.getElementById('eng-issue-print-modal')?.classList.remove('hidden');
  }

  function toolingSourceLabel(stencilSrc, waveSrc) {
    const s = stencilSrc || '客供';
    const w = waveSrc || '客供';
    // 纯贴片可无波峰治具；纯插件可无钢网；两者皆无时写「钢网治具无」
    if (s === '无' && w === '无') return '钢网治具无';
    if (s === w) return `钢网治具${s}`;
    if (s === '无') return `无钢网·波峰${w}`;
    if (w === '无') return `钢网${s}·无波峰治具`;
    return `钢网${s}·波峰${w}`;
  }

  function lineMountKind(line) {
    const t = String(line?.mount_type || line?.process || '').toUpperCase();
    if (t.includes('SMT') || t === '贴片') return 'SMT';
    if (t.includes('DIP') || t === '插件') return 'DIP';
    return '';
  }

  function inferProcessLabel(lines) {
    let smt = 0;
    let dip = 0;
    (lines || []).forEach((l) => {
      const kind = lineMountKind(l);
      if (kind === 'SMT') smt += 1;
      else if (kind === 'DIP') dip += 1;
    });
    if (smt && dip) return 'SMT/DIP';
    if (dip && !smt) return 'DIP';
    if (smt) return 'SMT';
    const profile = selectedModel?.mount_profile_override || '';
    if (profile === 'dip_only') return 'DIP';
    if (profile === 'smt_only') return 'SMT';
    if (profile === 'mixed') return 'SMT/DIP';
    return 'SMT';
  }

  function filterLinesByProcess(lines, processFilter) {
    const filter = String(processFilter || 'ALL').toUpperCase();
    if (filter === 'ALL') return lines || [];
    return (lines || []).filter((l) => lineMountKind(l) === filter);
  }

  async function doPrintIssueSlip() {
    const processFilter = document.getElementById('eng-issue-process-filter')?.value || 'SMT';
    const stencilSrc = document.getElementById('eng-issue-stencil-src')?.value || '客供';
    const waveSrc = document.getElementById('eng-issue-wave-src')?.value || '客供';
    document.getElementById('eng-issue-print-modal')?.classList.add('hidden');
    // 同步打开，避免异步后被浏览器拦截
    let w = null;
    try {
      w = window.open('about:blank', '_blank');
    } catch (_) {
      w = null;
    }
    try {
      const payload = normalizeLinesPayload(await engApi(`/models/${selectedModelId}/lines`));
      // 管制停用行不再进入发料单；仅打印生效明细
      const allLines = (payload.lines || []).filter((l) => l.is_active !== false);
      if (!allLines.length) {
        if (w) try { w.close(); } catch (_) {}
        window.EMS.showToast('BOM 无明细，无法打印发料单', 'error');
        return;
      }
      const lines = filterLinesByProcess(allLines, processFilter);
      if (!lines.length) {
        if (w) try { w.close(); } catch (_) {}
        const label = processFilter === 'ALL' ? 'BOM' : processFilter;
        window.EMS.showToast(`本订单无 ${label} 明细，无法打印`, 'error');
        return;
      }
      const orderQty = Number(selectedModel.order_qty || 1);
      const factory = selectedModel.internal_code || '';
      const toolLabel = toolingSourceLabel(stencilSrc, waveSrc);
      const processLabel = processFilter === 'ALL' ? inferProcessLabel(lines) : processFilter;
      const mountTypeOrder = { SMT: 1, DIP: 2, ASSY: 3, 'N/A': 4 };
      const mountSideOrder = { TOP: 1, BOT: 2, 'TOP+BOT': 3 };
      const printMountType = (t) => {
        const u = String(t || '').toUpperCase();
        if (u === 'SMT') return 'SMT';
        if (u === 'DIP') return 'DIP';
        if (u === 'ASSY') return '装配';
        if (u === 'N/A') return 'N/A';
        return t || '—';
      };
      const printMountSide = (s) => {
        const u = String(s || '').toUpperCase();
        if (u === 'TOP') return 'T面';
        if (u === 'BOT') return 'B面';
        if (u === 'TOP+BOT') return '双面';
        return s || '—';
      };
      const cmpCode = (a, b) => {
        const ca = String(a || '').trim();
        const cb = String(b || '').trim();
        const na = Number(ca);
        const nb = Number(cb);
        if (ca !== '' && cb !== '' && Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
        return ca.localeCompare(cb, 'zh-CN', { numeric: true, sensitivity: 'base' });
      };
      // 先按贴装类型、面别分组，再按元件品号升序，方便按工序/面发料
      const sortedLines = [...lines].sort((a, b) => {
        const ta = mountTypeOrder[String(a.mount_type || '').toUpperCase()] || 9;
        const tb = mountTypeOrder[String(b.mount_type || '').toUpperCase()] || 9;
        if (ta !== tb) return ta - tb;
        const sa = mountSideOrder[String(a.mount_side || '').toUpperCase()] || 9;
        const sb = mountSideOrder[String(b.mount_side || '').toUpperCase()] || 9;
        if (sa !== sb) return sa - sb;
        return cmpCode(a.material_code, b.material_code);
      });
      // 永联：按机型拉取替代规则，发料单标注投产料号 + 分板用量
      const subByComp = {};
      const isYonglian = (selectedModel.customer_id || '') === 'yonglian'
        || (selectedModel.internal_code || '') === 'A067';
      if (isYonglian && selectedModel.model_code) {
        try {
          const rules = await engApi(
            '/substitutions?' + new URLSearchParams({
              customer_id: selectedModel.customer_id || 'yonglian',
              parent_code: selectedModel.model_code,
              page: '1',
              page_size: '500',
            }).toString()
          );
          (rules || []).forEach((r) => {
            const key = String(r.comp_code || '').trim().toUpperCase();
            if (!key) return;
            if (!subByComp[key]) subByComp[key] = r;
          });
        } catch (_) { /* 无替代规则时仍打印 BOM */ }
      }
      const hasSubMarks = Object.keys(subByComp).length > 0;
      const hasControlMarks = sortedLines.some((l) => l.source === 'control' || l.control_id);
      const rowsHtml = sortedLines.map((l, idx) => {
        const codeKey = String(l.material_code || '').trim().toUpperCase();
        const rule = subByComp[codeKey];
        const per = rule && rule.qty != null && rule.qty !== ''
          ? Number(rule.qty)
          : Number(l.qty_per ?? 0);
        const need = Math.round(per * orderQty * 10000) / 10000;
        const isCtrl = l.source === 'control' || !!l.control_id;
        const codeCell = isCtrl
          ? `<span style="color:#c00;font-weight:700">${escapeHtml(l.material_code || '')}</span><div style="color:#c00;font-size:10px">变更</div>`
          : escapeHtml(l.material_code || '');
        const subCell = rule
          ? `<span style="color:#c00;font-weight:700">${escapeHtml(rule.sub_code || '')}</span>`
          : '';
        const nameText = l.material_name || (l.spec || '').split(' / ')[0] || '';
        return `<tr>
          <td>${idx + 1}</td>
          <td>${escapeHtml(printMountType(l.mount_type))}</td>
          <td>${escapeHtml(printMountSide(l.mount_side))}</td>
          <td>${codeCell}</td>
          <td>${subCell}</td>
          <td>${escapeHtml(nameText)}</td>
          <td class="cell-wrap">${escapeHtml(l.spec || '')}</td>
          <td>${escapeHtml(l.unit || 'PCS')}</td>
          <td>${per}</td>
          <td class="eng-kit-pos">${escapeHtml(l.position || '')}</td>
          <td>${need}</td>
          <td></td>
          <td></td>
        </tr>`;
      }).join('');
      const hints = [];
      if (hasControlMarks) hints.push('本单含管制变更料（红色「变更」），已按生效 BOM 发料');
      if (hasSubMarks) hints.push('本单含替代料，请按「投产料号」备料（元件品号为 BOM 子项）');
      const subHint = hints.length
        ? `<div class="head" style="color:#c00;font-size:13px;margin-top:-4px">${hints.join('；')}</div>`
        : '';
      const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>发料单 ${escapeHtml(processLabel)} ${escapeHtml(selectedModel.purchase_no || '')}</title>
<style>
  *{box-sizing:border-box}
  body{font-family:"SimSun","Songti SC","PingFang SC","Microsoft YaHei",serif;color:#111;margin:8px;font-size:12px}
  .head{margin:0 0 10px;line-height:1.8;font-size:16px;font-weight:700;text-align:center;word-spacing:2px}
  .tool{color:#c00;font-weight:700;margin:0 6px}
  table{width:100%;border-collapse:collapse;table-layout:fixed}
  th,td{border:1px solid #333;padding:3px 4px;text-align:center;vertical-align:middle;word-break:break-all}
  th{background:#d9d9d9;font-weight:700}
  td:nth-child(6),td:nth-child(7),td:nth-child(10){text-align:left;white-space:normal;line-height:1.35}
  .eng-kit-pos{white-space:normal;word-break:break-all;line-height:1.35;font-size:11px}
  @media print{
    body{margin:4mm}
    .no-print{display:none!important}
    @page{size:A4 landscape;margin:4mm}
  }
</style></head><body>
  <div class="head">
    客户: ${escapeHtml(factory)}
    &nbsp;&nbsp;${escapeHtml(selectedModel.model_code || '')}
    &nbsp;&nbsp;订单${orderQty}PCS
    <span class="tool">${escapeHtml(toolLabel)}</span>
    订单号：${escapeHtml(selectedModel.purchase_no || '—')}
    &nbsp;&nbsp;${escapeHtml(processLabel)}
  </div>
  ${subHint}
  <table>
    <thead>
      <tr>
        <th style="width:3%">序号</th>
        <th style="width:4%">贴装</th>
        <th style="width:4%">面别</th>
        <th style="width:9%">元件品号</th>
        <th style="width:9%">投产/替代</th>
        <th style="width:8%">元件品名</th>
        <th style="width:16%">元件规格</th>
        <th style="width:3%">单位</th>
        <th style="width:4%">用量</th>
        <th style="width:14%">插件位置</th>
        <th style="width:5%">需求</th>
        <th style="width:10%">发料数</th>
        <th style="width:7%">退料数</th>
      </tr>
    </thead>
    <tbody>${rowsHtml}</tbody>
  </table>
  <p class="no-print" style="margin-top:16px;text-align:center">
    <button onclick="window.print()">打印</button>
    <button onclick="window.close()">关闭</button>
  </p>
</body></html>`;
      if (w && !w.closed) {
        w.document.open();
        w.document.write(html + '<script>setTimeout(function(){window.print()},300)<\\/script>');
        w.document.close();
        return;
      }
      // 弹窗被拦时：用隐藏 iframe 同页打印
      let frame = document.getElementById('eng-issue-print-frame');
      if (!frame) {
        frame = document.createElement('iframe');
        frame.id = 'eng-issue-print-frame';
        frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;opacity:0;pointer-events:none';
        document.body.appendChild(frame);
      }
      const doc = frame.contentDocument || frame.contentWindow.document;
      doc.open();
      doc.write(html);
      doc.close();
      setTimeout(() => {
        try {
          frame.contentWindow.focus();
          frame.contentWindow.print();
        } catch (err) {
          window.EMS.showToast('无法调起打印，请检查浏览器打印权限', 'error');
        }
      }, 300);
    } catch (e) {
      if (w) try { w.close(); } catch (_) {}
      window.EMS.showToast(e.message || '打印失败', 'error');
    }
  }

  async function reloadModelLines() {
    if (!selectedModelId) return;
    const payload = normalizeLinesPayload(await engApi(`/models/${selectedModelId}/lines`));
    renderBomLines(payload.lines, payload);
    updateDetailTitle(selectedModel, payload.lines, payload);
    return payload;
  }

  async function saveMountProfile() {
    if (!selectedModelId) return;
    const sel = document.getElementById('eng-mount-profile');
    try {
      await engApi(`/models/${selectedModelId}/mount-profile`, {
        method: 'PUT',
        body: JSON.stringify({ mount_profile_override: sel?.value || '' }),
      });
      if (selectedModel) {
        selectedModel.eng_review_status = 'pending_review';
        selectedModel.mount_profile_override = sel?.value || '';
      }
      updateReviewBar({ eng_review_status: 'pending_review' });
      const profileLabel = PROFILE_LABELS[sel?.value] || (sel?.value ? sel.value : '自动识别');
      window.EMS.showToast(
        sel?.value === 'dip_only'
          ? `贴装画像已设为「${profileLabel}」，纯插件免贴片坐标；请重新打开审核工作台后再通过`
          : `贴装画像已保存（${profileLabel}），请点「审核通过」更新资料`,
      );
      await reloadModelLines();
      // 审核弹窗若已打开，立即刷新齐套门禁
      const modal = document.getElementById('eng-kit-modal');
      if (modal && !modal.classList.contains('hidden')) {
        await loadReviewDossier(selectedModelId);
      }
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
      await reloadModelLines().catch(() => {});
    }
  }

  async function selectModel(model) {
    if (!model) return;
    selectedModelKey = modelRowKey(model);
    selectedModelId = model.id || model.bom_model_id || null;
    selectedModel = model;
    document.querySelectorAll('.eng-model-row').forEach(tr => tr.classList.toggle('selected', tr.dataset.key === selectedModelKey));
    const title = document.getElementById('eng-detail-title');
    const kitBar = document.getElementById('eng-kit-bar');
    const profileBar = document.getElementById('eng-mount-profile-bar');
    const tbody = document.getElementById('eng-lines-table');
    const filterCode = document.getElementById('eng-filter-code');
    if (filterCode) filterCode.value = model.internal_code;
    const status = resolveBomStatus(model);
    const orderPart = model.purchase_no ? ` · 订单 ${model.purchase_no}` : '';
    if (title) title.textContent = `${model.internal_code} · ${model.model_code}${orderPart} · ${model.model_name || ''}`;
    if (!selectedModelId || status === 'pending') {
      kitBar?.classList.add('hidden');
      profileBar?.classList.add('hidden');
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="11" class="empty">订单 ${escapeHtml(model.purchase_no || '')} 尚未确认 BOM，请点击页头「导入 BOM」上传本订单专用 Excel</td></tr>`;
      }
      clearMountReadinessPanel();
      await syncAssetsForSelectedModel();
      return;
    }
    kitBar?.classList.remove('hidden');
    if (tbody) tbody.innerHTML = '<tr><td colspan="11" class="empty">加载中…</td></tr>';
    try {
      const payload = normalizeLinesPayload(await engApi(`/models/${selectedModelId}/lines`));
      if (payload.eng_review_status) selectedModel.eng_review_status = payload.eng_review_status;
      updateDetailTitle(model, payload.lines, payload);
      renderBomLines(payload.lines, payload);
      await syncAssetsForSelectedModel();
      await loadMountReadiness({ silent: true });
    } catch (e) {
      profileBar?.classList.add('hidden');
      if (tbody) tbody.innerHTML = '<tr><td colspan="11" class="empty">明细加载失败</td></tr>';
      window.EMS.showToast('BOM 明细加载失败：' + e.message, 'error', 6000);
      clearMountReadinessPanel();
      await syncAssetsForSelectedModel();
    }
  }

  async function saveLine(lineId, data) {
    try {
      await engApi(`/lines/${lineId}`, { method: 'PUT', body: JSON.stringify(data) });
      window.EMS.showToast('BOM 行已保存');
      await reloadModelLines();
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  async function importBomManual() {
    const fileInput = document.getElementById('eng-bom-import-file');
    const pairInput = document.getElementById('eng-bom-import-file-pair');
    const importBtn = document.getElementById('btn-eng-import-manual');
    const statusEl = document.getElementById('eng-import-status');
    const setImportStatus = (msg) => { if (statusEl) statusEl.textContent = msg || ''; };
    const lockedIc = (
      getActiveInternalCode()
      || document.getElementById('eng-filter-code')?.value?.trim()
      || selectedModel?.internal_code
      || ''
    ).toUpperCase();
    let purchaseNo = (selectedModel?.purchase_no || '').trim();
    if (!purchaseNo) {
      const kw = document.getElementById('eng-search')?.value?.trim() || '';
      if (kw && /^\d{4}-/.test(kw)) purchaseNo = kw;
    }
    if (!purchaseNo) {
      window.EMS.showToast('请先在左侧点选一条在制订单（含订单号），再导入该订单 BOM', 'error');
      return;
    }
    const lockedPurchaseNo = purchaseNo;

    async function afterImportSuccess(data) {
      const tip = data.message && data.message !== 'ok'
        ? data.message
        : `已导入 ${data.model_code} / ${lockedPurchaseNo}，共 ${data.lines} 行 BOM`;
      window.EMS.showToast(tip, 'success', 5000);
      setImportStatus(tip);
      if (data.model_code) {
        const search = document.getElementById('eng-search');
        if (search) search.value = data.model_code;
      }
      await loadCoverage();
      const rows = await loadModels();
      const hit = rows.find(r =>
        (r.purchase_no || '') === lockedPurchaseNo
        && (Number(r.id) === Number(data.bom_model_id) || r.model_code === data.model_code)
      ) || rows.find(r => (r.purchase_no || '') === lockedPurchaseNo);
      if (hit) {
        await selectModel(hit);
        selectedModelKey = modelRowKey(hit);
      }
      document.querySelector(`.eng-model-row[data-key="${selectedModelKey}"]`)
        ?.scrollIntoView({ block: 'nearest' });
      await loadReviewInbox({ silent: true });
    }

    // 亿兰科：1 份（纯 DIP/纯 SMT）或 2 份（SMT+DIP，不分先后）
    if (lockedIc === 'A120') {
      if (!pairInput) {
        window.EMS.showToast('页面缺少文件选择框，请强制刷新（Ctrl+F5）后再试', 'error');
        return;
      }
      // 勿用 display:none；确保可程序化唤起文件框
      pairInput.classList.remove('hidden');
      pairInput.classList.add('visually-hidden');
      pairInput.multiple = true;
      if (pairInput._emsAbort) {
        try { pairInput._emsAbort.abort(); } catch (_) { /* ignore */ }
      }
      const ac = new AbortController();
      pairInput._emsAbort = ac;
      pairInput.value = '';
      const onPairChange = async () => {
        const files = Array.from(pairInput.files || []);
        if (!files.length) {
          const msg = '未选择文件';
          window.EMS.showToast(msg, 'error', 4000);
          setImportStatus(msg);
          return;
        }
        if (files.length > 2) {
          const msg = `选了 ${files.length} 个文件，最多两份（SMT+DIP）；纯插件只需 1 份`;
          window.EMS.showToast(msg, 'error', 5000);
          setImportStatus(msg);
          pairInput.value = '';
          return;
        }
        const names = files.map(f => f.name).join(' + ');
        const tip = files.length === 1
          ? `正在导入单份 BOM：${names}`
          : `正在合并导入：${names}`;
        setImportStatus(tip);
        window.EMS.showToast(tip, 'success', 4000);
        if (importBtn) importBtn.disabled = true;
        const form = new FormData();
        form.append('file_smt', files[0]);
        if (files[1]) form.append('file_dip', files[1]);
        form.append('internal_code', 'A120');
        form.append('purchase_no', lockedPurchaseNo);
        try {
          const res = await fetch(API + '/models/import-yilanke', {
            method: 'POST',
            headers: window.EMS.authHeaders(),
            body: form,
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) throw new Error(formatApiDetail(data.detail, res.statusText));
          if (data.status === 'failed') throw new Error(data.message || '导入失败');
          await afterImportSuccess(data);
        } catch (e) {
          const err = e.message || '导入失败';
          window.EMS.showToast(err, 'error', 8000);
          setImportStatus(err);
        } finally {
          pairInput.value = '';
          if (importBtn) importBtn.disabled = false;
        }
      };
      pairInput.addEventListener('change', onPairChange, { signal: ac.signal, once: true });
      setImportStatus('纯插件选 1 份 DIP；有贴片则 Command/Ctrl 多选 SMT+DIP 两份');
      window.EMS.showToast('纯插件选 1 份即可；SMT+DIP 请一次选两份（Command/Ctrl）', 'success', 6000);
      // 必须在用户点击的同步调用栈里 click，否则部分浏览器会拦截
      pairInput.click();
      return;
    }

    if (!fileInput) return;
    fileInput.value = '';
    const onSingleChange = async () => {
      fileInput.removeEventListener('change', onSingleChange);
      const file = fileInput.files?.[0];
      if (!file) return;
      const form = new FormData();
      form.append('file', file);
      form.append('internal_code', lockedIc || 'A123');
      form.append('purchase_no', lockedPurchaseNo);
      try {
        const res = await fetch(API + '/models/import', {
          method: 'POST',
          headers: window.EMS.authHeaders(),
          body: form,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(formatApiDetail(data.detail, res.statusText));
        if (data.status === 'failed') throw new Error(data.message || '导入失败');
        await afterImportSuccess(data);
      } catch (e) {
        window.EMS.showToast(e.message || '导入失败', 'error');
      } finally {
        fileInput.value = '';
      }
    };
    fileInput.addEventListener('change', onSingleChange);
    fileInput.click();
  }

  async function exportBom() {
    if (!selectedModelId) {
      window.EMS.showToast('请先选择左侧机型', 'error');
      return;
    }
    try {
      const res = await fetch(`${API}/models/${selectedModelId}/export`, {
        headers: window.EMS.authHeaders(),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(formatApiDetail(data.detail, res.statusText));
      }
      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition') || '';
      const utfMatch = cd.match(/filename\*=UTF-8''([^;]+)/i);
      const asciiMatch = cd.match(/filename=\"([^\"]+)\"/i);
      const filename = utfMatch
        ? decodeURIComponent(utfMatch[1])
        : (asciiMatch ? asciiMatch[1] : 'bom.xlsx');
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      window.EMS.showToast('BOM 已导出');
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  async function clearBom() {
    if (!selectedModelId) {
      window.EMS.showToast('请先选择已确认 BOM 的订单', 'error');
      return;
    }
    const code = selectedModel?.model_code || String(selectedModelId);
    const pn = selectedModel?.purchase_no || '';
    const label = pn ? `${code} / ${pn}` : code;
    if (!confirm(`确定清除订单「${label}」的 BOM？\n清除后可重新导入本订单正确文件。`)) return;
    try {
      const res = await engApi(`/models/${selectedModelId}`, { method: 'DELETE' });
      window.EMS.showToast(res.message || '已清除 BOM', 'success');
      const keepPn = pn;
      const keepCode = code;
      selectedModelId = null;
      selectedModel = null;
      selectedModelKey = null;
      document.getElementById('eng-kit-bar')?.classList.add('hidden');
      document.getElementById('eng-mount-profile-bar')?.classList.add('hidden');
      await loadCoverage();
      const rows = await loadModels();
      const hit = rows.find((r) => (r.purchase_no || '') === keepPn && r.model_code === keepCode)
        || rows.find((r) => (r.purchase_no || '') === keepPn);
      if (hit) {
        await selectModel(hit);
      } else {
        const title = document.getElementById('eng-detail-title');
        const tbody = document.getElementById('eng-lines-table');
        if (title) title.textContent = '选择左侧订单查看 BOM 明细';
        if (tbody) tbody.innerHTML = '<tr><td colspan="10" class="empty">—</td></tr>';
      }
    } catch (e) {
      window.EMS.showToast(e.message || '清除失败', 'error');
    }
  }

  async function deleteOrder() {
    if (!selectedModel?.purchase_no) {
      window.EMS.showToast('请先在左侧选择要删除的订单', 'error');
      return;
    }
    const code = selectedModel.model_code || '';
    const pn = (selectedModel.purchase_no || '').trim();
    const label = code ? `${code} / ${pn}` : pn;
    if (!confirm(
      `确定从工程资料删除订单「${label}」？\n\n将清除本订单 BOM、待审推送与订单级坐标/Gerber/位号图，并从左侧列表移除。\n不会删除 SRM 在制订单数据。`,
    )) return;
    const password = prompt('请输入删除订单操作密码');
    if (password == null) return;
    if (!String(password).trim()) {
      window.EMS.showToast('请输入操作密码', 'error');
      return;
    }
    try {
      const res = await engApi('/orders/delete', {
        method: 'POST',
        body: JSON.stringify({
          password: String(password).trim(),
          internal_code: selectedModel.internal_code || getActiveInternalCode() || '',
          purchase_no: pn,
          model_code: code,
          bom_model_id: selectedModelId || selectedModel.bom_model_id || null,
        }),
      });
      window.EMS.showToast(res.message || '已删除订单', 'success');
      selectedModelId = null;
      selectedModel = null;
      selectedModelKey = null;
      document.getElementById('eng-kit-bar')?.classList.add('hidden');
      document.getElementById('eng-mount-profile-bar')?.classList.add('hidden');
      const title = document.getElementById('eng-detail-title');
      const tbody = document.getElementById('eng-lines-table');
      if (title) title.textContent = '选择左侧订单查看工程资料';
      if (tbody) tbody.innerHTML = '<tr><td colspan="11" class="empty">—</td></tr>';
      clearMountReadinessPanel();
      await loadCoverage();
      await loadModels();
    } catch (e) {
      window.EMS.showToast(e.message || '删除失败', 'error');
    }
  }

  async function autoBind() {
    try {
      const res = await engApi('/orders/auto-bind', { method: 'POST' });
      window.EMS.showToast(res.message || '完成');
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  function formatQty(n) {
    const v = Number(n ?? 0);
    if (!Number.isFinite(v)) return '0';
    return v % 1 === 0 ? v.toLocaleString('zh-CN') : v.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
  }

  function renderSubstitutes(line) {
    const subs = line.substitutes || [];
    if (!subs.length) {
      const codes = line.substitute_codes || [];
      return codes.length ? codes.map(c => `<div class="eng-kit-sub-row"><span class="eng-kit-sub-code">${c}</span></div>`).join('') : '—';
    }
    return subs.map(s => `
      <div class="eng-kit-sub-row">
        <span class="eng-kit-sub-code">${s.material_code}</span>
        <span class="eng-kit-sub-qty">库存 <strong>${formatQty(s.stock_qty != null ? s.stock_qty : s.available_qty)}</strong></span>
      </div>`).join('');
  }

  function mountTypeBadge(type) {
    if (type === 'SMT') return '<span class="mount-badge mount-smt">SMT</span>';
    if (type === 'DIP') return '<span class="mount-badge mount-dip">DIP</span>';
    if (type === 'ASSY') return '<span class="mount-badge mount-assy">装配</span>';
    if (type === 'N/A') return '<span class="mount-badge mount-na">N/A</span>';
    return '<span class="muted">—</span>';
  }

  function mountSideBadge(side) {
    if (!side) return '<span class="muted">—</span>';
    if (side === 'TOP') return '<span class="mount-badge mount-top">TOP</span>';
    if (side === 'BOT') return '<span class="mount-badge mount-bot">BOT</span>';
    if (side === 'TOP+BOT') return '<span class="mount-badge mount-mix">TOP+BOT</span>';
    return side;
  }

  function mountSourceHint(source) {
    if (source === 'placement') return '坐标判定';
    if (source === 'rule') return '规则推断';
    if (source === 'master') return '物料主数据';
    return '';
  }

  function canEditMount() {
    return !isImportOnly();
  }

  function mountTypeSelect(line) {
    if (!canEditMount()) return mountTypeBadge(line.mount_type);
    const cur = (line.mount_type || '').toUpperCase();
    const opts = [
      { value: '', label: '—' },
      { value: 'SMT', label: 'SMT' },
      { value: 'DIP', label: 'DIP' },
      { value: 'ASSY', label: '装配' },
      { value: 'N/A', label: 'N/A' },
    ].map((o) => `<option value="${o.value}"${o.value === cur ? ' selected' : ''}>${o.label}</option>`).join('');
    const code = encodeURIComponent(line.material_code || '');
    const name = encodeURIComponent(line.material_name || '');
    return `<select class="sched-inline eng-mount-type-sel" data-code="${code}" data-name="${name}" data-side="${escapeHtml(line.mount_side || '')}" title="修正贴装类型">${opts}</select>`;
  }

  function mountSideSelect(line) {
    if (!canEditMount()) return mountSideBadge(line.mount_side);
    const cur = (line.mount_side || '').toUpperCase();
    const mt = (line.mount_type || '').toUpperCase();
    const disabled = mt === 'ASSY' || mt === 'N/A' || !mt;
    const opts = [
      { value: '', label: '—' },
      { value: 'TOP', label: 'T面' },
      { value: 'BOT', label: 'B面' },
      { value: 'TOP+BOT', label: '双面' },
    ].map((o) => `<option value="${o.value}"${o.value === cur ? ' selected' : ''}>${o.label}</option>`).join('');
    const code = encodeURIComponent(line.material_code || '');
    const name = encodeURIComponent(line.material_name || '');
    return `<select class="sched-inline eng-mount-side-sel" data-code="${code}" data-name="${name}" data-type="${escapeHtml(mt)}" ${disabled ? 'disabled' : ''} title="修正面别 T/B">${opts}</select>`;
  }

  function mountConfirmButtons(line) {
    return '';
  }

  async function confirmMountType(materialCode, mountType, materialName, mountSide) {
    try {
      const body = {
        material_code: materialCode,
        mount_type: mountType,
        material_name: materialName || null,
      };
      if (mountSide != null) body.mount_side = mountSide;
      if (selectedModelId) body.bom_model_id = selectedModelId;
      await engApi('/mount-profiles', {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      // 修正后需重新点「审核通过」定稿
      if (selectedModel) selectedModel.eng_review_status = 'pending_review';
      updateReviewBar({ eng_review_status: 'pending_review' });
      const typeLabel = mountType === 'ASSY' ? '装配' : mountType;
      const sideLabel = mountSide === 'TOP' ? 'T面' : mountSide === 'BOT' ? 'B面' : mountSide === 'TOP+BOT' ? '双面' : '';
      window.EMS.showToast(
        sideLabel
          ? `已修正 ${materialCode} = ${typeLabel} / ${sideLabel}，请点「审核通过」更新资料`
          : `已修正 ${materialCode} = ${typeLabel}，请点「审核通过」更新资料`,
      );
      const kitOpen = !document.getElementById('eng-kit-modal')?.classList.contains('hidden');
      if (kitOpen) await showKitting();
      else await reloadModelLines();
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  function bindMountEditors(root) {
    const scope = root || document;
    scope.querySelectorAll('.eng-mount-type-sel').forEach((sel) => {
      sel.addEventListener('change', () => {
        const code = decodeURIComponent(sel.dataset.code || '');
        const name = decodeURIComponent(sel.dataset.name || '');
        const type = sel.value || '';
        if (!code || !type) {
          window.EMS.showToast('请选择贴装类型', 'error');
          return;
        }
        let side = sel.dataset.side || '';
        if (type === 'ASSY' || type === 'N/A') side = '';
        confirmMountType(code, type, name, side);
      });
    });
    scope.querySelectorAll('.eng-mount-side-sel').forEach((sel) => {
      sel.addEventListener('change', () => {
        const code = decodeURIComponent(sel.dataset.code || '');
        const name = decodeURIComponent(sel.dataset.name || '');
        const type = (sel.dataset.type || '').toUpperCase();
        const side = sel.value || '';
        if (!code) return;
        if (!type || type === 'ASSY' || type === 'N/A') {
          window.EMS.showToast('请先设定贴装类型（SMT/DIP）再改面别', 'error');
          return;
        }
        confirmMountType(code, type, name, side);
      });
    });
  }

  function kitLineNeedsAttention(line) {
    const type = (line.mount_type || '').trim().toUpperCase();
    if (!type) return true;
    if ((type === 'SMT' || type === 'DIP') && !(line.mount_side || '').trim()) return true;
    return false;
  }

  function kitLineMissingType(line) {
    return !(line.mount_type || '').trim();
  }

  function renderKitLinesTable(lines) {
    const tbody = document.getElementById('eng-kit-lines');
    if (!tbody) return;
    let filtered = lines;
    if (kitMountFilter === 'no-type') {
      filtered = lines.filter(kitLineMissingType);
    } else if (kitMountFilter === 'unresolved') {
      filtered = lines.filter(kitLineNeedsAttention);
    }
    if (!filtered.length) {
      const emptyMsg =
        kitMountFilter === 'no-type'
          ? '没有缺贴装类型的行'
          : kitMountFilter === 'unresolved'
            ? '没有待确认贴装行'
            : '无明细';
      tbody.innerHTML = `<tr><td colspan="13" class="empty">${emptyMsg}</td></tr>`;
      return;
    }
    tbody.innerHTML = filtered.map((l) => {
      const stockQty = l.stock_qty != null ? Number(l.stock_qty) : Number(l.own_stock_qty ?? 0);
      const stockClass = stockQty < 0 ? 'qty-negative' : '';
      const stockCell = `<strong class="${stockClass}">${formatQty(stockQty)}</strong>`;
      const rowCls = kitLineNeedsAttention(l) ? ' eng-kit-row-warn' : '';
      return `
        <tr class="${rowCls.trim()}" title="${mountSourceHint(l.mount_source)}">
          <td>${l.material_code}</td>
          <td>${l.material_name || '—'}</td>
          <td class="cell-muted eng-kit-spec">${escapeHtml(l.spec || '—')}</td>
          <td>${mountTypeSelect(l)}</td>
          <td>${mountSideSelect(l)}</td>
          <td>${mountReasonCell(l)}</td>
          <td>${l.qty_per ?? '—'}</td>
          <td class="eng-kit-pos">${l.position || '—'}</td>
          <td class="eng-kit-stock-col">${l.required_qty}</td>
          <td class="eng-kit-stock-col">${stockCell}</td>
          <td class="eng-kit-stock-col">${l.shortage_qty}</td>
          <td class="eng-kit-stock-col"><span class="${kitClass(l.status)}">${kitLabel(l.status)}</span></td>
          <td class="eng-kit-sub eng-kit-stock-col">${renderSubstitutes(l)}</td>
        </tr>`;
    }).join('');
    bindMountEditors(document.getElementById('eng-kit-modal'));
  }

  async function showKitting() {
    if (!selectedModelId && !selectedModel?.line_key) return;
    const qty = Number(selectedModel?.order_qty || 1);
    try {
      let kit;
      if (selectedModel?.line_key) {
        kit = await engApi(`/orders/${encodeURIComponent(selectedModel.line_key)}/kitting`);
      } else {
        kit = await engApi(`/kitting?bom_model_id=${selectedModelId}&order_qty=${qty}`);
      }
      const badge = document.getElementById('eng-kit-badge');
      if (badge) {
        badge.classList.add('hidden'); // 工程审核不算库存齐套
      }
      const dossier = await loadReviewDossier(selectedModelId || kit.bom_model_id);
      lastReviewDossier = dossier;
      lastKitLines = kit.lines || [];
      const unresolved = lastKitLines.filter(kitLineNeedsAttention).length;
      const missingType = lastKitLines.filter(kitLineMissingType).length;
      // 缺类型优先（卡住审核通过）；否则看待确认；都没有则看全部
      kitMountFilter = missingType > 0 ? 'no-type' : unresolved > 0 ? 'unresolved' : 'all';
      const orderLabel = selectedModel?.purchase_no ? `订单 ${selectedModel.purchase_no} · ` : '';
      const summaryEl = document.getElementById('eng-kit-summary');
      if (summaryEl) {
        const stats = dossier?.mount_stats;
        let text =
          `${orderLabel}${kit.model_code || selectedModel?.model_code || ''} × ${kit.order_qty}` +
          ` · 缺类型 ${missingType} · 待确认 ${unresolved}（本页不核算库存齐套）`;
        if (effectiveReviewStatus(selectedModel, dossier) === 'pending_review') {
          text += ' · 请先核对上方齐套检查，再点「审核通过」或「退回修正」';
        }
        summaryEl.textContent = text;
      }
      const filterHint = document.getElementById('eng-kit-filter-count');
      if (filterHint) {
        filterHint.textContent = missingType
          ? `缺类型 ${missingType} · 待确认 ${unresolved}`
          : unresolved
            ? `待确认 ${unresolved}`
            : '全部已识别';
      }
      document.querySelectorAll('[data-kit-filter]').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.kitFilter === kitMountFilter);
      });
      renderKitLinesTable(lastKitLines);
      lastKitExport = selectedModel?.line_key
        ? { line_key: selectedModel.line_key }
        : { bom_model_id: selectedModelId, order_qty: qty };
      const kitModal = document.getElementById('eng-kit-modal');
      kitModal?.classList.remove('hidden');
      document.body.classList.toggle('eng-hide-stock', isImportOnly() || isAuditOnly());
      syncKitApproveButton(
        effectiveReviewStatus(selectedModel, dossier),
        canEngAudit(),
      );
      applyApproveGate(dossier);
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  let reviewTodoItems = [];
  let reviewTodoMeta = { title: '待处理事项', hint: '', todo_kind: '' };
  let lastReviewTodoCount = -1;
  let reviewTodoTimer = null;

  function canReceiveTodoPush() {
    const u = window.EMS.getCurrentUser() || {};
    const role = u.role || '';
    const name = engUsername();
    // 黄星待审；邱梦林待导入/退回；WGQ/其它管理员待审
    return (
      isEngImportOnly()
      || isEngAuditOnly()
      || role === 'admin'
      || role === 'engineering'
      || name === 'wgq'
      || name === 'dxsmt001'
      || name === 'dxgc'
    );
  }

  function formatReviewTodoTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).replace('T', ' ').slice(0, 16);
    const p = (n) => String(n).padStart(2, '0');
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  function todoActionLabel(item) {
    const kind = (item && item.todo_type) || reviewTodoMeta.todo_kind;
    if (kind === 'import') return '去导入';
    if (kind === 'rejected') return '去修正';
    return '去处理';
  }

  function todoTypeBadge(item) {
    const kind = (item && item.todo_type) || reviewTodoMeta.todo_kind || 'review';
    const map = {
      review: { label: '待审核', cls: 'eng-todo-type-review' },
      import: { label: '待导入', cls: 'eng-todo-type-import' },
      rejected: { label: '已退回', cls: 'eng-todo-type-rejected' },
    };
    const m = map[kind] || map.review;
    return `<span class="eng-todo-type ${m.cls}">${m.label}</span>`;
  }

  function renderReviewTodoList(targetId) {
    const tbody = document.getElementById(targetId);
    if (!tbody) return;
    if (!reviewTodoItems.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty">暂无待处理事项</td></tr>';
      return;
    }
    tbody.innerHTML = reviewTodoItems.map((item, idx) => {
      const kind = item.todo_type || reviewTodoMeta.todo_kind;
      const modelLabel = item.model_name
        ? `<strong>${escapeHtml(item.model_code || '—')}</strong><div class="muted" style="font-size:12px;font-weight:400">${escapeHtml(item.model_name)}</div>`
        : `<strong>${escapeHtml(item.model_code || '—')}</strong>`;
      const who = kind === 'import'
        ? (item.summary || '待导入 BOM')
        : (item.submitter || '—');
      const summaryCls = kind === 'rejected' ? 'eng-todo-summary eng-todo-summary-reject' : 'eng-todo-summary';
      const rowCls = kind === 'rejected' ? 'eng-todo-row-rejected' : '';
      return `
      <tr class="${rowCls}">
        <td>${todoTypeBadge(item)}</td>
        <td>${escapeHtml(item.internal_code || '—')}</td>
        <td>${modelLabel}</td>
        <td>${escapeHtml(item.purchase_no || '—')}</td>
        <td>${escapeHtml(who)}</td>
        <td title="${escapeHtml(item.summary || '')}" class="${summaryCls}">${escapeHtml(item.summary || reviewTodoMeta.title || '待处理')}</td>
        <td>${formatReviewTodoTime(item.submitted_at || item.updated_at)}</td>
        <td><button type="button" class="btn btn-primary btn-sm eng-todo-open" data-idx="${idx}">${todoActionLabel(item)}</button></td>
      </tr>`;
    }).join('');
    tbody.querySelectorAll('.eng-todo-open').forEach((btn) => {
      btn.addEventListener('click', () => {
        const item = reviewTodoItems[Number(btn.dataset.idx)];
        if (item) openReviewTodoItem(item);
      });
    });
  }

  function renderReviewTodoPanel() {
    const panel = document.getElementById('eng-todo-panel');
    const list = document.getElementById('eng-todo-list');
    const banner = document.getElementById('eng-review-banner');
    const badge = document.getElementById('eng-todo-badge');
    const headHint = panel?.querySelector('.eng-todo-head .muted');
    const headTitle = panel?.querySelector('.eng-todo-head strong');
    if (!canReceiveTodoPush()) {
      panel?.classList.add('hidden');
      banner?.classList.add('hidden');
      return;
    }
    banner?.classList.remove('hidden');
    if (badge) badge.textContent = String(reviewTodoItems.length);
    if (headTitle) headTitle.textContent = reviewTodoMeta.title || '待处理事项';
    if (headHint) headHint.textContent = ` · ${reviewTodoMeta.hint || '按你的帐号推送，无需自己查找'}`;
    if (banner) {
      const label = reviewTodoMeta.title || '待处理事项';
      const n = reviewTodoItems.length;
      const urgent = n > 0 ? ' eng-review-banner-urgent' : '';
      banner.className = `eng-review-banner${urgent}`;
      banner.innerHTML = `${escapeHtml(label)} <span id="eng-todo-badge" class="eng-todo-badge${n > 0 ? ' eng-todo-badge-pulse' : ''}">${n}</span>`;
    }
    if (!reviewTodoItems.length) {
      panel?.classList.add('hidden');
      if (list) list.innerHTML = '';
      return;
    }
    panel?.classList.remove('hidden');
    if (list) {
      list.innerHTML = reviewTodoItems.map((item, idx) => {
        const kind = item.todo_type || reviewTodoMeta.todo_kind;
        const rejectCls = kind === 'rejected' ? ' eng-todo-item-rejected' : '';
        return `
        <div class="eng-todo-item${rejectCls}">
          <div class="eng-todo-item-main">
            <div class="eng-todo-item-title">${todoTypeBadge(item)} ${escapeHtml(item.internal_code || '')} · ${escapeHtml(item.model_code || '')} · 订单 ${escapeHtml(item.purchase_no || '—')}</div>
          </div>
          <button type="button" class="btn btn-primary btn-sm eng-todo-open" data-idx="${idx}">${todoActionLabel(item)}</button>
        </div>`;
      }).join('');
      list.querySelectorAll('.eng-todo-open').forEach((btn) => {
        btn.addEventListener('click', () => {
          const item = reviewTodoItems[Number(btn.dataset.idx)];
          if (item) openReviewTodoItem(item);
        });
      });
    }
  }

  async function openReviewTodoItem(item) {
    document.getElementById('eng-review-inbox-modal')?.classList.add('hidden');
    const itemCode = (item.internal_code || '').trim().toUpperCase();
    if (itemCode && itemCode !== getActiveInternalCode()) {
      const hitCust = resolveCustomerFromList(itemCode);
      if (hitCust) await enterCustomerWorkspace(hitCust, { silent: true });
    }
    const kind = item.todo_type || reviewTodoMeta.todo_kind;
    if (kind === 'rejected' && item.inbox_id) {
      try {
        await engApi(`/todos/${item.inbox_id}/ack`, { method: 'POST' });
      } catch (_) { /* 忽略确认失败，仍定位订单 */ }
    }
    const search = document.getElementById('eng-search');
    if (search) search.value = item.purchase_no || item.model_code || '';
    const filterCode = document.getElementById('eng-filter-code');
    if (filterCode && item.internal_code) filterCode.value = item.internal_code;
    const rows = await loadModels();
    const bomId = item.bom_model_id != null ? Number(item.bom_model_id) : null;
    const hit = rows.find((r) => bomId && Number(r.id || r.bom_model_id) === bomId)
      || rows.find((r) => item.purchase_no && r.purchase_no === item.purchase_no)
      || rows.find((r) => item.line_key && r.line_key === item.line_key)
      || rows.find((r) => item.model_code && r.model_code === item.model_code && r.internal_code === item.internal_code);
    if (!hit) {
      window.EMS.showToast('未在左侧列表找到该订单，请确认是否仍在制', 'error');
      return;
    }
    await selectModel(hit);
    if (kind === 'import') {
      const importBtn = document.getElementById('btn-eng-import-manual');
      importBtn?.classList.add('eng-import-pulse');
      importBtn?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setTimeout(() => importBtn?.classList.remove('eng-import-pulse'), 4000);
      window.EMS.showToast('已定位该订单，请点击高亮的「导入 BOM」上传资料', 'warning', 5000);
      return;
    }
    if (kind === 'rejected') {
      window.EMS.showToast(item.summary || '资料已退回，请按工作台齐套检查修正后重新送审', 'error', 10000);
      await loadReviewInbox({ silent: true });
      await showKitting();
      return;
    }
    await showKitting();
  }

  async function loadReviewInbox({ silent } = {}) {
    if (!canReceiveTodoPush()) {
      document.getElementById('eng-todo-panel')?.classList.add('hidden');
      document.getElementById('eng-review-banner')?.classList.add('hidden');
      return;
    }
    try {
      const ic = getActiveInternalCode();
      const qs = ic ? `?internal_code=${encodeURIComponent(ic)}` : '';
      const data = await engApi(`/todos${qs}`);
      reviewTodoItems = Array.isArray(data?.items) ? data.items : [];
      reviewTodoMeta = {
        title: data?.title || '待处理事项',
        hint: data?.hint || '',
        todo_kind: data?.todo_kind || '',
      };
      const n = reviewTodoItems.length;
      if (!silent && lastReviewTodoCount >= 0 && n > lastReviewTodoCount) {
        const added = n - lastReviewTodoCount;
        const tip = reviewTodoMeta.todo_kind === 'import'
          ? '待导入'
          : (reviewTodoMeta.todo_kind === 'rejected' ? '审核退回' : '待处理');
        window.EMS.showToast(`收到 ${added} 条新的${tip}事项`, 'warning', 6000);
      }
      lastReviewTodoCount = n;
      renderReviewTodoPanel();
      renderReviewTodoList('eng-review-inbox-table');
      const modalTitle = document.querySelector('#eng-review-inbox-modal h2');
      const modalHint = document.querySelector('#eng-review-inbox-modal .muted');
      if (modalTitle) modalTitle.textContent = reviewTodoMeta.title || '待处理事项';
      if (modalHint) {
        modalHint.textContent = reviewTodoMeta.hint
          || '系统按账号推送；点「去处理」打开审核工作台，查看订单档案、资料齐套与贴装明细。';
      }
    } catch (_) {
      if (!silent) {
        document.getElementById('eng-todo-panel')?.classList.add('hidden');
      }
    }
  }

  function openReviewTodoModal() {
    const modal = document.getElementById('eng-review-inbox-modal');
    modal?.classList.remove('hidden');
    // 审核员等角色首次点开时确保已拉取待办（避免 Vue 顶栏跳转时列表仍空）
    void loadReviewInbox({ silent: true }).then(() => {
      renderReviewTodoList('eng-review-inbox-table');
    });
  }

  const ENG_TODO_AUTO_SESSION_KEY = 'eng_todo_auto_opened_v1';

  /** 登录后本会话首次有待办时自动弹出（不依赖外部推送） */
  function maybeAutoOpenTodoOnSession() {
    if (!canReceiveTodoPush()) return;
    if (sessionStorage.getItem(ENG_TODO_AUTO_SESSION_KEY) === '1') return;
    void loadReviewInbox({ silent: true }).then(() => {
      if (!reviewTodoItems.length) return;
      sessionStorage.setItem(ENG_TODO_AUTO_SESSION_KEY, '1');
      openReviewTodoModal();
    });
  }

  function startReviewTodoPolling() {
    if (!canReceiveTodoPush()) return;
    if (reviewTodoTimer) clearInterval(reviewTodoTimer);
    loadReviewInbox({ silent: true });
    reviewTodoTimer = setInterval(() => loadReviewInbox({ silent: false }), 30000);
  }

  async function exportKitting() {
    if (!lastKitExport?.bom_model_id && !lastKitExport?.line_key) {
      window.EMS.showToast('请先打开 BOM 资料审核', 'error');
      return;
    }
    try {
      const urlPath = lastKitExport.line_key
        ? `${API}/orders/${encodeURIComponent(lastKitExport.line_key)}/kitting/export`
        : `${API}/kitting/export?${new URLSearchParams({
            bom_model_id: String(lastKitExport.bom_model_id),
            order_qty: String(lastKitExport.order_qty),
          }).toString()}`;
      const res = await fetch(urlPath, {
        headers: window.EMS.authHeaders(),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || '导出失败');
      }
      const disposition = res.headers.get('Content-Disposition') || '';
      const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
      const asciiMatch = disposition.match(/filename="([^"]+)"/);
      const filename = utf8Match
        ? decodeURIComponent(utf8Match[1])
        : (asciiMatch ? asciiMatch[1] : 'kitting.xlsx');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      window.EMS.showToast('齐套明细已导出');
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  async function importGerberZip() {
    const ic = selectedModel?.internal_code
      || document.getElementById('eng-place-import-ic')?.value?.trim()
      || document.getElementById('eng-gerber-import-ic')?.value?.trim();
    const modelCode = selectedModel?.model_code
      || document.getElementById('eng-place-import-model')?.value?.trim()
      || document.getElementById('eng-gerber-import-model')?.value?.trim();
    const fileInput = document.getElementById('eng-gerber-import-file');
    if (!ic || !modelCode) {
      window.EMS.showToast('请先在左侧选择订单', 'error');
      return;
    }
    if (!fileInput) return;
    fileInput.value = '';
    fileInput.onchange = async () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      const form = new FormData();
      form.append('file', file);
      form.append('internal_code', ic);
      form.append('model_code', modelCode);
      appendBomScopeToForm(form);
      try {
        const res = await fetch(API + '/gerbers/import', {
          method: 'POST',
          headers: window.EMS.authHeaders(),
          body: form,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(formatApiDetail(data.detail, res.statusText));
        if (data.status === 'failed') throw new Error(data.message || data.audit_message || 'Gerber 审核未通过');
        const toastType = data.audit_status === 'warning' ? 'warning' : 'success';
        window.EMS.showToast(data.message || `已导入 ${data.file_count} 个文件`, toastType);
        await syncAssetsForSelectedModel();
      } catch (e) {
        window.EMS.showToast(e.message, 'error');
      } finally {
        fileInput.value = '';
      }
    };
    fileInput.click();
  }

  const ENG_TAB_ALIASES = {
    bom: 'bom',
    docs: 'bom',
    substitution: 'substitution',
    process: 'process',
    'customer-assets': 'bom',
    files: 'bom',
  };

  function applyEngTabFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const raw = params.get('tab') || '';
    const tab = ENG_TAB_ALIASES[raw];
    if (tab) switchEngTab(tab);
    // 审核员点顶栏「待审核资料」或登录带 todo=1：强制打开待办
    if (params.get('todo') === '1' && canReceiveTodoPush()) {
      sessionStorage.setItem(ENG_TODO_AUTO_SESSION_KEY, '1');
      openReviewTodoModal();
    } else {
      maybeAutoOpenTodoOnSession();
    }
  }

  async function load() {
    try {
      applyEngImportOnlyUI();
      await loadConfig();
      const params = new URLSearchParams(window.location.search);
      const urlCustomer = (params.get('customer') || params.get('internal_code') || '').trim().toUpperCase();
      const stored = readStoredCustomer();
      let target = null;
      if (urlCustomer) target = resolveCustomerFromList(urlCustomer);
      if (!target && stored?.internal_code) target = resolveCustomerFromList(stored.internal_code);
      const intendedTab = ENG_TAB_ALIASES[params.get('tab') || ''] || 'bom';
      if (intendedTab === 'substitution' || intendedTab === 'process') {
        // 替代料/工序对照直达：只绑定客户上下文，不进 BOM 选客户页
        if (target) {
          activeEngCustomer = target;
          writeStoredCustomer(target);
          fillCustomerSelects(target.internal_code);
        } else if (engCustomers[0]) {
          activeEngCustomer = engCustomers[0];
          fillCustomerSelects(engCustomers[0].internal_code);
        }
      } else if (target) {
        await enterCustomerWorkspace(target, { silent: true });
      } else {
        showCustomerPicker();
        const counts = await loadCustomerTodoCounts();
        renderCustomerCards(counts);
      }
    } catch (e) {
      window.EMS.showToast('工程模块加载失败：' + e.message + '（若提示 Not Found，请重启 backend/start.sh）', 'error', 8000);
    } finally {
      applyEngTabFromUrl();
    }
  }

  function bindEvents() {
    document.querySelectorAll('[data-eng-tab]').forEach(btn => {
      btn.addEventListener('click', () => switchEngTab(btn.dataset.engTab));
    });
    document.getElementById('btn-eng-switch-customer')?.addEventListener('click', leaveCustomerWorkspace);
    document.getElementById('btn-eng-import-manual')?.addEventListener('click', importBomManual);
    document.getElementById('btn-eng-bom-export')?.addEventListener('click', exportBom);
    document.getElementById('btn-eng-bom-delete')?.addEventListener('click', clearBom);
    document.getElementById('btn-eng-order-delete')?.addEventListener('click', deleteOrder);
    document.getElementById('btn-eng-auto-bind')?.addEventListener('click', autoBind);
    document.getElementById('btn-eng-search')?.addEventListener('click', loadModels);
    document.getElementById('eng-search')?.addEventListener('keydown', e => { if (e.key === 'Enter') loadModels(); });
    document.getElementById('eng-filter-code')?.addEventListener('change', loadModels);
    document.getElementById('eng-review-banner')?.addEventListener('click', openReviewTodoModal);
    document.getElementById('btn-eng-todo-refresh')?.addEventListener('click', () => loadReviewInbox({ silent: true }));
    document.getElementById('btn-eng-review-inbox-close')?.addEventListener('click', () => {
      document.getElementById('eng-review-inbox-modal')?.classList.add('hidden');
    });
    document.getElementById('btn-eng-kitting')?.addEventListener('click', showKitting);
    document.getElementById('btn-eng-print-issue')?.addEventListener('click', printIssueSlip);
    document.getElementById('btn-eng-issue-print-ok')?.addEventListener('click', doPrintIssueSlip);
    document.getElementById('btn-eng-issue-print-cancel')?.addEventListener('click', () => {
      document.getElementById('eng-issue-print-modal')?.classList.add('hidden');
    });
    document.getElementById('btn-eng-kit-export')?.addEventListener('click', exportKitting);
    document.getElementById('btn-eng-kit-close')?.addEventListener('click', () => {
      document.getElementById('eng-kit-modal')?.classList.add('hidden');
      renderReviewDossier(null);
    });
    document.getElementById('btn-eng-kit-approve')?.addEventListener('click', async () => {
      try {
        await approveEngReview();
      } catch (e) {
        window.EMS.showToast(e.message, 'error');
      }
    });
    document.getElementById('btn-eng-review-approve')?.addEventListener('click', async () => {
      try {
        await approveEngReview();
      } catch (e) {
        window.EMS.showToast(e.message, 'error');
      }
    });
    document.getElementById('btn-eng-kit-reject')?.addEventListener('click', () => openRejectModal());
    document.getElementById('btn-eng-review-reject')?.addEventListener('click', async () => {
      const kitOpen = !document.getElementById('eng-kit-modal')?.classList.contains('hidden');
      if (!kitOpen) await showKitting();
      openRejectModal();
    });
    document.getElementById('btn-eng-reject-cancel')?.addEventListener('click', () => {
      document.getElementById('eng-reject-modal')?.classList.add('hidden');
    });
    document.getElementById('btn-eng-reject-ok')?.addEventListener('click', async () => {
      try {
        await submitRejectModal();
      } catch (e) {
        window.EMS.showToast(e.message, 'error');
      }
    });
    document.querySelectorAll('[data-kit-filter]').forEach((btn) => {
      btn.addEventListener('click', () => {
        kitMountFilter = btn.dataset.kitFilter || 'all';
        document.querySelectorAll('[data-kit-filter]').forEach((b) => {
          b.classList.toggle('active', b.dataset.kitFilter === kitMountFilter);
        });
        renderKitLinesTable(lastKitLines);
      });
    });
    document.getElementById('btn-eng-sub-search')?.addEventListener('click', () => loadSubstitutions(1));
    document.getElementById('eng-sub-search')?.addEventListener('keydown', e => { if (e.key === 'Enter') loadSubstitutions(1); });
    document.getElementById('btn-eng-sub-prev')?.addEventListener('click', () => { if (subPage > 1) loadSubstitutions(subPage - 1); });
    document.getElementById('btn-eng-sub-next')?.addEventListener('click', () => loadSubstitutions(subPage + 1));
    document.getElementById('eng-sub-customer')?.addEventListener('change', () => {
      subPage = 1;
      loadSubstitutionMeta().then(() => loadSubstitutions(1));
    });
    document.getElementById('btn-eng-sub-tpl')?.addEventListener('click', downloadSubTemplate);
    document.getElementById('btn-eng-sub-xlsx')?.addEventListener('click', () => document.getElementById('eng-sub-xlsx-input')?.click());
    document.getElementById('btn-eng-sub-add')?.addEventListener('click', addSubstitutionManual);
    document.getElementById('eng-sub-xlsx-input')?.addEventListener('change', async (e) => {
      const file = e.target.files?.[0] || null;
      e.target.value = '';
      if (!file) return;
      try { await parseSubXlsx(file); } catch (err) { window.EMS.showToast(err.message, 'error'); }
    });
    document.getElementById('btn-eng-sub-import-close')?.addEventListener('click', closeSubImportModal);
    document.getElementById('btn-eng-sub-import-confirm')?.addEventListener('click', confirmSubImport);
    document.getElementById('btn-eng-proc-search')?.addEventListener('click', loadProcModels);
    document.getElementById('eng-proc-search')?.addEventListener('keydown', e => { if (e.key === 'Enter') loadProcModels(); });
    // eng-proc-filter-code 的 change 由 bindProcFilterCustomer 统一处理（避免先按旧客户回写下拉）
    document.getElementById('btn-eng-proc-sync')?.addEventListener('click', syncProcessRoutes);
    document.getElementById('btn-eng-proc-new')?.addEventListener('click', newProcModel);
    document.getElementById('btn-eng-proc-save')?.addEventListener('click', saveProcRoute);
    document.getElementById('btn-eng-place-import')?.addEventListener('click', importPlacement);
    document.getElementById('btn-eng-mount-readiness')?.addEventListener('click', () => loadMountReadiness());
    document.getElementById('btn-eng-mount-ready-copy')?.addEventListener('click', copyMountReadinessAdvice);
    document.getElementById('btn-eng-place-delete')?.addEventListener('click', () => deleteCustomerAsset('placement'));
    document.getElementById('btn-eng-place-line-search')?.addEventListener('click', loadPlaceLines);
    document.getElementById('eng-place-line-search')?.addEventListener('keydown', e => { if (e.key === 'Enter') loadPlaceLines(); });
    document.getElementById('btn-eng-gerber-import')?.addEventListener('click', importGerberZip);
    document.getElementById('btn-eng-gerber-delete')?.addEventListener('click', () => deleteCustomerAsset('gerber'));
    document.getElementById('btn-eng-refmap-prev')?.addEventListener('click', () => stepRefmapPreview(-1));
    document.getElementById('btn-eng-refmap-next')?.addEventListener('click', () => stepRefmapPreview(1));
    document.getElementById('btn-eng-refmap-open')?.addEventListener('click', () => {
      if (refmapPreviewUrl) window.open(refmapPreviewUrl, '_blank', 'noopener');
    });
    document.getElementById('btn-eng-refmap-import')?.addEventListener('click', importRefmap);
    document.getElementById('btn-eng-refmap-delete')?.addEventListener('click', () => deleteCustomerAsset('refmap'));
    document.getElementById('eng-mount-profile')?.addEventListener('change', saveMountProfile);
  }

  bindEvents();
  bindAssetSectionToggles();
  window.EngineeringApp = {
    load,
    switchTab: switchEngTab,
    openTodo: openReviewTodoModal,
    refreshTodo: () => loadReviewInbox({ silent: true }),
    ensureCustomer: async (code) => {
      const hit = resolveCustomerFromList(code);
      if (!hit) return false;
      if (getActiveInternalCode() === (hit.internal_code || '').toUpperCase()) return true;
      await enterCustomerWorkspace(hit, { silent: true });
      return true;
    },
  };
})();
