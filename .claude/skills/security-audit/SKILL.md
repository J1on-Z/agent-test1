---
name: security-audit
description: 对代码库进行安全审查（敏感信息泄露、SQL 注入、配置明文密钥、认证授权缺陷、XSS/路径穿越/命令注入等），输出分级安全报告。用户说「安全审查 / 安全检查 / 漏洞扫描 / security audit」时使用。
---

# 代码安全审查技能（security-audit）

对项目做系统化安全审查，覆盖 4 大维度，输出按严重级别分级的报告。
**所有结论必须来自实际扫描命令的输出，不得凭印象编造。**

## 何时使用

- 用户要求做安全审查 / 漏洞检查
- 代码入库前（git commit 前）、交付/答辩前
- 新增了涉及认证、文件上传、数据库查询、外部请求的代码后

## 审查流程（4 个维度，逐一执行）

### 维度 1：敏感信息泄露（代码 + 配置 + 版本库）

```bash
cd <项目根>

# 1.1 代码中硬编码密钥/密码/令牌
grep -rniE "(password|passwd|secret|token|api[_-]?key|private[_-]?key|access[_-]?key)\s*[:=]\s*[\"'][^\"']{6,}" \
  --include="*.py" --include="*.js" --include="*.vue" --include="*.java" --include="*.go" \
  --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=dist .

# 1.2 配置文件是否被版本控制忽略（最关键）
cat .gitignore | grep -iE "\.env|secret|credential|\.key|\.pem"
git check-ignore -v backend/.env          # 必须命中，否则密钥会进仓库

# 1.3 版本库历史中是否残留密钥（gitignore 只保护未来，不保护过去）
git log --all --full-history --oneline -- "*.env" "*.key" "*.pem" "*secret*"
git grep -iE "sk-[a-z0-9]{10,}|AKIA[0-9A-Z]{16}" $(git rev-list --all) 2>/dev/null | head -20

# 1.4 日志中是否打印敏感信息
grep -rnE "logger?\.(info|debug|warning|error).*\{.*\}" --include="*.py" app/ | grep -iE "password|token|key|secret"
```

**判定基准**：
- 密钥出现在 `.env`（已 gitignore）→ **合规**，但需确认 `.env.example` 只含占位符
- 密钥出现在代码/测试/Markdown/日志 → **高危**，必须移除并**轮换密钥**（泄露过的密钥换掉才算修复）
- gitignore 只防未来，历史提交过就必须认为已泄露 → 需 `git filter-repo` 清理 + 轮换

### 维度 2：注入类漏洞

```bash
# 2.1 SQL 注入：原始 SQL 拼接（ORM 参数绑定是安全的）
grep -rnE "execute\(|text\(|executemany\(|raw\(" --include="*.py" app/ | grep -E "f[\"']|%s|\.format\(|\+ *[a-z_]+ *(\)|,|\+)"

# 2.2 命令注入
grep -rnE "os\.system|os\.popen|subprocess\.(call|run|Popen).*shell\s*=\s*True|eval\(|exec\(" --include="*.py" --exclude-dir=.venv .

# 2.3 路径穿越（文件读写用用户输入拼路径）
grep -rnE "open\(|Path\(|shutil\.(copy|move|rmtree)|\.unlink\(|send_file" --include="*.py" app/ | grep -vE "^\s*#"

# 2.4 反序列化
grep -rnE "pickle\.loads?|yaml\.load\((?!.*Loader)|\bmarshal\." --include="*.py" --exclude-dir=.venv .

# 2.5 前端 XSS（v-html / innerHTML / dangerouslySetInnerHTML）
grep -rnE "v-html|innerHTML|outerHTML|document\.write" --include="*.vue" --include="*.js" frontend/src/
```

**判定基准**：
- SQLAlchemy ORM（`select(Model).where(...)`）与参数绑定 → 安全
- `text("... %s" % userinput)` / f-string 拼 SQL → **高危**
- `v-html` 内容必须过 DOMPurify（白名单），否则 **高危**
- 文件路径含用户输入 → 必须有 uuid 重命名 / `Path.resolve()` 校验在根目录内

### 维度 3：认证、授权与会话安全

```bash
# 3.1 JWT 密钥与算法
grep -rnE "jwt\.(encode|decode)|algorithms?\s*=|SECRET_KEY" --include="*.py" app/
# 检查：算法是否为 none 可取（必须显式指定 algorithms=[...]）、密钥长度、是否硬编码默认值

# 3.2 越权（IDOR）：按 id 查询后是否校验归属
grep -rnE "db\.get\(|\.filter_by\(|select\(" --include="*.py" app/api/ app/services/ | grep -iE "user_id|owner"

# 3.3 密码存储
grep -rnE "bcrypt|argon2|pbkdf2|hashlib\.(md5|sha1|sha256)|passlib" --include="*.py" app/
# md5/sha1 存密码 → 高危；bcrypt/scrypt/argon2 → 合规

# 3.4 权限校验是否覆盖管理接口
grep -rn "require_admin\|Depends(get_current_user)" --include="*.py" app/api/

# 3.5 CORS 与限流
grep -rnE "allow_origins|CORSMiddleware" --include="*.py" app/
grep -rnE "limiter\.limit|default_limits" --include="*.py" app/
```

**判定基准**：
- `allow_origins=["*"]` 且 `allow_credentials=True` → **高危**（浏览器规范禁止组合，且等于放弃同源保护）
- JWT 未显式指定 `algorithms` 列表 → 可能受 alg=none 攻击
- 按 id 取资源但未校验 `user_id == current_user.id` → 越权读写他人数据
- 管理接口缺少 `require_admin` 依赖 → 权限绕过

### 维度 4：其他隐患与依赖风险

```bash
# 4.1 错误信息泄露（堆栈返回给用户）
grep -rnE "detail=str\(e\)|f\".*\{e\}|traceback\.format_exc" --include="*.py" app/api/ app/core/

# 4.2 调试开关 / 默认弱凭证
grep -rniE "debug\s*=\s*True|reload\s*=\s*True|admin.*123456|password.*=.*[\"'](admin|123456|password|test)[\"']" \
  --include="*.py" --include="*.env*" --include="*.bat" .

# 4.3 文件上传校验（类型/大小/落盘名）
grep -rnE "UploadFile|allowed_extensions|max_upload" --include="*.py" app/

# 4.4 外部请求 SSRF（URL 由用户可控）
grep -rnE "httpx\.(get|post|Client)|requests\.(get|post)" --include="*.py" app/ | grep -iE "url|user|input"

# 4.5 依赖已知漏洞（CVE）
backend/.venv/Scripts/python.exe -m pip install pip-audit -q && \
backend/.venv/Scripts/python.exe -m pip-audit --desc
cd frontend && npm audit --omit=dev
```

## 本项目已知基线（无需重复报告，除非状态变化）

| 项 | 状态 | 说明 |
|---|---|---|
| `admin/123456` 默认管理员 | **已接受的业务需求** | 用户明确要求的毕设演示账号；缓解：仅监听 127.0.0.1 + 登录限流 5/分钟；README 已建议公网部署前改密 |
| `DASHSCOPE_API_KEY` 在 `backend/.env` | **合规** | 已 gitignore；代码中零硬编码，统一走 `settings.dashscope_api_key` |
| 测试文件中的 `test123456` 等密码 | **合规** | 仅用于临时测试库，非真实凭证 |
| `SECRET_KEY` 默认值 `dev-secret-change-me` | **需关注** | 仅当 `.env` 未配置时生效；`.env` 已配 64 位随机串 |
| 单机无 HTTPS | **已接受** | 本地演示环境；README 说明生产需反代 + TLS |

## 报告格式（输出到 项目根/安全审查报告.md）

```markdown
# 安全审查报告 · <项目名>
> 审查时间 / 审查范围 / 扫描方式

## 1. 结论摘要
| 严重级别 | 数量 | 说明 |
|---|---|---|
| 🔴 高危 | n | ... |
| 🟡 中危 | n | ... |
| 🟢 低危/建议 | n | ... |

## 2. 详细发现（每项包含）
### [级别] 标题
- **位置**：file:line
- **证据**：实际扫描输出（必填，不得编造）
- **影响**：攻击者能做什么
- **修复建议**：具体到代码改法
- **状态**：已修复 / 待修复 / 已接受（附理由）

## 3. 合规项确认（扫描通过的安全实践）
## 4. 未覆盖范围（如实说明，如：未做渗透测试、未审计第三方依赖源码）
```

## 注意事项

- **只读审查**：本技能默认不修改代码；发现问题先报告，经用户确认后再修
- **误报处理**：正则命中后必须**打开文件确认**，不要仅凭 grep 结果就定性
- **修复建议要可执行**：写清「哪一行改成什么」，而不是泛泛说"加强校验"
- **密钥泄露的处理顺序**：先轮换密钥（止损），再清理代码与 git 历史
- Windows 下 grep 若无 `--include` 支持改用 `git grep`；大仓库优先用 `git grep` 更快且自动忽略 .gitignore
