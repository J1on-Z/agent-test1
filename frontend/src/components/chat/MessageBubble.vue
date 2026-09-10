<template>
  <div class="msg-row" :class="msg.role">
    <div class="avatar" v-if="msg.role === 'assistant'">🤖</div>
    <div class="bubble-wrap">
      <div v-if="msg.role === 'user'" class="user-bubble">{{ msg.content }}</div>

      <div v-else class="assistant-bubble">
        <!-- 思考过程折叠块（思考模式） -->
        <el-collapse v-if="msg.thinking" class="thinking-block">
          <el-collapse-item name="think">
            <template #title>
              <span class="thinking-title">🧠 思考过程</span>
            </template>
            <div class="thinking-content">{{ msg.thinking }}</div>
          </el-collapse-item>
        </el-collapse>

        <!-- 回答正文：markdown + 【n】引文上标 -->
        <div
          class="markdown-body"
          v-html="rendered"
          @click="onContentClick"
        ></div>

        <div v-if="msg.streaming && !msg.content" class="typing">
          <span></span><span></span><span></span>
        </div>
        <div v-if="msg.error" class="error-line">⚠ {{ msg.error }}</div>
        <div v-if="msg.interrupted" class="error-line">⏹ 已停止生成</div>

        <!-- 点击引文上标后的片段预览卡 -->
        <div v-if="activeCitation" class="cite-popover">
          <div class="cite-popover-head">
            <b>引用片段</b>
            <el-tag size="small" type="info">来源：{{ activeCitation.doc_name }}</el-tag>
          </div>
          <div class="cite-popover-meta">
            <span v-if="activeCitation.title">{{ activeCitation.title }}</span>
            <span v-if="activeCitation.page"> · 第 {{ activeCitation.page }} 页</span>
            <span v-if="activeCitation.score != null"> · 相关度 {{ activeCitation.score }}</span>
          </div>
          <div class="cite-popover-snippet">{{ activeCitation.snippet }}</div>
        </div>

        <!-- 引用卡片列表 -->
        <div v-if="msg.citations && msg.citations.length" class="citation-list">
          <div class="citation-title">📚 引用来源</div>
          <div v-for="c in msg.citations" :key="c.index" class="citation-card" @click="toggleCitation(c)">
            <div class="citation-head">
              <span class="cite-index">[{{ c.index }}]</span>
              <span class="cite-doc">《{{ c.doc_name }}》</span>
              <el-tag v-if="c.score != null" size="small" type="success">相关度 {{ c.score }}</el-tag>
            </div>
            <div class="citation-sub">
              <span v-if="c.title">{{ c.title }}</span>
              <span v-if="c.page"> · 第 {{ c.page }} 页</span>
            </div>
          </div>
        </div>

        <!-- 消息元信息与操作 -->
        <div class="msg-meta">
          <span v-if="msg.model">{{ msg.model }}</span>
          <el-tag v-if="msg.from_cache" size="small" type="warning">命中缓存 · 0 tokens</el-tag>
          <span v-if="msg.latency_ms != null">总耗时 {{ (msg.latency_ms / 1000).toFixed(1) }}s</span>
          <span v-if="msg.ttft_ms != null">首字 {{ (msg.ttft_ms / 1000).toFixed(1) }}s</span>
          <span v-if="msg.token_usage && msg.token_usage.total_tokens">
            {{ msg.token_usage.total_tokens }} tokens
          </span>
          <span class="meta-actions" v-if="!msg.streaming">
            <el-button link size="small" @click="copyMessage">复制</el-button>
            <el-button link size="small" type="primary" @click="$emit('regenerate')" v-if="canRegenerate">重新生成</el-button>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { renderMarkdown } from '../../utils/markdown'

const props = defineProps({
  msg: { type: Object, required: true },
  canRegenerate: { type: Boolean, default: false },
})
defineEmits(['regenerate'])

const activeCitation = ref(null)
const rendered = computed(() => renderMarkdown(props.msg.content))

function findCitation(num) {
  return (props.msg.citations || []).find((c) => String(c.index) === String(num))
}

function onContentClick(e) {
  const badge = e.target.closest('.cite-badge')
  if (!badge) return
  const cite = findCitation(badge.dataset.cite)
  if (cite) toggleCitation(cite)
}

function toggleCitation(c) {
  activeCitation.value = activeCitation.value?.index === c.index ? null : c
}

async function copyMessage() {
  let text = props.msg.content
  if (props.msg.citations?.length) {
    text += '\n\n【引用来源】\n' + props.msg.citations
      .map((c) => `[${c.index}] 《${c.doc_name}》${c.page ? ` 第${c.page}页` : ''}：${(c.snippet || '').slice(0, 100)}`)
      .join('\n')
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}
</script>

<style scoped>
.msg-row { display: flex; gap: 10px; margin-bottom: 18px; }
.msg-row.user { flex-direction: row-reverse; }
.avatar { width: 36px; height: 36px; border-radius: 50%; background: #eef2ff; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
.bubble-wrap { max-width: 78%; }
.user-bubble { background: #409eff; color: #fff; padding: 10px 14px; border-radius: 12px 2px 12px 12px; white-space: pre-wrap; word-break: break-word; }
.assistant-bubble { background: #fff; border: 1px solid #e4e7ed; border-radius: 2px 12px 12px 12px; padding: 12px 16px; }
.markdown-body { line-height: 1.7; word-break: break-word; }
.markdown-body :deep(pre) { background: #f6f8fa; padding: 10px; border-radius: 6px; overflow-x: auto; }
.markdown-body :deep(code) { background: #f6f8fa; padding: 1px 5px; border-radius: 4px; font-size: 13px; }
.markdown-body :deep(pre code) { background: none; padding: 0; }
.markdown-body :deep(.cite-badge) {
  color: #409eff; background: #ecf5ff; border-radius: 4px; padding: 0 4px; margin: 0 1px;
  font-size: 12px; cursor: pointer; font-weight: 600; user-select: none;
}
.markdown-body :deep(.cite-badge:hover) { background: #409eff; color: #fff; }
.markdown-body :deep(table) { border-collapse: collapse; }
.markdown-body :deep(th), .markdown-body :deep(td) { border: 1px solid #dcdfe6; padding: 4px 10px; }

.thinking-block { margin-bottom: 8px; }
.thinking-title { color: #909399; font-size: 13px; }
.thinking-content { white-space: pre-wrap; color: #606266; font-size: 13px; line-height: 1.6; background: #fafafa; padding: 8px; border-radius: 6px; }

.typing span { display: inline-block; width: 6px; height: 6px; margin-right: 4px; background: #909399; border-radius: 50%; animation: blink 1.2s infinite; }
.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%, 100% { opacity: 0.2; } 50% { opacity: 1; } }
.error-line { color: #f56c6c; font-size: 13px; margin-top: 6px; }

.cite-popover { margin-top: 10px; border: 1px solid #d9ecff; background: #f4f9ff; border-radius: 8px; padding: 10px 12px; }
.cite-popover-head { display: flex; gap: 8px; align-items: center; margin-bottom: 4px; }
.cite-popover-meta { color: #909399; font-size: 12px; margin-bottom: 6px; }
.cite-popover-snippet { color: #303133; font-size: 13px; line-height: 1.7; white-space: pre-wrap; }

.citation-list { margin-top: 10px; border-top: 1px dashed #e4e7ed; padding-top: 8px; }
.citation-title { font-size: 13px; color: #909399; margin-bottom: 6px; }
.citation-card { border: 1px solid #e4e7ed; border-radius: 8px; padding: 8px 10px; margin-bottom: 6px; cursor: pointer; transition: border-color 0.15s; }
.citation-card:hover { border-color: #409eff; }
.citation-head { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.cite-index { color: #409eff; font-weight: 700; }
.citation-sub { color: #909399; font-size: 12px; margin-top: 3px; }

.msg-meta { margin-top: 8px; color: #a8abb2; font-size: 12px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.meta-actions { margin-left: auto; }
</style>
