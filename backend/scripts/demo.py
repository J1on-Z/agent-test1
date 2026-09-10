"""5 分钟演示动线：一条命令跑完答辩演示的核心路径。

流程：注册演示用户 → 登录 → 流式问答（含引文）→ 多轮追问 →
      相同问题命中缓存 → 相似问题语义命中 → 无关问题拒答 → 管理员统计看板数据

用法：python scripts/demo.py
"""
import json
import sys
import time
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

HOST = "http://127.0.0.1:8000"


def parse_sse(resp):
    buffer, event = "", "message"
    for chunk in resp.iter_bytes():
        buffer += chunk.decode("utf-8")
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            data_lines = []
            for line in block.split("\n"):
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
            if data_lines:
                try:
                    data = json.loads("".join(data_lines))
                except json.JSONDecodeError:
                    data = "".join(data_lines)
                yield event, data
            event = "message"


def main() -> None:
    step = 0

    def banner(title: str) -> None:
        nonlocal step
        step += 1
        print(f"\n{'=' * 60}\n【演示 {step}】{title}\n{'=' * 60}")

    with httpx.Client(base_url=HOST, timeout=180) as c:
        banner("注册并登录演示用户（如已存在则直接登录）")
        c.post("/api/auth/register", json={"username": "demo_user", "password": "demo123456"})
        token = c.post("/api/auth/login", json={"username": "demo_user", "password": "demo123456"}).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        def ask(question: str, conv_id: int | None = None) -> dict:
            body = {"question": question}
            if conv_id:
                body["conversation_id"] = conv_id
            out = {}
            t0 = time.perf_counter()
            with c.stream("POST", "/api/chat", json=body, headers=h) as r:
                for ev, d in parse_sse(r):
                    if ev == "meta":
                        out["conv_id"] = d["conversation_id"]
                    elif ev == "token":
                        print(d["delta"], end="", flush=True)
                    elif ev == "done":
                        out.update(d)
            print()
            out["wall_ms"] = int((time.perf_counter() - t0) * 1000)
            return out

        banner("流式问答：商品咨询（注意逐字输出与引文标注）")
        r1 = ask("星辰X1 Pro 的电池容量和快充功率是多少？")
        conv_id = r1["conv_id"]
        print(f"→ 首 token {r1.get('ttft_ms')}ms，总耗时 {r1['wall_ms']}ms")

        banner("多轮追问：指代消解（「那它的保修呢」自动改写为完整问题）")
        r2 = ask("那它的保修期是多久？", conv_id)

        banner("重复提问：精确缓存命中（零 LLM 调用）")
        r3 = ask("星辰X1 Pro 的电池容量和快充功率是多少？", conv_id)
        print(f"→ 命中缓存={r3['from_cache']}，耗时 {r3['wall_ms']}ms（首次 {r1['wall_ms']}ms）")

        banner("换措辞提问：语义缓存命中（余弦相似度匹配）")
        r4 = ask("星辰X1 Pro 电池多大，充电快不快", conv_id)
        print(f"→ 命中缓存={r4['from_cache']}，耗时 {r4['wall_ms']}ms")

        banner("无关问题：相关度门槛拦截（确定性拒答，不调 LLM）")
        ask("帮我写一首关于春天的诗", conv_id)

        banner("会话历史找回（模拟重新登录）")
        msgs = c.get(f"/api/conversations/{conv_id}/messages", headers=h).json()
        print(f"→ 会话共 {msgs['total']} 条消息，引文卡片完整保存")

        banner("管理员统计看板")
        at = c.post("/api/auth/login", json={"username": "admin", "password": "123456"}).json()["access_token"]
        ah = {"Authorization": f"Bearer {at}"}
        ov = c.get("/api/stats/overview", headers=ah).json()
        print(f"→ 用户 {ov['user_count']} | 消息 {ov['message_count']} | 缓存命中 {ov['cache_hits']} 次")
        print(f"→ 平均延迟 {ov['avg_latency_ms']}ms | p95 {ov['p95_latency_ms']}ms | 累计成本 ¥{ov['estimated_cost_yuan']}")

    print("\n演示完成！浏览器打开 http://localhost:5173 体验完整界面")


if __name__ == "__main__":
    main()
