---
name: run-project
description: 一键启动电商 RAG 知识库智能问答系统（后端 FastAPI + 前端 Vue3），含环境自检、首次初始化、健康验证与常见故障处理。用户说「运行项目 / 启动项目 / 跑起来 / 打开系统 / run project」时使用。
---

# 一键运行项目（run-project）

启动本项目的后端（FastAPI，端口 8000）与前端（Vite，端口 5173），并对用户可访问性做验证。

**核心原则**：先自检、再启动、后验证；**已在运行的服务不重复启动**（避免端口冲突）。

## 步骤 0：环境自检（必须先做，避免误判）

```bash
cd <项目根>
# 后端是否已在运行
netstat -ano | grep -E ":8000.*LISTENING"
# 前端是否已在运行
netstat -ano | grep -E ":5173.*LISTENING"
# 依赖与配置
test -f backend/.venv/Scripts/python.exe && echo "venv OK" || echo "venv 缺失"
test -d frontend/node_modules && echo "node_modules OK" || echo "需 npm install"
test -f backend/.env && grep -q "DASHSCOPE_API_KEY=sk-" backend/.env && echo ".env OK" || echo ".env 未配置"
test -f backend/data/app.db && echo "知识库数据 OK" || echo "需初始化数据"
```

根据结果分流：
- 8000 与 5173 都 LISTENING → **服务已在运行**，直接跳到「步骤 4 验证」并告知用户访问地址，不要重复启动
- 缺依赖 / `.env` / 数据 → 先执行「步骤 1 初始化」
- 否则 → 直接「步骤 2 启动后端」

## 步骤 1：首次初始化（仅缺失时执行）

```bash
cd backend

# 1.1 依赖（仅 venv 缺失时）
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt

# 1.2 环境配置（仅 .env 缺失时）——必须先向用户索取 DashScope API Key
cp .env.example .env
# 然后编辑 .env 填入 DASHSCOPE_API_KEY（以及工作空间专属端点，若为 sk-ws- 开头的 Key）

# 1.3 前端依赖（仅 node_modules 缺失时）
cd ../frontend && npm install

# 1.4 知识库数据（仅 app.db 缺失时）——生成 40+ 份示例商品文档
cd ../backend
PYTHONUTF8=1 ./.venv/Scripts/python.exe scripts/generate_mock_docs.py
```

## 步骤 2：启动后端

以**后台任务**方式启动（不要阻塞当前会话）：

```bash
cd backend
PYTHONUTF8=1 ./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

等待约 10 秒后做健康检查（**三个子系统必须全 ok**）：

```bash
curl -s http://127.0.0.1:8000/api/health
# 期望：{"status":"ok", ..., "database":{"ok":true}, "vector_store":{"ok":true}, "dashscope":{"ok":true}}
```

- `dashscope.ok=false` → API Key 或端点配置有误（工作空间级 Key 需用 `ws-xxx.cn-beijing.maas.aliyuncs.com` 专属域名）
- `vector_store.ok=false` → 知识库索引未就绪，跑 `scripts/ingest_all.py` 重新灌入

**首次灌数据**（仅当知识库为空，即 health 显示 `db_chunks: 0`）：

```bash
cd backend
PYTHONUTF8=1 ./.venv/Scripts/python.exe scripts/ingest_all.py
# 约 1-3 分钟（含 embedding 调用），完成后应显示「知识库就绪文档: N/N」
```

## 步骤 3：启动前端

同样以后台任务方式启动：

```bash
cd frontend
npm run dev
```

验证可访问（Vite 启动约 2 秒）：

```bash
curl -s -o /dev/null -w "frontend HTTP %{http_code}\n" http://localhost:5173/   # 期望 200
curl -s http://localhost:5173/api/health | head -c 80              # 验证代理连通
```

> 提示：`curl -w` 里不要写中文，Git Bash 下会显示乱码（仅影响观感，不影响结果）。

## 步骤 4：向用户交付

告知用户：

```
系统已启动：
  前端界面  http://localhost:5173
  后端接口  http://127.0.0.1:8000/api/health
  接口文档  http://127.0.0.1:8000/docs

管理员账号：admin / 123456（仅可访问知识库管理与统计看板）
普通用户：注册任意账号即可体验问答
```

可选：跑一次端到端冒烟验证（真实调用 LLM，约 3-6 秒，成本极低）：

```bash
cd backend
PYTHONUTF8=1 ./.venv/Scripts/python.exe scripts/demo.py
```

## 停止服务

前端/后端均为后台任务，用 TaskStop 停止对应任务；或按端口杀进程：

```bash
netstat -ano | grep ":8000.*LISTENING"      # 取 PID
taskkill //F //PID <PID>
```

## 常见故障

| 现象 | 原因与处理 |
|---|---|
| `[Errno 10048] 端口被占用` | 已有实例运行中。先确认 `netstat` 输出，若是本项目实例则直接复用，否则 `taskkill` 掉旧进程 |
| health 里 `dashscope.ok=false` | 检查 `.env` 的 `DASHSCOPE_API_KEY` 与 `DASHSCOPE_BASE_URL`；工作空间级 Key 必须配工作空间专属域名 |
| 问答报「模型服务暂不可用」 | 百炼控制台「模型广场」里对应模型未开通或额度耗尽，开通后无需重启（模型列表接口动态下发） |
| 前端报 401 且自动跳登录 | token 过期（30 分钟），重新登录即可 |
| 摄入任务长时间卡在「向量化」 | DashScope embedding 限速，属正常排队；可在「知识库管理」页看任务进度 |
| 想彻底重来 | 停服务后删除 `backend/data/` 整个目录，重新执行步骤 1.4 + 灌数据 |

## 注意事项

- **Windows 必须带 `PYTHONUTF8=1`**：项目路径含中文，不加会因 GBK 编码报错
- **不要用 `--reload`**：开发模式热重载会起两个进程，压测/演示时干扰端口判断
- **服务已在运行时不重复启动**：先 netstat 判断，直接复用并告知用户访问地址
- **首次启动会创建管理员**：`admin/123456` 来自 `.env` 的 `ADMIN_USERNAME/PASSWORD`，仅首次建库时生效
