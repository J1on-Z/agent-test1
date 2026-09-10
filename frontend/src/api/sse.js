/**
 * SSE 流式消费（POST 场景 fetch 实现）：
 * 手动解析 text/event-stream 帧，支持 AbortController 停止与 401 错误识别。
 *
 * 返回 { abort, done: Promise }
 * 回调 onEvent(event, data)：
 *   meta(会话/消息/模型) / token(增量) / thinking(思考增量) /
 *   citations(引文) / done(usage/延迟) / error(失败)
 */
export function postSSE(url, body, { onEvent, getToken }) {
  const controller = new AbortController()

  const run = async () => {
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getToken()}`,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    if (resp.status === 401) {
      // 触发统一刷新逻辑（由上层处理后重试或跳登录）
      throw new Error(`SSE_UNAUTHORIZED:${resp.status}`)
    }
    if (!resp.ok || !resp.body) {
      const text = await resp.text().catch(() => '')
      throw new Error(`SSE_HTTP_${resp.status}:${text.slice(0, 200)}`)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    const parseBlock = (block) => {
      let event = 'message'
      const dataLines = []
      for (const line of block.split('\n')) {
        if (line.startsWith(':')) continue // 心跳注释帧
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (!dataLines.length) return
      try {
        onEvent(event, JSON.parse(dataLines.join('\n')))
      } catch {
        onEvent(event, dataLines.join('\n'))
      }
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        if (block.trim()) parseBlock(block)
      }
    }
    if (buffer.trim()) parseBlock(buffer) // 末尾无空行的事件
  }

  return {
    abort: () => controller.abort(),
    done: run(),
  }
}
