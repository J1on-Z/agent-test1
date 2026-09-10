<template>
  <div class="chat-input-wrap">
    <div v-if="examples.length" class="examples">
      <span class="examples-label">试试：</span>
      <el-tag
        v-for="q in examples"
        :key="q"
        class="example-tag"
        @click="$emit('quick', q)"
      >{{ q }}</el-tag>
    </div>
    <div class="input-box">
      <el-input
        v-model="text"
        type="textarea"
        :rows="2"
        resize="none"
        placeholder="输入商品相关问题，如：星辰X1 Pro 的电池容量是多少？（Enter 发送，Shift+Enter 换行）"
        @keydown.enter.exact.prevent="submit"
      />
      <div class="input-toolbar">
        <div class="toolbar-left">
          <span class="tool-label">模型</span>
          <el-select v-model="model" size="small" style="width: 170px">
            <el-option v-for="m in models" :key="m.name" :label="m.label" :value="m.name" />
          </el-select>
          <el-tooltip content="开启后展示模型的思考过程，回答更深入但速度更慢" placement="top">
            <el-switch v-model="thinking" size="small" active-text="思考" />
          </el-tooltip>
        </div>
        <div class="toolbar-right">
          <el-button v-if="streaming" type="danger" size="small" @click="$emit('stop')">
            ⏹ 停止生成
          </el-button>
          <el-button type="primary" size="small" :disabled="!canSend" @click="submit">
            发送
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import request from '../../api/request'

const props = defineProps({
  streaming: { type: Boolean, default: false },
  examples: { type: Array, default: () => [] },
})
const emit = defineEmits(['send', 'stop', 'quick'])

const text = ref('')
const models = ref([])
const model = ref('')
const thinking = ref(false)
const canSend = computed(() => text.value.trim().length > 0 && !props.streaming)

onMounted(async () => {
  try {
    models.value = await request.get('/chat/models', {}, { _silent: true })
    model.value = models.value[0]?.name || ''
  } catch { /* 加载失败时保持空选项 */ }
})

function submit() {
  if (!canSend.value) return
  emit('send', { question: text.value.trim(), model: model.value || undefined, thinking: thinking.value })
  text.value = ''
}
</script>

<style scoped>
.chat-input-wrap { padding: 0 20px 16px; }
.examples { margin-bottom: 8px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.examples-label { font-size: 12px; color: #909399; }
.example-tag { cursor: pointer; font-size: 12px; }
.example-tag:hover { background: #ecf5ff; }
.input-box { border: 1px solid #dcdfe6; border-radius: 10px; padding: 10px 12px 8px; background: #fff; }
.input-box :deep(.el-textarea__inner) { box-shadow: none; padding: 2px; }
.input-toolbar { display: flex; justify-content: space-between; align-items: center; margin-top: 6px; }
.toolbar-left { display: flex; align-items: center; gap: 8px; }
.tool-label { font-size: 12px; color: #909399; }
</style>
