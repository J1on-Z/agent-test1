<template>
  <div class="stats-page">
    <div class="stats-header">
      <h2>运营统计看板</h2>
      <div class="header-right">
        <el-radio-group v-model="days" size="small" @change="loadAll">
          <el-radio-button :value="7">近 7 天</el-radio-button>
          <el-radio-button :value="14">近 14 天</el-radio-button>
          <el-radio-button :value="30">近 30 天</el-radio-button>
        </el-radio-group>
        <el-button link @click="$router.push('/')">← 返回问答</el-button>
      </div>
    </div>

    <!-- 总览指标卡（hero numbers） -->
    <div class="stat-grid" v-if="overview">
      <div v-for="card in cards" :key="card.label" class="stat-tile">
        <div class="tile-label">{{ card.label }}</div>
        <div class="tile-value">{{ card.value }}</div>
        <div class="tile-sub">{{ card.sub }}</div>
      </div>
    </div>

    <div class="chart-grid">
      <div class="chart-card">
        <div class="chart-title">每日问答量与活跃用户</div>
        <div ref="dailyEl" class="chart-body"></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">每日 Token 消耗（按模型）</div>
        <div ref="tokenEl" class="chart-body"></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">回答延迟 p50 / p95（ms）</div>
        <div ref="latencyEl" class="chart-body"></div>
      </div>
      <div class="chart-card">
        <div class="chart-title">语义缓存命中率（%）</div>
        <div ref="cacheEl" class="chart-body"></div>
      </div>
    </div>

    <div class="chart-card table-card">
      <div class="chart-title">活跃用户 Top 10</div>
      <el-table :data="topUsers" size="small">
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="message_count" label="消息数" width="110" />
        <el-table-column prop="total_tokens" label="消耗 tokens" width="130" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import * as echarts from 'echarts'
import { getOverview, getDaily, getTokenUsage, getLatency, getCache, getTopUsers } from '../../api/stats'
import { fmtTokens } from '../../utils/format'

// 参考色板（dataviz 验证通过）：分类固定顺序，文本走 ink 而非系列色
const C = {
  series1: '#2a78d6', // blue
  series2: '#eb6834', // orange
  series3: '#1baf7a', // aqua
  ink: '#0b0b0b',
  inkSecondary: '#52514e',
  muted: '#898781',
  grid: '#e1e0d9',
  surface: '#fcfcfb',
}

const days = ref(14)
const overview = ref(null)
const topUsers = ref([])
const charts = {}
const dailyEl = ref(null)
const tokenEl = ref(null)
const latencyEl = ref(null)
const cacheEl = ref(null)

const cards = computed(() => {
  if (!overview.value) return []
  const o = overview.value
  return [
    { label: '注册用户', value: o.user_count, sub: `今日活跃 ${o.active_users_today}` },
    { label: '累计问答', value: o.message_count, sub: `会话 ${o.conversation_count} 个` },
    { label: '知识库文档', value: `${o.ready_documents}/${o.document_count}`, sub: '就绪/总数' },
    { label: '累计 Token', value: fmtTokens(o.total_tokens), sub: `约 ${o.estimated_cost_yuan} 元` },
    { label: '缓存命中率', value: `${o.cache_hit_rate}%`, sub: `节省 ${fmtTokens(o.saved_tokens)} tokens` },
    { label: '平均延迟', value: `${o.avg_latency_ms}ms`, sub: `p95 ${o.p95_latency_ms}ms` },
  ]
})

const baseLineOption = (xData, series, { yName = '' } = {}) => ({
  grid: { left: 48, right: 16, top: 24, bottom: 28 },
  tooltip: { trigger: 'axis', backgroundColor: C.surface, borderColor: C.grid, textStyle: { color: C.ink } },
  legend: { data: series.map((s) => s.name), textStyle: { color: C.inkSecondary }, top: 0, icon: 'rect', itemWidth: 10, itemHeight: 2 },
  xAxis: { type: 'category', data: xData, axisLine: { lineStyle: { color: '#c3c2b7' } }, axisLabel: { color: C.muted }, axisTick: { show: false } },
  yAxis: { type: 'value', name: yName, nameTextStyle: { color: C.muted }, splitLine: { lineStyle: { color: C.grid } }, axisLabel: { color: C.muted } },
  series: series.map((s, i) => ({
    name: s.name,
    type: s.type || 'line',
    data: s.data,
    symbol: 'circle',
    symbolSize: 5,
    lineStyle: { width: 2, color: [C.series1, C.series2, C.series3][i] },
    itemStyle: { color: [C.series1, C.series2, C.series3][i] },
    ...(s.type === 'bar' ? { barMaxWidth: 18, itemStyle: { color: [C.series1, C.series2, C.series3][i], borderRadius: [3, 3, 0, 0] } } : {}),
    ...(s.type === 'bar' && s.stack ? { stack: 'total' } : {}),
  })),
})

function renderChart(el, option) {
  if (!el.value) return
  if (!charts[el]) charts[el] = echarts.init(el.value)
  charts[el].setOption(option, true)
}

async function loadAll() {
  try {
    const [ov, daily, tokens, latency, cache, top] = await Promise.all([
      getOverview(), getDaily(days.value), getTokenUsage(days.value), getLatency(), getCache(days.value), getTopUsers(),
    ])
    overview.value = ov
    topUsers.value = top

    renderChart(dailyEl, baseLineOption(daily.dates, [
      { name: '问答数', data: daily.message_counts },
      { name: '活跃用户', data: daily.active_users },
    ], { yName: '次数' }))

    renderChart(tokenEl, baseLineOption(tokens.dates, tokens.models.map((m, i) => ({
      name: m, type: 'bar', stack: true, data: tokens.series[i],
    })), { yName: 'tokens' }))

    renderChart(latencyEl, baseLineOption(latency.dates, [
      { name: 'p50', data: latency.p50 },
      { name: 'p95', data: latency.p95 },
    ], { yName: 'ms' }))

    renderChart(cacheEl, baseLineOption(cache.dates, [
      { name: '命中率', data: cache.hit_rate },
    ], { yName: '%' }))
  } catch { /* 接口失败时页面保留空状态 */ }
}

const resize = () => Object.values(charts).forEach((c) => c.resize())

onMounted(() => {
  loadAll()
  window.addEventListener('resize', resize)
})
onUnmounted(() => {
  window.removeEventListener('resize', resize)
  Object.values(charts).forEach((c) => c.dispose())
})
</script>

<style scoped>
.stats-page { min-height: 100vh; background: #f2f3f7; padding: 20px 24px; }
.stats-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.stats-header h2 { margin: 0; }
.header-right { display: flex; gap: 16px; align-items: center; }
.stat-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 16px; }
.stat-tile { background: #fff; border: 1px solid #e4e7ed; border-radius: 10px; padding: 14px 16px; }
.tile-label { font-size: 12px; color: #898781; }
.tile-value { font-size: 24px; font-weight: 700; color: #0b0b0b; margin: 6px 0 2px; font-variant-numeric: tabular-nums; }
.tile-sub { font-size: 12px; color: #52514e; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
.chart-card { background: #fff; border: 1px solid #e4e7ed; border-radius: 10px; padding: 14px 16px; }
.chart-title { font-size: 14px; font-weight: 600; color: #0b0b0b; margin-bottom: 6px; }
.chart-body { height: 240px; }
.table-card { margin-bottom: 20px; }
</style>
