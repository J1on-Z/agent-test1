import request from './request'

export const getOverview = () => request.get('/stats/overview')
export const getDaily = (days = 14) => request.get('/stats/daily', { params: { days } })
export const getTokenUsage = (days = 14) => request.get('/stats/token-usage', { params: { days } })
export const getLatency = () => request.get('/stats/latency')
export const getCache = (days = 14) => request.get('/stats/cache', { params: { days } })
export const getTopUsers = (limit = 10) => request.get('/stats/top-users', { params: { limit } })
