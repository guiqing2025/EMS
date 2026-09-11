<template>
  <div v-if="soId || soNo" class="flow-backlink">
    <span>所属销售订单：{{ soNo || `#${soId}` }}</span>
    <el-button link type="primary" @click="go">打开订单流程</el-button>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const props = defineProps<{ soId?: number | null; soNo?: string }>()
const router = useRouter()

function go() {
  const q: Record<string, string> = {}
  if (props.soId) q.so_id = String(props.soId)
  router.push({ path: '/sales/flow', query: q })
}
</script>

<style scoped>
.flow-backlink {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #f1f5f9;
  border-radius: 6px;
  font-size: 13px;
  color: #334155;
}
</style>
