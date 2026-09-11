<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">计划</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            MC 齐套运算与 PMC 排产
          </p>
        </div>
      </div>
      <div class="erp-page-body" style="max-width: 640px">
        <div class="entry-list">
          <div class="entry" @click="$router.push('/planning/mc-kitting')">
            <div class="entry-title">MC齐套运算</div>
            <div class="entry-desc">销售订单 × BOM × 库存，计算齐套与缺料</div>
          </div>
          <div class="entry" @click="$router.push('/planning/pmc-schedule')">
            <div class="entry-title">PMC排产</div>
            <div class="entry-desc">SMT / DIP 产线排产、日计划与备料状态</div>
          </div>
        </div>
        <div style="margin-top: 16px">
          <el-button @click="$router.push('/sales/flow')">去订单流程</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.entry-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.entry {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 14px 16px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.entry:hover {
  border-color: var(--el-color-primary);
  background: var(--el-fill-color-light);
}
.entry-title {
  font-size: 15px;
  font-weight: 600;
}
.entry-desc {
  margin-top: 4px;
  font-size: 13px;
  color: var(--erp-text-muted);
}
</style>
