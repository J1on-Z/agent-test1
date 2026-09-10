---
name: unit-test
description: 运行本项目后端单元测试（pytest + 覆盖率）并生成测试报告；编写符合项目规范的新测试用例。用户说「跑测试 / 单元测试 / 测试报告 / 覆盖率」时使用。
---

# 单元测试技能（电商 RAG 知识库智能问答系统）

## 何时使用

- 用户要求执行单元测试、查看测试结果或生成测试报告
- 修改代码后需要回归验证
- 用户要求为某个模块新增测试用例

## 执行测试（标准流程）

```bash
cd backend
PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/ -q
```

带覆盖率（生成测试报告的必选步骤）：

```bash
cd backend
PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/ -q \
  --cov=app --cov-report=term-missing
```

前置条件：
- venv 已安装（`.venv/`），依赖含 `pytest`、`pytest-asyncio`、`pytest-cov`
- `tests/test_parsers.py` 依赖真实样例文档，需先生成：
  `PYTHONUTF8=1 ./.venv/Scripts/python.exe scripts/generate_mock_docs.py`
  （缺失时该文件用例会 skip，不算失败）

## 项目测试约定（新增用例必须遵守）

1. **环境隔离**：`tests/conftest.py` 自动设置 `APP_ENV=test`（关闭限流），
   每个用例使用独立临时 SQLite 库（`client` fixture），互不干扰
2. **数据准备**：认证类用例用 `create_user(session, username, role=...)` 直接插入用户
3. **不碰真实 API**：LLM 用 Fake 模型（参考 `tests/test_graph.py` 的 `RouterFakeLLM`
   按提示词路由返回固定答案）；检索/重排用桩函数；禁止测试里调用 DashScope
4. **异步用例**：直接写 `async def test_xxx`（pytest.ini 已配 `asyncio_mode = auto`）
5. **SSE 端到端**：用 `httpx.ASGITransport` + `client.stream` 逐帧断言事件序列
6. **分块/解析**：用 `data/sample_docs/` 真实生成文件，不用手工构造的假路径

## 新增测试的模板

```python
"""模块名测试：验证 xxx。"""
import pytest

class TestXxx:
    async def test_normal_case(self, client):
        # 依赖 client fixture（临时库 + ASGI transport）
        ...

    def test_pure_function(self):
        # 纯函数直接断言
        ...
```

## 生成测试报告

运行带覆盖率的命令后，把结果写入项目根目录 `测试报告.md`，结构固定为：

1. **总体结论**：通过/失败数、通过率、覆盖率
2. **覆盖率明细**：按模块列表（app/graph、app/services、app/api 等），
   标注低覆盖模块的原因（如 chat_service 由 SSE 手工验收覆盖）
3. **用例清单**：每个测试文件的功能点一句话概括
4. **已知限制**：如实说明未自动化覆盖的部分（前端无自动化测试、
   真实 API 集成未纳入单测等）
5. **复现命令**

报告数据必须来自实际运行输出，不得编造。

## 注意事项

- Windows 下必须带 `PYTHONUTF8=1`（中文路径与断言消息）
- 若测试因修改代码失败：先修复代码再重跑，不要改测试来掩盖失败
- `test_parsers.py` 的 skip 属于正常现象（样例文档未生成时）
