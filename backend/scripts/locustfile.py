"""Locust 压测脚本：模拟 100 人同时使用核心问答链路。

运行方式（在 backend 目录下）：
  # 常态场景（思考间隔 5-15s）
  LOAD_WAIT=normal .venv/Scripts/locust.exe -f scripts/locustfile.py --host http://127.0.0.1:8000 \
      -u 100 -r 10 -t 5m --headless --csv data/load_s1

  # 突发场景（无间隔，100 人瞬间并发）
  LOAD_WAIT=burst .venv/Scripts/locust.exe -f scripts/locustfile.py --host http://127.0.0.1:8000 \
      -u 100 -r 100 -t 2m --headless --csv data/load_s2

计时正确性说明：
  应答为 SSE 流式响应，必须等整个流读完才代表「回答完成」，因此不使用 stream=True
  （那会在响应头到达时即计时，严重低估）。requests 默认读完整个 body，
  Locust 据此计时的即为用户真实感知的完整耗时。

前置：先运行 scripts/prepare_load_users.py 生成 token 池与问题池。
"""
import json
import os
import random
import re
import threading
from itertools import count
from pathlib import Path

from locust import HttpUser, between, constant, task

BASE_DIR = Path(__file__).resolve().parent.parent
TOKENS_FILE = BASE_DIR / "data" / "load_tokens.json"
QUESTIONS_FILE = BASE_DIR / "data" / "load_questions.json"


def _load_json(path: Path, what: str):
    if not path.exists():
        raise SystemExit(f"[错误] 未找到{what}：{path}\n请先运行：python scripts/prepare_load_users.py")
    return json.loads(path.read_text(encoding="utf-8"))


TOKENS = _load_json(TOKENS_FILE, "token 池")
QUESTIONS = _load_json(QUESTIONS_FILE, "问题池")
HOT_RATIO = 0.2  # 热点问题抽取比例（触发语义缓存）

# 100 个虚拟用户各分配一个不同 token
_token_counter = count()
_token_lock = threading.Lock()

# 等待模式：normal=常态思考间隔(5-15s)；burst=突发无间隔
WAIT_MODE = os.getenv("LOAD_WAIT", "normal")


class LoadTestUser(HttpUser):
    """压测用户：持 token 提问 + 查看会话列表。"""

    wait_time = constant(0) if WAIT_MODE == "burst" else between(5, 15)

    def on_start(self):
        with _token_lock:
            idx = next(_token_counter) % len(TOKENS)
        self.token = TOKENS[idx]["token"]
        self.username = TOKENS[idx]["username"]
        self.conversation_id = None  # 首次提问后由服务端返回

    @property
    def auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def _pick_question(self) -> str:
        if random.random() < HOT_RATIO:
            return random.choice(QUESTIONS["hot"])
        return random.choice(QUESTIONS["normal"])

    @task(85)
    def ask_question(self):
        """核心链路：知识库问答（SSE 流式，计时含完整生成耗时）。"""
        body = {"question": self._pick_question()}
        if self.conversation_id:
            body["conversation_id"] = self.conversation_id

        with self.client.post(
            "/api/chat",
            json=body,
            headers=self.auth_headers,
            catch_response=True,
            timeout=180,
            name="/api/chat [问答]",
        ) as resp:
            if resp.status_code == 429:
                resp.failure("429 限流（系统自保护）")
                return
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:120]}")
                return
            text = resp.text
            if "event: done" not in text and "event: error" not in text:
                resp.failure("流未正常结束（无 done/error 事件）")
                return
            if '"delta"' not in text:
                resp.failure("未收到回答内容")
                return
            # 记录会话 id，后续提问携带（模拟真实的多轮使用）
            if self.conversation_id is None:
                m = re.search(r'"conversation_id":\s*(\d+)', text)
                if m:
                    self.conversation_id = int(m.group(1))
            resp.success()

    @task(15)
    def list_conversations(self):
        """辅助链路：进入会话列表页。"""
        with self.client.get(
            "/api/conversations",
            headers=self.auth_headers,
            catch_response=True,
            timeout=30,
            name="/api/conversations [会话列表]",
        ) as resp:
            if resp.status_code == 429:
                resp.failure("429 限流（系统自保护）")
            elif resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
            else:
                resp.success()
