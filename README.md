# 电商 RAG 知识库智能问答系统

基于 **LangChain + LangGraph** 的企业级知识库问答系统（毕业设计）。用户通过浏览器对电商平台商品进行知识库问答，回答自动引用知识库片段并展示来源；支持多用户多会话、历史找回、管理员知识库管理与运营统计。

## 功能总览

| 需求 | 实现 |
|---|---|
| 浏览器知识库管理 | 管理员上传 PDF/DOCX/XLSX/MD/TXT → 自动解析、分块、向量化，进度实时轮询，去重拦截 |
| 知识库问答 + 引用展示 | LangGraph 编排流水线，回答中【n】标注可点击，展示引用片段/来源文件/页码/相关度 |
| 多用户多会话 | JWT 认证 + 会话按 user_id 隔离（SQL 层强制），每用户独立会话列表 |
| 会话记录找回 | 全量消息/引文/摘要持久化 SQLite，重新登录完整恢复 |
| 注册登录改密 | bcrypt 哈希、access+refresh 双 token（旋转吊销）、改密后强制下线 |
| 管理员权限 | admin/123456 内置种子；知识库管理/统计接口后端 `require_admin` + 前端路由守卫双重隔离 |
| 企业级优化 | 混合检索（RRF）、重排序、语义缓存（精确+语义两级）、流式 SSE + 心跳、限流、分节点延迟埋点、token 成本核算 |
| 附加功能 | 统计看板（ECharts）、检索调试四层对比、思考模式、重新生成、停止生成、会话导出 Markdown、多模型切换 |

## 技术架构

```
浏览器 (Vue 3 + Element Plus + Pinia)
   │  REST /api + SSE 流式
   ▼
FastAPI（async, SQLAlchemy 2.0, slowapi 限流, JWT 鉴权）
   │
   ├─ LangGraph 问答流水线
   │    query 改写 → 混合检索(向量+BM25, RRF) → 重排序(gte/qwen-rerank)
   │    → 相关度门槛 → 带引用流式生成 / 确定性拒答 → 滚动摘要维护
   │
   ├─ 检索层
   │    ├─ 向量检索：自研 numpy 内存矩阵（SQLite 存 float32 向量）
   │    ├─ BM25：jieba 分词 + rank_bm25 常驻内存索引
   │    └─ 重排序：DashScope qwen3.7-text-rerank（原生 API）
   │
   ├─ 摄入流水线（后台线程池 + 任务状态机）
   │    解析(5 格式) → 中文分块 → 批量向量化 → 双写(SQLite 权威 + 向量表)
   │
   ├─ 服务层：会话/记忆(摘要+窗口)/语义缓存/统计
   │
   ▼
SQLite（WAL）业务数据 · DashScope API（LLM/embedding/rerank 一份 Key）
```

### 企业级叙事（论文「架构演进」素材）

| 演示版选择 | 生产环境替换 | 原因 |
|---|---|---|
| SQLite + WAL | MySQL/PG + 连接池 + 读写分离 | 多实例并发写、在线 DDL |
| 自研 numpy 向量检索 | Milvus / Qdrant 集群 | 亿级向量、HNSW 分布式索引、GPU 检索 |
| rank_bm25 内存索引 | Elasticsearch BM25 | 海量文档倒排、分布式召回 |
| ThreadPool 后台任务 | Celery + Redis | 任务持久化、重试、多 worker 水平扩展 |
| slowapi 内存限流 | API 网关 / Redis 令牌桶 | 多实例共享计数 |
| SQLite 语义缓存 | Redis Vector / GPTCache | 低延迟共享缓存 |
| SSE 单机直连 | WebSocket + 消息队列 | 大规模连接管理、削峰 |

> 注：chromadb 1.5.9 的 chroma-hnswlib 原生扩展在 Python 3.14/Windows 下 upsert 稳定段错误（已最小复现脚本验证），故向量检索按预案改为自研轻量实现；万级 chunk 单次查询 <10ms，接口层与生产替换方案完全一致。

## 快速开始

### 前置条件
- Python 3.13+（本机 3.14.6 验证通过）
- Node.js 20+（本机 24 验证通过）
- 阿里云百炼 DashScope API Key（[注册入口](https://bailian.console.aliyun.com/)）：
  控制台 → API-KEY 管理 → 创建 Key。一份 Key 同时用于 LLM（qwen-plus/qwen-max）、
  embedding（qwen3.7-text-embedding）与 rerank（qwen3.7-text-rerank）。
  新用户有免费额度，演示成本约几分钱。

### 1. 后端

```bat
cd backend
copy .env.example .env        :: 编辑 .env 填入 DASHSCOPE_API_KEY（其余保持默认）
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
:: 生成示例数据 + 预灌知识库（40+ 份多格式商品文档）
.venv\Scripts\python scripts\generate_mock_docs.py
start_backend.bat             :: 或 .venv\Scripts\python run.py
```

验证：浏览器打开 http://127.0.0.1:8000/api/health，应看到 database / vector_store / dashscope 全 ok。

导入示例数据（服务启动后）：

```bat
.venv\Scripts\python scripts\ingest_all.py
```

### 2. 前端

```bat
cd frontend
start_frontend.bat             :: npm install + vite dev
```

浏览器打开 http://localhost:5173
- 普通用户：注册任意账号体验问答
- 管理员：admin / 123456，可访问「知识库管理」与「统计看板」

### 3. 答辩演示（一键动线）

```bat
.venv\Scripts\python scripts\demo.py
```

自动完成：注册登录 → 流式问答（引文）→ 多轮追问（改写）→ 重复问题（精确缓存）→ 换措辞（语义缓存）→ 无关拒答 → 历史找回 → 统计看板。

## 实验数据（可直接引用）

| 指标 | 结果 | 复现命令 |
|---|---|---|
| 检索 recall@5 | **1.000（49/49）** | `python scripts/eval_retrieval.py` |
| rerank top1 准确率 | **1.000（49/49）** | 同上 |
| 无关问题拒答正确率 | **1.000（2/2）** | 同上 |
| 检索延迟分解 / TTFT / 并发吞吐 | 见输出 | `python scripts/benchmark.py` |
| 缓存精确命中 | **~100ms（零 LLM 调用）** | demo.py 步骤 3 |
| 单测 | 41 个用例全通过 | `python -m pytest tests/ -q` |

## 目录结构

```
backend/
├── app/
│   ├── main.py / config.py / database.py / dependencies.py
│   ├── models/          # 10 张表（users/refresh_tokens/conversations/messages/
│   │                    #   documents/chunks/vector_embeddings/ingest_jobs/
│   │                    #   request_logs/semantic_cache_entries）
│   ├── api/             # auth/conversations/chat(SSE)/kb/stats/health
│   ├── core/            # security(bcrypt+JWT)/exceptions/rate_limit/logging
│   ├── services/
│   │   ├── ingest/      # parsers(5格式)/chunker(中文)/pipeline/jobs(线程池)
│   │   ├── retrieval/   # vector_store(numpy)/bm25(jieba)/hybrid(RRF)/reranker
│   │   ├── llm/         # qwen(ChatOpenAI→DashScope)/embeddings/prompts
│   │   └── chat/conversation/memory/cache/kb/stats/auth_service
│   └── graph/           # LangGraph: state/nodes/edges/builder
├── scripts/             # 示例数据/预灌/评估/基准/演示
└── tests/               # 41 个用例
frontend/src/            # views(登录/注册/聊天/改密/知识库/统计)
                         # components/chat(流式气泡/引文卡片/思考块)
                         # api(axios+401自动刷新, SSE解析) stores composables
```

## 关键设计说明

- **引文机制**：上下文分块按【1】..【K】编号注入提示词，模型按硬约束标注；流式结束后正则解析编号 → 结构化引文（片段/来源/页码/分数）随消息持久化，历史会话直接还原。前端 markdown-it 自定义 inline rule 渲染可点击上标，DOMPurify 防 XSS。
- **记忆**：滑动窗口（最近 6 条原文）+ 滚动摘要（超过 10 条后 LLM 合并旧摘要与窗口外消息），LangGraph `update_summary` 节点后台异步维护，失败静默降级。
- **语义缓存**：两级查找——精确文本匹配（<20ms，零 LLM）→ 查询向量余弦相似度（换措辞命中）；key 含会话摘要 hash（记忆感知，多轮不串味）；TTL 24h。
- **拒答**：相关度门槛（rerank 分数 < 0.35）触发确定性拒答文案 + 「您可能想问」建议，不消耗 LLM 调用，拒答率可评估。
- **流式**：SSE 事件序列 `meta → token* → citations → done`，15s 心跳注释帧防断连，客户端断开时已生成部分以 interrupted 状态落库。
- **一致性**：SQLite 为权威数据源，向量表为其镜像，health 接口校验两边行数一致，rebuild-index 可修复漂移。

## 常见问题

- **问答报「模型服务暂不可用 / AccessDenied.Unpurchased」**：工作空间的对话模型未开通或免费额度已耗尽。登录[百炼控制台](https://bailian.console.aliyun.com/) → 「模型广场」→ 找到 qwen-plus / qwen-max → 点击开通（或检查账户余额）。开通后改 `backend/.env` 的 `LLM_MODEL=qwen-plus` 重启即可。系统的 embedding/rerank 与向量检索不依赖对话模型，知识库管理功能不受影响。
- **health 里 dashscope 不 ok**：检查 .env 的 DASHSCOPE_API_KEY 与端点域名；工作空间级 Key（sk-ws- 开头）必须使用工作空间专属域名（如 `ws-xxx.cn-beijing.maas.aliyuncs.com`），且 rerank 路径为双段 `text-rerank/text-rerank`。
- **端口占用**：改 .env 的 SERVER_PORT 与 frontend/vite.config.js 代理 target。
- **想清空重来**：停服务后删除 `backend/data/` 整个目录再启动。
