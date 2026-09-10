import { defineStore } from 'pinia'
import { listConversations, listMessages } from '../api/chat'

export const useChatStore = defineStore('chat', {
  state: () => ({
    conversations: [],
    currentId: null,
    messages: [],
    streaming: false,
    loadingHistory: false,
  }),
  actions: {
    async loadConversations() {
      const data = await listConversations(1, 100)
      this.conversations = data.items
    },
    async openConversation(id) {
      this.currentId = id
      this.messages = []
      this.loadingHistory = true
      try {
        const data = await listMessages(id, 1, 200)
        this.messages = data.items
      } finally {
        this.loadingHistory = false
      }
    },
    startNewChat() {
      this.currentId = null
      this.messages = []
    },
    pushMessage(msg) {
      this.messages.push(msg)
    },
    updateMessage(id, patch) {
      const idx = this.messages.findIndex((m) => m.id === id || m._tempKey === id)
      if (idx >= 0) this.messages[idx] = { ...this.messages[idx], ...patch }
    },
    refreshConversationMeta() {
      this.loadConversations().catch(() => {})
    },
  },
})
