import { ref } from 'vue'
import { useChatStore } from '../stores/chat'
import { useAuthStore } from '../stores/auth'
import { postSSE } from '../api/sse'
import { ElMessage } from 'element-plus'

/**
 * SSE 流式问答状态机：
 * idle → streaming → done / error / aborted
 * 维护消息列表中的「流式占位消息」（_tempKey 标识），事件驱动增量更新。
 */
export function useChatStream() {
  const chat = useChatStore()
  const auth = useAuthStore()
  const streaming = ref(false)
  const thinkingText = ref('')
  let abortFn = null

  function makeTempKey() {
    return `tmp_${Date.now()}_${Math.random().toString(36).slice(2)}`
  }

  async function send(question, { model = undefined, thinking = false, regenerateTarget = null } = {}) {
    if (streaming.value) return
    streaming.value = true
    thinkingText.value = ''

    const tempKey = makeTempKey()
    if (!regenerateTarget) {
      chat.pushMessage({ _tempKey: tempKey, role: 'user', content: question, created_at: new Date().toISOString() })
    }
    const assistantTemp = { _tempKey: `a_${tempKey}`, role: 'assistant', content: '', thinking: '', citations: [], streaming: true }
    chat.pushMessage(assistantTemp)

    const questionBody = regenerateTarget ? regenerateTarget.question : question
    const body = {
      conversation_id: chat.currentId,
      question: questionBody,
      model,
      thinking,
    }

    try {
      const handle = postSSE('/api/chat', body, {
        getToken: () => auth.accessToken,
        onEvent(event, data) {
          if (event === 'meta') {
            if (data.conversation_id && !chat.currentId) {
              chat.currentId = data.conversation_id
              chat.refreshConversationMeta()
            }
          } else if (event === 'token') {
            assistantTemp.content += data.delta
            chat.updateMessage(assistantTemp._tempKey, { content: assistantTemp.content })
          } else if (event === 'thinking') {
            assistantTemp.thinking += data.delta
            chat.updateMessage(assistantTemp._tempKey, { thinking: assistantTemp.thinking })
          } else if (event === 'citations') {
            assistantTemp.citations = data.citations || []
            chat.updateMessage(assistantTemp._tempKey, { citations: assistantTemp.citations })
          } else if (event === 'done') {
            chat.updateMessage(assistantTemp._tempKey, {
              ...data,
              streaming: false,
              content: assistantTemp.content,
            })
            // 用真实消息 id 替换临时键
            if (data.message_id) {
              const idx = chat.messages.findIndex((m) => m._tempKey === assistantTemp._tempKey)
              if (idx >= 0) {
                chat.messages[idx] = { ...chat.messages[idx], _tempKey: null, id: data.message_id }
              }
            }
            chat.refreshConversationMeta()
          } else if (event === 'error') {
            chat.updateMessage(assistantTemp._tempKey, {
              streaming: false,
              error: data.message || '生成失败',
            })
          }
        },
      })
      abortFn = handle.abort
      await handle.done
    } catch (e) {
      if (String(e).includes('AbortError') || String(e).includes('aborted')) {
        chat.updateMessage(assistantTemp._tempKey, { streaming: false, interrupted: true })
      } else if (String(e).includes('SSE_UNAUTHORIZED')) {
        // 401：清会话状态，交由路由守卫跳登录
        auth.clear()
        window.location.href = '/login'
      } else {
        chat.updateMessage(assistantTemp._tempKey, {
          streaming: false,
          error: String(e).includes('SSE_HTTP') ? '服务异常，请稍后重试' : e.message || '生成失败',
        })
      }
    } finally {
      streaming.value = false
      thinkingText.value = ''
      abortFn = null
    }
  }

  function stop() {
    if (abortFn) abortFn()
  }

  return { streaming, thinkingText, send, stop }
}
