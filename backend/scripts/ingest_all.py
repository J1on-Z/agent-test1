"""命令行批量预灌：把 sample_docs 下全部文档通过 API 上传摄入（管理员身份）。

用法：python scripts/ingest_all.py [目录] [--host http://127.0.0.1:8000]
环境变量/参数默认 admin / 123456（或通过 .env 的 ADMIN_USERNAME/ADMIN_PASSWORD）
"""
import sys
import time
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config import settings  # noqa: E402

HOST = "http://127.0.0.1:8000"


def main() -> None:
    doc_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else settings.resolve_path("data/sample_docs")
    files = sorted([p for p in doc_dir.iterdir() if p.is_file() and p.suffix.lower() in settings.allowed_ext_list])
    if not files:
        print(f"[错误] {doc_dir} 下没有可导入的文档")
        return
    print(f"共 {len(files)} 份文档待导入")

    with httpx.Client(base_url=HOST, timeout=60) as client:
        # 登录
        r = client.post(
            "/api/auth/login",
            json={"username": settings.admin_username, "password": settings.admin_password},
        )
        if r.status_code != 200:
            print(f"[错误] 管理员登录失败: {r.text}")
            return
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 上传
        multipart = [("files", (p.name, p.read_bytes())) for p in files]
        r = client.post("/api/kb/documents", files=multipart, headers=headers)
        result = r.json()
        print(f"上传结果: 成功 {result['succeeded']}，跳过 {len(result['skipped'])}")
        for s in result["skipped"]:
            print(f"  [跳过] {s['filename']}: {s['reason']}")
        if not result["jobs"]:
            return

        # 轮询任务
        job_ids = set(result["jobs"])
        pending = set(job_ids)
        while pending:
            active = 0
            for jid in list(pending):
                jr = client.get(f"/api/kb/ingest-jobs/{jid}", headers=headers).json()
                if jr["status"] in ("succeeded", "failed", "cancelled"):
                    pending.discard(jid)
                    print(f"  任务 {jid}: {jr['status']} - {jr.get('message') or ''}")
                else:
                    active += 1
            if active:
                time.sleep(1)
        print("全部任务完成")

        # 汇总
        docs = client.get("/api/kb/documents", params={"page_size": 100}, headers=headers).json()
        ready = sum(1 for d in docs["items"] if d["status"] == "ready")
        print(f"知识库就绪文档: {ready}/{docs['total']}")


if __name__ == "__main__":
    main()
