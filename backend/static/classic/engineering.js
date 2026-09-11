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
  let subImportFormat = '';
  let subRowsCache = [];
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
    // 前台不展示客户规则摘要（规则仍在后台生效）
    const box = document.getElementById('eng-rules-summary');
    if (box) {
      box.innerHTML = '';
      box.hidden = true;
    }
  }

  function updatePickerChrome() {
    const h1 = document.querySelector('#eng-customer-picker .page-title');
    const p = document.querySelector('#eng-customer-picker .page-subtitle');
    if (activeEngTab === 'substitution') {
      if (h1) h1.textContent = '替代料';
      if (p) p.textContent = '请选择客户后查看或导入《TDA 变更记录》';
    } else if (activeEngTab === 'process') {
      if (h1) h1.textContent = '工序对照';
      if (p) p.textContent = '请选择客户后维护机型工序对照';
    } else {
      if (h1) h1.textContent = '工程资料';
      if (p) p.textContent = '请选择客户模块进入工作台；各客户资料相互隔离';
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
      const subCid = (document.getElementById('eng-sub-customer')?.value || getActiveCustomerId() || '').trim();
      if (title) title.textContent = custLabel ? `替代料 · ${custLabel}` : '替代料';
      if (sub) {
        sub.textContent = subCid === 'yonglian'
          ? '按客户查询与维护委外投产替代表'
          : '按《TDA 变更记录》一览表：登记·工单·产品·原/变更物料（点「详情」可看完整字段）';
      }
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
      box.innerHTML = '<p class="empty">暂无工程客户。ERP 模式下按需在配置中登记，不预置旧客户资料。</p>';
      return;
    }
    const counts = todoCounts || {};
    box.innerHTML = engCustomers.map((c) => {
      const ic = c.internal_code || '';
      const cstat = counts[ic] || {};
      const imp = Number(cstat.pending_import || 0);
      const rev = Number(cstat.pending_review || 0);
      const badges = `
        <span class="eng-card-stat eng-card-stat-import" title="待导入">待导入 <b>${imp}</b></span>
        <span class="eng-card-stat eng-card-stat-review" title="待审核">待审核 <b>${rev}</b></span>`;
      const folder = c.bom_folder ? `<div class="eng-customer-card-meta">目录 ${escapeHtml(c.bom_folder)}</div>` : '';
      return `<button type="button" class="eng-customer-card" data-code="${escapeHtml(ic)}">
        <div class="eng-customer-card-top">
          <strong>${escapeHtml(ic)}</strong>
        </div>
        <div class="eng-customer-card-name">${escapeHtml(c.name || '')}</div>
        <div class="eng-customer-card-stats">${badges}</div>
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
    try {
      const data = await engApi('/status-summary');
      const by = data?.by_customer || {};
      engCustomers.forEach((c) => {
        const ic = c.internal_code || '';
        const one = by[ic] || {};
        counts[ic] = {
          pending_import: Number(one.pending_import || 0),
          pending_review: Number(one.pending_review || 0),
        };
      });
    } catch (_) {
      engCustomers.forEach((c) => {
        counts[c.internal_code || ''] = { pending_import: 0, pending_review: 0 };
      });
    }
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
    await loadEngStatusBoard({ silent: true });
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
    // 兼容误写 /api/xxx（API 前缀已是 /api，否则会变成 /api/api/... → 405）
    if (path.startsWith('/api/')) path = path.slice(4);
    const timeoutMs = opts.timeoutMs ?? 45000;
    const { timeoutMs: _tm, signal: userSignal, ...fetchOpts } = opts;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    if (userSignal) {
      if (userSignal.aborted) controller.abort();
      else userSignal.addEventListener('abort', () => controller.abort(), { once: true });
    }
    let res;
    try {
      res = await fetch(API + path, {
        ...fetchOpts,
        signal: controller.signal,
        headers: { ...window.EMS.authHeaders(), 'Content-Type': 'application/json', ...(fetchOpts.headers || {}) },
      });
    } catch (e) {
      if (e && (e.name === 'AbortError' || controller.signal.aborted)) {
        throw new Error('请求超时，请稍后重试');
      }
      throw e;
    } finally {
      clearTimeout(timer);
    }
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

  /** 黄星 dxsmt001：工程资料全局管理（导入+审核+导出+替代料/工序） */
  function isEngFullManager() {
    return engUsername() === 'dxsmt001';
  }

  /** 邱梦林 dxgc / 任玉娴 dxgc002 / engineering：资料导入与退回处理（虽是 admin 也按资料员） */
  function isEngImportOnly() {
    if (isEngFullManager()) return false;
    const name = engUsername();
    const role = window.EMS.getCurrentUser()?.role;
    return name === 'dxgc' || name === 'dxgc002' || role === 'engineering';
  }

  /** 王总 dx003 / eng_auditor；dxpz001 仅查看+导出；黄星走全局管理，不套 audit-only */
  function isEngAuditOnly() {
    if (isEngFullManager()) return false;
    const name = engUsername();
    const role = window.EMS.getCurrentUser()?.role;
    // dxpz001 为仅查看+导出，不算审核员（不收推送、无通过/退回）
    if (name === 'dxpz001' || isEngViewExportOnly()) return false;
    return name === 'dx003' || role === 'eng_auditor';
  }

  function isEngViewExportOnly() {
    return engUsername() === 'dxpz001';
  }

  function canEngAudit() {
    if (isEngFullManager()) return true;
    // 资料员不显示审核通过/退回（即使帐号角色是 admin）
    if (isEngImportOnly()) return false;
    // dxpz001：仅查看资料与导出，不可审核通过/退回
    if (isEngViewExportOnly()) return false;
    const role = window.EMS.getCurrentUser()?.role;
    return isEngAuditOnly() || role === 'admin' || role === 'planner' || engUsername() === 'wgq';
  }

  function applyEngImportOnlyUI() {
    if (isEngFullManager()) {
      document.body.classList.remove('eng-import-only', 'eng-audit-only');
      const hintFull = document.getElementById('eng-review-hint');
      if (hintFull) {
        hintFull.textContent = '工程全局管理（黄星）：可导入/审核/导出 BOM，并维护替代料与工序对照。';
      }
      return;
    }
    document.body.classList.toggle('eng-import-only', isEngImportOnly());
    // 查看账号沿用审核员布局（隐藏导入），但无通过/退回、不收推送
    document.body.classList.toggle('eng-audit-only', isEngAuditOnly() || isEngViewExportOnly());
    const hint = document.getElementById('eng-review-hint');
    if (hint) {
      if (isEngViewExportOnly()) {
        hint.textContent = '查看账号（王玉兰）：可查看 BOM 审核资料并导出 XLSX；不可导入、不可审核通过/退回，不收待审推送。';
      } else if (isEngAuditOnly()) {
        hint.textContent = '审核员：导入/重导后进入「待审核资料」人工审核通过或退回。纯插件免贴片坐标；混贴/纯贴片须有坐标。';
      } else if (isEngImportOnly()) {
        hint.textContent = '资料员（邱梦林/任玉娴）：须导入 BOM（+坐标/Gerber 按客户要求）；纯插件可选「纯插件」画像后免坐标送审。';
      } else {
        hint.textContent = '导入后自动送审；纯插件免坐标，混贴/纯贴片须有坐标。请审核员「审核通过/退回」。';
      }
    }
  }

  function switchEngTab(tab) {
    if (tab === 'customer-assets' || tab === 'files' || tab === 'docs') tab = 'bom';
    // 全局管理可进全部页签；审核员/查看仅 BOM；资料员可进替代料，仍不可进工序对照
    if (!isEngFullManager()) {
      if ((isEngAuditOnly() || isEngViewExportOnly()) && tab !== 'bom') {
        tab = 'bom';
      } else if (isEngImportOnly() && tab !== 'bom' && tab !== 'substitution') {
        tab = 'bom';
      }
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

    function tdaRemarkField(remark, label) {
    const m = String(remark || '').match(new RegExp(`${label}:([^；]+)`));
    return m ? m[1].trim() : '';
  }

  function isTdaSubMode(cid) {
    return (cid || currentSubCustomerId() || '') !== 'yonglian';
  }

  function tdaCellStack(main, sub, extra) {
    const m = (main || '').trim() || '—';
    const s = (sub || '').trim();
    const e = (extra || '').trim();
    return `<div class="tda-main">${escapeHtml(m)}</div>`
      + (s ? `<div class="tda-sub">${escapeHtml(s)}</div>` : '')
      + (e ? `<div class="tda-extra" title="${escapeHtml(e)}">${escapeHtml(e)}</div>` : '');
  }

  function tdaSubTheadHtml() {
    return `<tr class="tda-head">
      <th>登记</th><th>工单编号</th><th>产品</th>
      <th>原物料</th><th>变更物料</th>
      <th>变更原因</th><th>核对</th><th>操作</th>
    </tr>`;
  }

  function renderTdaSubRow(r, { editable } = { editable: true }) {
    const reason = tdaRemarkField(r.remark, '变更原因') || '—';
    const check = tdaRemarkField(r.remark, '核对结果') || '—';
    const origQty = tdaRemarkField(r.remark, '原数量');
    const qtyChange = r.qty != null ? r.qty : '—';
    const pending = (r.confirm_status || '') === 'pending' || !r.sub_code;

    const regCell = tdaCellStack(
      `#${r.sub_order || '—'} · ${r.relation_type || 'OPEN'}`,
      r.effective_date || '—',
      tdaRemarkField(r.remark, '登记人') ? `登记人 ${tdaRemarkField(r.remark, '登记人')}` : '',
    );
    const prodCell = tdaCellStack(r.parent_code, r.parent_name, r.parent_spec);
    const compCell = tdaCellStack(r.comp_code, r.comp_name, r.comp_spec)
      + (origQty || r.qty != null ? `<div class="tda-qty">原数量 ${origQty || qtyChange}</div>` : '');

    let subCell;
    if (pending && editable) {
      subCell = `<div class="tda-edit-stack">
        <input type="text" class="eng-sub-manual-code" placeholder="变更物料料号" value="${escapeHtml(r.sub_code || '')}">
        <input type="text" class="eng-sub-manual-name" placeholder="变更品名" value="${escapeHtml(r.sub_name || '')}">
        <input type="text" class="eng-sub-manual-spec" placeholder="变更规格" value="${escapeHtml(r.sub_spec || '')}">
        <div class="tda-qty tda-qty-change">变更数量 ${qtyChange}</div>
      </div>`;
    } else {
      subCell = tdaCellStack(r.sub_code, r.sub_name, r.sub_spec)
        + `<div class="tda-qty tda-qty-change">变更 ${qtyChange}</div>`;
    }

    const checkCls = check === '相同' ? 'tda-badge tda-badge-ok' : 'tda-badge';
    let ops = '';
    if (editable) {
      ops = `<button type="button" class="btn btn-sm btn-eng-tda-detail" data-id="${r.id}">详情</button>`;
      if (pending) {
        ops += `<button type="button" class="btn btn-sm btn-primary btn-eng-sub-confirm" data-id="${r.id}">确认</button>`;
      } else {
        ops += `<button type="button" class="btn btn-sm btn-eng-sub-edit" data-id="${r.id}">编辑</button>`;
      }
      ops += `<button type="button" class="btn btn-sm btn-eng-sub-del" data-id="${r.id}">删</button>`;
    }

    return `<tr data-id="${r.id || ''}" class="${pending ? 'eng-sub-pending' : ''}">
      <td class="tda-col-reg">${regCell}</td>
      <td class="tda-col-po"><strong>${escapeHtml(r.purchase_no || '—')}</strong></td>
      <td class="tda-col-prod">${prodCell}</td>
      <td class="tda-col-comp">${compCell}</td>
      <td class="tda-col-sub">${subCell}</td>
      <td class="tda-col-reason" title="${escapeHtml(reason)}">${escapeHtml(reason)}</td>
      <td class="tda-col-check"><span class="${checkCls}">${escapeHtml(check)}</span></td>
      <td class="tda-col-ops">${ops}</td>
    </tr>`;
  }

  function findSubRow(id) {
    return subRowsCache.find((r) => Number(r.id) === Number(id));
  }

  function openTdaDetailModal(id) {
    const r = findSubRow(id);
    if (!r) return;
    const modal = document.getElementById('eng-tda-detail-modal');
    if (!modal) return;
    modal.dataset.ruleId = String(id);
    const set = (fid, val) => {
      const el = document.getElementById(fid);
      if (el) el.textContent = (val || '').trim() || '—';
    };
    const setInput = (fid, val) => {
      const el = document.getElementById(fid);
      if (el) el.value = (val || '').trim();
    };
    set('tda-d-seq', r.sub_order ? `#${r.sub_order}` : '—');
    set('tda-d-date', r.effective_date);
    set('tda-d-status', r.relation_type);
    set('tda-d-po', r.purchase_no);
    set('tda-d-parent', r.parent_code);
    set('tda-d-pname', r.parent_name);
    set('tda-d-pspec', r.parent_spec);
    setInput('tda-d-comp', r.comp_code);
    setInput('tda-d-cname', r.comp_name);
    setInput('tda-d-cspec', r.comp_spec);
    set('tda-d-cqty', tdaRemarkField(r.remark, '原数量') || (r.qty != null ? String(r.qty) : '—'));
    setInput('tda-d-sub', r.sub_code);
    setInput('tda-d-sname', r.sub_name);
    setInput('tda-d-sspec', r.sub_spec);
    set('tda-d-sqty', r.qty != null ? String(r.qty) : '—');
    set('tda-d-reason', tdaRemarkField(r.remark, '变更原因'));
    set('tda-d-check', tdaRemarkField(r.remark, '核对结果'));
    set('tda-d-registrant', tdaRemarkField(r.remark, '登记人'));
    set('tda-d-legacy', tdaRemarkField(r.remark, '0703替代物料表'));
    modal.classList.remove('hidden');
  }

  function closeTdaDetailModal() {
    document.getElementById('eng-tda-detail-modal')?.classList.add('hidden');
  }

  async function saveTdaDetailModal() {
    const modal = document.getElementById('eng-tda-detail-modal');
    const id = Number(modal?.dataset.ruleId || 0);
    if (!id) return;
    const subCode = document.getElementById('tda-d-sub')?.value?.trim() || '';
    const subName = document.getElementById('tda-d-sname')?.value?.trim() || '';
    const subSpec = document.getElementById('tda-d-sspec')?.value?.trim() || '';
    if (!subCode) {
      window.EMS.showToast('请填写变更物料料号', 'error');
      return;
    }
    try {
      await engApi('/substitutions/' + id + '/confirm-manual', {
        method: 'POST',
        body: JSON.stringify({ sub_code: subCode, sub_name: subName || null, sub_spec: subSpec || null }),
      });
      window.EMS.showToast('已保存', 'success');
      closeTdaDetailModal();
      await loadSubstitutionMeta();
      await loadSubstitutions(subPage);
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
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
        ? `${meta.customer_name || cid} · TDA变更 ${meta.row_count} 条 · 更新 ${fmtTime(meta.synced_at)}`
        : `${meta.customer_name || cid} · 暂无记录（请下载「景立创TDA变更记录」模板后导入）`;
    }
    document.body.classList.toggle('eng-sub-yonglian', cid === 'yonglian');
    document.body.classList.toggle('eng-sub-tda', cid !== 'yonglian');
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
        thead.innerHTML = tdaSubTheadHtml();
      }
    }
    document.querySelectorAll('#eng-sub-import-modal .eng-sub-col-comp').forEach((el) => {
      el.textContent = isYl ? '子项物料编码' : '材料品号';
    });
    document.querySelectorAll('#eng-sub-import-modal .eng-sub-col-sub').forEach((el) => {
      el.textContent = isYl ? '投产物料编码' : '变更物料料号';
    });
  }

  function subTableColspan() {
    return currentSubCustomerId() === 'yonglian' ? 15 : 8;
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
        <td>
          <button type="button" class="btn btn-sm btn-eng-sub-edit-group" data-ids="${g.ids.join(',')}">编辑</button>
          <button type="button" class="btn btn-sm btn-eng-sub-del-group" data-ids="${g.ids.join(',')}">删除</button>
        </td>
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
    tbody.querySelectorAll('.btn-eng-sub-edit-group').forEach((btn) => {
      btn.addEventListener('click', () => beginEditYonglianGroup(btn.closest('tr')));
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
    // 客户C：拉全量后按子项/投产透视成 D1/U1…列（对齐客户 Excel）
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
    subRowsCache = rows || [];
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="${cols}" class="empty">该客户暂无 TDA 变更记录，请下载模板后导入 XLSX</td></tr>`;
    } else {
      tbody.innerHTML = rows.map((r) => renderTdaSubRow(r)).join('');
      tbody.querySelectorAll('.btn-eng-sub-del').forEach((btn) => {
        btn.addEventListener('click', () => deleteSubstitution(Number(btn.dataset.id)));
      });
      tbody.querySelectorAll('.btn-eng-sub-confirm').forEach((btn) => {
        btn.addEventListener('click', () => confirmSubstitutionManual(Number(btn.dataset.id), btn.closest('tr')));
      });
      tbody.querySelectorAll('.btn-eng-sub-edit').forEach((btn) => {
        btn.addEventListener('click', () => openTdaDetailModal(Number(btn.dataset.id)));
      });
      tbody.querySelectorAll('.btn-eng-tda-detail').forEach((btn) => {
        btn.addEventListener('click', () => openTdaDetailModal(Number(btn.dataset.id)));
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

  function cellTextOrEmpty(td) {
    const t = (td?.textContent || '').trim();
    return t === '—' ? '' : t;
  }

  function fillSubInputs(tr, code, name, spec) {
    const tds = tr?.children;
    if (!tds) return;
    const isYl = currentSubCustomerId() === 'yonglian';
    const subIdx = isYl ? 5 : 11;
    if (tds.length <= subIdx + 2) return;
    tds[subIdx].innerHTML = `<input type="text" class="eng-sub-manual-code" placeholder="${isYl ? '投产物料编码' : '变更物料料号'}" value="${escapeHtml(code || '')}">`;
    tds[subIdx + 1].innerHTML = `<input type="text" class="eng-sub-manual-name" placeholder="${isYl ? '物料名称' : '变更品名'}" value="${escapeHtml(name || '')}">`;
    tds[subIdx + 2].innerHTML = `<input type="text" class="eng-sub-manual-spec" placeholder="${isYl ? '规格型号' : '变更规格'}" value="${escapeHtml(spec || '')}">`;
  }

  function beginEditSubstitution(tr) {
    if (currentSubCustomerId() !== 'yonglian') {
      const id = Number(tr?.dataset?.id || 0);
      if (id) openTdaDetailModal(id);
      return;
    }
    beginEditYonglianGroup(tr);
  }

  function beginEditYonglianGroup(tr) {
    if (!tr || tr.classList.contains('eng-sub-editing')) return;
    const tds = tr.children;
    if (!tds || tds.length < 15) return;
    const code = cellTextOrEmpty(tds[2]);
    const name = cellTextOrEmpty(tds[3]);
    const spec = cellTextOrEmpty(tds[4]);
    tds[2].innerHTML = `<input type="text" class="eng-sub-manual-code" placeholder="投产物料编码" value="${escapeHtml(code)}">`;
    tds[3].innerHTML = `<input type="text" class="eng-sub-manual-name" placeholder="物料名称" value="${escapeHtml(name)}">`;
    tds[4].innerHTML = `<input type="text" class="eng-sub-manual-spec" placeholder="规格型号" value="${escapeHtml(spec)}">`;
    const last = tds[tds.length - 1];
    last.innerHTML = `
      <button type="button" class="btn btn-sm btn-primary btn-eng-sub-save-group">保存</button>
      <button type="button" class="btn btn-sm btn-eng-sub-cancel">取消</button>`;
    tr.classList.add('eng-sub-editing');
    last.querySelector('.btn-eng-sub-save-group')?.addEventListener('click', () => saveYonglianGroup(tr));
    last.querySelector('.btn-eng-sub-cancel')?.addEventListener('click', () => loadSubstitutions(subPage));
    tr.querySelector('.eng-sub-manual-code')?.focus();
  }

  async function saveYonglianGroup(tr) {
    const ids = String(tr?.dataset?.ids || '').split(',').map((x) => Number(x)).filter(Boolean);
    const subCode = tr.querySelector('.eng-sub-manual-code')?.value?.trim() || '';
    const subName = tr.querySelector('.eng-sub-manual-name')?.value?.trim() || '';
    const subSpec = tr.querySelector('.eng-sub-manual-spec')?.value?.trim() || '';
    if (!ids.length) return;
    if (!subCode) {
      window.EMS.showToast('请填写投产物料编码', 'error');
      return;
    }
    if (!confirm('修改后将同步到发料单与 BOM，是否继续？')) return;
    try {
      for (const id of ids) {
        await engApi('/substitutions/' + id + '/confirm-manual', {
          method: 'POST',
          body: JSON.stringify({
            sub_code: subCode,
            sub_name: subName || null,
            sub_spec: subSpec || null,
          }),
        });
      }
      window.EMS.showToast('已更新替代料，已同步发料/BOM', 'success');
      await loadSubstitutionMeta();
      await loadSubstitutions(subPage);
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  async function confirmSubstitutionManual(id, tr, opts = {}) {
    if (!id || !tr) return;
    const subCode = tr.querySelector('.eng-sub-manual-code')?.value?.trim() || '';
    const subName = tr.querySelector('.eng-sub-manual-name')?.value?.trim() || '';
    const subSpec = tr.querySelector('.eng-sub-manual-spec')?.value?.trim() || '';
    if (!subCode) {
      window.EMS.showToast('请填写变更物料料号', 'error');
      return;
    }
    const editing = !!opts.editing;
    const msg = editing
      ? '修改后将同步到发料单与 BOM，是否继续？'
      : '确认后将同步到发料单与 BOM，是否继续？';
    if (!confirm(msg)) return;
    try {
      await engApi('/substitutions/' + id + '/confirm-manual', {
        method: 'POST',
        body: JSON.stringify({
          sub_code: subCode,
          sub_name: subName || null,
          sub_spec: subSpec || null,
        }),
      });
      window.EMS.showToast(editing ? '已更新替代料，已同步发料/BOM' : '已确认，已同步发料/BOM', 'success');
      await loadSubstitutionMeta();
      await loadSubstitutions(subPage);
    } catch (e) {
      window.EMS.showToast(e.message, 'error');
    }
  }

  function openSubImportModal(title, rows, sourceType, sourceFile, message, format) {
    subImportRows = rows || [];
    subImportSourceType = sourceType || 'xlsx';
    subImportSourceFile = sourceFile || '';
    subImportFormat = format || '';
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
      if (thead) thead.innerHTML = tdaSubTheadHtml();
      tb.innerHTML = subImportRows.length
        ? subImportRows.map((r) => renderTdaSubRow(r, { editable: false })).join('')
        : `<tr><td colspan="8" class="empty">无有效行</td></tr>`;
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
    const useReplace = subImportFormat === 'tda' || (cid !== 'yonglian' && subImportFormat !== 'yonglian');
    if (useReplace && !confirm('导入将删除该客户现有全部 TDA/替代记录，并以本次表格全量替换。是否继续？')) {
      return;
    }
    try {
      const res = await engApi('/substitutions/import-confirm', {
        method: 'POST',
        body: JSON.stringify({
          customer_id: cid,
          mode: useReplace ? 'replace' : 'add',
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
    openSubImportModal('XLSX 导入预览', data.rows || [], 'xlsx', file.name, data.message || '', data.format || '');
  }

  async function addSubstitutionManual() {
    const cid = currentSubCustomerId();
    if (!cid) {
      window.EMS.showToast('请先选择客户', 'error');
      return;
    }
    const isYl = cid === 'yonglian';
    // 机型 → 订单号 → 原物料 → 替代物料
    const purchaseNo = prompt('工单编号（可留空）');
    if (purchaseNo === null) return;
    const parent = prompt('产品品号 / 机型（可留空）');
    if (parent === null) return;
    const comp = prompt(isYl ? '子项物料编码（BOM 原料）' : '材料品号（原物料）');
    if (!comp) return;
    const sub = prompt(isYl ? '投产物料编码（实际发料）' : '变更物料料号');
    if (!sub) return;
    try {
      await engApi('/substitutions', {
        method: 'POST',
        body: JSON.stringify({
          customer_id: cid,
          comp_code: comp.trim(),
          sub_code: sub.trim(),
          parent_code: (parent || '').trim(),
          purchase_no: (purchaseNo || '').trim(),
          relation_type: isYl ? '替代料件' : 'OPEN',
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
    a.download = cid === 'yonglian' ? 'yonglian_substitution_template.xlsx' : 'TDA变更记录模板.xlsx';
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
      pre_oven_aoi: false,
      insert: false,
      post_solder: false,
      post_oven_label: false,
      test: false,
      conformal: { enabled: false, type: '普通三防' },
      // 界面已去掉灌胶勾选，保存时保留原值以免冲掉历史数据
      potting: !!procCurrentRoute?.steps?.potting,
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
      pre_oven_aoi: !!steps.pre_oven_aoi,
      insert: !!steps.insert,
      post_solder: !!steps.post_solder,
      post_oven_label: !!steps.post_oven_label,
      test: !!steps.test,
      conformal_enabled: !!steps.conformal?.enabled,
      conformal_type: steps.conformal?.type || '普通三防',
      potting: !!steps.potting,
    };
  }

  function buildRoutePreview(steps) {
    const parts = [];
    if (steps.laser_label) parts.push('镭雕/贴码');
    if (steps.smt) parts.push('SMT-AOI');
    if (steps.pre_oven_aoi) parts.push('炉前AOI');
    if (steps.insert) parts.push('插件');
    if (steps.post_solder) parts.push('后焊');
    if (steps.post_oven_label) parts.push('炉后贴码');
    if (steps.test) parts.push('ICT测试');
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
      laser_label: false, smt: false, pre_oven_aoi: false, insert: false, post_solder: false, post_oven_label: false, test: false,
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
    const delBtn = document.getElementById('btn-eng-proc-delete');
    if (delBtn) delBtn.classList.toggle('hidden', !(route.id > 0));
  }

  function hideProcEditor() {
    procCurrentRoute = null;
    procIsNew = false;
    document.getElementById('eng-proc-editor')?.classList.add('hidden');
    document.getElementById('eng-proc-empty')?.classList.remove('hidden');
    const title = document.getElementById('eng-proc-title');
    if (title) title.textContent = '选择或新建机型配置工序';
    document.getElementById('btn-eng-proc-delete')?.classList.add('hidden');
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
        laser_label: false, smt: false, pre_oven_aoi: false, insert: false, post_solder: false, post_oven_label: false, test: false,
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

  async function deleteProcRoute() {
    const id = procSelectedId || procCurrentRoute?.id;
    if (!id) {
      window.EMS.showToast('请先选择已保存的机型再删除', 'error');
      return;
    }
    const label = `${procCurrentRoute?.internal_code || ''} · ${procCurrentRoute?.model_code || id}`;
    if (!confirm(`确认删除工序对照「${label}」？删除后扫码将按未配置处理。`)) return;
    try {
      const res = await engApi(`/process-routes/${id}`, { method: 'DELETE' });
      window.EMS.showToast(res.message || '已删除');
      procSelectedId = null;
      hideProcEditor();
      await loadProcMeta();
      await loadProcModels();
    } catch (e) {
      window.EMS.showToast(e.message || '删除失败', 'error');
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
    const placeExportBtn = document.getElementById('btn-eng-place-export');
    const gerberExportBtn = document.getElementById('btn-eng-gerber-export');
    const hasPlace = !!(row?.placement_file_id && row?.placement_line_count);
    const hasGerber = !!(row?.gerber_package_id && row?.gerber_file_count);
    const hasRefmap = !!(row?.refmap_file_id && row?.refmap_file_name);
    placeBtn?.classList.toggle('hidden', !hasPlace);
    gerberBtn?.classList.toggle('hidden', !hasGerber);
    refmapBtn?.classList.toggle('hidden', !hasRefmap);
    placeExportBtn?.classList.toggle('hidden', !hasPlace);
    gerberExportBtn?.classList.toggle('hidden', !hasGerber);
  }

  async function downloadEngAssetExport(url, fallbackName, okToast) {
    const res = await fetch(url, { headers: window.EMS.authHeaders() });
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
      : (asciiMatch ? asciiMatch[1] : fallbackName);
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(objectUrl);
    window.EMS.showToast(okToast || '已导出');
  }

  async function exportPlacement() {
    const id = assetsSelectedRow?.placement_file_id;
    if (!id) {
      window.EMS.showToast('请先选择已导入坐标的订单', 'error');
      return;
    }
    try {
      await downloadEngAssetExport(
        `${API}/placements/${id}/export`,
        'placement.csv',
        '坐标已导出'
      );
    } catch (e) {
      window.EMS.showToast(e.message || '导出失败', 'error');
    }
  }

  async function exportGerber() {
    const id = assetsSelectedRow?.gerber_package_id;
    if (!id) {
      window.EMS.showToast('请先选择已导入 Gerber 的订单', 'error');
      return;
    }
    try {
      await downloadEngAssetExport(
        `${API}/gerbers/${id}/export`,
        'gerber.zip',
        'Gerber 已导出'
      );
    } catch (e) {
      window.EMS.showToast(e.message || '导出失败', 'error');
    }
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
      // 延迟加载坐标明细，优先让 BOM 明细可交互
      void loadPlaceLines().catch((err) => console.warn('坐标明细加载失败', err));
    }

    const gerberHint = document.getElementById('eng-gerber-audit-hint');
    const gerberEmpty = document.getElementById('eng-gerber-empty');
    const gerberWrap = document.getElementById('eng-gerber-files-wrap');
    if (!row.gerber_package_id || !row.gerber_file_count) {
      gerberWrap?.classList.add('hidden');
      gerberEmpty?.classList.remove('hidden');
      if (gerberHint) { gerberHint.textContent = ''; gerberHint.className = 'eng-gerber-audit-hint'; }
      if (gerberEmpty) gerberEmpty.textContent = '尚未导入 Gerber（必交；zip/7z/rar）。缺 Gerber 不能送审。';
    } else {
      gerberEmpty?.classList.add('hidden');
      gerberWrap?.classList.remove('hidden');
      if (gerberHint) {
        gerberHint.textContent = row.gerber_audit_message || '';
        gerberHint.className = `eng-gerber-audit-hint audit-${row.gerber_audit_status || 'pending'}`;
      }
      void engApi(`/gerbers/${row.gerber_package_id}/files`)
        .then((files) => renderGerberFilesTable(files, row.gerber_package_id))
        .catch((err) => console.warn('Gerber 列表加载失败', err));
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
      if (tbody) tbody.innerHTML = '<tr><td colspan="10" class="empty">请先选择客户模块</td></tr>';
      return [];
    }
    const filterEl = document.getElementById('eng-filter-code');
    if (filterEl) filterEl.value = code;
    const keyword = document.getElementById('eng-search')?.value?.trim() || '';
    const params = new URLSearchParams();
    params.set('internal_code', code);
    if (keyword) params.set('keyword', keyword);
    const [rows] = await Promise.all([
      engApi('/models?' + params.toString()),
      loadEngStatusBoard({ silent: true }),
    ]);
    const tbody = document.getElementById('eng-models-table');
    if (!tbody) return [];
    const counts = engStatusBoard.counts || {};
    const pendingCount = rows.filter(r => resolveBomStatus(r) === 'pending').length;
    const importedCount = rows.length - pendingCount;
    const closedCount = rows.filter(r => r.is_order_completed).length;
    const openCount = rows.length - closedCount;
    const meta = document.getElementById('eng-path-info');
    if (meta) {
      meta.textContent = `${code} 共 ${rows.length} 笔（在制 ${openCount} · 已结案 ${closedCount}） · BOM已确认 ${importedCount} · 待导入 ${counts.pending_import ?? pendingCount} · 待审核 ${counts.pending_review ?? 0}`;
    }
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="10" class="empty">暂无订单资料</td></tr>';
      return [];
    }
    tbody.innerHTML = rows.map(r => {
      const status = resolveBomStatus(r);
      const rev = effectiveReviewStatus(r);
      const gap = findImportGapForModel(r);
      const hasBom = status === 'imported';
      const hasPlace = gap ? !!gap.has_placement : (hasBom && rev !== 'pending_import');
      const hasGb = gap ? !!gap.has_gerber : (hasBom && rev !== 'pending_import');
      const reviewCell = gap
        ? `<span class="kit-badge ${reviewStatusClass('pending_import')}">工程待导入</span><div>${missingChips(gap.missing_imports)}</div>`
        : `<span class="kit-badge ${reviewStatusClass(rev)}" title="资料审核状态">${hasBom ? reviewStatusLabel(rev) : '—'}</span>`;
      return `
      <tr class="eng-model-row${selectedModelKey === modelRowKey(r) ? ' selected' : ''}${status === 'pending' ? ' eng-model-pending' : ' eng-model-imported'}${rev === 'pending_review' ? ' eng-model-pending-review' : ''}" data-key="${modelRowKey(r)}" data-id="${r.id || ''}" data-purchase="${escapeHtml(r.purchase_no || '')}" data-eng-review="${escapeHtml(rev || '')}">
        <td>${r.internal_code}</td>
        <td>${r.customer_name || r.customer_id}</td>
        <td><strong>${r.model_code}</strong>${modelFolderSubtitle(r)}${r.is_order_completed ? ' <span class="kit-badge kit-unknown" title="订单已结案，工程资料仍保留可查">已结案</span>' : ''}${(r.has_substitution || r.substitution_rule_count > 0) ? ` <span class="kit-badge kit-partial" title="本订单本机型已绑定替代料 ${r.substitution_rule_count || 0} 条">替×${r.substitution_rule_count || ''}</span>` : ''}</td>
        <td><strong>${r.purchase_no || '—'}</strong></td>
        <td>${r.model_name || '—'}</td>
        <td>${assetMark(hasBom)}${hasBom ? ` <span class="muted">${r.line_count}</span>` : ''}</td>
        <td>${hasBom ? assetMark(hasPlace) : '<span class="muted">—</span>'}</td>
        <td>${hasBom ? assetMark(hasGb) : '<span class="muted">—</span>'}</td>
        <td data-eng-review-cell>${reviewCell}</td>
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
    // 与下拉框保持同步，避免打印时 selectedModel 画像为空误拦
    if (selectedModel) {
      selectedModel.mount_profile_override = override;
    }
    const detected = meta?.detected_profile || 'unknown';
    if (override) {
      hint.textContent = `当前：已选「${PROFILE_LABELS[override] || override}」（审核/发料前必选）`;
    } else if (detected && detected !== 'unknown') {
      const conf = meta?.profile_confidence ? ` / ${meta.profile_confidence}` : '';
      hint.textContent = `未选定画像（自动参考：${PROFILE_LABELS[detected] || detected}${conf}）— 请先选纯贴片/纯插件/混贴再审核`;
    } else {
      hint.textContent = '未选定画像 — 请先选纯贴片 SMT / 纯插件 DIP / 混贴，否则不能审核通过';
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
      pending_import: '工程待导入',
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

  /** 工程状态以库为准；未齐套（缺 BOM/坐标/Gerber）保持待导入，不伪装成待审核 */
  function effectiveReviewStatus(model, meta) {
    const raw = (meta?.eng_review_status || model?.eng_review_status || '').trim();
    return raw || 'pending_import';
  }

  /** 详情状态变更后同步左侧列表「审核」列，避免仍显示旧的「已通过」 */
  function syncListReviewBadge(model, status) {
    if (!model) return;
    const st = (status || effectiveReviewStatus(model) || '').trim();
    if (st) model.eng_review_status = st;
    const key = modelRowKey(model);
    const tr = document.querySelector(`.eng-model-row[data-key="${CSS.escape(key)}"]`);
    if (!tr) return;
    tr.classList.toggle('eng-model-pending-review', st === 'pending_review');
    const cell = tr.querySelector('[data-eng-review-cell]');
    if (!cell) return;
    const hasBom = resolveBomStatus(model) === 'imported' || !!(model.id || model.bom_model_id);
    if (!hasBom) {
      cell.innerHTML = '<span class="muted">—</span>';
      return;
    }
    if (st === 'pending_import') {
      const gap = findImportGapForModel(model);
      cell.innerHTML = gap
        ? `<span class="kit-badge ${reviewStatusClass('pending_import')}">工程待导入</span><div>${missingChips(gap.missing_imports)}</div>`
        : `<span class="kit-badge ${reviewStatusClass(st)}" title="资料审核状态">${reviewStatusLabel(st)}</span>`;
      return;
    }
    cell.innerHTML = `<span class="kit-badge ${reviewStatusClass(st)}" title="资料审核状态">${reviewStatusLabel(st)}</span>`;
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
      tbody.innerHTML = '<tr><td colspan="12" class="empty">无明细行</td></tr>';
      return;
    }
    tbody.innerHTML = active.map(l => {
      const ctrlMark = (l.source === 'control' || l.control_id)
        ? ' <span class="kit-badge kit-partial" title="管制变更料">变更</span>'
        : '';
      const subs = (l.substitute_codes || []).filter(Boolean);
      const subCell = subs.length
        ? `<span class="eng-bom-sub-codes" title="${escapeHtml(subs.join('、'))}">${escapeHtml(subs.join('、'))}</span>`
        : '<span class="muted">—</span>';
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
        <td class="eng-bom-col-sub">${subCell}</td>
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
    if (selectedModel) syncListReviewBadge(selectedModel, status);
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
    const profile = (dossier?.mount_profile_override || dossier?.checklist_policy?.mount_profile_override || '').trim();
    const profileLabel = PROFILE_LABELS[profile] || profile || '未选';
    let tip = blocked
      ? `审核条件未满足，暂不可通过：${blockers.map((c) => c.label).join('、')}`
      : '资料检查已满足，可审核通过';
    const reviewSt = (dossier?.eng_review_status || '').trim();
    if (reviewSt === 'approved') {
      ['btn-eng-kit-approve', 'btn-eng-review-approve'].forEach((id) => {
        const btn = document.getElementById(id);
        if (!btn) return;
        btn.disabled = true;
        btn.title = '本单已审核通过';
        btn.classList.add('eng-approve-blocked');
      });
      const gate = document.getElementById('eng-kit-approve-gate');
      if (gate) {
        gate.classList.remove('hidden');
        gate.textContent = '本单已审核通过，请阅读下方绿色提示后点「关闭」';
      }
      return;
    }
    if (reviewSt === 'pending_import') {
      tip = blocked
        ? `当前待导入，请先完成 BOM/坐标/Gerber 导入；与仓库备料齐套无关。未满足：${blockers.map((c) => c.label).join('、')}`
        : '导入完成后送审，再由审核员核对通过';
    }
    if (blocked && blockers.some((c) => c.label === '贴片坐标')) {
      if (profile === 'dip_only') {
        tip = '贴片坐标未导入，但已选「纯插件」应免坐标；请关闭后刷新再试，或联系管理员';
      } else if (profile === 'mixed' || profile === 'smt_only') {
        tip = `当前贴装画像为「${profileLabel}」，必须导入贴片坐标才能通过；若本单实际是纯插件，请先在外层改选「纯插件 DIP」再审核`;
      } else {
        tip = `${tip}（请先选定贴装画像；纯插件可免坐标，混贴/纯贴片必须有坐标）`;
      }
    }
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

  function formatImportBomCheckSummary(imp) {
    if (!imp) return '';
    if (!imp.has_snapshot) {
      return '【导入 vs 生效 BOM】尚无 Excel 导入快照，请重新导入 BOM 后再审核（当前无法比对漏料）';
    }
    const miss = imp.missing_in_bom || [];
    const extra = imp.extra_in_bom || [];
    if (!miss.length && !extra.length) {
      return `【导入 vs 生效 BOM】一致，共 ${imp.import_count || 0} 个料号（无漏料、无多余）`;
    }
    let parts = [
      `导入 ${imp.import_count || 0} 个料号，生效 BOM ${imp.active_count || 0} 个`,
    ];
    if (miss.length) {
      parts.push(`缺 ${miss.length} 个：${miss.slice(0, 12).join('、')}${miss.length > 12 ? '…' : ''}`);
    }
    if (extra.length) {
      parts.push(`多 ${extra.length} 个非导入料`);
    }
    return `【导入 vs 生效 BOM】${parts.join('；')}`;
  }

  function renderImportBomCheckPanel(imp) {
    if (!imp) return '';
    const miss = imp.missing_in_bom || [];
    const extra = imp.extra_in_bom || [];
    const ok = imp.has_snapshot && imp.ready && !miss.length;
    const warnNoSnap = !imp.has_snapshot;
    const cls = ok ? 'eng-import-check-ok' : (warnNoSnap ? 'eng-import-check-warn' : 'eng-dossier-reject');
    const title = ok
      ? `导入 BOM 比对：通过（${imp.import_count || 0} 个料号与生效明细一致）`
      : warnNoSnap
        ? '导入 BOM 比对：未建立 Excel 快照'
        : `导入 BOM 漏料（生效明细缺 ${miss.length} 个）`;
    const body = ok
      ? escapeHtml(imp.detail || '与最后一次导入 Excel 料号一致')
      : warnNoSnap
        ? escapeHtml(imp.detail || '请重新导入 BOM Excel，系统会在导入时自动建立料号快照')
        : `${escapeHtml(miss.slice(0, 40).join('、'))}${miss.length > 40 ? '…' : ''}`;
    const extraLine = extra.length
      ? `<div class="muted" style="font-size:12px;margin-top:6px">生效 BOM 另有 ${extra.length} 个料号不在导入 Excel 中</div>`
      : '';
    const src = imp.source_file
      ? `<div class="muted" style="font-size:11px;margin-top:6px">快照来源：${escapeHtml(imp.source_file)}</div>`
      : '';
    return `<div class="${cls}" role="alert" style="margin-top:10px">
      <div class="eng-dossier-reject-title">${escapeHtml(title)}</div>
      <div class="eng-dossier-reject-body">${body}</div>
      ${extraLine}
      ${src}
      ${!ok && !warnNoSnap ? '<div class="muted" style="font-size:12px;margin-top:6px">漏料不可审核通过，请核对 Excel 或重新导入</div>' : ''}
    </div>`;
  }

  function showEngApproveResult(title, detail) {
    const box = document.getElementById('eng-kit-approve-result');
    if (!box) return;
    box.innerHTML = `<div class="eng-kit-approve-result-title">${escapeHtml(title)}</div><div>${escapeHtml(detail || '')}</div>`;
    box.classList.remove('hidden');
    box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function hideEngApproveResult() {
    const box = document.getElementById('eng-kit-approve-result');
    if (box) {
      box.classList.add('hidden');
      box.innerHTML = '';
    }
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
      hideEngApproveResult();
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
          <div><span class="k">贴装统计</span><span>SMT ${stats.smt || 0} · DIP ${stats.dip || 0} · 装配 ${stats.assy || 0} · 待确认 ${stats.unresolved || 0}</span></div>
          ${st !== 'rejected' ? `<div class="eng-dossier-span"><span class="k">资料摘要</span><span>${escapeHtml(dossier.eng_review_message || '—')}</span></div>` : ''}
        </div>
      </div>
      <div class="eng-dossier-flow">${steps}</div>
      ${renderImportBomCheckPanel(dossier.import_bom_check)}
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
      window.EMS.showToast(`审核条件未满足：${blockers.map((c) => c.label).join('、')}`, 'error', 6000);
      applyApproveGate(dossier);
      return;
    }
    const impSummary = formatImportBomCheckSummary(dossier.import_bom_check);
    const imp = dossier.import_bom_check;
    if (imp?.has_snapshot && (imp.missing_in_bom || []).length) {
      window.EMS.showToast('导入 BOM 存在漏料，不可审核通过', 'error', 6000);
      applyApproveGate(dossier);
      return;
    }
    const confirmLines = [
      '确认审核通过本订单资料？通过后可用于发料打印。',
      impSummary,
    ].filter(Boolean);
    if (!window.confirm(confirmLines.join('\n\n'))) return;
    await engApi(`/models/${selectedModelId}/review/approve`, {
      method: 'POST',
      body: JSON.stringify({ message: '审核通过' }),
    });
    const detail = impSummary || '资料已审核通过，可用于发料打印。';
    showEngApproveResult('审核已通过', `${detail}\n\n请阅读后点击右上角「关闭」退出审核工作台。`);
    window.EMS.showToast('审核已通过，完整比对见审核工作台绿色提示框', 'success', 20000);
    await loadModels();
    await loadReviewInbox({ silent: true });
    await loadReviewDossier(selectedModelId);
    if (selectedModel) {
      selectedModel.eng_review_status = 'approved';
      await selectModel(selectedModel);
    }
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
      const tip = status === 'pending_review'
        ? '本单资料状态为「待审核」（例如改过贴装画像后需重新审核通过），请先点「审核通过」后再打印'
        : '资料未审核通过，请先完成审核后再打印';
      window.EMS.showToast(tip, 'error', 7000);
      return;
    }
    if (!selectedModelId) {
      window.EMS.showToast('请先导入并审核本订单 BOM', 'error');
      return;
    }
    // 画像以库/下拉为准，避免列表缓存空值误报「请先选择贴装画像」
    let profile = String(
      selectedModel.mount_profile_override
      || document.getElementById('eng-mount-profile')?.value
      || '',
    ).trim();
    try {
      const dossier = await engApi(`/models/${selectedModelId}/review-dossier`);
      const dossierProfile = String(dossier?.mount_profile_override || '').trim();
      if (dossierProfile) {
        profile = dossierProfile;
        selectedModel.mount_profile_override = dossierProfile;
        const sel = document.getElementById('eng-mount-profile');
        if (sel) sel.value = dossierProfile;
      }
      if (!['dip_only', 'smt_only', 'mixed'].includes(profile)) {
        window.EMS.showToast('请先选择贴装画像（纯贴片 SMT / 纯插件 DIP / 混贴）并审核通过后再打印', 'error', 6000);
        return;
      }
      // 已审核通过：优先用后端 print_blockers（与 dip_only 免坐标一致）；旧版无该字段时回退
      const printBlockers = Array.isArray(dossier?.print_blockers)
        ? dossier.print_blockers
        : (dossier?.approve_blockers || []).filter((b) => {
            if (profile === 'dip_only' && String(b).includes('坐标')) return false;
            return true;
          });
      if (printBlockers.length) {
        window.EMS.showToast(`不能打印发料单：${printBlockers.join('；')}`, 'error', 8000);
        return;
      }
      if (!Array.isArray(dossier?.print_blockers)) {
        const missProc = Number(dossier?.mount_stats?.unresolved || 0);
        const missSide = Number(dossier?.mount_stats?.missing_side || 0);
        if (missProc > 0 || missSide > 0) {
          window.EMS.showToast(
            `不能打印发料单：仍有物料缺工序(${missProc})或面别(${missSide})`,
            'error',
            8000,
          );
          return;
        }
      }
    } catch (e) {
      window.EMS.showToast(e.message || '校验发料条件失败', 'error');
      return;
    }
    document.getElementById('eng-issue-print-modal')?.classList.remove('hidden');
  }

  async function showIssuePrintHistory() {
    if (!selectedModelId) {
      window.EMS.showToast('请先选择订单机型', 'error');
      return;
    }
    const modal = document.getElementById('eng-print-history-modal');
    const body = document.getElementById('eng-print-history-body');
    if (!modal || !body) return;
    modal.classList.remove('hidden');
    body.innerHTML = '<p class="empty">加载中…</p>';
    try {
      const rows = await engApi(`/models/${selectedModelId}/issue-print-logs?limit=40`);
      if (!rows.length) {
        body.innerHTML = '<p class="empty">暂无打印记录。自本次升级后，每次确认打印将自动留痕料号清单。</p>';
        return;
      }
      body.innerHTML = `<table class="data-table eng-print-history-table"><thead><tr>
        <th>打印时间</th><th>工序</th><th>操作人</th><th>订单量</th><th>行数</th><th>钢网/波峰</th><th>料号清单</th>
      </tr></thead><tbody>${rows.map((r) => {
        const codes = (r.material_codes || []).join('、');
        const tool = `${r.stencil_src || '—'}/${r.wave_src || '—'}`;
        return `<tr>
          <td>${formatReviewTodoTime(r.created_at)}</td>
          <td><strong>${escapeHtml(r.process_filter || '')}</strong></td>
          <td>${escapeHtml(r.operator || '—')}</td>
          <td>${r.order_qty != null ? r.order_qty : '—'}</td>
          <td>${r.material_count || 0}</td>
          <td class="muted">${escapeHtml(tool)}</td>
          <td class="cell-wrap muted" style="font-size:11px;max-width:420px">${escapeHtml(codes)}</td>
        </tr>`;
      }).join('')}</tbody></table>`;
    } catch (e) {
      body.innerHTML = `<p class="empty">${escapeHtml(e.message || '加载失败')}</p>`;
    }
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
      // 整张发料单只按料号（元件品号）升序，方便按料号拣料
      const sortedLines = [...lines].sort((a, b) =>
        cmpCode(a.material_code, b.material_code)
      );
      // 与 BOM 明细预览同源：优先用 lines 上已算好的 substitute_details / substitute_codes
      const subByComp = {};
      sortedLines.forEach((l) => {
        const key = String(l.material_code || '').trim().toUpperCase();
        if (!key) return;
        const details = Array.isArray(l.substitute_details) ? l.substitute_details : [];
        if (details.length) {
          const d0 = details[0] || {};
          const alt = String(d0.material_code || '').trim();
          if (!alt) return;
          subByComp[key] = {
            alt_code: alt,
            alt_name: String(d0.material_name || '').trim(),
            alt_spec: String(d0.spec || '').trim(),
            _score: 10,
          };
          return;
        }
        const alts = (l.substitute_codes || []).map((c) => String(c || '').trim()).filter(Boolean);
        if (!alts.length) return;
        subByComp[key] = { alt_code: alts[0], sub_code: alts[0], alt_name: '', alt_spec: '', _score: 10 };
      });
      // 可选：用已确认规则补规格（客户C另可补分板用量 qty）
      const cid = String(selectedModel.customer_id || '').trim();
      const isYonglian = cid === 'yonglian' || String(selectedModel.internal_code || '').trim() === 'A067';
      const modelCode = String(selectedModel.model_code || '').trim();
      const orderPo = String(selectedModel.purchase_no || '').trim();
      if (cid) {
        try {
          const params = new URLSearchParams({
            customer_id: cid,
            page: '1',
            page_size: '500',
          });
          if (modelCode) params.set('parent_code', modelCode);
          if (orderPo) params.set('keyword', orderPo);
          const rules = await engApi('/substitutions?' + params.toString());
          (rules || []).forEach((r) => {
            if (String(r.confirm_status || 'confirmed') === 'pending') return;
            const rPo = String(r.purchase_no || '').trim();
            if (rPo && orderPo && rPo !== orderPo) return;
            const pairs = [
              {
                bom: String(r.comp_code || '').trim().toUpperCase(),
                alt: String(r.sub_code || '').trim(),
                name: String(r.sub_name || '').trim(),
                spec: String(r.sub_spec || '').trim(),
              },
              {
                bom: String(r.sub_code || '').trim().toUpperCase(),
                alt: String(r.comp_code || '').trim(),
                name: String(r.comp_name || '').trim(),
                spec: String(r.comp_spec || '').trim(),
              },
            ];
            pairs.forEach((p) => {
              if (!p.bom || !p.alt) return;
              const hit = subByComp[p.bom];
              if (!hit) return;
              // 客户A等客户规则 qty=整单总需求，不能当单台用量；仅客户C用 qty 覆盖 BOM
              if (isYonglian && r.qty != null && r.qty !== '' && hit.qty == null) hit.qty = r.qty;
              if (!hit.alt_spec && p.spec) hit.alt_spec = p.spec;
              if (!hit.alt_name && p.name) hit.alt_name = p.name;
            });
          });
        } catch (_) { /* 补全失败仍按 BOM 打印 */ }
      }
      const hasSubMarks = Object.keys(subByComp).length > 0;
      const hasControlMarks = sortedLines.some((l) => l.source === 'control' || l.control_id);
      // 表头管制单号：按本订单+机型取已生效管制（失败不影响打印）
      let controlNosLabel = '—';
      try {
        const pn = String(selectedModel.purchase_no || '').trim();
        const mc = String(selectedModel.model_code || '').trim();
        if (pn) {
          const qs = new URLSearchParams();
          if (mc) qs.set('model_code', mc);
          const res = await fetch(
            `/api/material-controls/by-purchase/${encodeURIComponent(pn)}${qs.toString() ? `?${qs}` : ''}`,
            { headers: { ...window.EMS.authHeaders() } }
          );
          if (res.ok) {
            const rows = await res.json();
            const nos = [];
            const seen = new Set();
            for (const r of rows || []) {
              if (String(r.status || '') !== 'active') continue;
              const no = String(r.control_no || '').trim();
              if (!no || seen.has(no)) continue;
              seen.add(no);
              nos.push(no);
            }
            // 若 BOM 行带 control_id 但 by-purchase 未命中 active，补一行号展示
            if (!nos.length) {
              const ids = [...new Set(
                sortedLines.map((l) => l.control_id).filter((id) => id != null && id !== '')
              )];
              for (const cid of ids.slice(0, 8)) {
                try {
                  const cr = await fetch(`/api/material-controls/${cid}`, {
                    headers: { ...window.EMS.authHeaders() },
                  });
                  if (!cr.ok) continue;
                  const doc = await cr.json();
                  const no = String(doc.control_no || '').trim();
                  if (no && !seen.has(no)) {
                    seen.add(no);
                    nos.push(no);
                  }
                } catch (_) { /* ignore */ }
              }
            }
            if (nos.length) controlNosLabel = nos.join('、');
          }
        }
      } catch (_) { /* 管制查询失败仍打印发料单 */ }
      const printMaterials = sortedLines.map((l) => {
        const codeKey = String(l.material_code || '').trim().toUpperCase();
        const rule = subByComp[codeKey];
        const per = isYonglian && rule && rule.qty != null && rule.qty !== ''
          ? Number(rule.qty)
          : Number(l.qty_per ?? 0);
        const need = Math.round(per * orderQty * 10000) / 10000;
        return {
          material_code: l.material_code || '',
          material_name: l.material_name || '',
          spec: l.spec || '',
          unit: l.unit || 'PCS',
          qty_per: per,
          issue_qty: need,
          mount_type: l.mount_type || lineMountKind(l) || '',
          mount_side: l.mount_side || '',
          position: l.position || '',
        };
      });
      try {
        await engApi(`/models/${selectedModelId}/issue-print-log`, {
          method: 'POST',
          body: JSON.stringify({
            process_filter: processFilter,
            stencil_src: stencilSrc,
            wave_src: waveSrc,
            order_qty: orderQty,
            line_key: selectedModel.line_key || '',
            materials: printMaterials,
          }),
        });
      } catch (logErr) {
        console.warn('发料打印留痕失败', logErr);
      }
      const rowsHtml = sortedLines.map((l, idx) => {
        const codeKey = String(l.material_code || '').trim().toUpperCase();
        const rule = subByComp[codeKey];
        const per = isYonglian && rule && rule.qty != null && rule.qty !== ''
          ? Number(rule.qty)
          : Number(l.qty_per ?? 0);
        const need = Math.round(per * orderQty * 10000) / 10000;
        const isCtrl = l.source === 'control' || !!l.control_id;
        const codeCell = isCtrl
          ? `<span style="color:#c00;font-weight:700">${escapeHtml(l.material_code || '')}</span><div style="color:#c00;font-size:10px">变更</div>`
          : escapeHtml(l.material_code || '');
        const subCode = rule ? String(rule.alt_code || rule.sub_code || '').trim() : '';
        const subSpec = rule ? String(rule.alt_spec || '').trim() : '';
        // 用 br+span，避免 table 内嵌套 div 在部分打印机预览有、出纸无
        const subCell = subCode
          ? `<span class="eng-print-sub">${escapeHtml(subCode)}</span>${
              subSpec ? `<br><span class="eng-print-sub-spec">${escapeHtml(subSpec)}</span>` : ''
            }`
          : '';
        const nameText = l.material_name || (l.spec || '').split(' / ')[0] || '';
        return `<tr>
          <td>${idx + 1}</td>
          <td>${escapeHtml(printMountType(l.mount_type))}</td>
          <td>${escapeHtml(printMountSide(l.mount_side))}</td>
          <td>${codeCell}</td>
          <td class="eng-print-sub-cell">${subCell}</td>
          <td>${escapeHtml(nameText)}</td>
          <td class="cell-wrap">${escapeHtml(l.spec || '')}</td>
          <td>${escapeHtml(l.unit || 'PCS')}</td>
          <td>${per}</td>
          <td class="eng-kit-pos">${escapeHtml(l.position || '')}</td>
          <td>${need}</td>
          <td class="eng-print-note"></td>
          <td class="eng-print-note"></td>
        </tr>`;
      }).join('');
      const hints = [];
      if (hasControlMarks) hints.push('本单含管制变更料（红色「变更」），已按生效 BOM 发料');
      if (hasSubMarks) hints.push('本单含替代料，请按「投产/替代」栏备料（含替代规格）');
      const subHint = hints.length
        ? `<div class="head" style="color:#c00;font-size:12px;margin-top:-4px">${hints.join('；')}</div>`
        : '';
      const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>发料单 ${escapeHtml(processLabel)} ${escapeHtml(selectedModel.purchase_no || '')}</title>
<style>
  *{box-sizing:border-box}
  body{font-family:"SimSun","Songti SC","PingFang SC","Microsoft YaHei",serif;color:#111;margin:6px;font-size:11px}
  .head{margin:0 0 8px;line-height:1.7;font-size:15px;font-weight:700;text-align:center;word-spacing:2px}
  .tool{color:#c00;font-weight:700;margin:0 6px}
  table{width:100%;border-collapse:collapse;table-layout:fixed}
  th,td{border:1px solid #333;padding:2px 3px;text-align:center;vertical-align:top;word-break:break-all;overflow:visible}
  th{background:#d9d9d9;font-weight:700;vertical-align:middle}
  td:nth-child(6),td:nth-child(7),td:nth-child(10),td.eng-print-sub-cell{text-align:left;white-space:normal;line-height:1.35}
  td.eng-print-sub-cell{overflow:visible;min-height:1.6em}
  .eng-kit-pos{white-space:normal;word-break:break-all;line-height:1.3;font-size:10px}
  .eng-print-sub{color:#b00000;font-weight:700}
  .eng-print-sub-spec{display:inline;color:#111;font-size:10px;font-weight:600;line-height:1.3}
  .eng-print-note{min-height:22px}
  @media print{
    body{margin:4mm;font-size:10.5px}
    .no-print{display:none!important}
    /* 出纸强制深色：避免红字/小字被打印机省墨吞掉（预览有、纸上无） */
    .eng-print-sub{color:#000!important;font-weight:700!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
    .eng-print-sub-spec{color:#000!important;font-size:10px!important;font-weight:600!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
    td.eng-print-sub-cell{overflow:visible!important}
    @page{size:A4 landscape;margin:4mm}
  }
</style></head><body>
  <div class="head">
    客户: ${escapeHtml(factory)}
    &nbsp;&nbsp;${escapeHtml(selectedModel.model_code || '')}
    &nbsp;&nbsp;订单${orderQty}PCS
    <span class="tool">${escapeHtml(toolLabel)}</span>
    订单号：${escapeHtml(selectedModel.purchase_no || '—')}
    &nbsp;&nbsp;管制单号：${escapeHtml(controlNosLabel)}
    &nbsp;&nbsp;${escapeHtml(processLabel)}
  </div>
  ${subHint}
  <table>
    <thead>
      <tr>
        <th style="width:2.5%">序号</th>
        <th style="width:3.5%">贴装</th>
        <th style="width:3.5%">面别</th>
        <th style="width:8%">元件品号</th>
        <th style="width:16%">投产/替代</th>
        <th style="width:6%">元件品名</th>
        <th style="width:11%">元件规格</th>
        <th style="width:2.5%">单位</th>
        <th style="width:3.5%">用量</th>
        <th style="width:9%">插件位置</th>
        <th style="width:4%">需求</th>
        <th style="width:14%">发料数</th>
        <th style="width:12%">退料数</th>
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
      syncListReviewBadge(selectedModel, 'pending_review');
      const profileLabel = PROFILE_LABELS[sel?.value] || (sel?.value ? sel.value : '未选择');
      window.EMS.showToast(
        !sel?.value
          ? '已清空贴装画像；未选纯贴片/纯插件/混贴前不能审核通过，也不能打印发料单'
          : sel?.value === 'dip_only'
          ? `贴装画像已设为「${profileLabel}」，纯插件免贴片坐标；已进入待审核，请点「审核通过」或打开「BOM 资料审核」后通过`
          : `贴装画像已保存（${profileLabel}）；状态已改回待审核，请点「审核通过」`,
        'warning',
        6000,
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
      void syncAssetsForSelectedModel().catch(() => {});
      return;
    }
    kitBar?.classList.remove('hidden');
    if (tbody) tbody.innerHTML = '<tr><td colspan="11" class="empty">加载中…</td></tr>';
    try {
      const payload = normalizeLinesPayload(await engApi(`/models/${selectedModelId}/lines`));
      if (payload.eng_review_status) selectedModel.eng_review_status = payload.eng_review_status;
      updateDetailTitle(model, payload.lines, payload);
      renderBomLines(payload.lines, payload);
      // 坐标/Gerber/完备性后台加载，避免点订单后整页卡住
      void syncAssetsForSelectedModel().catch((err) => console.warn('工程资料同步失败', err));
      void loadMountReadiness({ silent: true }).catch(() => {});
    } catch (e) {
      profileBar?.classList.add('hidden');
      if (tbody) tbody.innerHTML = '<tr><td colspan="11" class="empty">明细加载失败</td></tr>';
      window.EMS.showToast('BOM 明细加载失败：' + e.message, 'error', 6000);
      clearMountReadinessPanel();
      void syncAssetsForSelectedModel().catch(() => {});
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

    // 客户D：1 份（纯 DIP/纯 SMT）或 2 份（SMT+DIP，不分先后）
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
      const isZip = /\.zip$/i.test(filename) || (res.headers.get('Content-Type') || '').includes('zip');
      window.EMS.showToast(isZip ? '已导出 BOM（含管制 PDF）' : 'BOM 已导出（含替代料/管制信息）');
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
      tbody.innerHTML = `<tr><td colspan="8" class="empty">${emptyMsg}</td></tr>`;
      return;
    }
    tbody.innerHTML = filtered.map((l) => {
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
          `${orderLabel}${kit.model_code || selectedModel?.model_code || ''}` +
          ` · 缺类型 ${missingType} · 待确认 ${unresolved}`;
        if (effectiveReviewStatus(selectedModel, dossier) === 'pending_review') {
          text += ' · 请核对贴装后点「审核通过」或「退回修正」';
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
  let engStatusBoard = { counts: {}, import_items: [], review_items: [], missing_breakdown: {} };

  function assetMark(ok) {
    return ok
      ? '<span class="eng-asset-ok" title="已导入">✓</span>'
      : '<span class="eng-asset-miss" title="未导入">缺</span>';
  }

  function missingChips(missing) {
    const list = missing || [];
    if (!list.length) return '<span class="muted">—</span>';
    return list.map((m) => `<span class="eng-miss-chip">${escapeHtml(m)}</span>`).join('');
  }

  function statusBoardKey(item) {
    return `${item?.purchase_no || ''}|${item?.model_code || ''}|${item?.bom_model_id || item?.id || ''}`;
  }

  function findImportGapForModel(model) {
    const items = engStatusBoard.import_items || [];
    const pn = String(model?.purchase_no || '').trim();
    const code = String(model?.model_code || '').trim();
    const id = model?.id || model?.bom_model_id || null;
    return items.find((it) => {
      if (id && it.bom_model_id && Number(it.bom_model_id) === Number(id)) return true;
      return String(it.purchase_no || '').trim() === pn && String(it.model_code || '').trim() === code;
    }) || null;
  }

  function renderStatusBoardBar() {
    const counts = engStatusBoard.counts || {};
    const br = engStatusBoard.missing_breakdown || {};
    const imp = Number(counts.pending_import || 0);
    const rev = Number(counts.pending_review || 0);
    const elImp = document.getElementById('eng-status-import-n');
    const elRev = document.getElementById('eng-status-review-n');
    const elBr = document.getElementById('eng-status-breakdown');
    if (elImp) elImp.textContent = String(imp);
    if (elRev) elRev.textContent = String(rev);
    if (elBr) {
      elBr.textContent = imp
        ? `缺项分布：BOM ${br.bom || 0} · 坐标 ${br.placement || 0} · Gerber ${br.gerber || 0}`
        : '当前客户无待导入缺项';
    }
    const tabImp = document.getElementById('eng-status-tab-import');
    const tabRev = document.getElementById('eng-status-tab-review');
    if (tabImp) tabImp.textContent = `待导入（${imp}）`;
    if (tabRev) tabRev.textContent = `待审核（${rev}）`;
  }

  function setStatusBoardTab(tab) {
    const isImport = tab !== 'review';
    document.getElementById('eng-status-panel-import')?.classList.toggle('hidden', !isImport);
    document.getElementById('eng-status-panel-review')?.classList.toggle('hidden', isImport);
    document.getElementById('eng-status-tab-import')?.classList.toggle('active', isImport);
    document.getElementById('eng-status-tab-review')?.classList.toggle('active', !isImport);
  }

  function renderStatusBoardModal() {
    const importBody = document.getElementById('eng-status-import-table');
    const reviewBody = document.getElementById('eng-status-review-table');
    const hint = document.getElementById('eng-status-board-modal-hint');
    const counts = engStatusBoard.counts || {};
    if (hint) {
      hint.textContent = `待导入 ${counts.pending_import || 0} 份 · 待审核 ${counts.pending_review || 0} 份。缺 BOM/坐标/Gerber 任一不能送审；每料须有工序与面别才能审核通过。`;
    }
    const imports = engStatusBoard.import_items || [];
    if (importBody) {
      if (!imports.length) {
        importBody.innerHTML = '<tr><td colspan="8" class="empty">暂无待导入资料</td></tr>';
      } else {
        importBody.innerHTML = imports.map((it, idx) => {
          const modelLabel = it.model_name
            ? `<strong>${escapeHtml(it.model_code || '—')}</strong><div class="muted" style="font-size:12px">${escapeHtml(it.model_name)}</div>`
            : `<strong>${escapeHtml(it.model_code || '—')}</strong>`;
          return `<tr>
            <td>${escapeHtml(it.internal_code || '—')}</td>
            <td>${modelLabel}</td>
            <td>${escapeHtml(it.purchase_no || '—')}</td>
            <td>${assetMark(!!it.has_bom)}</td>
            <td>${assetMark(!!it.has_placement)}</td>
            <td>${assetMark(!!it.has_gerber)}</td>
            <td>${missingChips(it.missing_imports)}</td>
            <td><button type="button" class="btn btn-primary btn-sm eng-status-open-import" data-idx="${idx}">去导入</button></td>
          </tr>`;
        }).join('');
        importBody.querySelectorAll('.eng-status-open-import').forEach((btn) => {
          btn.addEventListener('click', () => {
            const item = imports[Number(btn.dataset.idx)];
            if (!item) return;
            document.getElementById('eng-status-board-modal')?.classList.add('hidden');
            openReviewTodoItem({ ...item, todo_type: 'import' });
          });
        });
      }
    }
    const reviews = engStatusBoard.review_items || [];
    if (reviewBody) {
      if (!reviews.length) {
        reviewBody.innerHTML = '<tr><td colspan="6" class="empty">暂无待审核资料</td></tr>';
      } else {
        reviewBody.innerHTML = reviews.map((it, idx) => {
          const modelLabel = it.model_name
            ? `<strong>${escapeHtml(it.model_code || '—')}</strong><div class="muted" style="font-size:12px">${escapeHtml(it.model_name)}</div>`
            : `<strong>${escapeHtml(it.model_code || '—')}</strong>`;
          return `<tr>
            <td>${escapeHtml(it.internal_code || '—')}</td>
            <td>${modelLabel}</td>
            <td>${escapeHtml(it.purchase_no || '—')}</td>
            <td>${escapeHtml(it.submitter || '—')}</td>
            <td class="eng-todo-summary" title="${escapeHtml(it.summary || '')}">${escapeHtml(it.summary || '资料待审核')}</td>
            <td><button type="button" class="btn btn-primary btn-sm eng-status-open-review" data-idx="${idx}">去处理</button></td>
          </tr>`;
        }).join('');
        reviewBody.querySelectorAll('.eng-status-open-review').forEach((btn) => {
          btn.addEventListener('click', () => {
            const item = reviews[Number(btn.dataset.idx)];
            if (!item) return;
            document.getElementById('eng-status-board-modal')?.classList.add('hidden');
            openReviewTodoItem({ ...item, todo_type: 'review' });
          });
        });
      }
    }
  }

  async function loadEngStatusBoard({ silent = true, openModal = false, tab = '', detail = false } = {}) {
    const code = getActiveInternalCode() || '';
    const needDetail = !!(openModal || detail);
    const qs = new URLSearchParams();
    if (code) qs.set('internal_code', code);
    qs.set('detail', needDetail ? '1' : '0');
    try {
      const data = await engApi(`/status-board?${qs.toString()}`) || {};
      if (needDetail) {
        engStatusBoard = data;
      } else {
        engStatusBoard = {
          ...engStatusBoard,
          counts: data.counts || engStatusBoard.counts || {},
          missing_breakdown: data.missing_breakdown || engStatusBoard.missing_breakdown || {},
          // 轻量模式不覆盖明细，避免把已加载明细清空
          import_items: engStatusBoard.import_items || [],
          review_items: engStatusBoard.review_items || [],
        };
      }
      renderStatusBoardBar();
      if (openModal) {
        renderStatusBoardModal();
        if (tab) setStatusBoardTab(tab);
        document.getElementById('eng-status-board-modal')?.classList.remove('hidden');
      }
    } catch (e) {
      if (!silent) window.EMS.showToast(e.message || '加载资料进度失败', 'error');
    }
    return engStatusBoard;
  }

  function openEngStatusBoard(tab) {
    void loadEngStatusBoard({ silent: false, openModal: true, tab: tab || 'import', detail: true }).then(() => {
      renderStatusBoardModal();
      setStatusBoardTab(tab || 'import');
    });
  }

  function canReceiveTodoPush() {
    const u = window.EMS.getCurrentUser() || {};
    const role = u.role || '';
    const name = engUsername();
    // 仅查看导出账号不收待审/待导入推送
    if (isEngViewExportOnly() || name === 'dxpz001') return false;
    // 黄星待审；邱梦林/任玉娴待导入/退回；WGQ/其它管理员待审
    return (
      isEngImportOnly()
      || isEngAuditOnly()
      || role === 'admin'
      || role === 'engineering'
      || name === 'wgq'
      || name === 'dxsmt001'
      || name === 'dxgc'
      || name === 'dxgc002'
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
        ? (item.missing_label ? `缺 ${item.missing_label}` : (item.summary || '待导入'))
        : (item.submitter || '—');
      const summaryHtml = kind === 'import' && (item.missing_imports || []).length
        ? `${missingChips(item.missing_imports)} <span class="muted">${escapeHtml(item.summary || '')}</span>`
        : escapeHtml(item.summary || reviewTodoMeta.title || '待处理');
      const summaryCls = kind === 'rejected' ? 'eng-todo-summary eng-todo-summary-reject' : 'eng-todo-summary';
      const rowCls = kind === 'rejected' ? 'eng-todo-row-rejected' : '';
      return `
      <tr class="${rowCls}">
        <td>${todoTypeBadge(item)}</td>
        <td>${escapeHtml(item.internal_code || '—')}</td>
        <td>${modelLabel}</td>
        <td>${escapeHtml(item.purchase_no || '—')}</td>
        <td>${escapeHtml(who)}</td>
        <td title="${escapeHtml(item.summary || '')}" class="${summaryCls}">${summaryHtml}</td>
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
      const counts = engStatusBoard.counts || {};
      const imp = Number(counts.pending_import || 0);
      const rev = Number(counts.pending_review || 0);
      const n = reviewTodoItems.length;
      const urgent = (imp + rev) > 0 || n > 0 ? ' eng-review-banner-urgent' : '';
      banner.className = `eng-review-banner${urgent}`;
      banner.innerHTML = `待导入 <span class="eng-todo-badge">${imp}</span> · 待审核 <span class="eng-todo-badge">${rev}</span>`;
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
        const missHtml = kind === 'import' && (item.missing_imports || []).length
          ? `<div class="eng-todo-item-meta">${missingChips(item.missing_imports)}</div>`
          : `<div class="eng-todo-item-meta">${escapeHtml(item.summary || '')}</div>`;
        return `
        <div class="eng-todo-item${rejectCls}">
          <div class="eng-todo-item-main">
            <div class="eng-todo-item-title">${todoTypeBadge(item)} ${escapeHtml(item.internal_code || '')} · ${escapeHtml(item.model_code || '')} · 订单 ${escapeHtml(item.purchase_no || '—')}</div>
            ${missHtml}
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
      if (data?.counts) {
        engStatusBoard = {
          ...engStatusBoard,
          counts: data.counts,
          missing_breakdown: data.missing_breakdown || engStatusBoard.missing_breakdown || {},
        };
        renderStatusBoardBar();
      }
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
    reviewTodoTimer = setInterval(() => loadReviewInbox({ silent: false }), 60000);
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

  let lastEngAuditPayload = null;

  function renderEngAuditBody(payload) {
    const el = document.getElementById('eng-data-audit-body');
    if (!el) return;
    if (!payload) {
      el.innerHTML = '<p class="empty">暂无数据</p>';
      return;
    }
    const s = payload.summary || {};
    const orders = payload.affected_orders || [];
    const reprint = payload.reprint_recommendations || [];
    const leaks = (payload.bom_leak_all || []).filter((r) => r.status === 'leak');
    const orderRows = orders.slice(0, 80).map((o) => `
      <tr>
        <td>${escapeHtml(o.purchase_no || '—')}</td>
        <td>${escapeHtml(o.model_code || '—')}</td>
        <td>${o.order_qty ?? '—'}</td>
        <td>${o.issue_line_count ?? 0}</td>
        <td class="cell-wrap">${escapeHtml(o.sample_materials || '')}</td>
      </tr>`).join('');
    const reprintRows = reprint.slice(0, 40).map((r) => `
      <tr>
        <td>${escapeHtml(r.purchase_no || '')}</td>
        <td>${escapeHtml(r.material_code || '')}</td>
        <td>${escapeHtml(r.sub_code || '—')}</td>
        <td>${r.bom_qty_per ?? '—'}</td>
        <td>${r.correct_need ?? '—'}</td>
        <td style="color:#c00">${r.wrong_printed_qty_per ?? '—'}</td>
      </tr>`).join('');
    el.innerHTML = `
      <div style="line-height:1.7;margin-bottom:12px">
        <div><strong>发料用量风险</strong>：${s.substitution_qty_issue_count ?? 0} 行 / ${s.substitution_affected_orders ?? 0} 订单（客户A等，规则 qty=整单总数）</div>
        <div><strong>BOM 漏料对比</strong>：${s.bom_total ?? 0} 套，一致 ${s.bom_ok ?? 0}，漏料 <span style="color:${leaks.length ? '#c00' : 'inherit'}">${s.bom_leak ?? 0}</span>，无快照 ${s.bom_no_snapshot ?? 0}</div>
        <div><strong>历史误打留痕</strong>：${s.wrong_print_log_rows ?? 0} 条；建议重打 ${s.reprint_order_count ?? 0} 单</div>
        <div class="muted" style="font-size:12px;margin-top:4px">生成：${escapeHtml((payload.generated_at || '').replace('T', ' ').slice(0, 19))} UTC</div>
      </div>
      ${orders.length ? `<h3 style="margin:12px 0 6px;font-size:14px">受影响订单（${orders.length}）</h3>
      <div style="max-height:220px;overflow:auto">
        <table class="data-table"><thead><tr>
          <th>订单号</th><th>机型</th><th>订单量</th><th>风险料数</th><th>示例料号</th>
        </tr></thead><tbody>${orderRows}</tbody></table>
      </div>` : ''}
      ${reprint.length ? `<h3 style="margin:12px 0 6px;font-size:14px">建议重打发料单（${reprint.length} 料）</h3>
      <div style="max-height:180px;overflow:auto">
        <table class="data-table"><thead><tr>
          <th>订单号</th><th>BOM料号</th><th>替代料</th><th>正确用量</th><th>正确需求</th><th>曾误打用量</th>
        </tr></thead><tbody>${reprintRows}</tbody></table>
      </div>` : ''}
      ${leaks.length ? `<p style="color:#c00;margin-top:10px">漏料 BOM ${leaks.length} 套，请下载 Excel 查看明细。</p>` : ''}
    `;
  }

  async function runEngDataAudit() {
    const btn = document.getElementById('btn-eng-data-audit-run');
    const body = document.getElementById('eng-data-audit-body');
    if (body) body.innerHTML = '<p class="empty">自查中，请稍候…</p>';
    if (btn) btn.disabled = true;
    try {
      const payload = await engApi('/audit/data-integrity');
      lastEngAuditPayload = payload;
      renderEngAuditBody(payload);
      window.EMS.showToast('工程资料自查完成', 'success', 4000);
    } catch (e) {
      if (body) body.innerHTML = `<p class="empty" style="color:#c00">${escapeHtml(e.message || '自查失败')}</p>`;
      window.EMS.showToast(e.message || '自查失败', 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function openEngDataAuditModal() {
    document.getElementById('eng-data-audit-modal')?.classList.remove('hidden');
    if (lastEngAuditPayload) {
      renderEngAuditBody(lastEngAuditPayload);
    }
  }

  async function downloadEngAuditXlsx() {
    try {
      const res = await fetch(API + '/audit/data-integrity.xlsx', { headers: { ...window.EMS.authHeaders() } });
      if (!res.ok) throw new Error('下载失败');
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `工程资料自查_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.xlsx`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      window.EMS.showToast(e.message || '下载失败', 'error');
    }
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
    document.getElementById('btn-eng-data-audit')?.addEventListener('click', openEngDataAuditModal);
    document.getElementById('btn-eng-data-audit-run')?.addEventListener('click', runEngDataAudit);
    document.getElementById('btn-eng-data-audit-xlsx')?.addEventListener('click', downloadEngAuditXlsx);
    document.getElementById('btn-eng-data-audit-close')?.addEventListener('click', () => {
      document.getElementById('eng-data-audit-modal')?.classList.add('hidden');
    });
    document.getElementById('btn-eng-search')?.addEventListener('click', loadModels);
    document.getElementById('eng-search')?.addEventListener('keydown', e => { if (e.key === 'Enter') loadModels(); });
    document.getElementById('eng-filter-code')?.addEventListener('change', loadModels);
    document.getElementById('eng-review-banner')?.addEventListener('click', openReviewTodoModal);
    document.getElementById('btn-eng-todo-refresh')?.addEventListener('click', () => {
      loadReviewInbox({ silent: true });
      loadEngStatusBoard({ silent: true });
    });
    document.getElementById('btn-eng-status-detail')?.addEventListener('click', () => openEngStatusBoard('import'));
    document.getElementById('eng-status-chip-import')?.addEventListener('click', () => openEngStatusBoard('import'));
    document.getElementById('eng-status-chip-review')?.addEventListener('click', () => openEngStatusBoard('review'));
    document.getElementById('eng-status-tab-import')?.addEventListener('click', () => setStatusBoardTab('import'));
    document.getElementById('eng-status-tab-review')?.addEventListener('click', () => setStatusBoardTab('review'));
    document.getElementById('btn-eng-status-board-close')?.addEventListener('click', () => {
      document.getElementById('eng-status-board-modal')?.classList.add('hidden');
    });
    document.getElementById('btn-eng-review-inbox-close')?.addEventListener('click', () => {
      document.getElementById('eng-review-inbox-modal')?.classList.add('hidden');
    });
    document.getElementById('btn-eng-review-auto-run')?.addEventListener('click', async () => {
      if (!canEngAudit()) {
        window.EMS.showToast('无审核权限', 'error');
        return;
      }
      const btn = document.getElementById('btn-eng-review-auto-run');
      const modal = document.getElementById('eng-auto-review-progress-modal');
      const bar = document.getElementById('eng-auto-review-progress-bar');
      const textEl = document.getElementById('eng-auto-review-progress-text');
      const statsEl = document.getElementById('eng-auto-review-progress-stats');
      const setProgress = (pct, text, stats) => {
        if (bar) bar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
        if (textEl && text) textEl.textContent = text;
        if (statsEl && stats != null) statsEl.textContent = stats;
      };
      const CHUNK = 8;
      let afterId = 0;
      let total = 0;
      let processed = 0;
      let approved = 0;
      let skipped = 0;
      if (btn) btn.disabled = true;
      modal?.classList.remove('hidden');
      setProgress(2, '正在启动自动审核…', '');
      try {
        while (true) {
          const data = await engApi(
            `/review-auto-run?limit=${CHUNK}&after_id=${afterId}`,
            { method: 'POST', body: '{}' },
          );
          if (!total) total = Number(data.total_pending || 0) || Number(data.scanned || 0);
          processed += Number(data.scanned || 0);
          approved += Number(data.approved || 0);
          skipped += Number(data.skipped || 0);
          afterId = Number(data.next_after_id || afterId);
          const pct = total > 0 ? Math.min(99, Math.round((processed / total) * 100)) : 50;
          setProgress(
            pct,
            data.done && processed >= total ? '正在汇总结果…' : `正在审核 ${processed}/${total || '…'}…`,
            `已通过 ${approved} · 仍待审 ${skipped}`,
          );
          if (data.done || !data.scanned) break;
        }
        setProgress(100, '自动审核完成', `扫描 ${processed} · 通过 ${approved} · 仍待审 ${skipped}`);
        await new Promise((r) => setTimeout(r, 350));
        window.EMS.showToast(
          `自动审核完成：扫描 ${processed}，通过 ${approved}，仍待审 ${skipped}`,
          'success',
        );
        await loadReviewInbox({ silent: true });
        renderReviewTodoList('eng-review-inbox-table');
        if (typeof loadModels === 'function') loadModels();
      } catch (e) {
        window.EMS.showToast(e.message || '自动审核失败', 'error');
      } finally {
        modal?.classList.add('hidden');
        if (bar) bar.style.width = '0%';
        if (btn) btn.disabled = false;
      }
    });
    document.getElementById('btn-eng-kitting')?.addEventListener('click', showKitting);
    document.getElementById('btn-eng-print-issue')?.addEventListener('click', printIssueSlip);
    document.getElementById('btn-eng-print-history')?.addEventListener('click', showIssuePrintHistory);
    document.getElementById('btn-eng-print-history-close')?.addEventListener('click', () => {
      document.getElementById('eng-print-history-modal')?.classList.add('hidden');
    });
    document.getElementById('btn-eng-issue-print-ok')?.addEventListener('click', doPrintIssueSlip);
    document.getElementById('btn-eng-issue-print-cancel')?.addEventListener('click', () => {
      document.getElementById('eng-issue-print-modal')?.classList.add('hidden');
    });
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
    document.getElementById('btn-tda-detail-close')?.addEventListener('click', closeTdaDetailModal);
    document.getElementById('btn-tda-detail-cancel')?.addEventListener('click', closeTdaDetailModal);
    document.getElementById('btn-tda-detail-save')?.addEventListener('click', saveTdaDetailModal);
    document.getElementById('btn-eng-proc-search')?.addEventListener('click', loadProcModels);
    document.getElementById('eng-proc-search')?.addEventListener('keydown', e => { if (e.key === 'Enter') loadProcModels(); });
    // eng-proc-filter-code 的 change 由 bindProcFilterCustomer 统一处理（避免先按旧客户回写下拉）
    document.getElementById('btn-eng-proc-sync')?.addEventListener('click', syncProcessRoutes);
    document.getElementById('btn-eng-proc-new')?.addEventListener('click', newProcModel);
    document.getElementById('btn-eng-proc-save')?.addEventListener('click', saveProcRoute);
    document.getElementById('btn-eng-proc-delete')?.addEventListener('click', deleteProcRoute);
    document.getElementById('btn-eng-place-import')?.addEventListener('click', importPlacement);
    document.getElementById('btn-eng-place-export')?.addEventListener('click', exportPlacement);
    document.getElementById('btn-eng-gerber-export')?.addEventListener('click', exportGerber);
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
