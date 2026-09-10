"""压测期间资源采样：每 2 秒记录一次 CPU / 内存，输出 CSV。

用法（压测前启动，压测结束后 Ctrl+C 或等 --duration 到期）：
  .venv/Scripts/python.exe scripts/sample_resources.py --duration 900 --out data/load_resources.csv
"""
import argparse
import csv
import time
from pathlib import Path

import psutil

BASE_DIR = Path(__file__).resolve().parent.parent


def find_backend_processes() -> list:
    """定位 uvicorn 后端进程（python.exe 且命令行含 uvicorn）。"""
    procs = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.info["name"] and "python" in p.info["name"].lower():
                cmdline = " ".join(p.info["cmdline"] or [])
                if "uvicorn" in cmdline or "run.py" in cmdline:
                    procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return procs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=1800, help="采样时长（秒）")
    parser.add_argument("--interval", type=float, default=2.0, help="采样间隔（秒）")
    parser.add_argument("--out", default="data/load_resources.csv")
    args = parser.parse_args()

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = BASE_DIR / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    procs = find_backend_processes()
    if procs:
        print(f"已定位后端进程：{[p.pid for p in procs]}")
    else:
        print("[警告] 未定位到 uvicorn 进程，仅采样系统整体指标")
    for p in procs:
        p.cpu_percent()  # 首次调用用于初始化基线

    start = time.time()
    rows = []
    print(f"开始采样（间隔 {args.interval}s，时长 {args.duration}s）-> {out_path}")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["elapsed_s", "sys_cpu_pct", "sys_mem_pct", "proc_cpu_pct", "proc_mem_mb", "proc_count"]
        )
        while time.time() - start < args.duration:
            elapsed = round(time.time() - start, 1)
            sys_cpu = psutil.cpu_percent(interval=None)
            sys_mem = psutil.virtual_memory().percent
            proc_cpu = sum(p.cpu_percent() for p in procs) if procs else 0.0
            proc_mem = sum(p.memory_info().rss for p in procs) / 1024 / 1024 if procs else 0.0
            writer.writerow([elapsed, sys_cpu, sys_mem, round(proc_cpu, 1), round(proc_mem, 1), len(procs)])
            f.flush()
            time.sleep(args.interval)
    print("采样结束")


if __name__ == "__main__":
    main()
