<template>
  <div class="chat-layout">
    <ConversationSidebar
      :current-id="chat.currentId"
      @new-chat="onNewChat"
      @select="onSelect"
    />

    <div class="chat-main">
      <div class="chat-scroll" ref="scrollEl">
        <div v-if="chat.loadingHistory" class="center-hint"><el-icon class="is-loading"><Loading /></el-icon> 加载历史消息…</div>
        <div v-else-if="!chat.messages.length" class="welcome">
          <div class="welcome-icon">🛒</div>
          <h2>星辰电商知识库智能问答</h2>
          <p>基于 LangChain + LangGraph 的企业级 RAG 问答系统<br/>商品参数、售后政策、物流配送，随问随答，答案附知识库引用来源</p>
        </div>
        <MessageBubble
          v-for="(m, i) in chat.messages"
          :key="m.id || m._tempKey"
          :msg="m"
          :can-regenerate="i === chat.messages.length - 1 && m.role === 'assistant' && !m.streaming && !chat.streaming"
          @regenerate="onRegenerate(m)"
        />
      </div>

      <ChatInput
        :streaming="stream"
        :examples="chat.messages.length ? [] : DEFAULT_QUESTIONS"
        @send="onSend"
        @stop="stopStream"
        @quick="onSend({ question: $event, thinking: false })"
      />
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { useChatStore } from '../stores/chat'
import { useChatStream } from '../composables/useChatStream'
import ConversationSidebar from '../components/chat/ConversationSidebar.vue'
import MessageBubble from '../components/chat/MessageBubble.vue'
import ChatInput from '../components/chat/ChatInput.vue'

const DEFAULT_QUESTIONS = [
  '星辰X1 Pro 的电池容量和快充功率是多少？',
  '七天无理由退货有什么条件？',
  '暖冬羽绒服怎么洗涤保养？',
  '偏远地区运费怎么算？',
]

const chat = useChatStore()
const { streaming: stream, send, stop } = useChatStream()
const scrollEl = ref(null)

onMounted(() => {
  chat.loadConversations().catch(() => {})
  // 默认打开最近一个会话
  if (chat.conversations.length && !chat.currentId) {
    chat.openConversation(chat.conversations[0].id)
  }
})

watch(
  () => chat.messages.map((m) => (m.streaming ? m.content.length : -1)).join(','),
  () => scrollToBottom(),
)

async function scrollToBottom() {
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}

function onNewChat() {
  chat.startNewChat()
}

async function onSelect(id) {
  await chat.openConversation(id)
  scrollToBottom()
}

function onSend({ question, model, thinking }) {
  send(question, { model, thinking })
}

function onRegenerate(msg) {
  const question = [...chat.messages].reverse().find((m) => m.role === 'user')?.content
  if (!question) return
  // 移除旧回答（本地显示层），后端 regenerate 会同步删除
  const idx = chat.messages.indexOf(msg)
  if (idx >= 0) chat.messages.splice(idx, 1)
  send(question, { model: msg.model || undefined, thinking: false, regenerateTarget: { question } })
}

function stopStream() {
  stop()
}
</script>

<style scoped>
.chat-layout { display: flex; height: 100vh; }
.chat-main { flex: 1; display: flex; flex-direction: column; background: #f2f3f7; }
.chat-scroll { flex: 1; overflow-y: auto; padding: 20px 24px 10px; }
.center-hint { text-align: center; color: #909399; padding: 30px 0; }
.welcome { text-align: center; margin-top: 15vh; color: #606266; }
.welcome-icon { font-size: 46px; }
.welcome h2 { color: #303133; margin: 10px 0 6px; }
.welcome p { color: #909399; line-height: 1.8; font-size: 14px; }
</style>
