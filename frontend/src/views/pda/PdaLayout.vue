<template>
  <div class="dev-shell">
    <header class="dev-shell-bar">
      <strong>PDA</strong>
      <span class="muted">开发占位（源码包缺此页）</span>
      <router-link to="/orders">回订单</router-link>
    </header>
    <main class="dev-shell-main">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
</script>

<style scoped>
.dev-shell { min-height: 100vh; background: #f5f7fb; color: #0f172a; }
.dev-shell-bar {
  display: flex; gap: 12px; align-items: center; padding: 12px 16px;
  background: #fff; border-bottom: 1px solid #e2e8f0; font-size: 14px;
}
.dev-shell-bar .muted { color: #64748b; flex: 1; }
.dev-shell-bar a { color: #2563eb; text-decoration: none; }
.dev-shell-main { padding: 16px; }
</style>
