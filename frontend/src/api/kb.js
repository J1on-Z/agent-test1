import request from './request'

export const listDocuments = (params) => request.get('/kb/documents', { params })

export const getDocument = (id) => request.get(`/kb/documents/${id}`)

export const deleteDocument = (id) => request.delete(`/kb/documents/${id}`)

export const listJobs = (params) => request.get('/kb/ingest-jobs', { params })

export const getJob = (id) => request.get(`/kb/ingest-jobs/${id}`)

export const rebuildIndex = (reEmbed = false) =>
  request.post('/kb/rebuild-index', null, { params: { re_embed: reEmbed } })

export const debugRetrieve = (query) => request.post('/kb/debug/retrieve', { query })

export function uploadDocuments(files, category) {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  return request.post('/kb/documents', form, { timeout: 300000 })
}
