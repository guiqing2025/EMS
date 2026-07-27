<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">{{ pageTitle }}</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            支持按客户、订单号、机型、结案与管制状态筛选；进入页面默认加载订单明细
          </p>
        </div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
          <el-button v-if="canManage" @click="manualOpen = true">手动录单</el-button>
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
          <el-table-column prop="purchase_no" label="订单号" width="132" show-overflow-tooltip>
            <template #default="{ row }">
              <el-button link type="primary" @click="openBoards(row)">{{ row.purchase_no }}</el-button>
              <el-tag v-if="row.is_new_order" type="danger" size="small" effect="dark" class="new-order-tag">新</el-tag>
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
              <strong
                v-if="inboundQty(row) > 0"
                :title="`待发 ${row.pending_ship_qty || 0} / 已发 ${row.shipped_local_qty || 0}`"
              >{{ inboundQty(row) }}</strong>
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
          <el-table-column
            v-if="canOperate || canManage"
            label="操作"
            :width="opColWidth"
            fixed="right"
            align="center"
          >
            <template #default="{ row }">
              <template v-if="canOperate">
                <el-dropdown v-if="canProcessScan" trigger="click" @command="(cmd: string) => openProcessScan(row, cmd as any)">
                  <el-button link size="small" :disabled="row.is_completed">工序</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="plugin">插件扫码</el-dropdown-item>
                      <el-dropdown-item command="post_solder">后焊扫码</el-dropdown-item>
                      <el-dropdown-item command="coating">三防扫码</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
                <el-button link size="small" :disabled="row.is_completed" @click="openScan(row)">入库</el-button>
              </template>
              <el-button
                v-if="canManage"
                link
                size="small"
                type="danger"
                :loading="deletingKey === row.line_key"
                @click="onDeleteOrder(row)"
              >
                删除
              </el-button>
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
    <ScanDialog
      v-model="scanOpen"
      :line-key="scanTarget.lineKey"
      :purchase-no="scanTarget.purchaseNo"
      :order-qty="scanTarget.orderQty"
      :pending-qty="scanTarget.pendingQty"
      :shipped-qty="scanTarget.shippedQty"
      @scanned="onScanned"
    />
    <ProcessScanDialog
      v-model="processScanOpen"
      :station="processScanStation"
      :purchase-no="processScanPurchaseNo"
      @scanned="onProcessScanned"
    />
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
          <el-tag type="success" size="small">PASS {{ boardsSummary.pass_count }}</el-tag>
          <el-tag
            type="danger"
            size="small"
            class="boards-fail-tag"
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
          默认不展示明细。搜索条码可查单板；点击上方 <strong>FAIL</strong> 可查看本单不良板码。
        </div>
        <template v-else>
          <div class="boards-detail-bar">
            <span v-if="boardsResultFilter === 'FAIL'">不良明细（{{ boardsSummary?.items?.length || 0 }}）</span>
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
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import {
  deleteOrder,
  exportOrdersBlob,
  fetchNewOrders,
  fetchOrderCount,
  fetchOrders,
  fetchStatusOptions,
  mergeCustomers,
  updateOrderRemark,
} from '@/api/orders'
import { fetchMaterialControlsByPurchase, materialControlAttachmentUrl } from '@/api/materialControls'
import {
  fetchOrderBoards,
  fetchOrderIctBoards,
  type OrderBoardSummary,
  type OrderIctBoardSummary,
} from '@/api/laser'
import { fetchProcessScans, type ProcessStation } from '@/api/processScan'
import { runSync } from '@/api/sync'
import ManualOrderDialog from '@/components/orders/ManualOrderDialog.vue'
import ProcessScanDialog from '@/components/orders/ProcessScanDialog.vue'
import ScanDialog from '@/components/orders/ScanDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { MaterialControl, MaterialControlGroup } from '@/types/materialControl'
import type { CustomerOption, OrderFilters, SrmOrder, StatusOption } from '@/types/order'
import { fmtDay, fmtQty, orderQty } from '@/utils/format'

const NOTIFY_KEY = 'ems_last_notified_sync_log_id'

const route = useRoute()
const auth = useAuthStore()

const pageTitle = computed(() =>
  '订单列表',
)
const canManage = computed(() => {
  const role = auth.user?.role
  return role === 'admin' || role === 'planner'
})

const canOperate = computed(() => {
  const role = auth.user?.role
  return role === 'admin' || role === 'planner' || role === 'warehouse' || role === 'floor' || role === 'packing'
})

/** 工序扫码（插件/后焊/三防）；包装账号仅能入库 */
const canProcessScan = computed(() => {
  const role = auth.user?.role
  return role === 'admin' || role === 'planner' || role === 'warehouse' || role === 'floor'
})

const opColWidth = computed(() => {
  let w = 0
  if (canOperate.value) {
    w += canProcessScan.value ? 168 : 72
  }
  if (canManage.value) w += 48
  return Math.max(w, 72)
})

const loading = ref(false)
const deletingKey = ref('')
const syncing = ref(false)
const newOrderCount = ref(0)
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
const scanOpen = ref(false)
const processScanOpen = ref(false)
const processScanStation = ref<ProcessStation>('plugin')
const processScanPurchaseNo = ref('')
const processListOpen = ref(false)
const processListLoading = ref(false)
const processListPurchaseNo = ref('')
const processListStation = ref<ProcessStation | ''>('plugin')
const processListKeyword = ref('')
const processListTotal = ref(0)
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
const scanTarget = reactive({ lineKey: '', purchaseNo: '', orderQty: 0, pendingQty: 0, shippedQty: 0 })
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
  () => !!boardsKeyword.value.trim() || boardsResultFilter.value === 'FAIL',
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
    scanOpen.value ||
    processScanOpen.value ||
    processListOpen.value ||
    controlDrawerOpen.value ||
    boardsOpen.value ||
    ictOpen.value ||
    newOrdersOpen.value,
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

/** 包装入库扫码总数 = 待发 + 已发 */
function inboundQty(row: SrmOrder) {
  return (row.pending_ship_qty || 0) + (row.shipped_local_qty || 0)
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
  return classes.join(' ')
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

async function loadOrders(opts?: { quiet?: boolean }) {
  const quiet = !!opts?.quiet
  if (!quiet) loading.value = true
  try {
    const f = buildFilterPayload()
    const [rows, countRes] = await Promise.all([
      fetchOrders({ ...f, page: page.value, page_size: pageSize.value }),
      fetchOrderCount(f),
    ])
    orders.value = rows.map((o) => {
      // 静默刷新时保留用户正在编辑、尚未失焦保存的备注
      const drafting = quiet && savingRemarkKey.value !== o.line_key && remarkDraft.has(o.line_key)
      const keepRemark = drafting ? (remarkDraft.get(o.line_key) ?? o.remark ?? '') : o.remark || ''
      remarkDraft.set(o.line_key, keepRemark)
      return { ...o, remark: keepRemark }
    })
    total.value = countRes.total
    refreshNewOrderCount()
  } catch (e) {
    if (!quiet) ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    if (!quiet) loading.value = false
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
  const wantItems =
    opts.includeItems === true ||
    !!boardsKeyword.value.trim() ||
    boardsResultFilter.value === 'FAIL'
  boardsLoading.value = true
  try {
    boardsSummary.value = await fetchOrderBoards(
      boardsPurchaseNo.value,
      boardsCustomerId.value,
      boardsKeyword.value,
      {
        result: boardsResultFilter.value,
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
  if (boardsResultFilter.value !== 'FAIL') {
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

function openScan(row: SrmOrder) {
  scanTarget.lineKey = row.line_key
  scanTarget.purchaseNo = row.purchase_no
  scanTarget.orderQty = orderQty(row)
  scanTarget.pendingQty = row.pending_ship_qty || 0
  scanTarget.shippedQty = row.shipped_local_qty || 0
  scanOpen.value = true
}

function openProcessScan(row: SrmOrder, station: ProcessStation) {
  processScanStation.value = station
  processScanPurchaseNo.value = row.purchase_no
  processScanOpen.value = true
}

/** 工序扫成功：只本地 +1，避免每次整表 loadOrders 拖慢扫码节奏 */
function onProcessScanned(station: ProcessStation) {
  const pn = (processScanPurchaseNo.value || '').trim()
  if (!pn) return
  for (const row of orders.value) {
    if ((row.purchase_no || '').trim() !== pn) continue
    if (station === 'plugin') row.plugin_qty = (row.plugin_qty || 0) + 1
    else if (station === 'post_solder') row.post_solder_qty = (row.post_solder_qty || 0) + 1
    else if (station === 'coating') row.coating_qty = (row.coating_qty || 0) + 1
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

function onScanned(pending: number, shipped: number) {
  const row = orders.value.find((o) => o.line_key === scanTarget.lineKey)
  if (row) {
    row.pending_ship_qty = pending
    row.shipped_local_qty = shipped
  }
  loadOrders()
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

async function askDeletePassword(): Promise<string | null> {
  try {
    const { value } = await ElMessageBox.prompt('请输入操作密码后继续', '删除订单 · 验证密码', {
      inputType: 'password',
      inputPlaceholder: '操作密码',
      confirmButtonText: '确定删除',
      cancelButtonText: '取消',
      type: 'warning',
      inputValidator: (v) => (!!v && !!String(v).trim() ? true : '请输入密码'),
    })
    return String(value || '').trim()
  } catch {
    return null
  }
}

async function onDeleteOrder(row: SrmOrder) {
  const label = [row.purchase_no, row.product_goods_no].filter(Boolean).join(' / ') || row.line_key
  try {
    await ElMessageBox.confirm(
      `确认删除订单「${label}」？删除后不可从本系统恢复（若 SRM 仍存在，下次同步可能重新导入）。`,
      '删除订单',
      { type: 'warning', confirmButtonText: '继续', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  const password = await askDeletePassword()
  if (!password) return
  deletingKey.value = row.line_key
  try {
    await deleteOrder(row.line_key, password)
    ElMessage.success('订单已删除')
    await loadOrders()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败')
  } finally {
    deletingKey.value = ''
  }
}

onMounted(async () => {
  await loadCustomers()
  await loadStatusOptions()
  await refreshNewOrderCount()
  await loadOrders()
  startOrdersAutoRefresh()
})

onUnmounted(() => {
  if (notifyTimer) clearInterval(notifyTimer)
  stopOrdersAutoRefresh()
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
.boards-fail-tag {
  cursor: pointer;
  user-select: none;
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
