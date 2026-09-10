"""压测数据二次分析：从 request_logs 导出分节点耗时、缓存命中、按分钟吞吐。

用途：
- 与 Locust 报告交叉验证（服务端实际处理了多少请求、耗时分布）
- 定位瓶颈节点（retrieve / rerank / generate 各占多少）
- 判断「客户端超时」与「服务端失败」的比例

用法：
  python scripts/export_load_report.py --minutes 30            # 分析最近 30 分钟
  python scripts/export_load_report.py --minutes 30 --csv out.csv
"""
import argparse
import csv
import statistics
import sys
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import select  # noqa: E402

from app.database import SyncSessionLocal  # noqa: E402
from app.models import RequestLog  # noqa: E402
from app.models.common import utcnow  # noqa: E402


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(int(len(s) * p), len(s) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=30, help="分析最近 N 分钟")
    parser.add_argument("--csv", default=None, help="导出明细 CSV 路径")
    args = parser.parse_args()

    since = utcnow() - timedelta(minutes=args.minutes)
    with SyncSessionLocal() as db:
        rows = list(
            db.scalars(
                select(RequestLog).where(RequestLog.created_at >= since).order_by(RequestLog.created_at)
            ).all()
        )

    if not rows:
        print(f"最近 {args.minutes} 分钟无请求日志")
        return

    total = len(rows)
    cached = [r for r in rows if r.from_cache]
    llm_calls = [r for r in rows if not r.from_cache]

    print(f"===== 服务端实际处理（最近 {args.minutes} 分钟）=====")
    print(f"request_logs 总数: {total}")
    print(f"  缓存命中: {len(cached)} ({len(cached)/total*100:.1f}%)")
    print(f"  LLM 调用: {len(llm_calls)} ({len(llm_calls)/total*100:.1f}%)")

    # 端到端延迟
    lat = [r.latency_ms for r in rows if r.latency_ms]
    if lat:
        print(f"\n端到端延迟: p50={_pct(lat,0.5):.0f}ms p95={_pct(lat,0.95):.0f}ms p99={_pct(lat,0.99):.0f}ms max={max(lat)}ms")
    ttft = [r.ttft_ms for r in rows if r.ttft_ms]
    if ttft:
        print(f"首 token:   p50={_pct(ttft,0.5):.0f}ms p95={_pct(ttft,0.95):.0f}ms max={max(ttft)}ms")

    # 分节点耗时（从 node_latencies JSON 聚合）
    nodes: dict[str, list[int]] = {}
    for r in rows:
        for k, v in (r.node_latencies or {}).items():
            if isinstance(v, (int, float)):
                nodes.setdefault(k, []).append(int(v))
    if nodes:
        print("\n分节点耗时（服务端视角）:")
        for k, vals in sorted(nodes.items()):
            print(f"  {k:10s} p50={_pct(vals,0.5):>6.0f}ms  p95={_pct(vals,0.95):>6.0f}ms  均值={statistics.mean(vals):>7.0f}ms  次数={len(vals)}")

    # 按分钟吞吐（判断是否出现排队堆积）
    per_min: dict[str, int] = {}
    for r in rows:
        key = r.created_at.strftime("%H:%M")
        per_min[key] = per_min.get(key, 0) + 1
    print("\n按分钟吞吐（服务端完成数）:")
    for k in sorted(per_min):
        print(f"  {k}  {'█' * min(per_min[k] // 5, 60)} {per_min[k]}")

    # 按模型 token 消耗
    tokens = sum(r.total_tokens or 0 for r in rows)
    print(f"\n累计 token: {tokens:,}")

    if args.csv:
        out = Path(args.csv)
        if not out.is_absolute():
            out = BASE_DIR / out
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time", "from_cache", "latency_ms", "ttft_ms", "total_tokens",
                        "retrieve_ms", "rerank_ms", "generate_ms"])
            for r in rows:
                nl = r.node_latencies or {}
                w.writerow([r.created_at, r.from_cache, r.latency_ms, r.ttft_ms, r.total_tokens,
                            nl.get("retrieve"), nl.get("rerank"), nl.get("generate")])
        print(f"\n明细已导出: {out}")


if __name__ == "__main__":
    main()
