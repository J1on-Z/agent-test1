import dayjs from 'dayjs'

export const fmtTime = (t) => (t ? dayjs(t + (t.endsWith('Z') ? '' : 'Z')).format('MM-DD HH:mm') : '')

export const fmtBytes = (n) => {
  if (n == null) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export const fmtTokens = (n) => {
  if (n == null) return '-'
  if (n < 1000) return `${n}`
  if (n < 1000000) return `${(n / 1000).toFixed(1)}K`
  return `${(n / 1000000).toFixed(2)}M`
}

export const fmtCost = (yuan) => (yuan == null ? '-' : `¥${Number(yuan).toFixed(4)}`)

// 后端时间存 naive UTC，前端补 Z 后本地化显示
export const fmtUTC = (t) => (t ? dayjs(`${t}Z`).format('YYYY-MM-DD HH:mm:ss') : '-')
