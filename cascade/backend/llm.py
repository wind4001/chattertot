"""LLM 客户端：调 deepseek-v4-flash（OpenAI 兼容接口）生成回复。"""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")

SYSTEM_PROMPT = (
    "你是「小云」，一个温柔可爱、很有耐心的大姐姐，专门陪小朋友聊天。"
    "你擅长讲故事、猜谜语、唱儿歌、玩词语接龙，能耐心回答小朋友的各种问题。"
    "说话要自然、口语化、带一点可爱的语气，像面对面聊天一样。"
    "日常闲聊要简短（1~2 句话）；讲故事要短小完整（150~250 字，有开头、经过、结尾），不要长篇大论。"
    "不要用表情符号。多鼓励和夸赞小朋友，适当用「呀、啦、哦、呢、吧」这样可爱的语气词。"
    "如果小朋友的话听起来不完整、只说了一半，你要温柔地追问「然后呢？」「你还想说什么呀？」，不要急着回答。"
)


async def chat(user_text: str, history: list | None = None, facts: str = ""):
    """生成回复；history 为多轮对话历史，facts 为长期记忆档案。失败返回 None。"""
    if not LLM_API_KEY:
        return None
    system = SYSTEM_PROMPT
    if facts:
        system += f"\n\n【关于这个小朋友，你记得这些】\n{facts}"
    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0),
            trust_env=False,
        ) as client:
            resp = await client.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json={
                    "model": LLM_MODEL,
                    "messages": messages,
                    "stream": False,
                    "max_tokens": 500,
                },
            )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        return content or None
    except Exception as e:
        print(f"[LLM] 调用失败: {e}", flush=True)
        return None


MEMORY_PROMPT = (
    "你是记忆整理助手。下面是一个小朋友和 AI 伙伴「小云」的对话片段，以及已有的记忆档案。\n"
    "请输出更新后的记忆档案，只记录值得长期记住的信息：\n"
    "- 小朋友的名字、年龄、称呼\n"
    "- 喜好（喜欢的动物/颜色/食物/故事类型等）\n"
    "- 家庭成员、宠物\n"
    "- 重要事件\n"
    "- 已经讲过的故事标题（避免以后重复讲同一个）\n"
    "规则：忽略寒暄和一次性内容；已有档案中的信息有变化就更新；合并去重；"
    "总长不超过 300 字；直接输出档案内容，不要标题、不要任何解释。"
)


async def summarize(conversation: str, existing_facts: str) -> str | None:
    """把对话片段摘要进长期记忆档案；失败返回 None。"""
    if not LLM_API_KEY:
        return None
    user = f"【已有记忆档案】\n{existing_facts or '（暂无）'}\n\n【本次对话片段】\n{conversation}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=20.0, pool=5.0),
            trust_env=False,
        ) as client:
            resp = await client.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": MEMORY_PROMPT},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "max_tokens": 600,
                },
            )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        return content or None
    except Exception as e:
        print(f"[LLM] 摘要失败: {e}", flush=True)
        return None
