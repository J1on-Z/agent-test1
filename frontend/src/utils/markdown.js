import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/github.css'

/**
 * Markdown 渲染 + 【n】引文标注：
 * - 自写 inline rule 把【n】渲染为 <sup class="cite-badge" data-cite="n">n</sup>，
 *   与正文同一遍渲染完成，避免先渲染 HTML 再字符串替换的 XSS 与错位问题
 * - 整体过 DOMPurify（白名单放行 sup 与 data-cite 属性），模型输出不可信
 */
const md = new MarkdownIt({
  html: false, // 禁用原始 HTML，全部由 DOMPurify 兜底
  linkify: true,
  breaks: true,
  highlight(str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(str, { language: lang }).value}</code></pre>`
      } catch { /* fallthrough */ }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(str)}</code></pre>`
  },
})

// 在普通文本规则之前拦截【n】
md.inline.ruler.before('text', 'cite_badge', (state, silent) => {
  const pos = state.pos
  if (state.src.charCodeAt(pos) !== 0x3010 /* 【 */) return false
  const match = state.src.slice(pos).match(/^【(\d{1,2})】/)
  if (!match) return false
  if (!silent) {
    const token = state.push('html_inline', '', 0)
    token.content = `<sup class="cite-badge" data-cite="${match[1]}">${match[1]}</sup>`
  }
  state.pos = pos + match[0].length
  return true
})

const sanitize = (html) =>
  DOMPurify.sanitize(html, {
    ADD_ATTR: ['data-cite'],
    ADD_TAGS: ['sup'],
    ALLOWED_ATTR: ['href', 'target', 'rel', 'class', 'data-cite'],
  })

export function renderMarkdown(text) {
  if (!text) return ''
  return sanitize(md.render(text))
}
