<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">{{ pageTitle }}</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            点击订单号进入工作台过站/入库；列表仅查进度与筛选，不影响 PDA 扫码
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
          <el-button v-if="canManualOrder" @click="manualOpen = true">手动录单</el-button>
          <el-badge :value="hubInboxCount" :hidden="!hubInboxCount" :max="99">
            <el-button plain @click="openHubInbox">待我处理</el-button>
          </el-badge>
          <el-badge :value="newOrderCount" :hidden="!newOrderCount" :max="99">
            <el-button type="warning" plain @click="openNewOrdersDialog()">新订单</el-button>
          </el-badge>
          <el-button v-if="canManage" type="primary" :loading="syncing" @click="onSync">立即同步</el-button>
        </div>
      </div>

      <div class="erp-page-body">
        <el-form :inline="true" class="orders-filter" @submit.prevent="onSearch">
          <el-form-item label="客户">
            <el-select v-model="filters.customer_id" clearable placeholder="全部客户" style="width: 140px" @change="onCustomerChange">
              <el-option v-for="c in customers" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="filters.keyword"
              placeholder="订单号 / 机型料号 / 品名"
              clearable
              style="width: 260px"
              @keyup.enter="onSearch"
            />
          </el-form-item>
          <el-form-item label="结案">
            <el-select v-model="filters.completed" style="width: 120px">
              <el-option label="全部" value="all" />
              <el-option label="进行中" value="incomplete" />
              <el-option label="已结案" value="completed" />
            </el-select>
          </el-form-item>
          <el-form-item label="SRM状态">
            <el-select v-model="filters.srm_status" clearable placeholder="全部" style="width: 150px">
              <el-option v-for="s in statusOptions" :key="s.name" :label="`${s.name} (${s.count})`" :value="s.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="收货">
            <el-select v-model="filters.receive_filter" style="width: 130px">
              <el-option label="全部" value="all" />
              <el-option label="有未收货" value="unreceived" />
              <el-option label="有已收货" value="received" />
              <el-option label="未交货" value="undelivered" />
            </el-select>
          </el-form-item>
          <el-form-item label="管制">
            <el-select v-model="filters.controlled" style="width: 120px">
              <el-option label="全部" value="all" />
              <el-option label="仅管制" value="yes" />
              <el-option label="非管制" value="no" />
            </el-select>
          </el-form-item>
          <el-form-item label="新订单">
            <el-select v-model="newOnlyFilter" style="width: 140px" @change="onNewOnlyChange">
              <el-option label="全部" value="all" />
              <el-option label="近3天新订单" value="yes" />
            </el-select>
          </el-form-item>
          <el-form-item label="下单日期">
            <el-date-picker v-model="filters.date_from" type="date" value-format="YYYY-MM-DD" placeholder="起" style="width: 140px" />
            <span style="margin: 0 6px">至</span>
            <el-date-picker v-model="filters.date_to" type="date" value-format="YYYY-MM-DD" placeholder="止" style="width: 140px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="onSearch">查询</el-button>
            <el-button @click="onReset">重置</el-button>
            <el-button @click="onExport">导出 XLSX</el-button>
          </el-form-item>
        </el-form>

        <el-table
          v-loading="loading"
          :data="orders"
          class="orders-table"
          stripe
          border
          size="small"
          style="width: 100%"
          :row-class-name="rowClassName"
          max-height="calc(100vh - 320px)"
        >
          <el-table-column prop="customer_name" label="客户" width="48" show-overflow-tooltip />
          <el-table-column prop="purchase_no" label="订单号" width="148" show-overflow-tooltip>
            <template #default="{ row }">
              <el-button link type="primary" @click="goHub(row)">{{ row.purchase_no }}</el-button>
              <el-tag v-if="row.is_new_order" type="danger" size="small" effect="dark" class="new-order-tag">新</el-tag>
              <el-tag v-if="hubInboxKeys.has(row.line_key)" type="warning" size="small" effect="plain">待我</el-tag>
              <el-tag v-if="dueBadge(row) === 'overdue'" type="danger" size="small" effect="plain">超期</el-tag>
              <el-tag v-else-if="dueBadge(row) === 'due_soon'" type="warning" size="small" effect="plain">临期</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="product_goods_no" label="料号" width="118" show-overflow-tooltip />
          <el-table-column label="品名/规格" min-width="120" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="orders-name-cell">
                <span class="orders-name-main">{{ row.product_goods_name || '—' }}</span>
                <span v-if="row.product_spec" class="orders-name-spec">{{ row.product_spec }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="数量" width="44" align="right">
            <template #default="{ row }">{{ orderQty(row) }}</template>
          </el-table-column>
          <el-table-column label="齐套" width="56" align="center">
            <template #default="{ row }">
              <template v-if="row.customer_kit_status !== 'na'">
                <el-tag
                  :type="kitTagType(row.customer_kit_status)"
                  size="small"
                  :title="`${row.collected_sets_qty || 0}/${orderQty(row)}套`"
                >
                  {{ row.customer_kit_status_label || row.customer_kit_status }}
                </el-tag>
              </template>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="交货" width="42" align="right">
            <template #default="{ row }">{{ fmtQty(row.delivery_qty, row.is_completed && !row.delivery_qty) }}</template>
          </el-table-column>
          <el-table-column label="收货" width="42" align="right">
            <template #default="{ row }">{{ fmtQty(row.receive_qty, row.is_completed && !row.receive_qty) }}</template>
          </el-table-column>
          <el-table-column label="未收" width="42" align="right">
            <template #default="{ row }">{{ row.is_completed ? fmtQty(0, true) : (row.un_receive_qty ?? 0) }}</template>
          </el-table-column>
          <el-table-column label="SMT-AOI" width="78" align="right">
            <template #default="{ row }">
              <el-button
                v-if="(row.aoi_test_qty || 0) > 0"
                link
                type="primary"
                @click="openBoards(row)"
              >
                <strong>{{ row.aoi_test_qty }}</strong>
              </el-button>
              <span v-else class="cell-muted">0</span>
            </template>
          </el-table-column>
          <el-table-column label="插件" width="48" align="right">
            <template #default="{ row }">
              <el-button
                v-if="(row.plugin_qty || 0) > 0"
                link
                type="primary"
                @click="openProcessList(row, 'plugin')"
              >
                <strong>{{ row.plugin_qty }}</strong>
              </el-button>
              <span v-else class="cell-muted">0</span>
            </template>
          </el-table-column>
          <el-table-column label="炉前AOI" width="78" align="right">
            <template #default="{ row }">
              <el-button
                v-if="(row.pre_oven_aoi_qty || 0) > 0"
                link
                type="primary"
                @click="openPreOvenAoiBoards(row)"
              >
                <strong>{{ row.pre_oven_aoi_qty }}</strong>
              </el-button>
              <span v-else class="cell-muted">0</span>
            </template>
          </el-table-column>
          <el-table-column label="后焊" width="48" align="right">
            <template #default="{ row }">
              <el-button
                v-if="(row.post_solder_qty || 0) > 0"
                link
                type="primary"
                @click="openProcessList(row, 'post_solder')"
              >
                <strong>{{ row.post_solder_qty }}</strong>
              </el-button>
              <span v-else class="cell-muted">0</span>
            </template>
          </el-table-column>
          <el-table-column label="ICT" width="44" align="right">
            <template #default="{ row }">
              <el-button
                v-if="(row.ict_test_qty || 0) > 0"
                link
                type="primary"
                @click="openIctBoards(row)"
              >
                <strong>{{ row.ict_test_qty }}</strong>
              </el-button>
              <span v-else class="cell-muted">0</span>
            </template>
          </el-table-column>
          <el-table-column label="三防" width="48" align="right">
            <template #default="{ row }">
              <el-button
                v-if="(row.coating_qty || 0) > 0"
                link
                type="primary"
                @click="openProcessList(row, 'coating')"
              >
                <strong>{{ row.coating_qty }}</strong>
              </el-button>
              <span v-else class="cell-muted">0</span>
            </template>
          </el-table-column>
          <el-table-column label="入库" width="48" align="right">
            <template #default="{ row }">
              <el-button
                v-if="inboundQty(row) > 0"
                link
                type="primary"
                :title="`入库 ${inboundQty(row)} = 待发 ${row.pending_ship_qty || 0} + 待审 ${row.awaiting_ship_qty || 0} + 已发 ${row.shipped_local_qty || 0}；今日发 ${row.shipped_today_qty || 0}；点击查看/导出编码`"
                @click="openInboundDetail(row)"
              >
                <strong>{{ inboundQty(row) }}</strong>
              </el-button>
              <span v-else class="cell-muted">0</span>
            </template>
          </el-table-column>
          <el-table-column label="今日发" width="56" align="right">
            <template #default="{ row }">
              <strong
                v-if="(row.shipped_today_qty || 0) > 0"
                :title="'本单今日已确认发货（不含历史补录）'"
              >{{ row.shipped_today_qty }}</strong>
              <span v-else class="cell-muted">0</span>
            </template>
          </el-table-column>
          <el-table-column label="累计发" width="56" align="right">
            <template #default="{ row }">
              <strong
                v-if="(row.shipped_local_qty || 0) > 0"
                :title="'本单累计已确认发货（含历史补录）'"
              >{{ row.shipped_local_qty }}</strong>
              <span v-else class="cell-muted">0</span>
            </template>
          </el-table-column>
          <el-table-column label="下单" width="78" align="center">
            <template #default="{ row }">{{ fmtDay(row.purchase_date) }}</template>
          </el-table-column>
          <el-table-column label="交期" width="78" align="center">
            <template #default="{ row }">{{ fmtDay(row.expect_arrival_date) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="68" align="center">
            <template #default="{ row }">
              <el-tag :type="row.is_completed ? 'success' : 'warning'" size="small" :title="row.srm_status_name || ''">
                {{ shortStatus(row) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="管制" width="72" align="center">
            <template #default="{ row }">
              <template v-if="row.is_controlled || (row.control_nos && row.control_nos.length)">
                <el-button link type="danger" size="small" @click="openControlDetail(row)">管制</el-button>
              </template>
              <template v-else-if="row.has_control || (row.control_draft_nos && row.control_draft_nos.length)">
                <el-button link type="warning" size="small" @click="openControlDetail(row)">草稿</el-button>
              </template>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="备注" width="96">
            <template #default="{ row }">
              <el-input
                v-model="row.remark"
                size="small"
                placeholder="备注"
                :disabled="savingRemarkKey === row.line_key"
                @blur="saveRemark(row)"
                @keyup.enter="($event.target as HTMLInputElement)?.blur()"
              />
            </template>
          </el-table-column>
        </el-table>

        <div class="orders-pagination">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="total"
            :page-sizes="[50, 100, 200, 500]"
            layout="total, sizes, prev, pager, next"
            background
            @current-change="loadOrders"
            @size-change="onPageSizeChange"
          />
        </div>
      </div>
    </div>

    <ManualOrderDialog v-model="manualOpen" @saved="onManualSaved" />
    <el-drawer v-model="processListOpen" :title="processListTitle" size="560px">
      <div v-loading="processListLoading">
        <el-input
          v-model="processListKeyword"
          placeholder="条码搜索"
          clearable
          style="margin-bottom: 12px"
          @keyup.enter="reloadProcessList"
          @clear="reloadProcessList"
        >
          <template #append>
            <el-button @click="reloadProcessList">搜索</el-button>
          </template>
        </el-input>
        <div class="boards-summary">合计 {{ processListTotal }}</div>
        <el-table :data="processListItems" size="small" border stripe max-height="520" empty-text="暂无扫码记录">
          <el-table-column prop="barcode" label="条码" min-width="180" show-overflow-tooltip />
          <el-table-column prop="operator" label="操作人" width="90" />
          <el-table-column prop="scanned_at" label="时间" width="160" />
        </el-table>
      </div>
    </el-drawer>

    <el-drawer v-model="inboundOpen" :title="inboundTitle" size="780px">
      <div v-loading="inboundLoading">
        <div class="boards-summary">
          <span>合计 {{ inboundTotal }}</span>
          <el-tag
            type="warning"
            size="small"
            class="boards-result-tag"
            :class="{ active: inboundStatusFilter === 'pending' }"
            @click="onInboundStatusFilter('pending')"
          >
            待发 {{ inboundPendingCount }}
          </el-tag>
          <el-tag
            type="success"
            size="small"
            class="boards-result-tag"
            :class="{ active: inboundStatusFilter === 'shipped' }"
            @click="onInboundStatusFilter('shipped')"
          >
            已出库 {{ inboundShippedCount }}
          </el-tag>
          <el-tag
            type="info"
            size="small"
            class="boards-result-tag"
            :class="{ active: inboundStatusFilter === 'all' }"
            @click="onInboundStatusFilter('all')"
          >
            全部
          </el-tag>
          <el-button type="primary" plain size="small" :loading="inboundExporting" @click="onExportInbound">
            导出入库明细
          </el-button>
          <el-button size="small" :disabled="!inboundItems.length" @click="onCopyInboundCodes">
            复制编码
          </el-button>
        </div>
        <h4 class="inbound-box-h">
          本单入箱
          <el-button link type="primary" size="small" @click="router.push('/warehouse/pack-boxes')">
            打开批次记录
          </el-button>
        </h4>
        <el-table
          :data="inboundBoxes"
          size="small"
          border
          stripe
          empty-text="本单还没有入箱记录。请在「包装扫码」里先填每箱数量再扫板，扫满或点本箱装完后会出现。"
          style="margin-bottom: 14px"
        >
          <el-table-column prop="box_no" label="箱号" min-width="160" />
          <el-table-column label="数量" width="110" align="right">
            <template #default="{ row }">{{ row.qty }} / {{ row.qty_target || row.qty }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">{{ inboundBoxStatus(row.status) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120" align="center">
            <template #default="{ row }">
              <span v-if="isBoxLabelPrinted(row)" class="muted">已打印</span>
              <el-button
                v-else-if="row.status && row.status !== 'open'"
                link
                type="primary"
                size="small"
                @click="printInboundBox(row.box_no)"
              >
                打印二维码
              </el-button>
              <span v-else class="muted">装箱中</span>
            </template>
          </el-table-column>
        </el-table>
        <el-input
          v-model="inboundKeyword"
          placeholder="条码 / 箱号 BX-…"
          clearable
          style="margin: 8px 0 12px"
          @keyup.enter="reloadInboundDetail"
          @clear="reloadInboundDetail"
        >
          <template #append>
            <el-button @click="reloadInboundDetail">搜索</el-button>
          </template>
        </el-input>
        <el-table
          :data="inboundItems"
          size="small"
          border
          stripe
          max-height="520"
          empty-text="暂无入库编码"
        >
          <el-table-column prop="barcode" label="条码/编码" min-width="180" show-overflow-tooltip />
          <el-table-column label="箱号" min-width="150" show-overflow-tooltip>
            <template #default="{ row }">
              <el-button
                v-if="row.box_no"
                link
                type="primary"
                size="small"
                @click="openBoxTrace(row.box_no)"
              >
                {{ row.box_no }}
              </el-button>
              <span v-else class="muted">未装箱</span>
            </template>
          </el-table-column>
          <el-table-column prop="status_label" label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.status === 'pending' ? 'warning' : row.status === 'shipped' ? 'success' : 'info'"
              >
                {{ row.status_label || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="operator" label="操作人" width="90" show-overflow-tooltip />
          <el-table-column prop="scanned_at" label="入库时间" width="160" show-overflow-tooltip />
          <el-table-column prop="shipped_at" label="出库时间" width="160" show-overflow-tooltip />
          <el-table-column prop="code_type" label="码类型" width="80" show-overflow-tooltip />
        </el-table>
      </div>
    </el-drawer>

    <el-drawer v-model="controlDrawerOpen" title="管制详情" size="860px">
      <div v-loading="controlLoading">
        <template v-if="controlRows.length">
          <div v-for="c in controlRows" :key="c.id" class="control-block">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="管制单号">{{ c.control_no }}</el-descriptions-item>
              <el-descriptions-item label="本工单机型">
                {{ groupsForPurchase(c).map((g) => g.model_code).join('、') || '—' }}
              </el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag size="small" :type="c.status === 'active' ? 'success' : c.status === 'draft' ? 'warning' : 'info'">
                  {{ c.status === 'active' ? '已生效' : c.status === 'draft' ? '草稿（待确认）' : c.status }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="录入帐号">{{ c.created_by || '—' }}</el-descriptions-item>
              <el-descriptions-item label="录入时间">{{ formatControlDt(c.created_at) }}</el-descriptions-item>
              <el-descriptions-item label="确认帐号">{{ c.confirmed_by || '—' }}</el-descriptions-item>
              <el-descriptions-item label="确认时间">{{ formatControlDt(c.confirmed_at) }}</el-descriptions-item>
              <el-descriptions-item label="放入的料">{{ controlAddSummary(c) }}</el-descriptions-item>
              <el-descriptions-item label="ECN">{{ c.ecn_no || '—' }}</el-descriptions-item>
              <el-descriptions-item label="原因">{{ c.reason || '—' }}</el-descriptions-item>
              <el-descriptions-item label="原件">
                <a
                  v-if="c.attachment_path"
                  :href="controlAttachmentHref(c.id)"
                  target="_blank"
                  rel="noopener"
                >{{ c.attachment_name || '查看附件' }}</a>
                <span v-else>—</span>
              </el-descriptions-item>
            </el-descriptions>
            <template v-if="groupsForPurchase(c).length">
              <div v-for="(g, gi) in groupsForPurchase(c)" :key="`${c.id}-${gi}`" class="control-group">
                <h4 style="margin: 12px 0 6px">换料明细（删掉 → 放入）· {{ g.model_code }} · 共 {{ g.changes?.length || 0 }} 行</h4>
                <el-table :data="g.changes" size="small" border class="control-change-table">
                  <el-table-column prop="remove_code" label="删掉的料" min-width="120" />
                  <el-table-column prop="remove_qty" label="删量" width="64" />
                  <el-table-column label="删位号" min-width="160">
                    <template #default="{ row }">
                      <span class="control-refdes">{{ row.remove_refdes || '—' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="add_code" label="放入的料" min-width="120" />
                  <el-table-column prop="add_qty" label="放量" width="64" />
                  <el-table-column label="放位号" min-width="160">
                    <template #default="{ row }">
                      <span class="control-refdes">{{ row.add_refdes || '—' }}</span>
                    </template>
                  </el-table-column>
                </el-table>
                <h4 style="margin: 12px 0 6px">管制数量（本工单）</h4>
                <el-table
                  :data="g.orders.filter((o) => o.purchase_no === controlPurchaseNo)"
                  size="small"
                  border
                >
                  <el-table-column prop="purchase_no" label="订单号" />
                  <el-table-column prop="control_qty" label="管制数量" width="100" />
                </el-table>
              </div>
            </template>
            <el-empty v-else description="本工单未匹配到机型分组换料" :image-size="64" />
          </div>
        </template>
        <el-empty v-else-if="!controlLoading" description="暂无管制记录" />
      </div>
    </el-drawer>

    <el-drawer v-model="boardsOpen" title="SMT-AOI测试数据" size="720px">
      <div v-loading="boardsLoading">
        <div v-if="boardsSummary" class="boards-summary">
          <span>合计 {{ boardsSummary.total }}</span>
          <el-tag
            type="success"
            size="small"
            class="boards-result-tag boards-pass-tag"
            :class="{ active: boardsResultFilter === 'PASS' }"
            @click="onClickPass"
          >
            PASS {{ boardsSummary.pass_count }}
          </el-tag>
          <el-tag
            type="danger"
            size="small"
            class="boards-result-tag boards-fail-tag"
            :class="{ active: boardsResultFilter === 'FAIL' }"
            @click="onClickFail"
          >
            FAIL {{ boardsSummary.fail_count }}
          </el-tag>
          <el-tag type="info" size="small">其他 {{ boardsSummary.unknown_count }}</el-tag>
          <el-button
            v-if="(boardsSummary.fail_count || 0) > 0"
            type="danger"
            plain
            size="small"
            :loading="boardsExporting"
            @click="onExportFail"
          >
            导出 FAIL
          </el-button>
        </div>
        <el-input
          v-model="boardsKeyword"
          placeholder="输入条码查询明细"
          clearable
          style="margin: 8px 0 12px"
          @keyup.enter="onSearchBoards"
          @clear="onClearBoardsSearch"
        >
          <template #append>
            <el-button @click="onSearchBoards">搜索</el-button>
          </template>
        </el-input>
        <div v-if="boardsSummary?.laser_batches?.length" class="boards-batches">
          <div v-for="b in boardsSummary.laser_batches" :key="b.id" class="boards-batch-line">
            镭雕 {{ b.laser_date }} · {{ b.model_code }} · 流水
            {{ String(b.seq_from).padStart(5, '0') }}-{{ String(b.seq_to).padStart(5, '0') }}
          </div>
        </div>
        <div v-if="!showBoardsTable" class="boards-empty-hint">
          默认不展示明细。搜索条码可查单板；点击上方 <strong>PASS</strong> / <strong>FAIL</strong> 可查看本单对应板码。
        </div>
        <template v-else>
          <div class="boards-detail-bar">
            <span v-if="boardsResultFilter === 'PASS'">PASS 明细（{{ boardsSummary?.items?.length || 0 }}）</span>
            <span v-else-if="boardsResultFilter === 'FAIL'">不良明细（{{ boardsSummary?.items?.length || 0 }}）</span>
            <span v-else>搜索结果（{{ boardsSummary?.items?.length || 0 }}）</span>
            <el-button link type="primary" @click="onClearBoardsDetail">收起明细</el-button>
          </div>
          <el-table
            :data="boardsSummary?.items || []"
            size="small"
            border
            stripe
            max-height="520"
            empty-text="未找到匹配板码"
          >
            <el-table-column prop="barcode" label="PCBA编码" min-width="180" show-overflow-tooltip />
            <el-table-column prop="result" label="AOI" width="80">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="row.result === 'PASS' ? 'success' : row.result === 'FAIL' ? 'danger' : 'info'"
                >
                  {{ row.result }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="side" label="面" width="50" />
            <el-table-column prop="laser_date" label="日期" width="80" />
            <el-table-column prop="seq" label="流水" width="70" />
            <el-table-column prop="tested_at" label="测试时间" width="150" show-overflow-tooltip />
          </el-table>
        </template>
      </div>
    </el-drawer>

    <el-drawer v-model="preOvenOpen" title="炉前AOI测试数据" size="720px">
      <div v-loading="preOvenLoading">
        <div v-if="preOvenSummary" class="boards-summary">
          <span>合计 {{ preOvenSummary.total }}</span>
          <el-tag
            type="success"
            size="small"
            class="boards-result-tag boards-pass-tag"
            :class="{ active: preOvenResultFilter === 'PASS' }"
            @click="onClickPreOvenPass"
          >
            PASS {{ preOvenSummary.pass_count }}
          </el-tag>
          <el-tag
            type="danger"
            size="small"
            class="boards-result-tag boards-fail-tag"
            :class="{ active: preOvenResultFilter === 'FAIL' }"
            @click="onClickPreOvenFail"
          >
            FAIL {{ preOvenSummary.fail_count }}
          </el-tag>
          <el-tag type="info" size="small">其他 {{ preOvenSummary.unknown_count }}</el-tag>
          <el-button
            v-if="(preOvenSummary.fail_count || 0) > 0"
            type="danger"
            plain
            size="small"
            :loading="preOvenExporting"
            @click="onExportPreOvenFail"
          >
            导出 FAIL
          </el-button>
        </div>
        <el-input
          v-model="preOvenKeyword"
          placeholder="输入条码查询明细"
          clearable
          style="margin: 8px 0 12px"
          @keyup.enter="onSearchPreOven"
          @clear="onClearPreOvenSearch"
        >
          <template #append>
            <el-button @click="onSearchPreOven">搜索</el-button>
          </template>
        </el-input>
        <div v-if="preOvenModelCode" class="boards-batches">
          <div class="boards-batch-line">料号 {{ preOvenModelCode }}</div>
        </div>
        <div v-if="!showPreOvenTable" class="boards-empty-hint">
          默认不展示明细。搜索条码可查单板；点击上方 <strong>PASS</strong> / <strong>FAIL</strong> 可查看本单对应板码。
        </div>
        <template v-else>
          <div class="boards-detail-bar">
            <span v-if="preOvenResultFilter === 'PASS'">PASS 明细（{{ preOvenSummary?.items?.length || 0 }}）</span>
            <span v-else-if="preOvenResultFilter === 'FAIL'">不良明细（{{ preOvenSummary?.items?.length || 0 }}）</span>
            <span v-else>搜索结果（{{ preOvenSummary?.items?.length || 0 }}）</span>
            <el-button link type="primary" @click="onClearPreOvenDetail">收起明细</el-button>
          </div>
          <el-table
            :data="preOvenSummary?.items || []"
            size="small"
            border
            stripe
            max-height="520"
            empty-text="未找到匹配板码"
          >
            <el-table-column prop="barcode" label="PCBA编码" min-width="180" show-overflow-tooltip />
            <el-table-column prop="result" label="AOI" width="80">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="row.result === 'PASS' ? 'success' : row.result === 'FAIL' ? 'danger' : 'info'"
                >
                  {{ row.result }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="side" label="面" width="50" />
            <el-table-column prop="laser_date" label="日期" width="80" />
            <el-table-column prop="seq" label="流水" width="70" />
            <el-table-column prop="tested_at" label="测试时间" width="150" show-overflow-tooltip />
          </el-table>
        </template>
      </div>
    </el-drawer>

    <el-drawer v-model="ictOpen" title="ICT测试数据" size="720px">
      <div v-loading="ictLoading">
        <div v-if="ictSummary" class="boards-summary">
          <span>合计 {{ ictSummary.total }}</span>
          <el-tag type="success" size="small">PASS {{ ictSummary.pass_count }}</el-tag>
          <el-tag
            type="danger"
            size="small"
            class="boards-fail-tag"
            :class="{ active: ictResultFilter === 'FAIL' }"
            @click="onClickIctFail"
          >
            FAIL {{ ictSummary.fail_count }}
          </el-tag>
          <el-tag type="info" size="small">其他 {{ ictSummary.unknown_count }}</el-tag>
          <el-button
            v-if="(ictSummary.fail_count || 0) > 0"
            type="danger"
            plain
            size="small"
            :loading="ictExporting"
            @click="onExportIctFail"
          >
            导出 FAIL
          </el-button>
        </div>
        <el-input
          v-model="ictKeyword"
          placeholder="输入条码查询明细"
          clearable
          style="margin: 8px 0 12px"
          @keyup.enter="onSearchIctBoards"
          @clear="onClearIctSearch"
        >
          <template #append>
            <el-button @click="onSearchIctBoards">搜索</el-button>
          </template>
        </el-input>
        <div v-if="!showIctTable" class="boards-empty-hint">
          默认不展示明细。搜索条码可查单板；点击上方 <strong>FAIL</strong> 可查看本单不良板码。
        </div>
        <template v-else>
          <div class="boards-detail-bar">
            <span v-if="ictResultFilter === 'FAIL'">不良明细（{{ ictSummary?.items?.length || 0 }}）</span>
            <span v-else>搜索结果（{{ ictSummary?.items?.length || 0 }}）</span>
            <el-button link type="primary" @click="onClearIctDetail">收起明细</el-button>
          </div>
          <el-table
            :data="ictSummary?.items || []"
            size="small"
            border
            stripe
            max-height="520"
            empty-text="未找到匹配板码"
          >
            <el-table-column prop="barcode" label="条码" min-width="160" show-overflow-tooltip />
            <el-table-column prop="result" label="ICT" width="80">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="row.result === 'PASS' ? 'success' : row.result === 'FAIL' ? 'danger' : 'info'"
                >
                  {{ row.result }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="board_name" label="板名" min-width="120" show-overflow-tooltip />
            <el-table-column prop="machine_id" label="机台" width="90" />
            <el-table-column prop="tested_at" label="测试时间" width="150" show-overflow-tooltip />
          </el-table>
        </template>
      </div>
    </el-drawer>

    <el-dialog
      v-model="newOrdersOpen"
      :title="newOrdersDialogTitle"
      width="860px"
      destroy-on-close
    >
      <p style="margin: 0 0 12px; color: var(--erp-text-muted); font-size: 13px">
        客户下单日期在近 {{ newOrdersDays }} 个自然日内（自 {{ newOrdersDateFrom || '—' }} 起）视为新订单。
        <template v-if="newOrdersSyncHint">{{ newOrdersSyncHint }}</template>
      </p>
      <el-table v-loading="newOrdersLoading" :data="newOrdersList" size="small" border stripe max-height="420">
        <el-table-column prop="customer_name" label="客户" width="100" show-overflow-tooltip />
        <el-table-column prop="purchase_no" label="订单号" width="140" show-overflow-tooltip />
        <el-table-column prop="product_goods_no" label="料号" width="110" show-overflow-tooltip />
        <el-table-column prop="product_goods_name" label="品名" min-width="120" show-overflow-tooltip />
        <el-table-column label="数量" width="70" align="right">
          <template #default="{ row }">{{ orderQty(row) }}</template>
        </el-table-column>
        <el-table-column prop="purchase_date" label="下单日期" width="100" />
        <el-table-column prop="expect_arrival_date" label="交期" width="100" />
      </el-table>
      <template #footer>
        <el-button @click="newOrdersOpen = false">关闭</el-button>
        <el-button type="primary" @click="filterToNewOrders">在列表中只看新订单</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="hubInboxOpen" title="待我处理" size="520px">
      <p style="margin: 0 0 12px; color: var(--erp-text-muted); font-size: 13px">
        按当前账号角色匹配订单「下一步」责任提示。
      </p>
      <el-table
        v-loading="hubInboxLoading"
        :data="hubInboxItems"
        size="small"
        border
        stripe
        max-height="70vh"
        @row-click="(row: OrderHubInboxItem) => goHubByKey(row.line_key)"
      >
        <el-table-column prop="purchase_no" label="订单号" width="120" show-overflow-tooltip />
        <el-table-column prop="product_goods_no" label="料号" width="110" show-overflow-tooltip />
        <el-table-column prop="customer_name" label="客户" width="80" show-overflow-tooltip />
        <el-table-column label="下一步" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.next_step?.title || '—' }}</template>
        </el-table-column>
        <el-table-column prop="expect_arrival_date" label="交期" width="96" />
      </el-table>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElNotification } from 'element-plus'
import {
  exportOrdersBlob,
  fetchNewOrders,
  fetchOrderCount,
  fetchOrders,
  fetchStatusOptions,
  mergeCustomers,
  updateOrderRemark,
} from '@/api/orders'
import { fetchOrderHubInbox, type OrderHubInboxItem } from '@/api/orderHub'
import { fetchMaterialControlsByPurchase, materialControlAttachmentUrl } from '@/api/materialControls'
import {
  fetchOrderBoards,
  fetchOrderIctBoards,
  fetchOrderPreOvenAoiBoards,
  type OrderBoardSummary,
  type OrderIctBoardSummary,
  type OrderPreOvenAoiSummary,
} from '@/api/laser'
import { fetchProcessScans, type ProcessStation } from '@/api/processScan'
import { exportInboundDetailBlob, fetchInboundDetail, fetchPackBoxCurrent, isBoxLabelPrinted, onBoxLabelPrinted, openBoxLabelPrint, type InboundScanItem, type PackBoxInfo } from '@/api/packing'
import { runSync } from '@/api/sync'
import ManualOrderDialog from '@/components/orders/ManualOrderDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { MaterialControl, MaterialControlGroup } from '@/types/materialControl'
import type { CustomerOption, OrderFilters, SrmOrder, StatusOption } from '@/types/order'
import { fmtDay, fmtQty, orderQty } from '@/utils/format'

const NOTIFY_KEY = 'ems_last_notified_sync_log_id'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const pageTitle = computed(() =>
  '订单列表',
)
const canManage = computed(() => {
  const role = auth.user?.role
  return role === 'admin' || role === 'planner' || role === 'pmc'
})

/** 手动录单：管理员 / 计划员 / 工程资料员（邱梦林、任玉娴） */
const canManualOrder = computed(() => {
  const role = auth.user?.role
  return role === 'admin' || role === 'planner' || role === 'eng_importer' || role === 'engineering' || role === 'pmc'
})

const loading = ref(false)
const syncing = ref(false)
const newOrderCount = ref(0)
const hubInboxCount = ref(0)
const hubInboxOpen = ref(false)
const hubInboxLoading = ref(false)
const hubInboxItems = ref<OrderHubInboxItem[]>([])
const hubInboxKeys = ref<Set<string>>(new Set())
const orders = ref<SrmOrder[]>([])
const customers = ref<CustomerOption[]>([])
const statusOptions = ref<StatusOption[]>([])
const page = ref(1)
const pageSize = ref(100)
const total = ref(0)
const newOnlyFilter = ref('all')

const newOrdersOpen = ref(false)
const newOrdersLoading = ref(false)
const newOrdersList = ref<SrmOrder[]>([])
const newOrdersDays = ref(3)
const newOrdersDateFrom = ref('')
const newOrdersSyncHint = ref('')
const newOrdersDialogTitle = computed(() => {
  const n = newOrdersList.value.length
  const totalN = newOrderCount.value
  return totalN ? `新订单（${totalN}）` : n ? `新订单（${n}）` : '新订单'
})

const filters = reactive<OrderFilters>({
  customer_id: '',
  keyword: '',
  completed: 'all',
  srm_status: '',
  receive_filter: 'all',
  date_from: '',
  date_to: '',
  controlled: 'all',
  new_only: '',
})

const manualOpen = ref(false)
const processListOpen = ref(false)
const processListLoading = ref(false)
const processListPurchaseNo = ref('')
const processListStation = ref<ProcessStation | ''>('plugin')
const processListKeyword = ref('')
const processListTotal = ref(0)

const inboundOpen = ref(false)
const inboundLoading = ref(false)
const inboundExporting = ref(false)
const inboundLineKey = ref('')
const inboundPurchaseNo = ref('')
const inboundModel = ref('')
const inboundKeyword = ref('')
const inboundStatusFilter = ref<'all' | 'pending' | 'shipped'>('all')
const inboundPendingCount = ref(0)
const inboundShippedCount = ref(0)
const inboundTotal = ref(0)
const inboundItems = ref<InboundScanItem[]>([])
const inboundBoxes = ref<PackBoxInfo[]>([])
let stopBoxPrintedWatch: (() => void) | undefined
const inboundTitle = computed(() => {
  const parts = ['入库明细']
  if (inboundPurchaseNo.value) parts.push(inboundPurchaseNo.value)
  if (inboundModel.value) parts.push(inboundModel.value)
  return parts.join(' · ')
})

const processListItems = ref<
  Array<{ id: number; barcode: string; operator?: string | null; scanned_at?: string | null }>
>([])
const processListTitle = computed(() => {
  const label =
    processListStation.value === 'plugin'
      ? '插件'
      : processListStation.value === 'post_solder'
        ? '后焊'
        : processListStation.value === 'coating'
          ? '三防'
          : '工序'
  return `${label}扫码 · ${processListPurchaseNo.value || ''}`
})
const savingRemarkKey = ref('')
const remarkDraft = new Map<string, string>()

const controlDrawerOpen = ref(false)
const boardsOpen = ref(false)
const boardsLoading = ref(false)
const boardsPurchaseNo = ref('')
const boardsCustomerId = ref('')
const boardsKeyword = ref('')
const boardsResultFilter = ref('')
const boardsSummary = ref<OrderBoardSummary | null>(null)
const boardsExporting = ref(false)
const showBoardsTable = computed(
  () =>
    !!boardsKeyword.value.trim() ||
    boardsResultFilter.value === 'FAIL' ||
    boardsResultFilter.value === 'PASS',
)
const preOvenOpen = ref(false)
const preOvenLoading = ref(false)
const preOvenPurchaseNo = ref('')
const preOvenCustomerId = ref('')
const preOvenModelCode = ref('')
const preOvenKeyword = ref('')
const preOvenResultFilter = ref('')
const preOvenSummary = ref<OrderPreOvenAoiSummary | null>(null)
const preOvenExporting = ref(false)
const showPreOvenTable = computed(
  () =>
    !!preOvenKeyword.value.trim() ||
    preOvenResultFilter.value === 'FAIL' ||
    preOvenResultFilter.value === 'PASS',
)
const ictOpen = ref(false)
const ictLoading = ref(false)
const ictPurchaseNo = ref('')
const ictCustomerId = ref('')
const ictKeyword = ref('')
const ictResultFilter = ref('')
const ictSummary = ref<OrderIctBoardSummary | null>(null)
const ictExporting = ref(false)
const showIctTable = computed(
  () => !!ictKeyword.value.trim() || ictResultFilter.value === 'FAIL',
)
const controlLoading = ref(false)
const controlRows = ref<MaterialControl[]>([])
const controlPurchaseNo = ref('')

let notifyTimer: ReturnType<typeof setInterval> | null = null
let ordersRefreshTimer: ReturnType<typeof setInterval> | null = null
const ORDERS_AUTO_REFRESH_MS = 45_000

const ordersOverlayOpen = computed(
  () =>
    manualOpen.value ||
    processListOpen.value ||
    inboundOpen.value ||
    controlDrawerOpen.value ||
    boardsOpen.value ||
    preOvenOpen.value ||
    ictOpen.value ||
    newOrdersOpen.value ||
    hubInboxOpen.value,
)

function startOrdersAutoRefresh() {
  stopOrdersAutoRefresh()
  ordersRefreshTimer = setInterval(() => {
    if (document.visibilityState === 'hidden') return
    if (ordersOverlayOpen.value || loading.value || savingRemarkKey.value) return
    void loadOrders({ quiet: true })
  }, ORDERS_AUTO_REFRESH_MS)
}

function stopOrdersAutoRefresh() {
  if (ordersRefreshTimer) {
    clearInterval(ordersRefreshTimer)
    ordersRefreshTimer = null
  }
}

function kitTagType(status?: string | null) {
  if (status === 'ready') return 'success'
  if (status === 'partial') return 'warning'
  if (status === 'unkit' || status === 'shortage') return 'danger'
  return 'info'
}

/** 入库数 = 待发 + 待审 + 已出库（本地包装扫码） */
function inboundQty(row: SrmOrder) {
  return (
    Number(row.pending_ship_qty || 0) +
    Number(row.awaiting_ship_qty || 0) +
    Number(row.shipped_local_qty || 0)
  )
}

function shortStatus(row: SrmOrder) {
  const name = (row.srm_status_name || '').trim()
  if (name) return name.length > 4 ? `${name.slice(0, 4)}…` : name
  return row.is_completed ? '结案' : '进行'
}

function rowClassName({ row }: { row: SrmOrder }) {
  const classes: string[] = []
  if (row.customer_kit_status === 'unkit') classes.push('row-kit-unkit')
  if (row.is_new_order) classes.push('row-new-order')
  if (hubInboxKeys.value.has(row.line_key)) classes.push('row-hub-inbox')
  const due = dueBadge(row)
  if (due === 'overdue') classes.push('row-due-overdue')
  else if (due === 'due_soon') classes.push('row-due-soon')
  return classes.join(' ')
}

function dueBadge(row: SrmOrder): '' | 'overdue' | 'due_soon' {
  if (row.is_completed) return ''
  const s = String(row.expect_arrival_date || '').slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return ''
  const due = new Date(`${s}T00:00:00`)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const diff = Math.round((due.getTime() - today.getTime()) / 86400000)
  if (diff < 0) return 'overdue'
  if (diff <= 2) return 'due_soon'
  return ''
}

function goHub(row: SrmOrder) {
  void router.push(`/orders/hub/${encodeURIComponent(row.line_key)}`)
}

function goHubByKey(lineKey: string) {
  hubInboxOpen.value = false
  void router.push(`/orders/hub/${encodeURIComponent(lineKey)}`)
}

async function refreshHubInbox(quiet = false) {
  try {
    const data = await fetchOrderHubInbox(40)
    hubInboxItems.value = data.items || []
    hubInboxCount.value = data.count || hubInboxItems.value.length
    hubInboxKeys.value = new Set(hubInboxItems.value.map((i) => i.line_key))
  } catch (e) {
    if (!quiet) ElMessage.error(e instanceof Error ? e.message : '加载待办失败')
  }
}

async function openHubInbox() {
  hubInboxOpen.value = true
  hubInboxLoading.value = true
  try {
    await refreshHubInbox()
  } finally {
    hubInboxLoading.value = false
  }
}

async function loadCustomers() {
  customers.value = await mergeCustomers()
}

async function loadStatusOptions() {
  statusOptions.value = await fetchStatusOptions(filters.customer_id || '')
}

function buildFilterPayload(): OrderFilters {
  const f: OrderFilters = { ...filters }
  if (newOnlyFilter.value === 'yes') f.new_only = 'true'
  else delete f.new_only
  return f
}

async function refreshNewOrderCount() {
  try {
    const data = await fetchNewOrders(1)
    newOrderCount.value = data.count || 0
    newOrdersDays.value = data.days || 3
    newOrdersDateFrom.value = data.date_from || ''
  } catch {
    /* ignore */
  }
}

async function openNewOrdersDialog(opts?: { syncHint?: string; items?: SrmOrder[] }) {
  newOrdersOpen.value = true
  newOrdersSyncHint.value = opts?.syncHint || ''
  if (opts?.items?.length) {
    newOrdersList.value = opts.items
    return
  }
  newOrdersLoading.value = true
  try {
    const data = await fetchNewOrders(200)
    newOrdersList.value = data.items || []
    newOrderCount.value = data.count || 0
    newOrdersDays.value = data.days || 3
    newOrdersDateFrom.value = data.date_from || ''
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载新订单失败')
  } finally {
    newOrdersLoading.value = false
  }
}

function filterToNewOrders() {
  newOnlyFilter.value = 'yes'
  newOrdersOpen.value = false
  page.value = 1
  loadOrders()
}

function onNewOnlyChange() {
  page.value = 1
  loadOrders()
}

/** 列表加载代数：翻页/筛选时作废进行中的「补汇总」请求，避免旧数据盖新表 */
let ordersLoadSeq = 0

function applyOrderRows(rows: SrmOrder[], opts?: { quiet?: boolean; keepDeviceFrom?: Map<string, SrmOrder> }) {
  const quiet = !!opts?.quiet
  const keepFrom = opts?.keepDeviceFrom
  orders.value = rows.map((o) => {
    const drafting = quiet && savingRemarkKey.value !== o.line_key && remarkDraft.has(o.line_key)
    const keepRemark = drafting ? (remarkDraft.get(o.line_key) ?? o.remark ?? '') : o.remark || ''
    remarkDraft.set(o.line_key, keepRemark)
    const prev = keepFrom?.get(o.line_key)
    if (prev) {
      return {
        ...o,
        remark: keepRemark,
        aoi_test_qty: prev.aoi_test_qty ?? o.aoi_test_qty,
        pre_oven_aoi_qty: prev.pre_oven_aoi_qty ?? o.pre_oven_aoi_qty,
        ict_test_qty: prev.ict_test_qty ?? o.ict_test_qty,
        plugin_qty: prev.plugin_qty ?? o.plugin_qty,
        post_solder_qty: prev.post_solder_qty ?? o.post_solder_qty,
        coating_qty: prev.coating_qty ?? o.coating_qty,
        tooling_registered_count: prev.tooling_registered_count ?? o.tooling_registered_count,
        tooling_complete: prev.tooling_complete ?? o.tooling_complete,
        tooling_status: prev.tooling_status ?? o.tooling_status,
        tooling_status_label: prev.tooling_status_label ?? o.tooling_status_label,
      }
    }
    return { ...o, remark: keepRemark }
  })
}

async function loadOrders(opts?: { quiet?: boolean }) {
  const quiet = !!opts?.quiet
  const seq = ++ordersLoadSeq
  if (!quiet) loading.value = true
  try {
    const f = buildFilterPayload()
    const pageNow = page.value
    const sizeNow = pageSize.value
    // 静默/首屏快显：先不带 AOI/ICT/工序汇总（入库数仍有）。扫码接口不受影响。
    const prevByKey = quiet
      ? new Map(orders.value.map((o) => [o.line_key, o] as const))
      : null
    const [rows, countRes] = await Promise.all([
      fetchOrders({
        ...f,
        page: pageNow,
        page_size: sizeNow,
        include_device_stats: false,
      }),
      fetchOrderCount(f),
    ])
    if (seq !== ordersLoadSeq) return
    applyOrderRows(rows, { quiet, keepDeviceFrom: prevByKey || undefined })
    total.value = countRes.total
    if (!quiet) loading.value = false

    // 第二阶段：补全设备汇总列（不挡表格；翻页则自动作废）
    if (!quiet) {
      void (async () => {
        try {
          const full = await fetchOrders({
            ...f,
            page: pageNow,
            page_size: sizeNow,
            include_device_stats: true,
          })
          if (seq !== ordersLoadSeq) return
          const byKey = new Map(full.map((o) => [o.line_key, o] as const))
          orders.value = orders.value.map((o) => {
            const rich = byKey.get(o.line_key)
            if (!rich) return o
            return {
              ...o,
              aoi_test_qty: rich.aoi_test_qty,
              pre_oven_aoi_qty: rich.pre_oven_aoi_qty,
              ict_test_qty: rich.ict_test_qty,
              plugin_qty: rich.plugin_qty,
              post_solder_qty: rich.post_solder_qty,
              coating_qty: rich.coating_qty,
              tooling_registered_count: rich.tooling_registered_count,
              tooling_complete: rich.tooling_complete,
              tooling_status: rich.tooling_status,
              tooling_status_label: rich.tooling_status_label,
              control_nos: rich.control_nos,
              control_draft_nos: rich.control_draft_nos,
              is_controlled: rich.is_controlled,
              has_control: rich.has_control,
              in_plan: rich.in_plan,
              plan_status: rich.plan_status,
              plan_status_label: rich.plan_status_label,
            }
          })
        } catch {
          /* 补汇总失败不影响已展示列表与扫码 */
        }
      })()
      void refreshNewOrderCount()
    }
  } catch (e) {
    if (!quiet && seq === ordersLoadSeq) {
      ElMessage.error(e instanceof Error ? e.message : '加载失败')
    }
  } finally {
    if (!quiet && seq === ordersLoadSeq) loading.value = false
  }
}

function onSearch() {
  page.value = 1
  loadOrders()
}

function onReset() {
  filters.customer_id = ''
  filters.keyword = ''
  filters.completed = 'all'
  filters.srm_status = ''
  filters.receive_filter = 'all'
  filters.date_from = ''
  filters.date_to = ''
  filters.controlled = 'all'
  filters.new_only = ''
  newOnlyFilter.value = 'all'
  page.value = 1
  loadStatusOptions()
  loadOrders()
}

function controlAttachmentHref(id: number) {
  const token = localStorage.getItem('ems_auth_token') ?? ''
  const base = materialControlAttachmentUrl(id)
  return token ? `${base}?access_token=${encodeURIComponent(token)}` : base
}

/** 订单详情只展示「本工单所在机型组」的换料，避免串入同单其他机型 */
function groupsForPurchase(c: MaterialControl): MaterialControlGroup[] {
  const pn = controlPurchaseNo.value
  if (c.groups?.length) {
    return c.groups.filter((g) => (g.orders || []).some((o) => o.purchase_no === pn))
  }
  // 旧数据无 groups：仅当本工单在 orders 里时展示扁平换料
  const hit = (c.orders || []).some((o) => o.purchase_no === pn)
  if (!hit) return []
  return [
    {
      model_code: c.model_code || '—',
      orders: c.orders || [],
      changes: c.changes || [],
    },
  ]
}

function controlAddSummary(c: MaterialControl) {
  const groups = c.groups?.length ? c.groups : [{ changes: c.changes || [] }]
  const codes = new Set<string>()
  for (const g of groups) {
    for (const ch of g.changes || []) {
      const code = (ch.add_code || '').trim()
      if (code) codes.add(code)
    }
  }
  return [...codes].join('、') || '—'
}

function formatControlDt(v?: string | null) {
  if (!v) return '—'
  const d = new Date(v)
  if (Number.isNaN(d.getTime())) return String(v).replace('T', ' ').slice(0, 19)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function openControlDetail(row: SrmOrder) {
  controlPurchaseNo.value = row.purchase_no
  controlDrawerOpen.value = true
  controlLoading.value = true
  controlRows.value = []
  try {
    controlRows.value = await fetchMaterialControlsByPurchase(
      row.purchase_no,
      row.product_goods_no || undefined,
    )
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载管制详情失败')
  } finally {
    controlLoading.value = false
  }
}

async function openBoards(row: SrmOrder) {
  boardsPurchaseNo.value = row.purchase_no
  boardsCustomerId.value = row.customer_id || filters.customer_id || ''
  boardsKeyword.value = ''
  boardsResultFilter.value = ''
  boardsOpen.value = true
  await reloadBoards({ includeItems: false })
}

async function reloadBoards(opts: { includeItems?: boolean } = {}) {
  if (!boardsPurchaseNo.value) return
  const filter = boardsResultFilter.value
  const wantItems =
    opts.includeItems === true ||
    !!boardsKeyword.value.trim() ||
    filter === 'FAIL' ||
    filter === 'PASS'
  boardsLoading.value = true
  try {
    boardsSummary.value = await fetchOrderBoards(
      boardsPurchaseNo.value,
      boardsCustomerId.value,
      boardsKeyword.value,
      {
        result: filter,
        includeItems: wantItems,
        limit: 5000,
      },
    )
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载板码失败')
  } finally {
    boardsLoading.value = false
  }
}

async function onSearchBoards() {
  const kw = boardsKeyword.value.trim()
  if (!kw) {
    ElMessage.warning('请输入要查询的条码')
    return
  }
  boardsResultFilter.value = ''
  await reloadBoards({ includeItems: true })
}

async function onClickPass() {
  if (!boardsSummary.value?.pass_count) {
    ElMessage.info('本单暂无 PASS 板码')
    return
  }
  boardsKeyword.value = ''
  boardsResultFilter.value = boardsResultFilter.value === 'PASS' ? '' : 'PASS'
  if (!boardsResultFilter.value) {
    await reloadBoards({ includeItems: false })
    return
  }
  await reloadBoards({ includeItems: true })
}

async function onClickFail() {
  if (!boardsSummary.value?.fail_count) {
    ElMessage.info('本单暂无不良板码')
    return
  }
  boardsKeyword.value = ''
  boardsResultFilter.value = boardsResultFilter.value === 'FAIL' ? '' : 'FAIL'
  if (!boardsResultFilter.value) {
    await reloadBoards({ includeItems: false })
    return
  }
  await reloadBoards({ includeItems: true })
}

async function onClearBoardsSearch() {
  boardsKeyword.value = ''
  if (boardsResultFilter.value !== 'FAIL' && boardsResultFilter.value !== 'PASS') {
    await reloadBoards({ includeItems: false })
  }
}

async function onClearBoardsDetail() {
  boardsKeyword.value = ''
  boardsResultFilter.value = ''
  await reloadBoards({ includeItems: false })
}

async function onExportFail() {
  if (!boardsPurchaseNo.value) return
  if (!(boardsSummary.value?.fail_count || 0)) {
    ElMessage.info('本单暂无不良板码可导出')
    return
  }
  boardsExporting.value = true
  try {
    let items = boardsSummary.value?.items || []
    const needFetch =
      boardsResultFilter.value !== 'FAIL' || !items.length || items.some((x) => x.result !== 'FAIL')
    if (needFetch) {
      const data = await fetchOrderBoards(boardsPurchaseNo.value, boardsCustomerId.value, '', {
        result: 'FAIL',
        includeItems: true,
        limit: 20000,
      })
      items = data.items || []
    }
    if (!items.length) {
      ElMessage.info('未找到不良明细')
      return
    }
    const headers = ['采购订单号', 'PCBA编码', 'AOI', '面', '日期', '流水', '测试时间', '机台', '源文件']
    const lines = [
      headers.join(','),
      ...items.map((r) =>
        [
          boardsPurchaseNo.value,
          r.barcode || '',
          r.result || '',
          r.side || '',
          r.laser_date || '',
          r.seq ?? '',
          r.tested_at || '',
          r.machine || '',
          r.source_file || '',
        ]
          .map((c) => `"${String(c).replace(/"/g, '""')}"`)
          .join(','),
      ),
    ]
    const blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `SMT-AOI-FAIL_${boardsPurchaseNo.value}.csv`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${items.length} 条 FAIL`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导出失败')
  } finally {
    boardsExporting.value = false
  }
}

async function openPreOvenAoiBoards(row: SrmOrder) {
  preOvenPurchaseNo.value = row.purchase_no
  preOvenCustomerId.value = row.customer_id || filters.customer_id || ''
  preOvenModelCode.value = (row.product_goods_no || '').trim()
  preOvenKeyword.value = ''
  preOvenResultFilter.value = ''
  preOvenOpen.value = true
  await reloadPreOvenBoards({ includeItems: false })
}

async function reloadPreOvenBoards(opts: { includeItems?: boolean } = {}) {
  if (!preOvenPurchaseNo.value) return
  const filter = preOvenResultFilter.value
  const wantItems =
    opts.includeItems === true ||
    !!preOvenKeyword.value.trim() ||
    filter === 'FAIL' ||
    filter === 'PASS'
  preOvenLoading.value = true
  try {
    preOvenSummary.value = await fetchOrderPreOvenAoiBoards(
      preOvenPurchaseNo.value,
      preOvenCustomerId.value,
      preOvenKeyword.value,
      {
        result: filter,
        includeItems: wantItems,
        limit: 5000,
        modelCode: preOvenModelCode.value,
      },
    )
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载炉前AOI板码失败')
  } finally {
    preOvenLoading.value = false
  }
}

async function onSearchPreOven() {
  const kw = preOvenKeyword.value.trim()
  if (!kw) {
    ElMessage.warning('请输入要查询的条码')
    return
  }
  preOvenResultFilter.value = ''
  await reloadPreOvenBoards({ includeItems: true })
}

async function onClickPreOvenPass() {
  if (!preOvenSummary.value?.pass_count) {
    ElMessage.info('本单暂无 PASS 板码')
    return
  }
  preOvenKeyword.value = ''
  preOvenResultFilter.value = preOvenResultFilter.value === 'PASS' ? '' : 'PASS'
  if (!preOvenResultFilter.value) {
    await reloadPreOvenBoards({ includeItems: false })
    return
  }
  await reloadPreOvenBoards({ includeItems: true })
}

async function onClickPreOvenFail() {
  if (!preOvenSummary.value?.fail_count) {
    ElMessage.info('本单暂无不良板码')
    return
  }
  preOvenKeyword.value = ''
  preOvenResultFilter.value = preOvenResultFilter.value === 'FAIL' ? '' : 'FAIL'
  if (!preOvenResultFilter.value) {
    await reloadPreOvenBoards({ includeItems: false })
    return
  }
  await reloadPreOvenBoards({ includeItems: true })
}

async function onClearPreOvenSearch() {
  preOvenKeyword.value = ''
  if (preOvenResultFilter.value !== 'FAIL' && preOvenResultFilter.value !== 'PASS') {
    await reloadPreOvenBoards({ includeItems: false })
  }
}

async function onClearPreOvenDetail() {
  preOvenKeyword.value = ''
  preOvenResultFilter.value = ''
  await reloadPreOvenBoards({ includeItems: false })
}

async function onExportPreOvenFail() {
  if (!preOvenPurchaseNo.value) return
  if (!(preOvenSummary.value?.fail_count || 0)) {
    ElMessage.info('本单暂无不良板码可导出')
    return
  }
  preOvenExporting.value = true
  try {
    let items = preOvenSummary.value?.items || []
    const needFetch =
      preOvenResultFilter.value !== 'FAIL' || !items.length || items.some((x) => x.result !== 'FAIL')
    if (needFetch) {
      const data = await fetchOrderPreOvenAoiBoards(
        preOvenPurchaseNo.value,
        preOvenCustomerId.value,
        '',
        {
          result: 'FAIL',
          includeItems: true,
          limit: 20000,
          modelCode: preOvenModelCode.value,
        },
      )
      items = data.items || []
    }
    if (!items.length) {
      ElMessage.info('未找到不良明细')
      return
    }
    const headers = ['采购订单号', '料号', 'PCBA编码', 'AOI', '面', '日期', '流水', '测试时间', '机台', '源文件']
    const lines = [
      headers.join(','),
      ...items.map((r) =>
        [
          preOvenPurchaseNo.value,
          r.model_code || preOvenModelCode.value,
          r.barcode || '',
          r.result || '',
          r.side || '',
          r.laser_date || '',
          r.seq ?? '',
          r.tested_at || '',
          r.machine || '',
          r.source_file || '',
        ]
          .map((c) => `"${String(c).replace(/"/g, '""')}"`)
          .join(','),
      ),
    ]
    const blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `炉前AOI-FAIL_${preOvenPurchaseNo.value}.csv`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${items.length} 条 FAIL`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导出失败')
  } finally {
    preOvenExporting.value = false
  }
}

async function openIctBoards(row: SrmOrder) {
  ictPurchaseNo.value = row.purchase_no
  ictCustomerId.value = row.customer_id || filters.customer_id || ''
  ictKeyword.value = ''
  ictResultFilter.value = ''
  ictOpen.value = true
  await reloadIctBoards({ includeItems: false })
}

async function reloadIctBoards(opts: { includeItems?: boolean } = {}) {
  if (!ictPurchaseNo.value) return
  const wantItems =
    opts.includeItems === true ||
    !!ictKeyword.value.trim() ||
    ictResultFilter.value === 'FAIL'
  ictLoading.value = true
  try {
    ictSummary.value = await fetchOrderIctBoards(
      ictPurchaseNo.value,
      ictCustomerId.value,
      ictKeyword.value,
      {
        result: ictResultFilter.value,
        includeItems: wantItems,
        limit: 5000,
      },
    )
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载 ICT 板码失败')
  } finally {
    ictLoading.value = false
  }
}

async function onSearchIctBoards() {
  const kw = ictKeyword.value.trim()
  if (!kw) {
    ElMessage.warning('请输入要查询的条码')
    return
  }
  ictResultFilter.value = ''
  await reloadIctBoards({ includeItems: true })
}

async function onClickIctFail() {
  if (!ictSummary.value?.fail_count) {
    ElMessage.info('本单暂无不良板码')
    return
  }
  ictKeyword.value = ''
  ictResultFilter.value = ictResultFilter.value === 'FAIL' ? '' : 'FAIL'
  if (!ictResultFilter.value) {
    await reloadIctBoards({ includeItems: false })
    return
  }
  await reloadIctBoards({ includeItems: true })
}

async function onClearIctSearch() {
  ictKeyword.value = ''
  if (ictResultFilter.value !== 'FAIL') {
    await reloadIctBoards({ includeItems: false })
  }
}

async function onClearIctDetail() {
  ictKeyword.value = ''
  ictResultFilter.value = ''
  await reloadIctBoards({ includeItems: false })
}

async function onExportIctFail() {
  if (!ictPurchaseNo.value) return
  if (!(ictSummary.value?.fail_count || 0)) {
    ElMessage.info('本单暂无不良板码可导出')
    return
  }
  ictExporting.value = true
  try {
    let items = ictSummary.value?.items || []
    const needFetch =
      ictResultFilter.value !== 'FAIL' || !items.length || items.some((x) => x.result !== 'FAIL')
    if (needFetch) {
      const data = await fetchOrderIctBoards(ictPurchaseNo.value, ictCustomerId.value, '', {
        result: 'FAIL',
        includeItems: true,
        limit: 20000,
      })
      items = data.items || []
    }
    if (!items.length) {
      ElMessage.info('未找到不良明细')
      return
    }
    const headers = ['采购订单号', '条码', 'ICT', '板名', '机台', '测试时间', '主机', '源文件']
    const lines = [
      headers.join(','),
      ...items.map((r) =>
        [
          ictPurchaseNo.value,
          r.barcode || '',
          r.result || '',
          r.board_name || '',
          r.machine_id || '',
          r.tested_at || '',
          r.source_host || '',
          r.source_file || '',
        ]
          .map((c) => `"${String(c).replace(/"/g, '""')}"`)
          .join(','),
      ),
    ]
    const blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ICT-FAIL_${ictPurchaseNo.value}.csv`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${items.length} 条 FAIL`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导出失败')
  } finally {
    ictExporting.value = false
  }
}

async function onCustomerChange() {
  page.value = 1
  await loadStatusOptions()
  loadOrders()
}

function onPageSizeChange() {
  page.value = 1
  loadOrders()
}

async function onExport() {
  try {
    const { blob, filename } = await exportOrdersBlob(buildFilterPayload())
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导出失败')
  }
}

async function onSync() {
  syncing.value = true
  try {
    const res = await runSync()
    if (res.status === 'failed' || res.status === 'running') {
      ElMessage.error(res.message || '同步失败')
    } else if (res.status === 'partial') {
      ElMessage.warning(res.message || '部分同步成功')
    } else {
      ElMessage.success(res.message || '同步完成')
    }
    if (res.sync_log_id) {
      localStorage.setItem(NOTIFY_KEY, String(res.sync_log_id))
    }
    await loadCustomers()
    await loadOrders()
    const n = Number(res.new_orders_count || 0)
    if (n > 0) {
      ElNotification({
        title: '新订单提醒',
        message: `本次同步新增 ${n} 条，点击「新订单」查看近3天列表`,
        type: 'warning',
        duration: 8000,
        onClick: () => openNewOrdersDialog({ syncHint: `（含本次同步新增 ${n} 条）` }),
      })
      await openNewOrdersDialog({ syncHint: `（含本次同步新增 ${n} 条）` })
    } else {
      await refreshNewOrderCount()
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '同步失败')
  } finally {
    syncing.value = false
  }
}

function onManualSaved() {
  loadCustomers()
  page.value = 1
  loadOrders()
}


async function openInboundDetail(row: SrmOrder) {
  inboundLineKey.value = row.line_key
  inboundPurchaseNo.value = row.purchase_no || ''
  inboundModel.value = row.product_goods_no || ''
  inboundKeyword.value = ''
  inboundStatusFilter.value = 'all'
  inboundOpen.value = true
  await reloadInboundDetail()
}

function onInboundStatusFilter(st: 'all' | 'pending' | 'shipped') {
  inboundStatusFilter.value = st
  void reloadInboundDetail()
}

function inboundBoxStatus(status?: string) {
  const s = (status || '').trim()
  if (s === 'open') return '装箱中'
  if (s === 'sealed') return '已封待发'
  if (s === 'awaiting') return '已发待审'
  if (s === 'shipped') return '已发货'
  return s || '—'
}

function printInboundBox(boxNo?: string | null) {
  if (boxNo) openBoxLabelPrint(boxNo)
}

function openBoxTrace(boxNo: string) {
  const no = String(boxNo || '').trim()
  if (!no) return
  window.open(`/static/box_trace.html?no=${encodeURIComponent(no)}`, '_blank')
}

async function reloadInboundDetail() {
  if (!inboundLineKey.value) return
  inboundLoading.value = true
  try {
    const [data, boxState] = await Promise.all([
      fetchInboundDetail(inboundLineKey.value, {
        status: inboundStatusFilter.value,
        keyword: inboundKeyword.value,
        limit: 10000,
      }),
      fetchPackBoxCurrent(inboundLineKey.value).catch(() => null),
    ])
    inboundPendingCount.value = data.pending_count || 0
    inboundShippedCount.value = data.shipped_count || 0
    inboundTotal.value = data.total || 0
    inboundItems.value = data.items || []
    inboundBoxes.value = boxState?.records || boxState?.sealed_boxes || []
    if (!inboundPurchaseNo.value && data.purchase_no) inboundPurchaseNo.value = data.purchase_no
    if (!inboundModel.value && data.model_code) inboundModel.value = data.model_code
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载入库明细失败')
  } finally {
    inboundLoading.value = false
  }
}

async function onExportInbound() {
  if (!inboundLineKey.value) return
  inboundExporting.value = true
  try {
    const { blob, filename } = await exportInboundDetailBlob(inboundLineKey.value, {
      status: inboundStatusFilter.value,
      keyword: inboundKeyword.value,
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('已导出入库明细')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导出失败')
  } finally {
    inboundExporting.value = false
  }
}

async function onCopyInboundCodes() {
  const codes = inboundItems.value.map((x) => x.barcode).filter(Boolean)
  if (!codes.length) {
    ElMessage.warning('无编码可复制')
    return
  }
  const textJoin = codes.join('\n')
  try {
    await navigator.clipboard.writeText(textJoin)
    ElMessage.success(`已复制 ${codes.length} 条编码`)
  } catch {
    ElMessage.error('复制失败，请手动选择表格编码')
  }
}

async function openProcessList(row: SrmOrder, station: ProcessStation) {
  processListPurchaseNo.value = row.purchase_no
  processListStation.value = station
  processListKeyword.value = ''
  processListOpen.value = true
  await reloadProcessList()
}

async function reloadProcessList() {
  if (!processListPurchaseNo.value) return
  processListLoading.value = true
  try {
    const data = await fetchProcessScans(processListPurchaseNo.value, {
      station: processListStation.value || '',
      keyword: processListKeyword.value,
      limit: 5000,
    })
    processListTotal.value = data.total || 0
    processListItems.value = data.items || []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载工序扫码失败')
  } finally {
    processListLoading.value = false
  }
}

async function saveRemark(row: SrmOrder) {
  const key = row.line_key
  const next = (row.remark || '').trim()
  const prev = remarkDraft.get(key) ?? ''
  if (next === prev) return
  savingRemarkKey.value = key
  try {
    const updated = await updateOrderRemark(key, next)
    row.remark = updated.remark || ''
    remarkDraft.set(key, row.remark)
    ElMessage.success('备注已保存')
  } catch (e) {
    row.remark = prev
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    savingRemarkKey.value = ''
  }
}

onMounted(() => {
  // 客户/状态下拉与列表并行，避免串行多等一轮
  void loadCustomers()
  void loadStatusOptions()
  void refreshNewOrderCount()
  void refreshHubInbox(true)
  void loadOrders().finally(() => startOrdersAutoRefresh())
  stopBoxPrintedWatch = onBoxLabelPrinted((boxNo) => {
    const row = inboundBoxes.value.find((r) => r.box_no === boxNo)
    if (row) {
      row.printed = true
      row.label_printed_at = new Date().toISOString()
    }
  })
})

onUnmounted(() => {
  if (notifyTimer) clearInterval(notifyTimer)
  stopOrdersAutoRefresh()
  stopBoxPrintedWatch?.()
})
</script>

<style scoped>
.orders-filter {
  margin-bottom: 12px;
}
.boards-summary {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 4px;
}
.inbound-box-h {
  margin: 12px 0 8px;
  font-size: 14px;
}
.muted {
  color: var(--erp-text-muted, #64748b);
}
.boards-result-tag {
  cursor: pointer;
  user-select: none;
}
.boards-pass-tag:hover,
.boards-pass-tag.active {
  outline: 2px solid #4ade80;
  outline-offset: 1px;
}
.boards-fail-tag:hover,
.boards-fail-tag.active {
  outline: 2px solid #f87171;
  outline-offset: 1px;
}
.boards-empty-hint {
  margin-top: 16px;
  padding: 16px;
  border-radius: 8px;
  background: #f8fafc;
  color: var(--erp-text-muted, #64748b);
  font-size: 13px;
  line-height: 1.6;
}
.boards-detail-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 4px 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}
.boards-batches {
  margin-bottom: 10px;
  font-size: 12px;
  color: var(--erp-text-muted);
}
.boards-batch-line {
  line-height: 1.6;
}
.orders-filter :deep(.el-form-item) {
  margin-bottom: 10px;
}
.orders-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
.kit-qty-hint {
  font-size: 11px;
  color: var(--erp-text-muted);
  margin-top: 0;
  line-height: 1.2;
}
.cell-muted {
  color: var(--erp-text-muted, #94a3b8);
}
.orders-name-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  overflow: hidden;
}
.orders-name-main,
.orders-name-spec {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.orders-name-spec {
  font-size: 11px;
  color: var(--erp-text-muted, #94a3b8);
}
:deep(.orders-table.el-table--small .el-table__cell) {
  padding: 2px 0;
}
:deep(.orders-table.el-table--small .cell) {
  padding: 0 3px;
  line-height: 1.25;
  font-size: 12px;
}
:deep(.orders-table .el-table__header .cell) {
  padding: 0 3px;
}
:deep(.orders-table .el-tag--small) {
  height: 18px;
  padding: 0 4px;
  line-height: 16px;
  max-width: 100%;
}
:deep(.orders-table .el-button.is-link) {
  padding: 0 2px;
  height: auto;
}
:deep(.orders-table .el-button--small) {
  --el-button-size: 22px;
  padding: 2px 6px;
  height: 22px;
}
:deep(.orders-table .el-input--small .el-input__wrapper) {
  padding: 0 6px;
  min-height: 22px;
}
:deep(.row-kit-unkit) {
  background-color: #fff1f2 !important;
}
:deep(.row-new-order) {
  background-color: #fff7ed !important;
}
:deep(.row-hub-inbox) td:first-child {
  box-shadow: inset 3px 0 0 #f59e0b;
}
:deep(.row-due-overdue) {
  background-color: #fef2f2 !important;
}
:deep(.row-due-soon) {
  background-color: #fffbeb !important;
}
.new-order-tag {
  margin-left: 4px;
  vertical-align: middle;
}
.control-block + .control-block {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color);
}
.control-group + .control-group {
  margin-top: 8px;
}
.control-change-table :deep(.cell) {
  white-space: normal;
  line-height: 1.4;
}
.control-refdes {
  display: block;
  white-space: normal;
  word-break: break-word;
  line-height: 1.45;
}
:deep(.el-table .el-input__wrapper) {
  box-shadow: none;
  background: transparent;
}
:deep(.el-table .el-input__wrapper:hover),
:deep(.el-table .el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--erp-primary) inset;
  background: #fff;
}
</style>
