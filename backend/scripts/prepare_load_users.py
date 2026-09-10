"""压测准备：批量创建压测账号、签发 token 池、构建问题池。

设计说明：
- 注册/登录接口有 5 次/分/IP 限流，100 个账号无法走 API —— 直接用同步 engine
  建库 + 直接签发 access token（create_access_token 无需密码校验）
- token 有效期 30 分钟；压测超过 30 分钟时重跑本脚本的 --tokens-only 刷新令牌
- 问题池含「热点问题」（压测按 20% 概率抽取）用于触发语义缓存命中

用法：
  python scripts/prepare_load_users.py                 # 全量：建账号 + 签发 token + 生成问题池
  python scripts/prepare_load_users.py --tokens-only   # 仅刷新 token（用户已存在时）
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import select  # noqa: E402

from app.core.security import create_access_token, hash_password  # noqa: E402
from app.database import SyncSessionLocal  # noqa: E402
from app.models import User  # noqa: E402

USER_COUNT = 100
PASSWORD = "load123456"
TOKENS_FILE = BASE_DIR / "data" / "load_tokens.json"
QUESTIONS_FILE = BASE_DIR / "data" / "load_questions.json"

# 热点问题：压测中 20% 概率抽取，模拟现实中的热点重复提问 → 触发语义缓存
HOT_QUESTIONS = [
    "七天无理由退货有什么条件？",
    "星辰X1 Pro 的电池容量和快充功率是多少？",
    "偏远地区运费怎么算？",
    "暖冬羽绒服怎么洗涤保养？",
    "积分有效期多久？",
]

# 普通问题补充池（覆盖各商品与政策，保证检索路径多样）
EXTRA_QUESTIONS = [
    "星辰X1 Pro 支持无线充电吗？",
    "星辰X1 Pro 防水等级是多少？",
    "星辰X1 Pro 有哪些颜色可选？",
    "Aurora Buds 2 的降噪深度是多少？",
    "Aurora Buds 2 续航多久？",
    "Aurora Buds 2 可以同时连接几台设备？",
    "动力侠移动电源能带上飞机吗？",
    "动力侠移动电源支持哪些快充协议？",
    "AirPure 5 空气净化器滤网多久换一次？",
    "AirPure 5 适合多大面积的房间？",
    "云朵洗衣机有哪些洗涤程序？",
    "云朵洗衣机能洗羽绒服吗？",
    "鲜源冰箱需要手动除霜吗？",
    "鲜源冰箱的日耗电量是多少？",
    "雪绒洁面乳适合敏感肌使用吗？",
    "雪绒洁面乳的核心成分是什么？",
    "焕彩水光精华套装包含哪些产品？",
    "焕彩精华套装的使用顺序是什么？",
    "疾风跑鞋的尺码应该怎么选？",
    "疾风跑鞋适合什么场景穿着？",
    "疾风跑鞋的大底寿命有多长？",
    "暖冬羽绒服填充的是什么绒？",
    "暖冬羽绒服的充绒量是多少？",
    "春山云雾茶怎么保存？",
    "茶叶可以七天无理由退货吗？",
    "智眠记忆棉枕头适合侧睡吗？",
    "记忆棉枕芯怎么清洁？",
    "手机激活后还能无理由退货吗？",
    "质量问题退换货的时限是多久？",
    "退款一般多久能到账？",
    "订单什么时候发货？",
    "物流停滞多久可以联系客服催件？",
    "积分怎么抵扣现金？",
    "会员等级是怎么划分的？",
    "钻石会员有什么权益？",
    "平台如何保存我的密码？",
    "注销账号后数据多久删除？",
    "大家电签收时需要注意什么？",
    "哪些商品不适用七天无理由退货？",
]


def build_question_pool() -> dict:
    """合并金标问题 + 补充问题作为普通池，热点问题单列。"""
    golden_path = BASE_DIR / "data" / "sample_docs" / "golden_qa.json"
    normal: list[str] = []
    if golden_path.exists():
        for item in json.loads(golden_path.read_text(encoding="utf-8")):
            # 排除无关问题（金标集中 expected_doc 为 null 的两条）
            if item.get("expected_doc"):
                normal.append(item["question"])
    normal.extend(EXTRA_QUESTIONS)
    # 去重保序
    normal = list(dict.fromkeys(normal))

    pool = {"normal": normal, "hot": HOT_QUESTIONS}
    QUESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUESTIONS_FILE.write_text(json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"问题池：普通 {len(normal)} 条 + 热点 {len(HOT_QUESTIONS)} 条 -> {QUESTIONS_FILE}")
    return pool


def prepare_users(tokens_only: bool = False) -> None:
    tokens: list[dict] = []
    with SyncSessionLocal() as db:
        for i in range(1, USER_COUNT + 1):
            username = f"load_user{i:03d}"
            user = db.scalar(select(User).where(User.username == username))
            if user is None:
                if tokens_only:
                    print(f"[警告] {username} 不存在，请先不带 --tokens-only 运行一次")
                    continue
                user = User(
                    username=username,
                    password_hash=hash_password(PASSWORD),
                    role="user",
                )
                db.add(user)
                db.commit()
                db.refresh(user)
            tokens.append(
                {
                    "username": username,
                    "user_id": user.id,
                    "token": create_access_token(user.id, user.username, user.role),
                }
            )
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKENS_FILE.write_text(json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已签发 {len(tokens)} 个 access token -> {TOKENS_FILE}")
    print(f"（有效期 30 分钟；压测超时后重跑：python scripts/prepare_load_users.py --tokens-only）")


def main() -> None:
    tokens_only = "--tokens-only" in sys.argv
    build_question_pool()
    prepare_users(tokens_only=tokens_only)
    print("\n压测前检查清单：")
    print("  1. 后端已启动（start_backend.bat）")
    print("  2. .env 限流配置符合当前场景（120/min=保留限流；100000/min=测容量）")
    print("  3. locust 已安装")


if __name__ == "__main__":
    main()
