<template>
  <div class="erp-content">
    <div class="erp-page-card">
      <div class="erp-page-toolbar">
        <div>
          <h2 style="margin: 0; font-size: 18px">订单编码</h2>
          <p style="margin: 4px 0 0; color: var(--erp-text-muted); font-size: 13px">
            登记销售订单单号规则：前缀 + 日期 + 流水。新建销售订单时自动按此规则取号。
          </p>
        </div>
        <div style="display: flex; gap: 8px">
          <el-button @click="load">刷新</el-button>
          <el-button type="primary" :loading="saving" @click="onSave">保存规则</el-button>
        </div>
      </div>
      <div class="erp-page-body" v-loading="loading">
        <el-form label-width="120px" style="max-width: 560px">
          <el-form-item label="单据类型">
            <el-input model-value="销售订单 (sales_order)" disabled />
          </el-form-item>
          <el-form-item label="规则名称">
            <el-input v-model="form.name" placeholder="销售订单" maxlength="64" />
          </el-form-item>
          <el-form-item label="前缀" required>
            <el-input v-model="form.prefix" placeholder="如 SO" maxlength="16" style="width: 160px" />
            <span class="hint">字母/数字，最长 16 位</span>
          </el-form-item>
          <el-form-item label="日期格式" required>
            <el-select v-model="form.date_fmt" style="width: 220px">
              <el-option label="年月日 YYYYMMDD" value="%Y%m%d" />
              <el-option label="年月 YYYYMM" value="%Y%m" />
              <el-option label="短年月日 YYMMDD" value="%y%m%d" />
            </el-select>
          </el-form-item>
          <el-form-item label="流水位数" required>
            <el-input-number v-model="form.seq_width" :min="3" :max="8" />
            <span class="hint">3～8 位，同日递增，跨日重置</span>
          </el-form-item>
          <el-form-item label="当前流水">
            <span>
              {{ form.last_date || '—' }}
              /
              第 {{ form.last_seq || 0 }} 号
            </span>
          </el-form-item>
          <el-form-item label="下一单号预览">
            <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
              <el-tag type="success" size="large" effect="plain">{{ previewNo || '—' }}</el-tag>
              <el-button link type="primary" :loading="previewing" @click="onPreview">重新预览</el-button>
            </div>
            <div class="hint" style="margin-top: 4px">预览不占用流水；真正新建订单时才会取号。</div>
          </el-form-item>
        </el-form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchSalesOrderCode, previewSalesOrderCode, saveSalesOrderCode } from '@/api/sales'

const loading = ref(false)
const saving = ref(false)
const previewing = ref(false)
const previewNo = ref('')

const form = reactive({
  name: '销售订单',
  prefix: 'SO',
  date_fmt: '%Y%m%d',
  seq_width: 4,
  last_date: '',
  last_seq: 0,
})

async function load() {
  loading.value = true
  try {
    const data = await fetchSalesOrderCode()
    form.name = data.name || '销售订单'
    form.prefix = data.prefix || 'SO'
    form.date_fmt = data.date_fmt || '%Y%m%d'
    form.seq_width = data.seq_width || 4
    form.last_date = data.last_date || ''
    form.last_seq = data.last_seq || 0
    previewNo.value = data.preview_no || ''
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onSave() {
  const prefix = form.prefix.trim().toUpperCase()
  if (!prefix) {
    ElMessage.warning('请填写前缀')
    return
  }
  saving.value = true
  try {
    const data = await saveSalesOrderCode({
      prefix,
      name: form.name.trim() || '销售订单',
      date_fmt: form.date_fmt,
      seq_width: form.seq_width,
    })
    form.prefix = data.prefix
    form.name = data.name
    form.date_fmt = data.date_fmt
    form.seq_width = data.seq_width
    form.last_date = data.last_date
    form.last_seq = data.last_seq
    previewNo.value = data.preview_no || ''
    ElMessage.success('规则已保存')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function onPreview() {
  previewing.value = true
  try {
    const res = await previewSalesOrderCode()
    previewNo.value = res.doc_no
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '预览失败')
  } finally {
    previewing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.hint {
  margin-left: 10px;
  color: var(--erp-text-muted);
  font-size: 12px;
}
</style>
