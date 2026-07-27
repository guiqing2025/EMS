<template>
  <div class="erp-content erp-content--flush">
    <iframe
      ref="iframeRef"
      :key="classicPageKey"
      class="legacy-frame"
      :src="frameSrc"
      title="业务页面"
      @load="onIframeLoad"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const iframeRef = ref<HTMLIFrameElement | null>(null)
const iframeReady = ref(false)

const classicPage = computed(() => (route.meta.classicPage as string) || 'orders')
const classicTab = computed(
  () => (route.meta.classicTab as string | undefined) || (route.query.tab as string | undefined) || '',
)
/** page+tab 作为 key，工程资料/替代料/工序对照互切时强制重载，避免串页 */
const classicPageKey = computed(() => {
  const tab = classicTab.value
  return tab ? `${classicPage.value}:${tab}` : classicPage.value
})

const frameSrc = computed(() => {
  const page = classicPage.value
  const params = new URLSearchParams({ embed: '1', page })
  const tab = classicTab.value
  if (tab) params.set('tab', tab)
  if (route.query.todo) params.set('todo', String(route.query.todo))
  if (route.query.customer) params.set('customer', String(route.query.customer))
  return `/classic/?${params.toString()}`
})

function postTabToIframe() {
  const page = route.meta.classicPage as string | undefined
  const tab = (route.meta.classicTab as string | undefined) || (route.query.tab as string | undefined)
  if (!page || !iframeRef.value?.contentWindow) return
  iframeRef.value.contentWindow.postMessage(
    {
      type: 'ems-embed-tab',
      page,
      tab,
      todo: route.query.todo ? String(route.query.todo) : '',
      customer: route.query.customer ? String(route.query.customer) : '',
    },
    window.location.origin,
  )
}

function onIframeLoad() {
  iframeReady.value = true
  postTabToIframe()
}

watch(
  () => [route.meta.classicTab, route.query.tab, route.query.todo, route.query.customer],
  () => {
    if (iframeReady.value) postTabToIframe()
  },
)

watch(classicPageKey, () => {
  iframeReady.value = false
})
</script>
