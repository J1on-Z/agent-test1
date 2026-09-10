<template>
  <div class="kb-page">
    <div class="kb-header">
      <div>
        <h2>知识库管理</h2>
        <span class="sub">支持 PDF / DOCX / XLSX / Markdown / TXT，上传后自动解析、分块、向量化</span>
      </div>
      <div class="header-actions">
        <el-button @click="rebuild(false)">重建 BM25 索引</el-button>
        <el-button @click="rebuild(true)">全量重向量化</el-button>
        <el-button type="primary" @click="uploadVisible = true"><el-icon><Upload /></el-icon>&nbsp;上传文档</el-button>
        <el-button link @click="$router.push('/')">← 返回问答</el-button>
      </div>
    </div>

    <!-- 统计条 -->
    <div class="status-bar">
      <el-tag v-for="s in statusCounts" :key="s.label" :type="s.type" effect="plain">
        {{ s.label }}：{{ s.count }}
      </el-tag>
    </div>

    <!-- 进行中任务 -->
    <el-card v-if="activeJobs.length" shadow="never" class="job-card">
      <template #header>进行中的任务</template>
      <div v-for="job in activeJobs" :key="job.id" class="job-row">
        <span class="job-type">{{ jobTypeName(job) }}</span>
        <el-progress :percentage="Math.round(job.progress)" class="job-progress" />
        <span class="job-stage">{{ job.stage || '' }}</span>
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="table-head">
          <span>文档列表</span>
          <div>
            <el-select v-model="filterStatus" placeholder="状态筛选" clearable size="small" style="width: 130px; margin-right: 8px">
              <el-option v-for="s in STATUS_OPTIONS" :key="s.value" :label="s.label" :value="s.value" />
            </el-select>
            <el-button size="small" @click="loadDocuments">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="documents" v-loading="loadingDocs" size="default">
        <el-table-column prop="filename" label="文件名" min-width="220" show-overflow-tooltip />
        <el-table-column label="类型" width="80">
          <template #default="{ row }"><el-tag size="small" type="info">{{ row.file_type.toUpperCase() }}</el-tag></template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="分块" width="70" />
        <el-table-column label="大小" width="90">
          <template #default="{ row }">{{ fmtBytes(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="上传时间" width="150">
          <template #default="{ row }">{{ fmtUTC(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link size="small" @click="viewDetail(row)">详情</el-button>
            <el-button link size="small" type="danger" @click="removeDoc(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        class="pager"
        @current-change="loadDocuments"
      />
    </el-card>

    <!-- 检索调试 -->
    <el-card shadow="never" class="debug-card">
      <template #header>🔬 检索调试（向量 → BM25 → RRF 融合 → 重排序 四层对比，不调用 LLM）</template>
      <div class="debug-input">
        <el-input v-model="debugQuery" placeholder="输入问题，如：星辰X1 Pro 充满电需要多久" @keyup.enter="runDebug" />
        <el-button type="primary" :loading="debugLoading" @click="runDebug">检索</el-button>
      </div>
      <div v-if="debugResult" class="debug-result">
        <div class="debug-latency">
          向量检索 {{ debugResult.latency_ms.vector }}ms · BM25 {{ debugResult.latency_ms.bm25 }}ms ·
          RRF 融合 {{ debugResult.latency_ms.fuse }}ms · 重排序 {{ debugResult.latency_ms.rerank }}ms ·
          总计 {{ debugResult.latency_ms.total }}ms
        </div>
        <el-row :gutter="12">
          <el-col :span="6" v-for="layer in LAYERS" :key="layer.key">
            <div class="layer-box">
              <div class="layer-title">{{ layer.label }}</div>
              <div v-for="(hit, i) in debugResult[layer.key] || []" :key="i" class="layer-hit">
                <div class="layer-score">{{ hit.score }}</div>
                <div class="layer-doc">{{ hit.doc_name }}</div>
                <div class="layer-snippet">{{ hit.snippet }}</div>
              </div>
              <el-empty v-if="!(debugResult[layer.key] || []).length" description="无命中" :image-size="40" />
            </div>
          </el-col>
        </el-row>
      </div>
    </el-card>

    <!-- 文档详情抽屉 -->
    <el-drawer v-model="detailVisible" :title="detailDoc?.filename" size="45%">
      <div v-if="detailDoc">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="状态">{{ statusText(detailDoc.status) }}</el-descriptions-item>
          <el-descriptions-item label="分块数">{{ detailDoc.chunk_count }}</el-descriptions-item>
          <el-descriptions-item label="字符数">{{ detailDoc.char_count }}</el-descriptions-item>
          <el-descriptions-item label="上传时间">{{ fmtUTC(detailDoc.created_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="detailDoc.error" label="错误" :span="2">{{ detailDoc.error }}</el-descriptions-item>
        </el-descriptions>
        <h4>分块预览（前 10 条）</h4>
        <div v-for="c in detailDoc.chunks || []" :key="c.id" class="chunk-preview">
          <div class="chunk-index">#{{ c.chunk_index }} <el-tag size="small" type="info">{{ c.meta?.doc_title || '' }}</el-tag></div>
          <div class="chunk-content">{{ c.content }}</div>
        </div>
      </div>
    </el-drawer>

    <!-- 上传对话框 -->
    <el-dialog v-model="uploadVisible" title="上传文档到知识库" width="520px">
      <el-upload
        ref="uploadRef"
        v-model:file-list="fileList"
        drag
        multiple
        :auto-upload="false"
        :limit="50"
        accept=".pdf,.docx,.xlsx,.md,.txt"
        :on-exceed="() => ElMessage.warning('单次最多上传 50 个文件')"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">拖拽文件到此处，或 <em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">支持 PDF / DOCX / XLSX / Markdown / TXT，单个不超过 20MB；重复内容将自动跳过</div>
        </template>
      </el-upload>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="doUpload">开始上传并入库</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listDocuments, getDocument, deleteDocument, listJobs, getJob, rebuildIndex, debugRetrieve, uploadDocuments } from '../../api/kb'
import { fmtBytes, fmtUTC } from '../../utils/format'

const STATUS_OPTIONS = [
  { label: '就绪', value: 'ready' },
  { label: '摄入中', value: 'uploaded' },
  { label: '失败', value: 'failed' },
]
const LAYERS = [
  { key: 'vector_hits', label: '① 向量检索（余弦相似度）' },
  { key: 'bm25_hits', label: '② BM25 关键词（归一化）' },
  { key: 'fused', label: '③ RRF 融合' },
  { key: 'reranked', label: '④ 重排序后' },
]

const documents = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const filterStatus = ref('')
const loadingDocs = ref(false)

const activeJobs = ref([])
const jobs = ref([])
let pollTimer = null

const uploadVisible = ref(false)
const uploading = ref(false)
const uploadRef = ref(null)
// 用官方推荐的 v-model:file-list 绑定（实例上的 uploadFiles 属性不保证暴露）
const fileList = ref([])

const detailVisible = ref(false)
const detailDoc = ref(null)

const debugQuery = ref('')
const debugLoading = ref(false)
const debugResult = ref(null)

const statusCounts = computed(() => {
  const counter = { ready: 0, processing: 0, failed: 0 }
  for (const d of documents.value) {
    if (d.status === 'ready') counter.ready++
    else if (d.status === 'failed') counter.failed++
    else counter.processing++
  }
  return [
    { label: '就绪', count: counter.ready, type: 'success' },
    { label: '摄入中', count: counter.processing, type: 'warning' },
    { label: '失败', count: counter.failed, type: 'danger' },
  ]
})

const statusText = (s) => ({
  uploaded: '等待摄入', parsing: '解析中', chunking: '分块中', embedding: '向量化中',
  indexing: '写索引', ready: '就绪', failed: '失败',
}[s] || s)
const statusType = (s) => s === 'ready' ? 'success' : s === 'failed' ? 'danger' : 'warning'
const jobTypeName = (j) => ({ ingest: '文档摄入', rebuild: '索引重建', delete: '文档删除' }[j.job_type] || j.job_type)

async function loadDocuments() {
  loadingDocs.value = true
  try {
    const data = await listDocuments({ page: page.value, page_size: pageSize, status: filterStatus.value || undefined })
    documents.value = data.items
    total.value = data.total
  } finally {
    loadingDocs.value = false
  }
}

async function loadJobs() {
  const data = await listJobs({ page: 1, page_size: 20 })
  jobs.value = data.items
  activeJobs.value = data.items.filter((j) => ['queued', 'running'].includes(j.status))
  // 有活动任务时 1s 轮询
  if (activeJobs.value.length) {
    startPolling()
  } else {
    stopPolling()
    loadDocuments()
  }
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    for (const job of activeJobs.value) {
      const fresh = await getJob(job.id).catch(() => null)
      if (fresh) {
        const idx = activeJobs.value.findIndex((j) => j.id === job.id)
        if (idx >= 0) activeJobs.value[idx] = fresh
      }
    }
    activeJobs.value = activeJobs.value.filter((j) => ['queued', 'running'].includes(j.status))
    if (!activeJobs.value.length) {
      stopPolling()
      loadDocuments()
      ElMessage.success('任务全部完成')
    }
  }, 1000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function doUpload() {
  const files = fileList.value.filter((f) => f.raw)
  if (!files.length) return ElMessage.warning('请先选择文件')
  uploading.value = true
  try {
    const result = await uploadDocuments(files.map((f) => f.raw))
    ElMessage.success(`上传成功 ${result.succeeded} 个，跳过 ${result.skipped.length} 个`)
    for (const s of result.skipped) {
      ElMessage.warning(`${s.filename}：${s.reason}`)
    }
    fileList.value = []
    uploadRef.value?.clearFiles()
    uploadVisible.value = false
    loadJobs()
  } finally {
    uploading.value = false
  }
}

async function removeDoc(row) {
  await ElMessageBox.confirm(`确定删除《${row.filename}》？其向量与分块将一并移除。`, '删除确认', { type: 'warning' })
  await deleteDocument(row.id)
  ElMessage.success('删除任务已提交')
  loadJobs()
}

async function viewDetail(row) {
  detailDoc.value = await getDocument(row.id)
  detailVisible.value = true
}

async function rebuild(reEmbed) {
  await ElMessageBox.confirm(
    reEmbed ? '将重新解析全部文档并重新生成向量（耗时较长），确定继续？' : '将根据当前分块重建 BM25 关键词索引，确定继续？',
    '重建确认',
    { type: 'warning' },
  )
  const job = await rebuildIndex(reEmbed)
  ElMessage.success('重建任务已提交')
  loadJobs()
}

async function runDebug() {
  if (!debugQuery.value.trim()) return ElMessage.warning('请输入检索问题')
  debugLoading.value = true
  try {
    debugResult.value = await debugRetrieve(debugQuery.value.trim())
  } finally {
    debugLoading.value = false
  }
}

onMounted(() => {
  loadDocuments()
  loadJobs()
})
onUnmounted(stopPolling)
</script>

<style scoped>
.kb-page { min-height: 100vh; background: #f2f3f7; padding: 20px 24px; }
.kb-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.kb-header h2 { margin: 0 0 4px; }
.sub { color: #909399; font-size: 13px; }
.header-actions { display: flex; gap: 4px; align-items: center; }
.status-bar { display: flex; gap: 8px; margin-bottom: 12px; }
.job-card { margin-bottom: 12px; }
.job-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.job-type { font-size: 13px; color: #606266; width: 80px; }
.job-progress { flex: 1; }
.job-stage { font-size: 12px; color: #909399; width: 90px; text-align: right; }
.table-head { display: flex; justify-content: space-between; align-items: center; }
.pager { margin-top: 10px; justify-content: flex-end; }
.debug-card { margin-top: 14px; }
.debug-input { display: flex; gap: 10px; margin-bottom: 12px; }
.debug-latency { color: #909399; font-size: 12px; margin-bottom: 10px; }
.layer-box { border: 1px solid #e4e7ed; border-radius: 8px; padding: 8px; min-height: 160px; }
.layer-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; color: #303133; }
.layer-hit { border-bottom: 1px dashed #f0f0f0; padding: 5px 0; }
.layer-score { color: #67c23a; font-size: 12px; font-weight: 700; }
.layer-doc { font-size: 12px; color: #409eff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.layer-snippet { font-size: 11px; color: #909399; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.chunk-preview { border: 1px solid #e4e7ed; border-radius: 6px; padding: 8px; margin-bottom: 8px; }
.chunk-index { font-size: 12px; color: #909399; margin-bottom: 4px; }
.chunk-content { font-size: 13px; line-height: 1.7; white-space: pre-wrap; }
</style>
