import request from './request'

export const listConversations = (page = 1, pageSize = 50) =>
  request.get('/conversations', { params: { page, page_size: pageSize } })

export const createConversation = () => request.post('/conversations')

export const renameConversation = (id, title) =>
  request.patch(`/conversations/${id}`, { title })

export const deleteConversation = (id) => request.delete(`/conversations/${id}`)

export const listMessages = (conversationId, page = 1, pageSize = 100) =>
  request.get(`/conversations/${conversationId}/messages`, { params: { page, page_size: pageSize } })

export const exportConversationUrl = (conversationId) =>
  `/api/conversations/${conversationId}/export`

export const stopMessage = (messageId) =>
  request.post(`/chat/messages/${messageId}/stop`, {}, { _silent: true })
