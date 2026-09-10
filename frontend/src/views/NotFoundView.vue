<template>
  <div class="nf-page">
    <h1>{{ is403 ? '403' : '404' }}</h1>
    <p>{{ is403 ? '仅管理员可访问该页面' : '页面不存在' }}</p>
    <el-button type="primary" @click="$router.push('/')">返回首页</el-button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
const is403 = computed(() => useRoute().meta.forbidden)
</script>

<style scoped>
.nf-page { height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: #606266; }
.nf-page h1 { font-size: 64px; margin: 0; color: #c0c4cc; }
</style>
