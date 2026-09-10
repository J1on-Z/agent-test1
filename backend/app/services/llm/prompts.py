"""全部提示词模板（集中管理，便于对照实验写进论文）。

引文机制：上下文分块按【1】【2】…编号，系统提示硬约束模型在引用处标注对应编号，
回答完成后由 chat_service 用正则解析编号并映射回具体分块（见 utils/text.py）。
"""
from app.config import settings

SYSTEM_PROMPT = """你是「星辰电商」平台的智能客服助手，专门解答与平台商品相关的售前咨询与售后问题。

回答规则：
1. 只能依据下方【参考知识】中的内容回答，不得编造知识库中不存在的商品参数、价格或政策。
2. 回答中引用参考知识时，必须在对应句末标注来源编号，格式如【1】；一句话引用多处依据时并列标注，如【1】【3】。
3. 参考知识不足以回答问题时，直接说明「知识库中未找到与该问题相关的信息」，并建议用户联系人工客服，严禁猜测。
4. 使用简体中文，回答结构清晰；涉及具体数字（价格、容量、时长）务必与参考知识一致。
5. 与商品/购物无关的问题（如写诗、行情分析），礼貌说明你只负责商品咨询服务。"""

REWRITE_PROMPT = """你负责改写用户问题，使其能独立用于知识库检索。
对话历史（最近的用户与助手对话）：
{history}

用户当前问题：{question}

要求：
1. 如果问题包含指代（如"它""这款""那个"），根据历史将其替换为具体商品或主题。
2. 如果问题是简短追问（如"保修呢？"），结合历史补全成完整问题。
3. 只输出改写后的完整问题本身，不要任何解释、前缀或标点包裹。"""

SUMMARY_PROMPT = """请把以下对话压缩成一段简洁摘要（200字以内），保留关键信息：涉及的商品、用户关注点、已给出的关键结论（价格/参数/政策）。
旧摘要：
{old_summary}

新增对话：
{new_messages}
"""

# 相关度门槛未过时的确定性拒答（不调 LLM，零成本）
NO_CONTEXT_ANSWER = """知识库中未找到与该问题相关的信息，建议您联系人工客服获取帮助。"""


def build_context_blocks(chunks: list[dict]) -> str:
    """把最终入选的上下文分块组装成带编号的参考知识文本。

    分块按分数降序编号 1..K；编号即引文编号（回答中的【n】与这里一一对应）。
    """
    blocks = []
    for i, c in enumerate(chunks, start=1):
        meta = c.get("meta") or {}
        doc_name = meta.get("doc_name", "未知文档")
        title = meta.get("doc_title") or meta.get("title") or ""
        loc = []
        if meta.get("page"):
            loc.append(f"第{meta['page']}页")
        if meta.get("sheet"):
            loc.append(f"工作表「{meta['sheet']}」")
        if meta.get("row_start"):
            loc.append(f"第{meta['row_start']}-{meta.get('row_end', meta['row_start'])}行")
        loc_str = " ".join(loc)
        parts = [f"【{i}】《{doc_name}》"]
        if loc_str:
            parts.append(f"{loc_str} ")
        if title:
            parts.append(f"· {title}")
        head = "".join(parts)
        if c.get("score") is not None:
            head += f"（相关度 {c['score']:.2f}）"
        blocks.append(f"{head}\n{c['content']}")
    return "\n\n".join(blocks)


def build_messages(question: str, history_messages: list, summary: str, top_chunks: list[dict]) -> list:
    """组装 LLM 输入：系统提示 + 摘要块 + 窗口历史 + 当前问题（上下文以 user 消息承载）。

    :param history_messages: [(role, content), ...] 窗口内最近消息（不含当前问题）
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if summary:
        messages.append({"role": "system", "content": f"以下是更早对话的摘要：\n{summary}"})
    for role, content in history_messages:
        messages.append({"role": role, "content": content})
    context = build_context_blocks(top_chunks)
    user_content = (
        f"【参考知识】\n{context}\n\n"
        f"【用户问题】\n{question}\n\n"
        f"请依据参考知识回答问题，引用时用【编号】标注来源。"
    )
    messages.append({"role": "user", "content": user_content})
    return messages
